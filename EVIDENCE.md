# EVIDENCE - one pasted proof per Definition-of-Done box

A box is done only when it has a real, pasted proof (test output, curl transcript,
or log line) below. No placeholders. Updated as gates pass.

## Metering

- [x] A billable action creates exactly one usage event, even under retries - dedup by idempotency key.

  Live curl transcript (server on `localhost:8000`, seeded demo tenant):
  ```
  $ curl -s -X POST .../generate -H "X-Tenant-Id: <demo>" -H "Idempotency-Key: demo-1" -d '{"usage_type":"ai_token","token_category":"cached_input","quantity":1000}'
  {"usage_event_id":"15e44774-...","cost_micro":300,...,"deduplicated":false}
  $ curl -s -X POST .../generate -H "X-Tenant-Id: <demo>" -H "Idempotency-Key: demo-1" -d '{same body}'
  {"usage_event_id":"15e44774-...","cost_micro":300,...,"deduplicated":true}
  ```
  Same `usage_event_id`, same stored `cost_micro`, `deduplicated: true`, no new row.

- [x] A test proves double-counting cannot happen.

  ```
  tests/test_metering.py::test_concurrent_duplicate_delivery_creates_one_row PASSED
  ```
  (8 concurrent `POST /generate` calls with the same key → exactly 1 `usage_events` row;
  7 responses report `deduplicated: true`. See `tests/test_metering.py:39`.)

## Quotas

- [x] Usage is checked against the tenant's plan; over-limit requests are rejected.

  Live transcript - fill 999 → land exactly on 1000 (allowed) → 1 more → rejected:
  ```
  $ ... -d '{"usage_type":"api_call","quantity":999}'      -> {"used":999,"limit":1000,...}
  $ ... -d '{"usage_type":"api_call","quantity":1}'        -> {"used":1000,"limit":1000,...}   (exact boundary allowed)
  $ ... -d '{"usage_type":"api_call","quantity":1}' [429]
  ```

- [x] Responses carry correct status codes (429/402) and an explanatory message.

  ```
  $ ... -d '{"usage_type":"api_call","quantity":1}' [429]
  {"code":"quota_exceeded","detail":"Monthly API-call quota exceeded: 1000/1000 already used, and this request needs 1 more. Resets at the start of next month. Upgrade to Pro for higher limits.","used":1000,"limit":1000}
  ```
  ```
  tests/test_quota.py::test_402_when_subscription_not_active PASSED   # canceled tenant -> 402 payment_required
  tests/test_quota.py::test_over_limit_rejected_429_with_message PASSED
  tests/test_quota.py::test_single_request_that_alone_exceeds_limit_rejected PASSED
  ```

## Cost calculation

- [x] Monthly usage rolls up into a cost figure per tenant.

  `GET /usage` returns `{ used, limit, cost }` where `cost` breaks down by
  category in integer micro-units. Pinned totals in one run (Pro tenant, mixed mix):
  ```
  tests/test_cost.py::test_pinned_cost_math_matches_config PASSED
  # api_calls_micro == 200        (2 calls x 100)
  # ai_input_micro == 300_000     (100K x 3000 / 1K)
  # ai_cached_input_micro == 30_000 (100K x 300 / 1K)
  # ai_output_micro == 1_500_000  (100K x 15000 / 1K)
  # ai_reasoning_micro == 750_000 (50K x 15000 / 1K)
  # total_micro == 2_580_200
  ```

- [x] AI token pricing handles cached input, reasoning tokens, and output pricing correctly.

  ```
  tests/test_cost.py::test_cached_input_is_cheaper_than_fresh_input PASSED
  # 1K fresh == 3_000 micro; 1K cached == 300 micro; fresh > cached
  tests/test_cost.py::test_reasoning_is_priced_as_output PASSED
  # 1K reasoning == 15_000 micro == 1K output
  tests/test_cost.py::test_token_categories_have_individual_rates PASSED
  # 1K each of 4 categories == 33_300 micro total
  ```

- [x] Pricing constants are pinned in config and covered by tests.

  Pinned in `app/domain/pricing.py` (`API_CALL_RATE_MICRO`, the per-category
  `AI_TOKEN_RATE_MICRO_PER_1K` map) and cross-checked by
  `test_pinned_constants_are_what_the_math_uses` so the tests fail if a constant
  drifts from the math:
  ```
  tests/test_cost.py::test_pinned_constants_are_what_the_math_uses PASSED
  ```

## Stripe integration

