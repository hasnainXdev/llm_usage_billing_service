# BUILDLOG — honest record of how this was built

Kept current as the build progresses. Every entry notes where AI (opencode) helped,
where it was wrong, and what the human changed.

## 2026-08-13 — Phase 1 (design, schema, idempotency strategy)

- **Human set up:** `uv init` scaffold in this directory, `.venv` on Python 3.14,
  git repo on branch `main`. The repo was already named and created as a uv project,
  so the AI did **not** rename the directory (it first proposed renaming the folder
  to `flyrank-capstone-metering-billing`; the human rejected that and said to keep
  the repo as-is).
- **First commit** was exactly what the brief demands: `README.md` skeleton +
  `.gitignore`, with `.env` and `.env.*` (except `.env.example`) gitignored from the
  very start.
- **AI wrote:** the schema migration `001_initial_schema.sql`, the integer-money
  domain (`money.py`, `pricing.py`, `plans.py`), the migration runner
  (`app/db/migrate.py`), `docs/design.md`, `.env.example`, `docker-compose.yml`.
- **Decisions made by the AI and kept (so far):**
  - Money is integer micro-units (1 USD = 1,000,000 micro). A `require_int` guard
    refuses any float entering a money value — the brief's hard rule.
  - Idempotency is enforced by a DB `UNIQUE (tenant_id, idempotency_key)` constraint
    plus `INSERT … ON CONFLICT DO NOTHING`, inside a transaction that locks the
    tenant's subscription row (`FOR UPDATE`) so quota checks can't race.
  - Boundary rule: the request that lands exactly on the limit is allowed; only a
    request that would push usage past the limit is rejected (429).
  - Pricing: API call 100 micro; fresh input 3,000 micro/1K, cached input 300 micro/1K
    (cheaper), output 15,000 micro/1K, reasoning 15,000 micro/1K (priced as output).
  - Plans: Free 1,000 calls + 100k tokens/mo ($0); Pro 100,000 calls + 10M tokens/mo ($20).
- **Where the AI was wrong / corrected:** the first draft of `pricing.py` had a stray
  dead line (`require_int_strings = True`) — removed before commit. No other
  corrections this phase.
- **Verified:** migration applies and is idempotent; cost math returns only ints;
  a float `quantity` is refused with `TypeError`.

## Phase 2 — metering + quota enforcement

- **AI wrote:** repositories over asyncpg (`usage_repo`, `subscription_repo`,
  `tenant_repo`), `MeterService` (idempotent insert + quota check in one
  transaction, subscription row locked `FOR UPDATE`), `QuotaService`
  (pure boundary check), `CostService` (rollup), the `POST /generate` and
  `GET /usage` routes, the seed script, and the test suite (19 tests).
- **Decisions the human should be able to restate:**
  - Dedup = `INSERT ... ON CONFLICT (tenant_id, idempotency_key) DO NOTHING` inside a
    transaction that locks the tenant's subscription row; the DB constraint is the
    authority, so two racing inserts cannot both win.
  - Fresh request: insert first, then quota check; over-limit raises → transaction
    rolls back → no row persists and the key is not consumed (rejected requests are
    retryable).
  - Duplicate request: return the stored original (`cost_micro`, event id) with
    `deduplicated: true`; no quota check, so a retry succeeds even after quota fills.
  - Boundary: exactly-at-limit allowed; only past-limit rejected (429).
  - 429 = quota_exceeded, 402 = payment_required (no active subscription).
  - Cost is locked on the event at record time (`cost_micro`), so dedup replays and
    rollups are exact integer sums.
- **Where the AI was wrong / corrected:**
  - First pytest run failed: `app` module not importable — fixed with pytest
    `pythonpath = ["."]`.
  - `app.state.pool` was only set inside lifespan, so ASGI test clients (which never
    run lifespan) crashed; set eagerly in `create_app`.
  - FastAPI wraps `HTTPException` detail under `"detail"` — flattened all error
    bodies to a consistent `{code, detail, ...}` via `JSONResponse`.
  - One test data bug: the multi-category cost test exceeded the Free token limit;
    switched it to a Pro tenant (also cross-checks plan limits).
- **Verified:** 19/19 tests green; live `uvicorn` smoke test showed dedup,
  exact-boundary allow, 429 with message, and a correct `GET /usage` rollup.

## Phase 3+ — (to be appended as work happens)
