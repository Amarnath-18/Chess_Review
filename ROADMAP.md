# Roadmap: Phase 2 (after the MVP)

Status: **proposal, for review.** Nothing here is built yet. The MVP (milestones M0–M7) is done and described in
[IMPLEMENTATION_PLAN.md](IMPLEMENTATION_PLAN.md); requirements are in [FRD.md](FRD.md). When this plan is approved the
new requirements below (FR-11…FR-19, AT-15…) get folded into the FRD as v1.1.

## 1. Decisions made

| Question | Decision |
|---|---|
| What matters most | **Understand games better**, **train and improve**, and **convenience** (all three) |
| "Why" explanations of mistakes | An **LLM, grounded in engine output** (not free-form chess opinions); **free model, not Claude** |
| Access for friends | **One invite code per friend**, revocable |
| Sharing reviews between people | **Not now**; each person's reviews are private |
| Accounts | **Stay anonymous** for now (browser session, PGN export as the backup) |
| Audience | **You plus a few friends or students** on a small private server |

What follows from them:

- A private server needs a **gate** so strangers cannot use your CPU or the explanation model: one revocable invite code
  per friend (§M11). Accounts stay out of scope, so this is deliberately small.
- The LLM is a **free, non-Claude model on a hosted free tier** (provider chosen by a bake-off), called from the server
  through a provider-neutral client. It must be **opt-in, capped and honest**: off by default, usage limits, a privacy notice, and
  every explanation labelled as AI-written with the engine's own lines beside it (this is FR-10.5 from the FRD).
- Without accounts, the app does not know **which player is "you"** in a game. Stats and puzzles need that, so Settings
  gets a "my names" list (§M10). Sync works by remembering usernames in the browser session (§M9), not by login.

## 2. Principles carried over (how every milestone is delivered)

1. Same bar as the MVP: unit + API + browser tests, accessibility audit (axe, light/dark, phone), screenshots looked at.
2. **Never present guesses as engine facts.** Anything derived (accuracy, stats, explanations) says what it is.
3. Small shippable steps. A milestone is done when its acceptance tests pass on the **production** stack too.
4. Measure before promising (the benchmark approach): costs and timings in the docs come from real runs.
5. Migrations are additive and reversible; existing reviews keep working.

## 3. Order and dependencies

```
M8  Richer review ───────────────┐          (accuracy, book moves, clocks, partial results, annotated PGN)
M9  Convenience ─────────────────┤          (analyze-all, auto-analyze, new-game check, notes/tags)
M10 Train ◄──────── needs M8 data (book/phase), "my names"      (retry-the-move, puzzles, dashboard)
M11 Explain ◄────── needs M8 facts, invite gate, usage limits    (LLM explanations)
```

M8 and M9 are independent and can be done in either order; M10 and M11 build on M8. Suggested order: **M8 → M9 → M10 → M11.**
Sizes are relative effort (S ≈ a day, M ≈ 2–3 days, L ≈ a week of the work done so far).

---

## M8. Richer review (understand)

