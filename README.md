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
