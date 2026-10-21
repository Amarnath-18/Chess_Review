# Implementation Plan — Chess Review Lab (MVP)

Companion to [FRD.md](FRD.md). Decisions confirmed in discussion:

| Decision | Choice |
|---|---|
| Auth | **Guest-only** with anonymous session (no signup in MVP) |
| Engine / jobs | Server-side Stockfish; **Postgres-backed job queue** + separate worker process (no Redis) |
| Deployment | **Docker Compose**: `db`, `api`, `worker`, `frontend` |
| Import scope | Chess.com / Lichess **by username (recent N games, pick subset)** + **by game URL**; plus PGN file/paste |

---

## 1. Deviations from / clarifications to the FRD

These should be reflected back into the FRD (v1.1) so tests and scope agree.

1. **Guest-only MVP.** FRD §2.1 and FR-09 assume registered users. We keep the *ownership model* but make the owner an anonymous user created lazily on first request and identified by an opaque session cookie. Consequences:
   - FR-09.1 / AT-12 (cross-user access denied) still apply and are testable with two sessions.
   - "Persistent history" (FR-02, AT-10) holds **per browser** until the cookie is lost. Document this in the UI ("Your games are stored in this browser's session").
   - FR-09.7 (stricter guest limits) becomes the *only* limit tier. Add a **retention policy**: purge anonymous users + their data after N days of inactivity (default 30).
   - FR-09.2/09.3 (credentials) are deferred. Schema is designed so a later "claim account" step attaches credentials to the existing `users` row without migrating game data.
