# Chess Review Lab

A personal chess game review tool. Import your games (PGN, Chess.com, Lichess), let Stockfish analyze them, and
step through each game on an interactive board with an evaluation graph, move-by-move quality marks
(Brilliant, Great, Best, Excellent, Good, Inaccuracy, Mistake, Blunder), the engine's alternative lines and a summary.
No account and no subscription: your games stay on your own machine.

Requirements: [FRD.md](FRD.md). Design and progress log: [IMPLEMENTATION_PLAN.md](IMPLEMENTATION_PLAN.md).
Everything runs in Docker; you do not need Python or Node installed.

**Contents:** [Quick start](#quick-start-development) · [Running it for real](#running-it-for-real-production) ·
[Going public](#going-public-checklist) · [Configuration](#configuration) · [Using the app](#using-the-app) ·
[Performance](#performance) · [API](#api) · [Testing](#testing) · [Acceptance tests](#acceptance-tests) ·
[Accessibility](#accessibility) · [Troubleshooting](#troubleshooting) · [Licences](#licences)

## Quick start (development)

```
copy .env.example .env        # (Linux/macOS: cp)  first time only
docker compose up -d --build
```

| What | Where (localhost only) |
|---|---|
| The app (Vite dev server, hot reload) | http://127.0.0.1:5173 |
| API + interactive docs | http://127.0.0.1:8010/api/docs |
| Postgres | internal only, not published |

API port 8010 (not 8000) because 8000 and 5432 are often taken on dev machines. The worker restarts by itself when
backend code changes. Database migrations run automatically when the `api` container starts, so after pulling new
code run `docker compose up -d --build` (or `docker compose restart api`).

## Running it for real (production)

`docker-compose.prod.yml` is the deployable stack: built images instead of hot reload, a non-root backend, no
published database or API ports, restart policies, health checks and one public entry point (nginx, which also
serves the built app and proxies `/api`).

```
copy .env.example .env         # then set POSTGRES_PASSWORD to a real secret
docker compose -f docker-compose.prod.yml up -d --build
```

Open http://127.0.0.1:8080. (`WEB_PORT` / `WEB_BIND` in `.env` change the port and the address it listens on.)

- The server **refuses to start** with the placeholder password (`ENVIRONMENT=production` is set by the compose file).
- **Check it:** `bash scripts/smoke-prod.sh` (add `--restart` to also recreate the containers and confirm the data
  survives). It checks the headers, caching, that API docs are off, that the backend is not root, that nothing is
  exposed beyond the web port, and that a real analysis completes.
- **Upgrade:** `git pull`, then `docker compose -f docker-compose.prod.yml up -d --build`. Migrations run first.
- **More analysis capacity:** `docker compose -f docker-compose.prod.yml up -d --scale worker=2`. Each worker process
  runs one Stockfish and one job at a time. See [Performance](#performance) for why this beats more engine threads.
- **Back up / restore the database:**
  ```
  docker compose -f docker-compose.prod.yml exec -T db pg_dump -U chess chess > backup.sql
  docker compose -f docker-compose.prod.yml exec -T db psql -U chess chess < backup.sql
  ```
  (Users can also export their own games as PGN from the Settings page.)
- **Logs:** `docker compose -f docker-compose.prod.yml logs -f api worker`.

## Going public checklist

The defaults are for one person on one machine. Before letting other people reach it, do all of these:

1. **HTTPS.** Put it behind a TLS-terminating reverse proxy (Caddy, Traefik, a cloud load balancer) and set
   `COOKIE_SECURE=true`, otherwise browsers will not keep the session cookie. Set `WEB_BIND=0.0.0.0` only when something
   in front of it handles TLS.
2. **Real secrets.** A strong `POSTGRES_PASSWORD` (enforced). Never commit `.env` (it is git-ignored).
3. **Limits.** Set `SESSIONS_PER_IP_PER_HOUR` (for example `30`), keep `MAX_ACTIVE_JOBS_PER_USER` and `MAX_QUEUE_LENGTH`
   modest, and keep `MAX_DEPTH` / `MAX_PLIES` at levels your hardware can afford. See [Performance](#performance).
4. **Capacity.** One worker analyzes one game at a time. Size `--scale worker=N` and the host's CPU/RAM to the number of
   people you expect; the job queue refuses new work when it is full, with a clear message.
5. **Identify yourself to Chess.com.** Put a contact in `EXTERNAL_USER_AGENT`.
6. **Privacy.** Decide `RETENTION_DAYS` (default 30; `0` keeps data forever) and tell your users. They can export and
   delete everything themselves from Settings.
7. **Licences.** If you give anyone the images or the source, read [Licences](#licences).
8. With several API workers (`API_WORKERS` > 1) the per-process limits (session throttle, search cooldown) become
   per-worker. For strict limits keep one API worker or add rate limiting at the proxy.

## Configuration

Set in `.env` (see [.env.example](.env.example)); both compose files read it. Defaults shown.

| Setting | Default | What it does |
|---|---|---|
| `POSTGRES_USER` / `POSTGRES_PASSWORD` / `POSTGRES_DB` | chess / `change-me` / chess | Database login. The password must be changed for production |
| `COOKIE_SECURE` | `false` | Send the session cookie only over HTTPS (set `true` when public) |
| `RETENTION_DAYS` | `30` | Delete a visitor's data after this many days without a visit; `0` = never |
| `RETENTION_PURGE_INTERVAL_SECONDS` | `3600` | How often the worker looks for data to delete |
| `MAX_DEPTH` / `MAX_NODES` | `22` / `5000000` | Hard caps on the search a user can ask for |
| `MAX_MULTIPV` | `5` | Most engine lines per position |
| `MAX_PLIES` | `300` | Longest game that can be analyzed |
| `DEFAULT_DEPTH` / `DEFAULT_MULTIPV` / `DEFAULT_IMPORT_COUNT` | `16` / `3` / `20` | Used until a user saves their own in Settings |
| `ENGINE_THREADS` / `ENGINE_HASH_MB` | `1` / `128` | Per Stockfish process (see [Performance](#performance)) |
| `MAX_SECONDS_PER_POSITION` | `30` | A single position is cut off after this long |
| `ANALYSIS_JOB_TIMEOUT_SECONDS` | `600` | Minimum time a job may run before it is stopped |
| `JOB_SECONDS_PER_POSITION` | `15` | ...or this much per position of the game, if that is more (long games get longer) |
| `MAX_ACTIVE_JOBS_PER_USER` / `MAX_QUEUE_LENGTH` | `2` / `50` | Queued+running analyses per person / in total |
| `JOB_MAX_ATTEMPTS` / `JOB_STALE_SECONDS` | `2` / `120` | A crashed job is retried; one with no heartbeat for this long is requeued |
| `MAX_REQUEST_BYTES` | `1500000` | Largest request body accepted (a 1 MB PGN plus overhead) |
| `MAX_GAMES_PER_USER` | `5000` | Saved games per person |
| `SESSIONS_PER_IP_PER_HOUR` | `0` (off) | New anonymous sessions allowed per address; set when public |
| `EXPORT_MAX_GAMES` | `5000` | Most games in one PGN export |
| `EXTERNAL_USER_AGENT` | ChessReviewLab/0.1 | Sent to Chess.com / Lichess; add a contact |
| `WEB_BIND` / `WEB_PORT` / `API_WORKERS` | `127.0.0.1` / `8080` / `1` | Production compose only |

## Using the app

- **Import** (home page): paste or upload a PGN; search a **Chess.com** or **Lichess** username (latest 10/20/50
  public games, then tick the ones you want); or paste a **game link**. Only public data is used, no login. Chess.com
  cannot look a game up from its link alone, so for a Chess.com link you also enter one player's username. Variants
  (Chess960, Atomic, ...) are listed but cannot be imported. Hosts are fixed and links are only parsed for an id, never
  fetched. Requests to those sites are paced; if one says "too many requests" you are told to wait a minute.
- **Analyze:** on a game's page pick a depth and a number of engine lines (1-5) and press *Analyze game*. It shows a
  rough time range first and refuses settings that would certainly be stopped by the time limit. Progress is live. A
  failed or interrupted analysis never damages a review you already have; you can retry.
- **Review:** board with the engine's lines as coloured arrows, a quality mark on every move, evaluation bar and graph
  (click to jump), move list, engine panel (click any line to play it out on the board; variations are never saved),
  summary with counts per side and key positions. Keyboard: `←` `→` move, `Home`/`End`, `F` flip, `Esc` leave a variation.
- **Games** (`/games`): search by player, filter by source, result, dates and analyzed or not, sort, page. Filters live in
  the URL. Download one game's PGN or export everything matching the filters.
- **Settings** (`/settings`): default depth and engine lines, import size; export all, **delete all games**, or **delete
  everything** (games, analyses, settings and the session).
- **Privacy:** your data belongs to this browser's anonymous session (a cookie), there is no account. It is deleted
  automatically after `RETENTION_DAYS` without a visit. If you clear your browser data you lose access, so export a PGN
  copy if the games matter.

How moves are classified (modelled on Chess.com's published rules, tuned in `ClassificationConfig`):
loss of winning chances versus the engine's best move: Best 0, Excellent <2, Good 2-5, Inaccuracy 5-10, Mistake 10-20,
Blunder 20+ (percentage points). *Great* is the only good move; *Brilliant* is a best or nearly-best piece sacrifice that
leaves you fine and was not needed to stay winning. These are guidance for study, not verdicts. Details: IMPLEMENTATION_PLAN.md §5.3.

## Performance

Measured with `python -m app.cli bench` on real Lichess games of 40, 80 and 151 plies, Stockfish 17.1, one engine
thread, 128 MB hash, on a 12-core desktop (your numbers will differ; the app corrects its estimate from your own runs).
Seconds to analyze the whole game:

| depth | lines | 40-ply game | 80-ply game | 151-ply game |
|---|---|---|---|---|
| 12 | 1 | 2.6 s | 5.1 s | 9.6 s |
| 12 | 3 | 6.3 s | 17.5 s | 17.7 s |
| 16 | 1 | 11.3 s | 27.7 s | 36.5 s |
| **16** | **3 (default)** | **39 s** | **89 s** | **97 s** |
| 20 | 1 | 40 s | 145 s | 125 s |
| 20 | 3 | 137 s | 955 s | 437 s |

- Cost grows about **1.5x per extra depth** and about **1.2x per extra engine line**, but the spread between games is
  large (the same settings took 2-3x longer on one game than another). So the app shows a *range*, not one number.
- **Defaults** (depth 16, 3 lines) take a minute or two for a normal game. Depth 20 with 3 lines can take 15 minutes.
- A job may run for `max(600 s, 15 s x positions)`; longer jobs are stopped and the user is told to lower depth or lines.
- **More engine threads barely help** at these depths (88.7 s with 1 thread, 68.7 s with 2, 74.9 s with 4 for the 80-ply
  game at depth 16 with 3 lines). Use spare CPU for **more workers** (`--scale worker=N`) so several games run at once.
  Memory: about 360 MB per worker idle; the compose file limits a worker to 2 GB.
- Reproduce: `docker compose run --rm worker python -m app.cli bench tests/fixtures/bench_80.pgn --depths 12,16 --lines 1,3`.

## API

Interactive docs at `/api/docs` in development (off in production). Everything is JSON except PGN files.

- Call `POST /api/session` first; it sets an anonymous session cookie.
- Every `POST`/`PUT`/`PATCH`/`DELETE` must send `X-Requested-With: ChessReviewLab` (a CSRF guard; Swagger's "Try it out"
  cannot send it, use the app or curl).

```
curl -c jar -b jar -H "X-Requested-With: ChessReviewLab" -X POST http://127.0.0.1:8010/api/session
curl -c jar -b jar -H "X-Requested-With: ChessReviewLab" -H "Content-Type: application/json" \
     -d '{"pgn_text": "1. e4 e5 2. Nf3 *"}' http://127.0.0.1:8010/api/imports/pgn
```

```
POST /api/imports/pgn | /pgn/upload      import PGN text / a file
POST /api/imports/preview | /commit      look up Chess.com/Lichess games, then import the picked ones
POST /api/imports/url                    import one game from a link (Chess.com also needs username_hint)
GET  /api/games                          ?q= &source= &result= &analyzed= &date_from= &date_to= &sort= &page=
GET  /api/games/{id}   DELETE /api/games/{id}   GET /api/games/{id}/pgn   GET /api/games/export
POST /api/games/{id}/analysis            {"depth":16,"multipv":3} -> 202 job, or 200 {"cached":true}
GET  /api/games/{id}/analysis            the completed review     GET .../analysis/estimate  rough time range
GET  /api/jobs/{id}   POST /api/jobs/{id}/retry
GET/PUT /api/settings                    DELETE /api/me/games   DELETE /api/me
```

## Testing

All in containers. The database container must be running for API tests (they use a separate `<db>_test` database).

```
docker compose run --rm worker python -m pytest -q                    # backend: unit + integration + real Stockfish
docker compose run --rm worker ruff check .                           # backend lint
docker compose run --rm frontend sh -c "npx tsc --noEmit && npx vitest run"   # frontend types + tests
docker compose --profile e2e run --rm e2e                             # browser tests, desktop + phone viewport
docker compose -f docker-compose.prod.yml --profile e2e run --rm e2e  # the same, against the production stack
bash scripts/smoke-prod.sh --restart                                  # production smoke test
```

Browser tests write screenshots to `e2e/screenshots`. They include an automated accessibility audit (axe-core, WCAG 2.1
A/AA, light and dark themes, desktop and phone, every page and state) and a check for browser console errors and
Content-Security-Policy violations. Tests that use the real Chess.com/Lichess are opt-in:
`docker compose run --rm -e RUN_LIVE=1 worker python -m pytest -q tests/live` and `... run --rm -e E2E_LIVE=1 e2e`.
After changing `frontend/package.json` refresh the container's modules with `docker compose run --rm frontend npm install`.
New migration: `docker compose run --rm worker alembic revision --autogenerate -m "what changed"`.

## Acceptance tests

The MVP acceptance scenarios from the FRD (section 8) and where each is verified automatically:

| ID | Scenario | Verified by |
|---|---|---|
| AT-01 | Upload a valid PGN | `test_games_api::test_import_valid_pgn_then_list_and_open`, `test_upload_pgn_file`; browser `review.spec` |
| AT-02 | Malformed PGN gives a clear error | `test_illegal_move_gives_a_clear_422`, `test_pgn_parser`; browser "malformed PGN" |
| AT-03 | Analyze a normal game | `test_engine_integration::test_normal_game_has_a_record_for_every_move`, `test_worker_engine::test_full_pipeline_with_real_stockfish` |
| AT-04 | Forced mate handled correctly | `test_engine_integration::test_forced_mate_*`, `test_fools_mate_game`, `test_classify` (mate cases) |
| AT-05 | Navigating moves matches the board | `ReviewPage.test` "navigation (AT-05)"; browser `review.spec` with the real board |
| AT-06 | Selecting a graph point selects the move | `ReviewPage.test` "evaluation graph (AT-06)"; browser `review.spec` |
| AT-07 | Import a public Chess.com game | `test_external_imports` (mocked) + live `test_at07_*` and live browser run |
| AT-08 | Import a Lichess game | `test_external_imports` (mocked) + live `test_at08_*` and live browser run |
| AT-09 | Repeat import is deduplicated | `test_reimport_does_not_create_a_duplicate`, cross-source `test_a_game_already_imported_as_pgn_*` |
| AT-10 | Restart keeps games and reviews | `scripts/smoke-prod.sh --restart` (containers recreated), `test_a_review_is_served_from_the_database_*` |
| AT-11 | Interrupted job is handled safely | `test_analysis_jobs` (crash retry, reaper, shutdown requeue, lost job); verified live with SIGTERM and SIGKILL |
| AT-12 | Another user's game is refused | `test_other_users_games_are_invisible`, per-endpoint isolation tests, browser "another browser session" |
| AT-13 | Exceeding limits is rejected or constrained | `test_request_validation`, `test_user_and_queue_limits`, `test_hardening`, `test_estimate_api` |
| AT-14 | Review usable on a phone | browser `review.spec` / `a11y.spec` / `history.spec` on a phone viewport (touch drag, tap sizes, no sideways scroll) |

## Accessibility

Automatically audited (axe-core) against WCAG 2.1 A and AA on every page and state, in both colour themes and on a phone
viewport: colour contrast, names and roles, landmarks, headings, one page title per route. Also tested: a skip link, a
visible focus ring, full keyboard operation of the review page, and `prefers-reduced-motion` (no sliding pieces, no
animated bars). Move quality is always shown by a symbol and a word as well as a colour. Moving pieces on the board needs
a mouse or touch; the keyboard alternative is to play an engine line from the list (every line is a button).
Automated tools find only part of the problems: a manual pass with a screen reader has not been done.

## Troubleshooting

- **A page or API call fails right after pulling new code:** the database needs the new migration. Run
  `docker compose up -d --build` (dev) or the production command (it migrates first).
- **"Blocked request. This host is not allowed" from the dev server:** open it as `localhost` or `127.0.0.1`; other
  host names must be listed in `frontend/vite.config.ts` (`allowedHosts`).
- **Analysis stays "queued":** the worker is busy (one game at a time per worker) or not running:
  `docker compose logs worker`. Add workers with `--scale worker=2`.
- **"Stopped: exceeded its time limit":** lower the depth or number of lines (the form warns beforehand), or raise
  `JOB_SECONDS_PER_POSITION`.
- **A game list is empty after clearing browser data:** games belong to the browser session; import them again (export a PGN
  first next time).
- **Port already in use:** change the published ports in `docker-compose.yml` / `WEB_PORT`.
- **Chess.com says "too many requests" or a month is "missing":** wait a minute and search again; the site's archives are
  sometimes briefly unavailable and the app skips (and tells you about) a month it cannot read.
- **Lichess link gives "only signed-in users can download this game":** that game is restricted; import it from the
  player's username instead, or paste its PGN.

## Licences

This project's source is not yet under a licence of its own: **choose one before sharing it**. Two of its dependencies are
GPL-3.0:

- **Stockfish** is installed from the Debian package into the backend image (not stored in this repository).
- **python-chess** is a Python dependency of the backend.

Running the app for yourself, or as a hosted service, does not oblige you to publish anything. If you **distribute** the
Docker images or the source to other people, the combined backend is subject to the GPL-3.0: ship it under GPL-3.0 (or a
compatible licence) and offer the corresponding source. The frontend deliberately avoids further copyleft libraries
(react-chessboard is MIT, chess.js is BSD). Other dependencies (FastAPI, SQLAlchemy, React, Tailwind, ...) are permissive.
