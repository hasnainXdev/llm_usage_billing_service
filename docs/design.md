# Design doc — flyrank-capstone-metering-billing

## Problem

A tenant-rentable LLM API needs to (a) meter every billable action, (b) enforce a
per-plan monthly quota, (c) price usage into a cost, and (d) let a tenant upgrade
its plan via Stripe Checkout. Usage must stay correct under retries and webhook
replays: no double-counting, no double-applied events.

## Scope lock (from the brief)

Exactly **2 plans** (Free / Pro), exactly **2 usage types** (API calls + AI
tokens, simulated — no model call, no AI key), exactly **1 billable endpoint**
(`POST /generate`). No invoicing, no proration, no overage billing in core.

## Data model (migrations: `app/db/migrations/001_initial_schema.sql`)

- `tenants(id, name, created_at)` — the customer.
- `plans(id, code UNIQUE, name, api_call_limit, ai_token_limit, price_micro, created_at)` —
  monthly limits and price pinned as integers; seeded from `app/domain/plans.py`.
- `subscriptions(id, tenant_id UNIQUE FK, plan_id FK, status, stripe_customer_id,
  stripe_subscription_id, current_period_end, created_at, updated_at)` — one row
  per tenant; `status` is a mirror of Stripe, never the source of truth.
- `usage_events(id, tenant_id FK, usage_type, quantity, idempotency_key,
  cost_micro, created_at, UNIQUE(tenant_id, idempotency_key))` — one row per
  metered action, ever.
- `stripe_events(id, stripe_event_id UNIQUE, event_type, received_at)` — webhook
  dedup ledger.

**Tenant isolation:** every tenant-scoped table has `tenant_id` FK and every
query is filtered by it; the idempotency uniqueness is scoped to the tenant, so a
key can never collide or leak across tenants.

## API surface

| Endpoint | Purpose |
|---|---|
| `POST /generate` | Billable action. Headers `X-Tenant-Id`, `Idempotency-Key`. Body `{usage_type: "api_call"\|"ai_token", quantity: int>0, token_category?: "input"\|"cached_input"\|"output"\|"reasoning"}`. Returns `{usage_event_id, usage_type, token_category, quantity, cost_micro, deduplicated}`. |
| `GET /usage` | Rollup `{used, limit, cost}` for the current UTC month per tenant (header `X-Tenant-Id`). |
| `POST /billing/checkout` | Create a Stripe Checkout session (test mode) to upgrade a tenant to Pro. |
| `POST /webhooks/stripe` | Verified, deduplicated Stripe event handling. |

Errors: **400** invalid input · **429** `quota_exceeded` (used+requested > limit,
human message with used/limit) · **402** `payment_required` (no active
subscription). Boundary rule: a request that lands usage **exactly on** the limit
is allowed; only a request that would push usage **past** the limit is rejected.

## Layer sketch

```
HTTP (FastAPI routes)  app/api/*
      │  never imports HTTP types downward
business logic  app/services/*  (MeterService, QuotaService, CostService, SubscriptionService)
      │  never imports Stripe SDK
data  app/repositories/*  over Postgres (asyncpg)
Stripe only in app/stripe_integration/*  (client + webhook verify/dispatch)
```

Swapping the DB or the payment provider never touches business logic.

## Pricing (pinned in `app/domain/pricing.py`, integer micro-units)

- API call: **100 micro** per call.
- AI tokens (per 1,000 tokens): fresh input **3,000**; cached input **300**
  (cheaper); output **15,000**; reasoning **15,000** (priced as output).
- Cost per event = integer math only; token cost rounds up to the nearest
  micro-unit. Categories are priced individually, never at one flat rate.

## Plans (pinned in `app/domain/plans.py`)

- **Free**: 1,000 API calls/mo, 100,000 AI tokens/mo, $0.
- **Pro**: 100,000 API calls/mo, 10,000,000 AI tokens/mo, $20/mo.

## Idempotency-key strategy

`POST /generate` requires an `Idempotency-Key` header (any client-chosen string,
scoped per tenant). The key is stored in `usage_events.idempotency_key` under a
`UNIQUE (tenant_id, idempotency_key)` constraint — **the database, not
application logic, is the dedup authority.** On each request the service opens a
transaction, locks the tenant's subscription row with `SELECT … FOR UPDATE`
(serializing that tenant's concurrent writes so quota checks cannot race), then
attempts `INSERT … ON CONFLICT (tenant_id, idempotency_key) DO NOTHING
RETURNING …`. If a row is returned the request is fresh: the quota check runs and,
if used+requested would exceed the limit, the transaction rolls back (no event
persists, the request is retryable) and the client receives 429/402. If the
insert conflicts, the key was already recorded: the service fetches the stored
row and returns the **original** result — its stored `cost_micro`, event id, and
`deduplicated: true` — with no quota check and no new event. A retried request
therefore always returns the original response and can never create a second
`usage_event` row, even under concurrent duplicate delivery, because two racing
inserts cannot both win a unique constraint. Cost is locked at record time in
`cost_micro`, so the original result is replayable forever.

## Non-goals (explicit)

No proration of plan fees, no invoicing, no overage billing, no usage alerts, no
reconciliation job, no multi-currency. AI tokens are simulated. These are out of
core and out of scope for this capstone.
