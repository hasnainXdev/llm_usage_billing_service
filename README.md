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

Requires Python 3.14 (`uv`), Docker, and (for the Stripe live gate) the Stripe CLI.

```bash
# 1. Database (Postgres 16)
docker compose up -d

# 2. Migrate + seed (plans + a "Demo Tenant" whose id is printed)
uv run python -m app.db.migrate
uv run python -m app.db.seed

# 3. Run the API
uv run uvicorn app.main:app --port 8000
```

Environment lives in `.env` (gitignored; copy `.env.example`). Stripe is test-mode
only, forever: set `STRIPE_SECRET_KEY` and `STRIPE_WEBHOOK_SECRET` (the latter is
printed by `stripe listen --forward-to localhost:8000/webhooks/stripe`).

```bash
uv run pytest          # 31 tests: metering, quotas, cost, isolation, Stripe
curl -s -X POST localhost:8000/generate \
  -H "X-Tenant-Id: <tenant id>" -H "Idempotency-Key: k1" \
  -d '{"usage_type":"api_call","quantity":5}'
curl -s localhost:8000/usage -H "X-Tenant-Id: <tenant id>"

# Stripe live gate (test mode):
stripe trigger checkout.session.completed \
  --override checkout_session:client_reference_id=<tenant id>
```

## Honest limitations

- **Simulated AI usage.** `POST /generate` meters a declared `quantity`; no model
  is ever called, and no real LLM key is used. Real metering would need an actual
  call path or SDK hook into a provider.
- **One purchasable plan.** Checkout only sells Pro (Free is the default). Adding
  more plans means more Stripe Prices/Products (one per plan, idempotently created).
- **Webhook events are fire-and-forget.** A 2xx to Stripe is the only ack. If the
  DB write fails after the event is delivered, Stripe retries and the dedup ledger
  makes the retry safe, but there is no outbound DLQ or alerting.
- **No authentication.** The `X-Tenant-Id` header is trusted as-is; tenant isolation
  is enforced by query scoping, not by credentials. A real deployment needs an auth
  layer in front of these routes.
- **No billing period rollover job yet.** "Resets at the start of next month" is
  implied by period-keyed queries (`period_label(utc_month_start())`); a cron
  that closes a month and opens the next is not implemented.
