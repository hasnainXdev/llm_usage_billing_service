-- 001_initial_schema.sql
-- Phase 1: tables + isolation + the idempotency constraint.
-- Every tenant-scoped row carries tenant_id and is always queried with it.

CREATE TABLE tenants (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name        TEXT NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE plans (
    id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    code             TEXT NOT NULL UNIQUE,          -- 'free' | 'pro'
    name             TEXT NOT NULL,
    api_call_limit   BIGINT NOT NULL CHECK (api_call_limit >= 0),  -- per month
    ai_token_limit   BIGINT NOT NULL CHECK (ai_token_limit >= 0),  -- per month
    price_micro      BIGINT NOT NULL CHECK (price_micro >= 0),     -- integer micro-units
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE subscriptions (
    id                     UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id              UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    plan_id                UUID NOT NULL REFERENCES plans(id),
    status                 TEXT NOT NULL,           -- mirror of Stripe truth
    stripe_customer_id     TEXT,
    stripe_subscription_id TEXT,
    current_period_end     TIMESTAMPTZ,
    created_at             TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at             TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (tenant_id)                             -- exactly one subscription per tenant
);

CREATE TABLE usage_events (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id       UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    usage_type      TEXT NOT NULL,                  -- api_call | ai_input | ai_cached_input | ai_output | ai_reasoning
    quantity        BIGINT NOT NULL CHECK (quantity > 0),
    idempotency_key TEXT NOT NULL,
    cost_micro      BIGINT NOT NULL,                -- cost locked at record time, integer micro-units
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (tenant_id, idempotency_key)             -- THE idempotency constraint: one row per (tenant, key), ever
);

CREATE INDEX idx_usage_events_tenant_created
    ON usage_events (tenant_id, created_at);

CREATE TABLE stripe_events (
    id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    stripe_event_id  TEXT NOT NULL UNIQUE,          -- webhook dedup key
    event_type       TEXT NOT NULL,
    received_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);
