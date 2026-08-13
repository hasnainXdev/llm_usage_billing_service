# EVIDENCE — one pasted proof per Definition-of-Done box

A box is done only when it has a real, pasted proof (test output, curl transcript,
or log line) below. No placeholders. Updated as gates pass.

## Metering

- [ ] A billable action creates exactly one usage event, even under retries — dedup by idempotency key.
- [ ] A test proves double-counting cannot happen.

## Quotas

- [ ] Usage is checked against the tenant's plan; over-limit requests are rejected.
- [ ] Responses carry correct status codes (429/402) and an explanatory message.

## Cost calculation

- [ ] Monthly usage rolls up into a cost figure per tenant.
- [ ] AI token pricing handles cached input, reasoning tokens, and output pricing correctly.
- [ ] Pricing constants are pinned in config and covered by tests.

## Stripe integration

- [ ] Subscription checkout works end-to-end in test mode.
- [ ] Webhooks verify signatures, ignore duplicate events, update tenant plan/status.

## Data model, tests & docs

- [ ] DB includes tenants, plans, subscriptions, usage events; tenant data isolated.
- [ ] Tests cover: duplicate usage, quota boundaries, cost calc, invalid webhook, duplicate webhook.
- [ ] README + architecture diagram + setup instructions; all §-required files present.
