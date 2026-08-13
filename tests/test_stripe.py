"""Stripe integration tests — signature verification, dedup, plan flip.

No Stripe account needed: events are signed locally with the same HMAC-SHA256
scheme Stripe uses, so `stripe.Webhook.construct_event` verifies them for real.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import time
import uuid

import pytest

from app.config import settings
from app.stripe_integration import client as stripe_client_mod
from app.stripe_integration.client import StripeNotConfigured

TEST_WHSEC = "whsec_testsecret_0123456789abcdef"


def sign(payload: dict) -> tuple[bytes, str]:
    raw = json.dumps(payload).encode()
    t = int(time.time())
    mac = hmac.new(TEST_WHSEC.encode(), f"{t}.".encode() + raw, hashlib.sha256).hexdigest()
    return raw, f"t={t},v1={mac}"


def checkout_completed_event(
    tenant_id: str,
    *,
    customer: str = "cus_test_1",
    subscription: str = "sub_test_1",
    event_id: str | None = None,
) -> dict:
    return {
        "id": event_id or f"evt_{uuid.uuid4()}",
        "type": "checkout.session.completed",
        "data": {
            "object": {
                "id": f"cs_{uuid.uuid4()}",
                "mode": "subscription",
                "client_reference_id": str(tenant_id),
                "customer": customer,
                "subscription": subscription,
            }
        },
    }


def subscription_updated_event(
    subscription_id: str,
    *,
    status: str = "active",
    tenant_id: str | None = None,
    current_period_end: int | None = None,
    event_id: str | None = None,
) -> dict:
    price = {"price": {"metadata": {"app_plan": "pro"}}}
    return {
        "id": event_id or f"evt_{uuid.uuid4()}",
        "type": "customer.subscription.updated",
        "data": {
            "object": {
                "id": subscription_id,
                "status": status,
                "customer": "cus_test_1",
                "metadata": {"tenant_id": tenant_id} if tenant_id else {},
                "current_period_end": current_period_end,
                "items": {"data": [price]},
            }
        },
    }


@pytest.fixture(autouse=True)
def stripe_secrets(monkeypatch):
    monkeypatch.setattr(settings, "stripe_webhook_secret", TEST_WHSEC)
    monkeypatch.setattr(settings, "stripe_secret_key", "sk_test_dummy")


async def test_forged_signature_rejected_400_no_db_change(
    client, make_tenant, fetch_subscription, count_stripe_events
):
    tid = await make_tenant()
    event = checkout_completed_event(tid)
    payload = json.dumps(event).encode()
    # Wrong timestamp / bogus HMAC.
    header = "t=1,v1=forged_forged_forged"
    r = await client.post(
        "/webhooks/stripe",
        content=payload,
        headers={"stripe-signature": header},
    )
    assert r.status_code == 400
    assert r.json()["code"] == "invalid_signature"
    sub = await fetch_subscription(tid)
    assert sub["plan_code"] == "free"  # nothing changed
    assert sub["status"] == "active"
    assert await count_stripe_events() == 0


async def test_missing_signature_rejected_400(client, make_tenant):
    tid = await make_tenant()
    payload = json.dumps(checkout_completed_event(tid)).encode()
    r = await client.post("/webhooks/stripe", content=payload)
    assert r.status_code == 400


async def test_checkout_completed_flips_tenant_free_to_pro(
    client, make_tenant, fetch_subscription, count_stripe_events
):
    tid = await make_tenant()  # free, active
    event = checkout_completed_event(tid)
    payload, header = sign(event)
    r = await client.post("/webhooks/stripe", content=payload, headers={"stripe-signature": header})
    assert r.status_code == 200
    assert r.json()["outcome"] == "applied"

    sub = await fetch_subscription(tid)
    assert sub["plan_code"] == "pro"
    assert sub["status"] == "active"
    assert sub["stripe_customer_id"] == "cus_test_1"
    assert sub["stripe_subscription_id"] == "sub_test_1"
    assert await count_stripe_events() == 1


async def test_replay_applied_once(client, make_tenant, fetch_subscription, count_stripe_events):
    tid = await make_tenant()
    event = checkout_completed_event(tid)
    payload, header = sign(event)

    r1 = await client.post("/webhooks/stripe", content=payload, headers={"stripe-signature": header})
    r2 = await client.post("/webhooks/stripe", content=payload, headers={"stripe-signature": header})

    assert r1.json()["outcome"] == "applied"
    assert r2.json()["outcome"] == "duplicate"
    assert await count_stripe_events() == 1  # exactly one dedup ledger row

    sub = await fetch_subscription(tid)
    assert sub["plan_code"] == "pro"
    assert sub["stripe_customer_id"] == "cus_test_1"  # applied exactly once


async def test_subscription_updated_sets_status_and_period(
    client, make_tenant, fetch_subscription
):
    tid = await make_tenant(plan="pro", stripe_subscription_id="sub_test_9")
    period_ts = 1_752_000_000
    event = subscription_updated_event("sub_test_9", status="past_due", current_period_end=period_ts)
    payload, header = sign(event)
    r = await client.post("/webhooks/stripe", content=payload, headers={"stripe-signature": header})
    assert r.status_code == 200
    sub = await fetch_subscription(tid)
    assert sub["status"] == "past_due"

    # past_due is not billable → 402 on the API.
    gen = await client.post(
        "/generate",
        headers={"X-Tenant-Id": tid, "Idempotency-Key": "k"},
        json={"usage_type": "api_call", "quantity": 1},
    )
    assert gen.status_code == 402
    assert gen.json()["code"] == "payment_required"


async def test_subscription_deleted_sets_canceled(client, make_tenant, fetch_subscription):
    tid = await make_tenant(plan="pro", stripe_subscription_id="sub_test_10")
    event = {
        "id": f"evt_{uuid.uuid4()}",
        "type": "customer.subscription.deleted",
        "data": {"object": {"id": "sub_test_10", "customer": "cus_test_1"}},
    }
    payload, header = sign(event)
    r = await client.post("/webhooks/stripe", content=payload, headers={"stripe-signature": header})
    assert r.status_code == 200
    sub = await fetch_subscription(tid)
    assert sub["status"] == "canceled"


async def test_webhook_unknown_tenant_is_unhandled_but_deduped(
    client, count_stripe_events
):
    event = checkout_completed_event("00000000-0000-0000-0000-000000000000")
    payload, header = sign(event)
    r1 = await client.post("/webhooks/stripe", content=payload, headers={"stripe-signature": header})
    r2 = await client.post("/webhooks/stripe", content=payload, headers={"stripe-signature": header})
    assert r1.json()["outcome"] == "unhandled"
    assert r2.json()["outcome"] == "duplicate"
    assert await count_stripe_events() == 1


async def test_checkout_endpoint_creates_session(client, make_tenant, monkeypatch):
    tid = await make_tenant()

    def fake_create_checkout_session(*, tenant_id, success_url, cancel_url):
        return {"checkout_session_id": "cs_test_1", "url": "https://checkout.stripe.com/c/pay/cs_test_1"}

    monkeypatch.setattr(stripe_client_mod, "create_checkout_session", fake_create_checkout_session)
    r = await client.post(
        "/billing/checkout",
        headers={"X-Tenant-Id": tid},
        json={"plan": "pro"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["checkout_session_id"] == "cs_test_1"
    assert body["url"].startswith("https://")


async def test_checkout_endpoint_503_when_stripe_not_configured(client, make_tenant, monkeypatch):
    tid = await make_tenant()

    def boom(*args, **kwargs):
        raise StripeNotConfigured("no key")

    monkeypatch.setattr(stripe_client_mod, "create_checkout_session", boom)
    r = await client.post(
        "/billing/checkout",
        headers={"X-Tenant-Id": tid},
        json={"plan": "pro"},
    )
    assert r.status_code == 503
    assert r.json()["code"] == "stripe_not_configured"
