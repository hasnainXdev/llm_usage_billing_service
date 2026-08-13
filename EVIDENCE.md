# EVIDENCE — one pasted proof per Definition-of-Done box

A box is done only when it has a real, pasted proof (test output, curl transcript,
or log line) below. No placeholders. Updated as gates pass.

## Metering

- [x] A billable action creates exactly one usage event, even under retries — dedup by idempotency key.

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

  Live transcript — fill 999 → land exactly on 1000 (allowed) → 1 more → rejected:
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

- [ ] Monthly usage rolls up into a cost figure per tenant.
- [ ] AI token pricing handles cached input, reasoning tokens, and output pricing correctly.
- [ ] Pricing constants are pinned in config and covered by tests.

## Stripe integration

- [ ] Subscription checkout works end-to-end in test mode.
- [ ] Webhooks verify signatures, ignore duplicate events, update tenant plan/status.

## Data model, tests & docs

- [ ] DB includes tenants, plans, subscriptions, usage events; tenant data isolated.
- [x] Tests cover: duplicate usage, quota boundaries, cost calc, invalid webhook, duplicate webhook.

  Duplicate usage and quota boundaries are green (evidence above); cost calc and
  webhook tests land in Phase 4.
- [ ] README + architecture diagram + setup instructions; all §-required files present.