**Status: done (not committed).** All five items built and tested: 348 backend tests, 158 frontend tests, and the browser
suite (desktop + phone, including the accessibility audit) pass. Deviations from the plan as first written: a book move
is never relabelled over a Mistake or Blunder (the dataset contains Fool's Mate), a move that ends the game is never
book, and "time trouble" is 10% of the starting time capped at 30 s.

Everything here uses data we already have, so no new infrastructure.

| # | Feature | Size |
|---|---|---|
| 8.1 | **Accuracy score** per side and per game | S |
| 8.2 | **Book moves and opening names** per move (Chess.com's "Book") | M |
| 8.3 | **Clock analysis**: time per move, clock graph, time-trouble flags | M |
| 8.4 | **Partial results while analyzing** | M |
| 8.5 | **Annotated PGN export** (evaluations and symbols embedded) | S |

**8.1 Accuracy.** Per-move accuracy from the win-probability loss we already store, combined into a game score. Use the
formula Lichess has published (reimplemented from the documentation, not copied), and label it "Accuracy" with a footnote
that it is not Chess.com's number (theirs is unpublished). *Before coding:* read the published description and confirm the
constants; add unit tests with hand-computed values. API: `summary.accuracy {white, black}` added at analysis time (new
runs) and computed on read for old runs (it only needs stored losses), so no migration is needed.

**8.2 Book / openings.** Vendor the open `lichess-org/chess-openings` dataset (CC0: ECO code, name, move sequence) as a
data file; build a position→opening lookup (positions keyed without move counters, so transpositions match). A move whose
resulting position is in the dataset is "Book" (a new quiet mark, not a quality class: it never overrides Best/Brilliant
and is excluded from error counts). The review header shows the opening for the deepest book position; the history page
gets an opening filter. Replaces the `ECOUrl`/`Opening` header heuristics where the dataset knows better.
Risks: dataset licence note in the README; some games start from a FEN (no book).

**8.3 Clocks.** PGNs from Chess.com/Lichess carry `[%clk h:mm:ss]` comments, which `python-chess` reads. From the stored PGN
(no analysis needed) compute per move: clock remaining, time spent (using the increment from `TimeControl`), and a
"time trouble" flag (default: under 10% of the base time or under 30 s). `GET /api/games/{id}` gains `clocks[]` when present.
UI: a clock graph tab (both sides, click to jump), time spent in the move-list tooltip, and a sentence in the summary such as
"3 of White's 4 blunders came with less than 30 s left". Games without clocks show nothing (never a zero).

**8.4 Partial results.** Positions are already saved while the job runs but hidden. Add `GET /api/games/{id}/analysis/partial`
(owner only, the active run's rows so far), classify the available moves on the fly with the existing pure functions, and let
the review page show the live graph and marks growing with a banner "Analyzing… 23 of 81 positions; not final".
The summary stays hidden and the atomic pointer swap is untouched, so FR-03.8 (never present incomplete analysis as
complete) still holds: partial data is clearly labelled and never stored as the review.

**8.5 Annotated PGN.** Option "with analysis" on the single-game and bulk export: `{[%eval 0.31]}` / `[%eval #3]` comments
and NAGs (`!!`, `!`, `?!`, `?`, `??`) as the common tools expect, plus "Best was Nf3 (+0.3)" comments on errors.
Test: round-trip through `python-chess` and a re-import (the game must still parse and dedupe).

**Acceptance (AT-15…AT-19):** accuracy values match hand-computed fixtures; a known opening game shows the right name and
book marks and a novelty ends them; a clocked game yields correct times and flags, an unclocked one shows no clock UI; a
running analysis shows partial marks but `GET …/analysis` still returns 404 until completion; an annotated export re-imports
cleanly. Browser + a11y tests for each new view.

---

## M9. Convenience

**Status: done (not committed).** Built as planned, with these differences: "check for new games" re-reads the latest
10/20/50 games and lists those not saved yet (instead of a `since` fetch, which reuses the existing paced fetchers and
needs no new upstream calls); a batch leaves one of the person's job slots free; cancelling a running job uses the
existing heartbeat check (its next progress report fails, so it stops and discards its partial run). The batch is fed
from the worker's idle loop, so it never waits for the maintenance interval between games. Lichess imports now ask for
clock comments so the Time section works for them too.

| # | Feature | Size |
|---|---|---|
| 9.1 | **Analyze all** (batch) with a queue view and cancel | L |
| 9.2 | **Auto-analyze after import** (setting) | S (on top of 9.1) |
| 9.3 | **Saved sources and "check for new games"** (sync without accounts) | M |
| 9.4 | **Notes, tags, favourites** | M |

**9.1 Batch.** Today a person may have 2 active jobs. A batch needs more without flooding the queue: new table
`analysis_batches(id, owner_id, status, settings, total, done, failed, created_at)`; the worker's maintenance loop keeps a
small number of each batch's jobs queued at a time (a fair share per user), so one batch never starves others. Adds a
`cancelled` job status (migration: widen the CHECK constraint) and a cancel flag the worker checks between positions (the
partial run is discarded, as for shutdown). `POST /api/analysis/batches {game_ids | filter, depth, multipv}` (filter =
the history filters, "everything not analyzed yet"), `GET /api/analysis/batches/{id}`, `POST …/cancel`. UI: a "Queue" page
and an "Analyze N unanalyzed games" button on the Games page, showing the *estimated range* for the whole batch (reusing the
estimate model). Guards: per-batch cap (e.g. 100 games), global queue cap still applies, time estimate shown first.

**9.2 Auto-analyze.** Setting `auto_analyze` (off by default; uses the user's default depth/lines). After any import that
saves new games, create a batch for them; the import result says "Analyzing 6 new games". Capped per import so a huge import
cannot queue everything silently.

**9.3 Saved sources.** "Remember this Chess.com/Lichess account" on a successful search stores
`linked_sources(owner_id, source, username, last_synced_at, newest_game_time)`. A **Check for new games** button (Games page
and Settings) fetches only what is new (Lichess supports `since`; Chess.com via the newest monthly archives), previews the
count, imports on confirm (or automatically, with auto-analyze, if the user opted in). Reuses the existing fetchers, pacing
and cooldown. Not background polling: it runs when you ask, which keeps rate-limit and privacy behaviour simple.
Usernames are the user's own saved settings, deleted with "delete everything".

**9.4 Notes, tags, favourites.** `games.favorite`, a game-level note (≤ 5000 chars), per-move notes
(`game_notes(game_id, ply, text)`), and `game_tags(game_id, tag)` (≤ 20 tags, short). History filters for favourite and
tag; notes and tags included in the annotated export as PGN comments if chosen. All owner-scoped like everything else; all
included in export and deletion.

**Acceptance (AT-20…AT-24):** a batch of N games finishes with correct counts and can be cancelled mid-run without
corrupting existing reviews; auto-analyze queues exactly the new games; "check for new games" imports only new ones and is
idempotent; another user's batch/sources/notes are invisible; delete-everything removes all of it. Fault tests as for M3
(worker killed mid-batch resumes).

---

## M10. Train (improve)

**Status: done (not committed).** Built as planned: "my names" in Settings (remembered accounts count too), retry-the-move
(judged against the saved lines; a move outside them is "not judged", never "wrong"), the puzzle trainer with Leitner
boxes, and the statistics page with sample sizes and "too few" labels. Additions beyond the plan: every board action also
has a typed-move box (`Nf3` / `e2e4`) so it works from a keyboard and with screen readers, and changing your names or
remembered accounts makes games be looked at again for puzzles. Deferred: "most common error situations" (waits for the
position facts in M11), and the puzzle's follow-up moves (single-move puzzles only for now).

| # | Feature | Size |
|---|---|---|
| 10.0 | **"My names"** in Settings (who is you) | S |
| 10.1 | **Retry this move** in the review | M |
| 10.2 | **Puzzle trainer** from your own mistakes | L |
| 10.3 | **Weakness dashboard** and **opening statistics** | L |

**10.0 My names.** A list of player names (and the saved sources' usernames, case-insensitive) that identifies "you" in a
game. A game where neither side matches is simply excluded from personal stats and puzzles, and says so.

**10.1 Retry this move.** On your Inaccuracy/Mistake/Blunder/Miss, offer "Try to find a better move": the board returns to
the position before the move; you play; it is judged **against the lines already stored** for that position (no new engine
call): success if your move is among the top lines and within the Excellent band of the best; otherwise "not among the
engine's top lines, try again / show answer". Honest limit, stated in the UI: a good move outside the stored lines is
reported as "not found in the engine's top N". Client-only (nothing saved), keyboard accessible via move buttons as well as
drag.

**10.2 Puzzles.** Source: your own analyzed games. A position becomes a puzzle when you made a Mistake/Blunder/Miss there,
the loss is large, and the best move is clearly the best (gap to the second line ≥ 10 points, so the answer is unambiguous).
Table `puzzles(owner_id, game_id, ply, fen, best_uci, accepted_uci[], played_uci, loss, box, due_at)` unique per
(game, ply), created lazily when `/train` is opened. Scheduling: Leitner boxes (right → next box, later due; wrong → box 1,
due soon) with `puzzle_attempts` history. UI `/train`: the next due puzzle with the side to move, a result with the original
game context ("you played X in this game"), streak and due counts, a link back to the game. Single-move puzzles first; the
engine's continuation as a follow-up question later.

**10.3 Dashboard and openings.** `GET /api/stats/…` over your current reviews: accuracy trend over time; error rate per 100
moves by **phase** (opening / middlegame / endgame, by move count and remaining material), by colour and by time control;
most common error situations (needs the facts from M11, so v1 shows phase/colour/time-control only); opening table
(games, win/draw/loss, average accuracy; uses the 8.2 opening names). **Honesty rules (FR-10.3):** every number shows its
sample size, anything under a minimum sample (default 10 games / 30 moves) is greyed and labelled "not enough data to
conclude", and nothing is called a "weakness" below that threshold.

**Acceptance (AT-25…AT-30):** puzzles come only from your own mistakes and each answer is unambiguous; scheduling moves cards
between boxes correctly; an unrelated game never creates a puzzle; stats match hand-computed fixtures including the
small-sample labelling; games where you cannot be identified are excluded and reported; retry-the-move judges correct, near-best
and unknown moves as described.

---

## M11. Explain (LLM, grounded)

**Status: built and tested with a fake model; not yet run against a real one (not committed).** Done: per-friend invite
codes with a CLI and an unlock page; the deterministic facts extractor; the provider-neutral client for any OpenAI-compatible
endpoint, with OpenRouter as the chosen provider (a model id and an API key in `.env`; no local model); the validated
pipeline (one retry, then a labelled plain fallback); opt-in, daily limit per invite, a server-wide request cap, a cache and
a usage log; and the UI (explain this move, explain key moments, Settings notice naming who receives the data). Verified in a
real browser against `e2e/fake_llm.py`. **Still to do, by you:** pick the model. `python -m app.cli llm-test` runs the real
bake-off (valid / retried / fallback rates and speed) once `LLM_MODEL` and `LLM_API_KEY` (an OpenRouter key) are set.
Differences from the plan: the gate binds an invite to the browser's anonymous user (`users.invite_id`); analysis job limits
stay per browser, only the explanation allowance is per invite; the explanation is requested synchronously (one position at a
time) rather than as a background job.

| # | Feature | Size |
|---|---|---|
| 11.1 | **Private access gate** (one invite code per friend) | M |
| 11.2 | **Position facts extractor** (deterministic) | L |
| 11.3 | **Explanation service** (free model, provider-neutral, grounded, validated) | L |
| 11.4 | **Usage limits and the opt-in** | M |
| 11.5 | **UI** | M |

**11.1 Access gate (invite per friend).** Table `invite_codes(id, label, code_hash, created_at, last_used_at, revoked_at)`.
You manage them from the command line on the server: `python -m app.cli invite create "Alice"` prints the code **once**
(only a hash is stored), `invite list`, `invite revoke <id>`. A friend opens the site, enters their code on a small unlock
page (`POST /api/access {code}`, constant-time compare, attempts rate-limited), and their anonymous session is bound to that
invite (`sessions.invite_id`). When `ACCESS_REQUIRED=true`, every `/api` route except health and the unlock call needs a
bound session; revoking an invite cuts off every session bound to it. Limits (analysis jobs, LLM requests) can then be
**per friend** rather than per browser, and `invite list` shows last use and usage. Codes are long random strings, not
passwords people choose. Local use leaves `ACCESS_REQUIRED=false` and behaves exactly as today. It is still not an account
system: a friend's data lives in their browser session, and a new device needs the code again and starts empty (export/import
PGN moves games across).

**11.2 Facts.** The model must never be asked "what is going on in this position?" from a bare FEN. A deterministic module
extracts facts from what we already store plus `python-chess`: side to move, move played vs engine's best, evaluation before
and after (as win-percentage and eval text), the engine's line, material change along the line, pieces left hanging after
the played move, whether the move allows or misses a forced mate (and in how many), captures/checks available, simple motif
flags (fork, pin, skewer, back-rank, discovered attack) from attack maps, game phase, and a list of **allowed moves** (SAN)
the explanation may mention. Fully unit-tested, no network. These facts also power the dashboard's "common error situations".

**11.3 Explanation service.** Provider-neutral and **free to run**: a small client over the widely supported
OpenAI-compatible chat endpoint using `httpx` (already a dependency), configured by `LLM_BASE_URL`, `LLM_MODEL` and an
optional `LLM_API_KEY`. Server-side only; a key never reaches the browser. The model is a **hosted free tier called from
the server** (no model runs on your own machine; the server only needs the API key and outbound internet). Candidates:
Google Gemini, Groq, OpenRouter's `:free` models. A short bake-off at the start of M11, on fixture positions, picks one
(valid-output rate, speed, quality).
  - Free tiers are **rate-limited, can change or disappear, and some may use prompts to improve their models**. Before
    choosing I will check the provider's current terms and the in-app notice will state them. Only positions and SAN moves
    are sent. Because the client is provider-neutral, switching providers is a config change.
  - **Both modes are supported, chosen in `.env`:** `LLM_BASE_URL`, `LLM_MODEL`, `LLM_API_KEY` point either at a hosted
    free API or at a **local Ollama** model, which ships as an optional compose service (`--profile llm`, for example
    `LLM_BASE_URL=http://ollama:11434/v1`, no key). Local is private and has no rate limits, but a 7–8B model needs about
    5–6 GB RAM and on CPU takes tens of seconds per explanation while sharing cores with Stockfish. Switching needs only an
    env change and a restart; the in-app privacy notice reads the mode from config so it always says where data goes.
  - Free models make more chess mistakes than large paid ones, so the validation below matters more, and the **fallback
    rate is a tracked metric** (acceptance below), not a hidden detail.
  - Requests go through one server-side queue with a global requests-per-minute limit below the provider's free quota, so
    a few friends cannot exhaust it at once.
- **Input:** the facts as JSON plus the user's level (beginner / intermediate / advanced). **Never** names, usernames, PGN
  headers or the whole game: only positions (FEN), SAN moves and numbers.
- **Output:** JSON `{explanation, mentioned_moves[], motif|null}` requested through the provider's JSON mode where it
  exists (small models do not reliably honour full schemas), then parsed and checked by us, so the format is never trusted.
- **Validation (the grounding):** every move in `mentioned_moves` must be in the allowed list and every move written in the
  prose must parse and be allowed; a number that contradicts the facts is rejected. On failure: one retry with the problem
  stated; on a second failure fall back to a plain sentence built from the facts, labelled as such. This is what makes the
  feature checkable instead of trusting the model.
- **Failure handling:** timeouts, rate limits (HTTP 429, honour `Retry-After`), provider
  down or model refusing: show "explanation unavailable, try later", never an error page, and never block the review.
- **Bulk:** "Explain key moments" (≤ 8 positions) runs as a background job, one position at a time.
- **Cache:** `move_explanations(run_id, ply, level, model, text, facts, tokens_in, tokens_out, seconds)` unique per
  (run, ply, level); asking again is instant.
- **Tests:** a fake client (no network) for validation, retry, fallback, timeout, 429 and limit paths, including a
  deliberately misbehaving fake that invents moves; an opt-in live test (`RUN_LIVE_LLM=1`) that runs the configured model on
  fixture positions and reports valid-output and fallback rates.

**11.4 Usage limits and consent.** Money is not the constraint now, so the controls are about **capacity and privacy**.
Off by default per person (Settings toggle with a plain-language notice: *which* data is sent, *to whom* (the named
hosted provider and its data terms, or "this server" for a local model), that it is optional) and off for the server unless `LLM_BASE_URL` is set.
Limits: `EXPLAIN_DAILY_LIMIT_PER_USER` (default 30; per invite when the gate is on) and `EXPLAIN_QUEUE_MAX` so a slow local
model cannot build an unbounded backlog, with the reason shown when a limit is hit. An `llm_usage` log (requests, tokens,
seconds, outcome: valid / retried / fallback / failed) feeds `python -m app.cli llm-usage`, which is how we see the real
fallback rate and speed.

**11.5 UI.** "Explain this move" in the engine panel for marked moves and an "Explain key moments" action in the summary. The
text sits in a card titled "AI explanation" with the note "Written by an AI from the engine's analysis; it can be wrong. The
engine's lines are the facts", the engine line it refers to shown right next to it, and playable like any other line. Loading,
limit-reached and unavailable states are explicit.

**Acceptance (AT-31…AT-37):** an explanation never mentions a move outside the allowed list (property-tested on fixtures with
a deliberately misbehaving fake model); a fallback appears when validation fails twice; no PII/headers in the request
(asserted on the captured payload); limits work and are visible; off-by-default, the access gate and revoked invites
refuse correctly; the label and engine line are always shown; cached explanations are instant; with the chosen real model
the live test reports a valid-output rate, and we set the minimum acceptable rate after the bake-off (below it, the
feature stays off and the roadmap says so).

---

## 4. Requirements to add to the FRD (v1.1)

FR-11 accuracy and book moves · FR-12 clock analysis · FR-13 partial results while analyzing · FR-14 annotated export ·
FR-15 batch analysis and auto-analyze · FR-16 saved sources and new-game check · FR-17 notes/tags/favourites ·
FR-18 training (retry, puzzles, dashboard, opening stats) · FR-19 AI explanations and the private access gate.
NFRs: LLM data minimisation and usage caps; honest small-sample statistics; the access gate (per-friend invites) is not an account system.

## 5. Risks

| Risk | Mitigation |
|---|---|
| LLM states something false about chess | Facts-in, validated-moves-out, fallback, label, engine line shown beside it; never the sole source |
| Free model is weak or slow | Bake-off before committing; validation + fallback; fallback rate measured; feature stays off if too poor |
| Free hosted tier changes terms or limits | Provider-neutral client (swap by config); global request-rate limit under the free quota; feature degrades to "unavailable" |
| Sending games to a third party | Data minimisation (positions and SAN only, no names), opt-in notice naming the provider and its data terms, easy off switch |
| An invite code is shared around | Per-invite limits and revoke; list shows usage |
| Batch jobs starve others / flood the queue | Fair-share enqueueing, per-batch and global caps, cancel |
| Stats mislead on small samples | Minimum-sample rules, sample sizes on every figure |
| "Who is me" is wrong | Explicit "my names"; unmatched games excluded and reported |
| Accuracy differs from other sites | Labelled as this app's number with the formula source |
| Scope creep from sharing/coach ideas | Deferred below until you decide about accounts |

## 6. Deferred (needs a decision about accounts, or low value now)

- **Sharing / coach view** (a coach seeing a student's reviews, read-only share links): needs either accounts or
  unguessable share tokens plus a privacy review. A cheap first step would be read-only share links with an expiry.
- **Auto-sync in the background, login with Lichess/Chess.com:** wait for the accounts decision.
- **Progressive deepening** (quick first pass, refine later), **engine in the browser**, **PWA/offline**, board themes and sounds.
- **Opponent preparation** reports (needs the identity and opening stats from M10).

## 7. Decisions on the open questions

1. **My names** in Settings identifies you. Confirmed.
2. **Free, non-Claude model, hosted API or local (Ollama), switched in `.env`.** Provider-neutral client; the default and
   the hosted provider are decided by a bake-off at the start of M11.
3. **Lichess-style accuracy formula**, labelled as such. Confirmed (recommended option).
4. **One invite code per friend**, revocable, with per-friend limits (§11.1). Confirmed.
5. **Reviews stay private to each person** (default, since undecided). Sharing and a coach view remain deferred (§6); revisit
   if students ask for it.

## 8. Still open (small, can wait until M11)

- Server size and host: Stockfish needs CPU (the estimates in the README come from measured runs), so a server with at
  least 2 cores is advisable for a few friends. We can size this when we get to the deployment notes for M9/M11.

---

**Update (provider decision):** the local-model option was dropped. AI explanations use **OpenRouter** only (`LLM_MODEL` +
`LLM_API_KEY`; the base URL defaults to OpenRouter's). Earlier mentions of Ollama above are superseded.

**Measured (real model):** `minimax/minimax-m3.1-flash:free` through OpenRouter on 8 real mistakes: 7 valid, 1 retried, 0 fell
back, about 10 s per explanation. The first run (token limit 400) had 50% fallbacks because this reasoning model spent its
budget thinking and returned cut-off or empty JSON, so the default `LLM_MAX_TOKENS` is now 1200. The checker caught one
invented move (`Kg2`) and forced a retry, which is what it is for.