2. **Chess.com import by URL.** The Published Data API has no lookup-by-game-id. Resolve by URL + username hint (scan that user's archives for the game id), otherwise ask the user to paste PGN. Username bulk import is unaffected.
3. **Classification definition.** FRD leaves thresholds undefined. We define loss in **win-probability points** (mover's perspective), not raw centipawns — see §5.
4. **"Missed win" and "key positions"** (FR-04.5, FR-07.4) get concrete, configurable definitions in §5.
5. **Licensing.** Stockfish *and* python-chess are GPL-3.0. Hosting as a service is fine; if the Docker images or source are distributed, the whole backend must be GPL-3.0-compatible. Frontend board stack chosen to avoid adding more GPL: `react-chessboard` (MIT) + `chess.js` (BSD), **not** Chessground (GPL).
6. **Cache key** for FR-02.7: `(game_id, engine_name+version, limit_type, limit_value, multipv, classification_config_hash)`.

---

## 2. Tech stack

**Backend:** Python 3.12, FastAPI, Pydantic v2, SQLAlchemy 2.0 (async or sync — see note), Alembic, PostgreSQL 16, `python-chess`, `httpx` (external APIs), `slowapi` (rate limits), `pytest` + `pytest-asyncio`, `ruff`, `mypy`.
**Frontend:** React 18 + TypeScript + Vite, TanStack Query, `react-chessboard`, `chess.js`, Recharts (eval graph), React Router, Vitest + Testing Library, Playwright (e2e).
**Infra:** Docker Compose; Stockfish installed in the worker image (pinned version, not committed to repo).

*Note:* Use sync SQLAlchemy in the worker (simple, one job at a time) and async in the API. Share models/session factories via a common package.

---

## 3. Repository layout

```
Chess/
  FRD.md
  IMPLEMENTATION_PLAN.md
  docker-compose.yml
  .env.example
  backend/
    pyproject.toml
    alembic/
    app/
      main.py                 # FastAPI app factory, middleware, routers
      config.py               # Settings (env), engine limits, thresholds path
      db.py                   # engine/session
      models/                 # SQLAlchemy models
      schemas/                # Pydantic request/response
      api/                    # routers: sessions, imports, games, analysis, settings
      services/
        sessions.py           # anonymous session issue/validate
        importing/            # pgn.py, chesscom.py, lichess.py, fingerprint.py
        analysis/             # engine.py, evaluator.py, normalize.py, runner.py
        classification/       # winprob.py, classify.py, summary.py, config.py
        jobs/                 # queue.py (enqueue/claim/heartbeat/reap)
        retention.py
    worker/
      main.py                 # poll loop: claim job -> run -> finalize
    tests/
      unit/ integration/ fixtures/   # PGNs: normal, mate, malformed, long, multi-game
  frontend/
    src/
      api/ (typed client)   pages/ (Home, Import, Review, History, Settings)
      components/ (Board, MoveList, EvalGraph, Summary, JobStatus, ...)
      hooks/ (useKeyboardNav, useJobPolling)
```

---

## 4. Data model (PostgreSQL)

```
users            id uuid PK, created_at, last_seen_at            -- anonymous owner; later gains email/password_hash
sessions         id uuid PK, user_id FK, token_hash (unique), created_at, expires_at
games            id uuid PK, owner_id FK users, source enum(pgn,chesscom,lichess),
                 external_id null, fingerprint text, pgn text,
                 white, black, white_elo null, black_elo null, result, played_at null,
                 time_control null, opening_name null, eco null, ply_count,
                 current_analysis_id null FK analysis_runs, created_at
                 UNIQUE(owner_id, fingerprint); INDEX(owner_id, played_at desc)
analysis_runs    id uuid PK, game_id FK, status enum(running,completed,failed),
                 engine_name, engine_version, limit_type enum(depth,nodes,movetime), limit_value,
                 multipv, class_config_hash, class_config jsonb, summary jsonb null,
                 error text null, started_at, finished_at null
                 INDEX(game_id), UNIQUE(game_id, cache_key) WHERE status='completed'
analysis_positions  run_id FK, ply int (0 = start position, k = after k-th half-move),
                 fen, score_cp int null, mate int null,           -- WHITE perspective, both null = unavailable
                 win_pct real null, best_move_uci null, pv_uci text[] null, depth_reached int,
                 played_move_uci null, played_move_san null,
                 classification enum(brilliant,great,best,good,inaccuracy,mistake,blunder) null,
                 loss_pct real null, missed_win bool default false,
                 alt_best_move_uci null, alt_score_cp null, alt_mate null,   -- 2nd PV line (multipv=2)
                 is_sacrifice bool null,
                 PK(run_id, ply)
analysis_jobs    id uuid PK, game_id FK, run_id FK null, owner_id FK, status enum(queued,running,completed,failed,cancelled),
                 attempts int, max_attempts int, params jsonb,
                 progress_done int, progress_total int,
                 locked_by null, heartbeat_at null, error null,
                 created_at, started_at, finished_at
                 INDEX(status, created_at)
```

Key rules:
- **Missing ≠ 0.** `score_cp` and `mate` are both nullable; "unavailable" is `NULL/NULL`. Exactly one of them set for an evaluated position (CHECK constraint).
- **Atomic visibility.** A game's review is only shown via `games.current_analysis_id`. A new run writes positions incrementally under its own `run_id` while `running`; on success a single transaction sets `status=completed`, computes summary, and swaps `current_analysis_id`. A failed/aborted run never touches the pointer → prior results survive (NFR-02, FR-08.7, AT-11).
- Deleting a game cascades to runs, positions, jobs (FR-02.4).

---

## 5. Core logic (the highest-risk part — built and tested first)

### 5.1 Evaluation normalization
- Every stored score is **White's perspective** (`PovScore.white()`), centipawns or mate-in-N (signed: +N White mates, −N Black mates).
- Convert to win probability (Lichess logistic): `win_pct(cp) = 50 + 50 * (2 / (1 + exp(-0.00368208 * cp)) - 1)`. Mate → 100 / 0. Convert to mover's perspective by `100 - win_pct` when Black moves.
- Graph y-value: clamp win% (or clamp cp to ±1000 with mate pinned to the edge) and **flag mate points** so they render distinctly (FR-06.5).

### 5.2 Search strategy
- N half-moves → **N+1 searches** (the eval *after* move k is the eval *before* move k+1). Each search stores `best_move`, `pv`, score.
- Loss for move k, from mover's perspective: `loss = win_pct_mover(before) − win_pct_mover(after_played)`; clamp ≥ 0.
- If the played move equals the engine best move, loss = 0 without a second search.
- **`multipv=2` by default** (needed for the Great/Brilliant "only move" test in §5.3). The 2nd line is stored in `alt_*` columns on `analysis_positions`. `multipv=1` remains selectable for faster runs; Great/Brilliant are then simply not awarded.
- Terminal positions (checkmate/stalemate/draw by rule): do not search; assign score directly (mate 0 / draw cp 0 as a *real* value, distinct from unavailable).
- Limits: configurable `depth` (default ~16–18) or `nodes`; per-move `movetime` safety cap; whole-job timeout; max plies per game (e.g. 300).

### 5.3 Classification (config in YAML/env, hashed into the cache key — FR-04.6)
Modelled on Chess.com's published Game Review rules (support article "How are moves classified?", fetched 2026-10-21). Defaults are tunable after dogfooding; loss is in win% points from the mover's perspective, which maps onto Chess.com's "expected points lost" (0–1) scale.

| Class | Rule (ours) | Chess.com's published rule |
|---|---|---|
| Brilliant | best or nearly best (loss ≤ 2) **piece sacrifice**; not left in a bad position (win% after ≥ 45); the best alternative is not already winning (< 80) | "a good piece sacrifice"; "best or nearly best"; not bad afterwards; not completely winning without it |
| Great | played the top move **and** it was an only move (2nd line ≥ 15 pts worse, position undecided or long mate) | "critical to the outcome": only good move, loss→equal, equal→win |
| Best | engine's top move, or loss < 0.5 | expected-points loss 0.00 |
| Excellent | loss 0.5–2 | 0.00–0.02 |
| Good | loss 2–5 | 0.02–0.05 |
| Inaccuracy | loss 5–10 | 0.05–0.10 |
| Mistake | loss 10–20 | 0.10–0.20 |
| Blunder | loss ≥ 20 | 0.20–1.00 |

Differences from Chess.com, deliberately: their Brilliant/Great/Miss thresholds vary with the player's rating (we have no rating model), and "Book" is not implemented (no opening book). Their text for Brilliant says only "a good piece sacrifice", so the sacrifice test is ours:
- *Sacrifice:* material (P=1, N/B=3, R=5, Q=9) is lower by ≥ 2 after the opponent's best reply in the engine line and is **not regained within the next `sac_horizon` (2) plies** — a piece genuinely given up, not a trade.
- "Best alternative" = the second engine line when the played move is the top move (otherwise the top line). Without a second line (1 engine line) the position's own evaluation is used.
- A sacrifice followed by an *immediate* mate (mate in 1) is not Brilliant; mate in 2 or more is allowed (the smothered mate).
- Great and Brilliant need ≥ 2 engine lines to be awarded reliably.

Class priority when several apply: Brilliant > Great > Best > Excellent > Good > Inaccuracy > Mistake > Blunder; `missed_win` is shown as "Miss" and is orthogonal. Summary counts all classes per side; only Inaccuracy/Mistake/Blunder count as "errors" (FR-07.2).

- **Miss (`missed_win`):** mover had `win_pct_before ≥ 85` (or a forced mate) and after the move `< 60` (or no longer a forced mate).
- **Mate handling:** moving from mate-for-you to non-mate, or allowing a forced mate against you, is handled by win% = 100/0 so it naturally yields a blunder; tested explicitly.
- **Key positions (FR-07.4):** plies that cost at least an inaccuracy (top-K by loss), any ply with `|Δwin%| ≥ swing_threshold`, plus `missed_win` plies. (Tiny losses are never flagged.)
- **FR-04.7:** classification is data; explanations (future LLM) are separate fields and never overwrite it. Summary copy avoids "objectively bad" language (FR-07.6).
- **Engine lines:** the user chooses 1–5 lines per analysis (`multipv`, server cap `MAX_MULTIPV`); all lines are stored and the review UI lets the user show any number up to what was analyzed.

Sources: [Chess.com support: How are moves classified?](https://support.chess.com/en/articles/8572705-how-are-moves-classified-what-is-a-blunder-or-brilliant-move).

### 5.4 Testing (FR-04 acceptance)
Pure-function unit tests with hand-built evaluation sequences: ordinary move, large loss, mate-in-N found/missed/allowed, perspective flip for Black, equal-loss symmetry, null-eval handling, terminal positions. These need no Stockfish and run fast.

---

## 6. Background jobs

- **Enqueue:** `POST /games/{id}/analysis` validates limits, checks cache (return existing completed run if key matches → FR-02.7), else creates `analysis_run(running)`-less job in `queued`.
- **Claim:** worker runs `SELECT … FOR UPDATE SKIP LOCKED` on `queued` jobs; sets `running`, `locked_by`, `heartbeat_at`.
- **Heartbeat + reaper:** worker updates `heartbeat_at` every few seconds; reaper requeues (attempts < max) or fails jobs with stale heartbeat — handles worker crash/restart (AT-11).
- **Concurrency control (FR-08.5):** each worker process owns exactly one Stockfish subprocess and runs one job at a time; `WORKER_CONCURRENCY` = number of worker processes; Stockfish `Threads`/`Hash` set from config. Per-session cap on queued+running jobs (e.g. 2).
- **Progress:** `progress_done/total` updated per position; frontend polls `GET /jobs/{id}` (1–2 s). SSE is a post-MVP nicety.
- **Retry safe:** retry creates a *new run*; idempotent because the pointer swap happens only on completion.
- **Timeouts:** per-search `asyncio`/`engine.analyse` timeout and whole-job deadline → `failed` with explicit reason; engine process is killed and restarted on hang.

---

## 7. API surface (all JSON, OpenAPI auto-documented)

```
POST /api/session                      issue anonymous session (cookie set; idempotent)
POST /api/imports/pgn                  {pgn_text} | multipart .pgn -> parsed games, saved
POST /api/imports/preview              {source, username, max} -> metadata list (not saved)
POST /api/imports/commit               {source, username, external_ids[]} -> saved games + dedupe report
POST /api/imports/url                  {url, username_hint?}
GET  /api/games?query&source&result&player&from&to&page
GET  /api/games/{id}                   metadata + pgn + current analysis summary/status
DELETE /api/games/{id}
POST /api/games/{id}/analysis          {limit_type, limit_value} -> job
GET  /api/games/{id}/analysis          positions + classifications + summary (current run)
GET  /api/jobs/{id}   POST /api/jobs/{id}/retry
GET/PUT /api/settings                  default analysis limits (stored per user)
DELETE /api/me/data                    delete everything for this session
GET  /api/healthz
```
Every query is scoped by `owner_id` taken from the session — never from a client-supplied id (AT-12). Return **404** (not 403) for others' resources.

**Anonymous session security:** 256-bit random token, only its hash stored; cookie `HttpOnly; Secure; SameSite=Lax`; CSRF mitigated by SameSite + requiring `Content-Type: application/json`/custom header on mutating requests; sliding expiry.

---

## 8. Import details

- **PGN:** `python-chess` `read_game` loop; max upload 1 MB, max 50 games per paste; reject illegal-move games with the offending move number in the error (AT-02); extract Event/Site/White/Black/Result/Date/Elo/TimeControl/ECO/Opening headers.
- **Fingerprint (FR-01.8):** `source:external_id` when known; else `sha256(white|black|date|normalized SAN movetext)`.
- **Chess.com:** `GET /pub/player/{u}/games/archives` → fetch monthly archives newest-first until N games; **serial requests, descriptive `User-Agent`, backoff on 429**; handle 404 (no user), 410, empty archives.
- **Lichess:** `GET /api/games/user/{u}?max=N&opening=true&clocks=false` with `Accept: application/x-ndjson`; single-game via `/game/export/{id}`; respect 429 `Retry-After`; one request at a time.
- Server-side TTL cache (in DB or in-memory) for archive listings to avoid hammering APIs; username regex validation; fixed allowlisted hosts (no SSRF surface).

---

## 9. Frontend

- **Review page:** board (react-chessboard, orientation toggle, last-move + best-move arrow), move list with classification glyphs/colors, eval graph (click → select ply, synced), engine line/PV panel, summary card, job-status banner.
- **Variation exploration (FR-05.6/05.7):** local-only `chess.js` state branched from the selected ply; "Return to game" button; never sent to the server, so it can't overwrite saved data.
- **Keyboard:** ←/→ prev/next, Home/End, F flip board.
- **Responsive:** board on top and move list/graph in tabs below ≤ 768 px; tap targets ≥ 44 px (AT-14).
- **States:** loading skeletons, empty, error, "analysis incomplete" never rendered as complete (FR-03.8).
- **Pages:** Home (import entry + recent games), Import (tabs: PGN file/paste/Chess.com/Lichess/URL; fetched-games checklist), Review, History (search/filter), Settings (default limits, delete-all-data, retention notice).

---

## 10. Milestones

Ordered so the riskiest logic lands first and every milestone is demoable.

| # | Milestone | Deliverables | Exit criteria |
|---|---|---|---|
| **M0** | Scaffolding | Repo layout, Docker Compose (db/api/worker/frontend), CI (ruff, mypy, pytest, vitest), Alembic baseline, `/healthz` | `docker compose up` brings up all services |
| **M1** | Core domain (no UI) | `normalize`, `winprob`, `classify`, `summary` + exhaustive unit tests; engine wrapper around python-chess + Stockfish; CLI to analyze a PGN | Unit tests for FR-04 cases pass; AT-03/04 pass via CLI on fixtures |
| **M2** | Sessions + PGN import + game storage | Anonymous session, models/migrations, PGN upload/paste, fingerprint dedupe, list/get/delete games, owner scoping | AT-01, 02, 09, 12 pass (API tests) |
| **M3** | Job system | Queue, worker, heartbeat/reaper, progress, limits, cache reuse, atomic run promotion, retry | AT-10, 11, 13 pass; kill-worker test recovers |
| **M4** | Review UI | Board, move list, navigation, eval graph, PV panel, summary, job polling, variation mode | AT-05, 06 pass (Vitest + Playwright) |
| **M5** | External imports | Lichess + Chess.com username/URL import with preview/select, rate limits, error mapping (mocked in CI, one live smoke test) | AT-07, 08 pass |
| **M6** | History, settings, privacy | History search/filter, settings, delete-all, retention purge job | FR-02 / 4.1 complete |
| **M7** | Hardening & release | Rate limiting, upload/size caps, mobile pass, a11y pass, perf measurement on 40/80/150-ply games, README + deploy docs, license notice | AT-01…14 green; MVP criteria §9 met |

Dependencies: M1 → M3; M2 → M3, M4, M5; M4 needs M3 only for live status (can start against fixtures after M1/M2).

---

## 11. Acceptance-test mapping

| AT | Covered in | Test type |
|---|---|---|
| 01, 02 | M2 | API integration |
| 03, 04 | M1 (+M3) | Engine integration (low depth, in worker image) |
| 05, 06 | M4 | Playwright + component |
| 07, 08 | M5 | Mocked HTTP + live smoke |
| 09 | M2 | API integration |
| 10 | M3 | Compose restart script |
| 11 | M3 | Kill worker mid-job |
| 12 | M2 (+all routes) | Parametrized two-session test over every endpoint |
| 13 | M3/M7 | API + worker |
| 14 | M7 | Playwright mobile viewport |

---

## 12. Risks & mitigations (additions to FRD §10)

| Risk | Mitigation |
|---|---|
| Anonymous-cookie loss = history loss | Clear UI notice; "Export my games (PGN)" in Settings; plan account-claim for post-MVP |
| Open anonymous endpoints invite abuse (CPU) | Per-session **and per-IP** job caps, global queue-length cap (reject with 429 + clear message), low default depth |
| Chess.com URL lookup limitation | Require username hint or PGN paste; surface clearly in UI |
| Stockfish hangs / OOM | Subprocess kill + restart, container memory limit, job deadline |
| Threshold tuning feels wrong | Config hash in cache key makes re-classification cheap; classification can re-run from stored evals **without re-searching** |
| GPL obligations | Don't vendor binaries; pin versions in Dockerfile; add LICENSE/NOTICE; revisit before any public image distribution |

---

## 12a. Progress log

- **M0 done** — Docker Compose stack (db, api, worker, frontend) builds and runs; `/api/healthz` works directly (host port **8010**) and through the Vite proxy. DB is not published to the host (ports 5432/8000 were taken on the dev machine). Python and Node run only inside containers.
- **M1 done** — `app/services/classification/{score,config,classify,summary}.py`, `app/services/analysis/{engine,runner}.py`, `app/cli.py`. 42 unit tests + 6 Stockfish integration tests pass (AT-03, AT-04 covered at engine level).
  - Deviations from §4–§5: terminal positions use `Score.final` ("1-0"/"0-1"/"1/2-1/2") instead of a mate-0 value, so `analysis_positions` needs a `terminal_result` column (the cp/mate CHECK becomes "exactly one of cp, mate, terminal_result, or all null = unavailable"). The Great "rescue/swing" clause was dropped as unreachable; delivering a short mate (≤ 2 moves) is never Great or Brilliant.
- **M2 done** — anonymous sessions (`sid` cookie: HttpOnly, SameSite=Lax, only the SHA-256 of the token stored, sliding 30-day expiry), `users`/`sessions`/`games` tables with Alembic migration `0001` (applied automatically when the `api` container starts), PGN parser/validator, `POST /api/imports/pgn` and `/pgn/upload`, `GET /api/games` (search/source/result/date filters, pagination), `GET /api/games/{id}` (metadata + stored PGN + per-ply SAN/UCI/FEN), `DELETE /api/games/{id}`. 81 tests pass (AT-01, 02, 09, 12 covered; AT-10 verified manually by restarting the API and DB containers).
  - **CSRF:** every mutating `/api/*` request must carry `X-Requested-With: ChessReviewLab` (403 otherwise). The Swagger "Try it out" button therefore can't send POST/DELETE; use the frontend or curl.
  - **Dedupe:** fingerprint = hash of players, date, start position and move list (not source or headers), so the same game imported via PGN and later via Lichess/Chess.com is still caught. A unique `(owner, source, external_id)` index handles API-sourced ids.
  - **Stored PGN** is python-chess's canonical export of each game (headers, moves, comments, variations), not the byte-for-byte input.
  - Import is limited to 1 MB / 50 games per request; only standard chess is accepted (variants and Chess960 are rejected with a clear message). Over-long games import fine but are rejected at analysis time (`MAX_PLIES`, default 300).
  - A request whose games are *all* invalid returns 422 with `detail` plus per-game `errors`; mixed results return 200 with `imported`, `duplicates`, `errors`.
  - The analysis tables, `games.current_analysis_id` and the `analysis_status` field (currently always `"none"`) arrive with M3.
- **M3 done** — migration `0002` (`analysis_runs`, `analysis_positions`, `analysis_jobs`, `games.current_analysis_id`); Postgres queue (`FOR UPDATE SKIP LOCKED`); worker (`backend/worker/`); analysis endpoints. 104 tests pass (23 new: fake-engine failure paths plus real-Stockfish pipeline and kill tests). Verified live against the running containers: normal run with progress, SIGTERM mid-job (job requeued without using an attempt), and SIGKILL mid-job (reaper requeued it, a fresh worker redid it, final review complete: AT-11).
  - **API:** `POST /api/games/{id}/analysis` (body optional: `depth`, `nodes`, `multipv` 1|2; 202 + job, or 200 `cached:true` when a completed run with identical settings exists), `GET /api/games/{id}/analysis` (current completed review: per-ply eval/best move/PV in SAN/second-best line/classification/loss, plus run settings and summary), `GET /api/jobs/{id}`, `POST /api/jobs/{id}/retry` (failed jobs only). `GET /api/games[/{id}]` now report `analysis_status` (none|queued|running|completed|failed) and `has_analysis`; the detail also has `latest_job`.
  - **Safety rules implemented:** results are written incrementally under a `running` run that no endpoint exposes; a single transaction at the end writes classifications, marks the run completed, swaps `games.current_analysis_id` and completes the job. Failed/interrupted runs lose their partial rows. A failed re-analysis leaves the old review (and `analysis_status: completed`) intact. A worker that lost its job to the reaper cannot overwrite it (all job writes are guarded by `status='running' AND locked_by=me`).
  - **Limits:** depth/nodes caps (`MAX_DEPTH`, `MAX_NODES`), `MAX_PLIES`, per-position time cap, whole-job timeout, max 2 active jobs per user, queue length cap, and one active job per game (enforced by a partial unique index, so it is race-proof). One Stockfish and one job per worker process; scale with `docker compose up -d --scale worker=N`.
  - **Failure handling:** engine crash → engine rebuilt, job retried once (`JOB_MAX_ATTEMPTS`); watchdog thread SIGKILLs an engine that makes no progress for `MAX_SECONDS_PER_POSITION + 30s`; reaper (every 15 s) requeues jobs with no heartbeat for `JOB_STALE_SECONDS`; any position without an evaluation fails the job rather than producing a partial review.
  - **Cache key:** `(engine name+version, depth, nodes, multipv, classification-config hash)` per game. A completed run with the same key is reused; switching settings back re-selects the earlier run instead of recomputing.
  - Progress is exposed by polling `GET /api/jobs/{id}` (SSE remains optional).
- **M4 done** — frontend (React 18 + TypeScript + Vite, **Tailwind CSS v4**, TanStack Query, react-router, react-chessboard, chess.js): Home (paste/upload PGN, recent games with status chips, delete) and Review page (board with orientation flip, eval bar, player bars, move list, hand-written SVG evaluation graph with click-to-seek, mate markers and swing ticks, engine panel, summary card, analysis start/progress/failure/retry panel). Keyboard: ←/→, Home/End, F, Esc. Variations (click an engine line or drag a piece) are local state only. Layout: two columns on wide screens, tabs on phones.
  - **Verification:** 49 Vitest/Testing-Library tests; 8 Playwright browser tests (desktop + Pixel 5 phone viewport, real Stockfish, real drag-and-drop on mouse and touch) run via `docker compose --profile e2e run --rm e2e`; screenshots in `e2e/screenshots/`. The suite passed 4/4 consecutive runs after fixing test-timing issues.
  - **Found and fixed while viewing screenshots:** key positions listed moves that cost fractions of a point as "Large evaluation loss"; the review header printed a redundant "*" result.
  - **Dev ergonomics:** the worker now restarts on backend code changes (`watchfiles`, graceful SIGTERM so a running job is requeued without using an attempt); Vite `allowedHosts` includes the compose service name for the browser-test container.
- **M4b (user-requested additions) done** — (1) **multiple engine lines**: choose 1–5 lines when analyzing; all lines are stored (`analysis_positions.lines`) and served; the review shows 1…N lines (user-selectable) with evaluations and clickable continuations, plus a coloured arrow per line on the board; (2) **a quality mark on every move**, chess.com-style: a badge on the destination square of the last move and a glyph on every move-list entry (Brilliant `!!`, Great `!`, Best `★`, Excellent `✓`, Good `○`, Inaccuracy `?!`, Mistake `?`, Blunder `??`; "Miss" shown in the engine panel); new **Excellent** class; (3) **Brilliant redefined from research** on Chess.com's published rules (see §5.3): no longer requires an only-move, uses the best-alternative "not already winning" test. Migration `0003`. Backend 116 tests, frontend 49.
- **Next: M5** — Chess.com / Lichess import (username + game URL, preview and pick games).

## 13. Resolved decisions (from discussion)

1. **Analysis depth:** default 16, **user-adjustable** in Settings and per analysis request (depth / nodes), with server-side hard caps from env so requests can't exceed what the machine can handle.
2. **Retention:** anonymous data purged after **30 days idle** (configurable via env).
3. **Deployment target:** **local use first.** Compose publishes ports on `127.0.0.1` only. M7 abuse protection is reduced to per-session job caps and a queue-length cap; the `Secure` cookie flag is env-driven (off on local http, on for any public deployment); public-hosting hardening becomes a documented follow-up checklist.
4. **Evaluation display:** show **both** the Stockfish evaluation (e.g. +0.8 / #3, White's perspective) and win% / eval bar.
5. **Move labels:** **Brilliant, Great, Best, Good, Inaccuracy, Mistake, Blunder** plus the `Missed win` flag (definitions in §5.3). This adds `multipv=2` and a sacrifice detector.

### Milestone impact
- **M1** grows: material/sacrifice detector, only-move logic, extra fixtures and tests for Brilliant/Great (positive and negative cases).
- **M4** grows slightly: seven class glyphs/colours, best vs. 2nd-best line in the engine panel.
- **M7** shrinks: no public-abuse hardening beyond session job caps.

### Remaining caveats
- Brilliant/Great are heuristic and will need tuning against real games once the review UI exists; expect to iterate on `great_gap`, `sac_horizon` and material thresholds. Classification re-runs from stored evaluations and PVs, so tuning needs no re-search.
- Guest-only means history is tied to the browser cookie; PGN export of saved games is in scope (M6) to mitigate.