- [x] Subscription checkout works end-to-end in test mode.

  Live test-mode run (real `sk_test_` key, real `whsec_` from `stripe listen`):
  ```
  $ curl -s -X POST http://localhost:8000/billing/checkout -H "X-Tenant-Id: <demo>" -d '{"plan":"pro"}'
  {"checkout_session_id":"cs_test_a1ecrG0qs7HqJxPBtZjnWUwJxMuphG0kVdCCXU4MlHVwOmj4dLG7wR4zCo",
   "url":"https://checkout.stripe.com/c/pay/cs_test_a1ecrG0qs7HqJxPBtZjnWUwJxMuphG0kVdCCXU4MlHVwOmj4dLG7wR4zCo#...",
   "price_id":"price_1U3xvzD3cXvEk4xpzkxAm4Vb"}
  ```
  A real hosted Checkout Session opens for the monthly Pro price (USD 20, metadata `app_plan=pro`).

- [x] Webhooks verify signatures, ignore duplicate events, update tenant plan/status.

  Forged/malformed signature → 400 `invalid_signature`, zero DB change (offline proof):
  ```
  tests/test_stripe.py::test_forged_signature_rejected_400_no_db_change PASSED
  ```

  Live `stripe trigger checkout.session.completed` (real signed event, overridden
  `client_reference_id` = demo tenant) - tenant flipped Free → Pro, event ledgered once:
  ```
  $ stripe trigger checkout.session.completed --override checkout_session:client_reference_id=<demo>
  Trigger succeeded!
  DB: SELECT p.code, s.status ... WHERE name='Demo Tenant'  ->  pro | active
  ```

  Live replay dedup - same real event replayed twice → `duplicate`, ledger still 1 row, DB unchanged:
  ```
  $ curl -s -X POST /webhooks/stripe -H "stripe-signature: t=...,v1=..." --data-binary @evt_1U3xwB...
  {"received":true,"outcome":"duplicate"}     # replay 1
  {"received":true,"outcome":"duplicate"}     # replay 2
  DB: SELECT count(*) FROM stripe_events WHERE stripe_event_id='evt_1U3xwBD3cXvEk4xp0ddMPx4p'  ->  1
  ```

  Live status mirroring via real Stripe objects - `metadata.tenant_id` update fired
  `customer.subscription.updated` (tenant mapped, plan/status/customer stored), then real
  cancellation fired `customer.subscription.deleted` (tenant → `canceled`):
  ```
  $ stripe subscriptions update sub_1U3xv7... -d "metadata[tenant_id]=<tenant2>"
  DB: pro | active | sub_1U3xv7D3cXvEk4xp34Tgb0eS
  $ stripe subscriptions cancel sub_1U3xv7... --confirm
  DB: pro | canceled
  ```
  (The test subscription genuinely reports `current_period_end: null`, and the DB mirrors
  that faithfully; the populated-period path is covered by
  `tests/test_stripe.py::test_subscription_updated_sets_status_and_period`.)

## Data model, tests & docs

- [x] DB includes tenants, plans, subscriptions, usage events; tenant data isolated.

  Migration `app/db/migrations/001_initial_schema.sql` creates `tenants`, `plans`,
  `subscriptions`, `usage_events`, and `stripe_events`. Isolation is enforced by
  tenant-scoped queries (X-Tenant-Id header) and proven:
  ```
  tests/test_isolation.py::test_usage_is_scoped_to_the_requesting_tenant PASSED
  # tenant B sees 0 usage; tenant A sees its own 3 calls
  tests/test_isolation.py::test_same_idempotency_key_across_tenants_does_not_collide PASSED
  tests/test_isolation.py::test_plan_quota_is_per_tenant PASSED
  ```
- [x] Tests cover: duplicate usage, quota boundaries, cost calc, invalid webhook, duplicate webhook.

  ```
  tests/test_metering.py::test_concurrent_duplicate_delivery_creates_one_row PASSED
  tests/test_quota.py::test_over_limit_rejected_429_with_message PASSED
  tests/test_cost.py::test_pinned_cost_math_matches_config PASSED
  tests/test_stripe.py::test_forged_signature_rejected_400_no_db_change PASSED
  tests/test_stripe.py::test_replay_applied_once PASSED
  ```
  31/31 tests green.
- [x] README + architecture diagram + setup instructions; all §-required files present.

  README.md has the architecture diagram (ASCII, `## Architecture`) plus run, seed,
  test, and live-Stripe instructions; `docs/design.md` documents the schema and
  decisions; `EVIDENCE.md` (this file) and `BUILDLOG.md` are maintained per gate.
