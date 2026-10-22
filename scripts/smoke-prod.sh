#!/usr/bin/env bash
# Smoke test for a running production stack (docker-compose.prod.yml).
#
#   bash scripts/smoke-prod.sh              checks the running stack
#   bash scripts/smoke-prod.sh --restart    also takes the stack down and up and checks the data survives
#
# Needs curl and docker. Works in Git Bash / WSL / Linux / macOS. If you used a different env file:
#   ENV_FILE=.env.mine bash scripts/smoke-prod.sh
# Exit status is 0 only if every check passed.

set -uo pipefail
cd "$(dirname "$0")/.."

BASE=${BASE:-http://127.0.0.1:8080}
export ENV_FILE=${ENV_FILE:-.env}
DC=(docker compose -f docker-compose.prod.yml --env-file "$ENV_FILE")
JAR=$(mktemp)
CSRF="X-Requested-With: ChessReviewLab"
FAILED=0

pass() { printf '  PASS  %s\n' "$1"; }
fail() { printf '  FAIL  %s\n' "$1"; FAILED=$((FAILED + 1)); }
check() { # check "description" expected actual
  if [ "$2" = "$3" ]; then pass "$1"; else fail "$1 (expected '$2', got '$3')"; fi
}
contains() { # contains "description" needle haystack
  if printf '%s' "$3" | grep -qiF -- "$2"; then pass "$1"; else fail "$1 (missing '$2')"; fi
}
http_code() { curl -s -o /dev/null -w '%{http_code}' "$@"; }
wait_healthy() {
  for _ in $(seq 1 60); do curl -sf "$BASE/api/healthz" >/dev/null 2>&1 && return 0; sleep 2; done
  return 1
}

echo "== stack is up =="
wait_healthy && pass "API answers through the web server" || { fail "stack did not become healthy"; exit 1; }

echo "== web server =="
check "home page" 200 "$(http_code "$BASE/")"
check "SPA routes fall back to index.html" 200 "$(http_code "$BASE/games")"
asset=$(curl -s "$BASE/" | grep -o '/assets/[^"]*\.js' | head -1)
contains "built assets are cached for a long time" "max-age=31536000" "$(curl -sI "$BASE$asset")"
contains "index.html is not cached" "no-cache" "$(curl -sI "$BASE/" | grep -i cache-control)"
headers=$(curl -sI "$BASE/")
contains "Content-Security-Policy is set" "content-security-policy" "$headers"
contains "X-Frame-Options is set" "x-frame-options: deny" "$headers"
contains "nosniff is set" "x-content-type-options: nosniff" "$headers"

echo "== API =="
check "interactive API docs are off in production" 404 "$(http_code "$BASE/api/docs")"
check "OpenAPI schema is off in production" 404 "$(http_code "$BASE/api/openapi.json")"
check "writes without the CSRF header are refused" 403 "$(http_code -X POST "$BASE/api/session")"
check "unknown session is refused" 401 "$(http_code "$BASE/api/games")"
contains "API responses are not cacheable" "no-store" "$(curl -sI "$BASE/api/healthz" | grep -i cache-control)"

echo "== container hardening =="
for svc in api worker; do
  uid=$("${DC[@]}" exec -T "$svc" id -u 2>/dev/null | tr -d '\r')
  if [ -n "$uid" ] && [ "$uid" != "0" ]; then pass "$svc runs as a non-root user (uid $uid)"; else fail "$svc runs as root"; fi
done
published=$(docker ps --filter "name=chess-review-lab-prod" --format '{{.Names}} {{.Ports}}' | grep -E '0\.0\.0\.0|:::' || true)
if [ -z "$published" ]; then pass "nothing is published on all interfaces"; else fail "published on all interfaces: $published"; fi
db_ports=$(docker ps --filter "name=chess-review-lab-prod-db" --format '{{.Ports}}')
if printf '%s' "$db_ports" | grep -q -- '->'; then fail "the database is published to the host ($db_ports)"; else pass "the database is not published"; fi

echo "== a real analysis through the web server =="
curl -s -c "$JAR" -b "$JAR" -H "$CSRF" -X POST "$BASE/api/session" >/dev/null
pgn='{"pgn_text":"[White \"Smoke\"]\n[Black \"Test\"]\n[Result \"1-0\"]\n\n1. e4 e5 2. Nf3 Nc6 3. Bc4 Bc5 1-0"}'
gid=$(curl -s -c "$JAR" -b "$JAR" -H "$CSRF" -H 'Content-Type: application/json' -d "$pgn" "$BASE/api/imports/pgn" \
      | grep -o '"id":"[^"]*"' | head -1 | cut -d'"' -f4)
[ -n "$gid" ] && pass "imported a game" || { fail "could not import a game"; exit 1; }
check "analysis is accepted" 202 "$(http_code -c "$JAR" -b "$JAR" -H "$CSRF" -H 'Content-Type: application/json' -d '{"depth":10}' "$BASE/api/games/$gid/analysis")"
status=""
for _ in $(seq 1 60); do
  status=$(curl -s -b "$JAR" "$BASE/api/games/$gid" | grep -o '"analysis_status":"[a-z]*"' | cut -d'"' -f4)
  [ "$status" = "completed" ] || [ "$status" = "failed" ] && break
  sleep 1
done
check "the worker completed the analysis" completed "$status"
contains "the review comes from Stockfish" "Stockfish" "$(curl -s -b "$JAR" "$BASE/api/games/$gid/analysis")"
contains "the PGN can be downloaded" "attachment" "$(curl -s -D - -o /dev/null -b "$JAR" "$BASE/api/games/$gid/pgn")"

if [ "${1:-}" = "--restart" ]; then
  echo "== restart: containers are recreated, data must survive =="
  "${DC[@]}" down >/dev/null 2>&1
  "${DC[@]}" up -d >/dev/null 2>&1
  wait_healthy && pass "stack came back healthy" || { fail "stack did not come back"; exit 1; }
  check "the saved game is still there" completed "$(curl -s -b "$JAR" "$BASE/api/games/$gid" | grep -o '"analysis_status":"[a-z]*"' | cut -d'"' -f4)"
  contains "the saved review is still there" "Stockfish" "$(curl -s -b "$JAR" "$BASE/api/games/$gid/analysis")"
  contains "the same browser session still works" '"new":false' "$(curl -s -b "$JAR" -H "$CSRF" -X POST "$BASE/api/session")"
fi

rm -f "$JAR"
echo
if [ "$FAILED" -eq 0 ]; then echo "All checks passed."; else echo "$FAILED check(s) FAILED."; fi
exit "$FAILED"
