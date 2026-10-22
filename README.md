# Chess Review Lab

See [FRD.md](FRD.md) for requirements and [IMPLEMENTATION_PLAN.md](IMPLEMENTATION_PLAN.md) for the plan.
Everything runs in Docker; no local Python or Node is needed.

## Run

```
copy .env.example .env      # first time only; set a real POSTGRES_PASSWORD
docker compose up -d --build
```

| Service | URL (localhost only) |
|---|---|
| Frontend (Vite) | http://127.0.0.1:5173 |
| API + docs | http://127.0.0.1:8010/api/docs |
| Postgres | internal only (not published to the host) |

Host port 8010 is used for the API because 8000 and 5432 are commonly taken on dev machines.

## Develop

The database container must be running for API tests (they use a separate `<db>_test` database,
created automatically).

```
# everything, including Stockfish integration tests
docker compose run --rm worker python -m pytest -q
# skip the slower Stockfish tests
docker compose run --rm worker python -m pytest -q -m "not engine"
# lint
docker compose run --rm worker ruff check .
# analyze a game from the command line
docker compose run --rm worker python -m app.cli analyze tests/fixtures/short_game.pgn --depth 14
# frontend: type-check, unit/component tests, production build (all inside the container)
docker compose run --rm frontend npx tsc --noEmit
docker compose run --rm frontend npx vitest run
docker compose run --rm frontend npx vite build
# after changing frontend/package.json, refresh the container's node_modules volume
docker compose run --rm frontend npm install
# browser tests (Playwright, desktop + phone viewport) against the running stack; screenshots
# are written to e2e/screenshots
docker compose --profile e2e run --rm e2e
# create a new migration after changing models
docker compose run --rm worker alembic revision --autogenerate -m "describe change"
```

Migrations are applied automatically when the `api` container starts.

## History, settings and privacy

- **Games** (`/games`): search by player, filter by source, result, date range and whether a game is analyzed,
  sort by date played or by when imported. Filters are kept in the URL, so a filtered list can be bookmarked.
  Download one game's PGN from its row or from the review page, or **export every game matching the current
  filters** as one PGN file (re-importable; duplicates are recognised).
- **Settings** (`/settings`): your default search depth and number of engine lines (used by "Analyze game" and
  still changeable per game) and how many games a Chess.com / Lichess search fetches. Choices are limited to what
  the server allows (`MAX_DEPTH`, `MAX_MULTIPV`).
- **Privacy:** your data is tied to this browser's anonymous session. It is deleted automatically after
  `RETENTION_DAYS` (default 30) without a visit; the worker checks hourly. In Settings you can export everything,
  **delete all games** (you stay signed in, settings kept), or **delete everything** (games, analyses, settings and
  the session). Deleting while an analysis is running is safe: the job simply disappears.

```
GET/PUT /api/settings        {"default_depth": 14, "default_multipv": 2, "import_count": 50}  (partial updates)
GET     /api/games           ?q=&source=&result=&analyzed=true|false&date_from=&date_to=&sort=played|added&page=
GET     /api/games/export    same filters -> one .pgn file (404 if nothing matches; capped by EXPORT_MAX_GAMES)
GET     /api/games/{id}/pgn  one game as a .pgn download
DELETE  /api/me/games        delete all my games              DELETE /api/me   delete everything
```

## Importing games

From the home page: paste/upload a **PGN**, search a **Chess.com** or **Lichess** username (latest 10/20/50
public games, then tick the ones you want), or paste a **game link**.

- Only public data is used; no login or password. Hosts are fixed (`api.chess.com`, `lichess.org`) and
  usernames/links are validated; a pasted link is parsed for its id and never fetched.
- Chess.com can't look a game up by link alone, so for a Chess.com link you also enter one player's username.
- Requests are paced (one at a time per site, small gap between calls, per-session cooldown). If a site answers
  "too many requests" you'll be told to wait a minute. Set `EXTERNAL_USER_AGENT` in `.env` with a contact, as
  Chess.com requests.
- Chess variants (Chess960, Atomic, …) are listed but marked "can't import"; a month of Chess.com's archive that
  fails to load is skipped and you're told games may be missing.

```
POST /api/imports/preview   {"source": "chesscom"|"lichess", "username": "...", "max_games": 20}  -> games found
POST /api/imports/commit    {"source": ..., "username": ..., "external_ids": ["..."]}           -> imports the picked
POST /api/imports/url       {"url": "...", "username_hint": "..."}  (hint needed for Chess.com links)
```

Tests that talk to the real sites are opt-in: `docker compose run --rm -e RUN_LIVE=1 worker python -m pytest -q tests/live`
(API) and `docker compose --profile e2e run --rm -e E2E_LIVE=1 e2e` (browser).

## Analysis

Analysis runs in the `worker` container (one Stockfish, one job at a time per worker process).
Add throughput with more worker processes: `docker compose up -d --scale worker=2`.

```
POST /api/games/{id}/analysis    body optional: {"depth": 16} or {"nodes": 500000}, "multipv": 1-5 (engine lines)
                                 -> 202 + job, or 200 {"cached": true} if the same settings were done
GET  /api/jobs/{job_id}          status queued|running|completed|failed + progress_done/progress_total
GET  /api/games/{id}/analysis    the completed review (404 until one exists)
POST /api/jobs/{job_id}/retry    retry a failed job
```

A failed or interrupted analysis never affects a review that already exists for the game.

## API notes

- Call `POST /api/session` first; it sets an anonymous session cookie (your games belong to that
  browser session and are purged after `RETENTION_DAYS` of inactivity).
- Every `POST`/`PUT`/`PATCH`/`DELETE` under `/api/` must send `X-Requested-With: ChessReviewLab`.
  Example with curl:

```
curl -c jar -b jar -H "X-Requested-With: ChessReviewLab" -X POST http://127.0.0.1:8010/api/session
curl -c jar -b jar -H "X-Requested-With: ChessReviewLab" -H "Content-Type: application/json" \
     -d '{"pgn_text": "1. e4 e5 2. Nf3 *"}' http://127.0.0.1:8010/api/imports/pgn
```

## Licensing note

Stockfish and python-chess are GPL-3.0. Stockfish is installed from the distro package in the
backend image, not vendored. Review obligations before distributing images or source.
