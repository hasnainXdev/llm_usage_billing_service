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

## Phase 3 — Stripe integration (offline), gate: 28/28 tests green

- **AI wrote:** `stripe_integration/client.py` (test-mode Checkout Session creation
  via the new sync `StripeClient` API, no network calls), `stripe_integration/webhook.py`
  (`stripe.Webhook.construct_event` signature verification), `plan_repo`,
  `subscription_repo.update_subscription` + `get_by_stripe_subscription_id`,
  `SubscriptionService` (applies verified events; dedup + apply in one transaction),
  `POST /billing/checkout`, `POST /webhooks/stripe`, `tests/test_stripe.py` (8 tests).
- **Decisions the human should be able to restate:**
  - The DB mirrors Stripe's truth, never the source: plan/status change ONLY from a
    signature-verified webhook event. Forged/missing signature → 400, zero DB change.
  - Dedup = `stripe_events.stripe_event_id` UNIQUE, inserted in the SAME transaction
    as the apply; a replay returns `duplicate` and its effect was already applied.
  - Unhandled events (unknown type, unknown tenant) are still recorded, so a replay
    of an unhandled event stays `duplicate`, never re-processed.
  - Stripe secrets live in `.env` (gitignored); unconfigured Stripe → `/billing/checkout`
    returns 503 `stripe_not_configured`.
  - Test-mode only, forever.
- **Where the AI was wrong / corrected:**
  - `dict(event)` crashes on Stripe's `StripeObject` in SDK 15.x (`KeyError: 0`);
    fixed with `event.to_dict(recursive=True)`.
  - A test fake for `create_checkout_session` was `async def` while the real function
    is sync (called via `asyncio.to_thread`); made the fake sync.
  - `_tenant_for_subscription` was called without `await` in two handlers — a coroutine
    leaked into `update_subscription` (`DataError`); added the missing awaits.
- **Verified:** 28/28 tests green (forged sig rejected 400 with no DB change, replay
  applied exactly once, Free→Pro flip via signed event, past_due → 402, deleted →
  canceled, unknown tenant → unhandled-but-deduped, checkout session + 503 paths).
- **LIVE GATE — real Stripe test-mode run (human's own test account):**
  - Human ran `stripe login` (OAuth, browser) → CLI stored `sk_test_...`; `stripe listen
    --forward-to localhost:8000/webhooks/stripe` printed the real `whsec_...`, which was
    written to `.env` (gitignored). Also fixed a stale `.env` where a `pk_test_` line had
    been sitting in the `STRIPE_WEBHOOK_SECRET` slot.
  - `POST /billing/checkout` returned a real hosted Checkout Session URL (Pro, USD 20/mo).
  - `stripe trigger checkout.session.completed --override checkout_session:client_reference_id=<demo>`
    delivered a real signed event → our webhook 200 → demo tenant flipped free→pro.
  - Replaying the same real event twice → `duplicate`, `stripe_events` ledger stays at
    1 row, DB unchanged. Forged signature → 400 covered by the offline test.
  - Real `stripe subscriptions update ... metadata[tenant_id]=<t2>` fired
    `customer.subscription.updated` → tenant2 plan/status/customer/stripe_subscription_id
    stored; real `stripe subscriptions cancel --confirm` fired `customer.subscription.deleted`
    → tenant2 status=canceled.
  - **Where the AI was wrong / corrected (live):** the first `stripe trigger` used
    `--override checkout:...` — the fixture key is `checkout_session`, so `client_reference_id`
    stayed null (event correctly recorded as `unhandled`); and injecting
    `checkout_session:subscription=sub_...` fails because `subscription` is not a
    session-create parameter (it's populated by Stripe only after a real purchase) —
    so the live demo drives the status path with real subscription objects instead.
    Stripe CLI also needs `--confirm` on destructive commands, and test `pm_card_visa`
    isn't valid as a PaymentMethod id (used `-d source=tok_visa` instead).

