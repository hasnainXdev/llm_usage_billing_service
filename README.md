# flyrank-capstone-metering-billing

Standalone LLM usage-metering and billing service (capstone project).

Meters billable actions per tenant, enforces monthly quotas per plan, aggregates
usage into costs, and lets tenants upgrade plans through Stripe Checkout -
**test mode only, forever**. AI token usage is simulated; no model is ever called.

## What it does

- Exactly 2 plans: **Free** and **Pro**, with pinned monthly quotas (config).
- Exactly 2 usage types: **API calls** and **AI tokens** (simulated).
- Exactly 1 billable endpoint: `POST /generate` - idempotent, quota-checked,
  returns a cost figure.
- `GET /usage` - monthly rollup `{ used, limit, cost }` per tenant.
- Stripe Checkout (test mode) upgrades a tenant's plan; signed webhooks keep the
  database a mirror of Stripe's truth (never the source).
- All money is integer micro-units (1 USD = 1,000,000 micro). No floats anywhere
  near money.

## Architecture

```text
 Client ──► Billable API request
   └─► MeterService.record(tenant, type, qty, idempotencyKey)
        ├─ duplicate key? → return original result (no new event)
        ├─ store usage_event
        └─► Quota Check ──► allowed
                          └─► limit exceeded → 402 / 429 + clear message

 GET /usage ◄── rollup(usage_events) → { used, limit, cost }

 Stripe Checkout (test mode) ──► subscription created
 Stripe ─signed webhook─► /webhooks/stripe
   ├─► verify signature (forged → 400)
   ├─► deduplicate event (replay → ignored)
   └─► update tenant plan / status

 Layers: HTTP (FastAPI routes) → business logic (services) → data (repositories over Postgres)
```

## Run + seed

_Skeleton - full instructions land in Phase 4._

## Honest limitations

_Skeleton - written up honestly as the build progresses._
