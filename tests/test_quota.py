"""Quota boundary tests: just under / exactly at / over the plan limit.

Free plan pins: 1,000 API calls/mo, 100,000 AI tokens/mo.
Boundary rule: a request that lands usage exactly ON the limit is allowed;
only a request that would push usage PAST the limit is rejected (429).
"""

from __future__ import annotations

FREE_CALL_LIMIT = 1_000
FREE_TOKEN_LIMIT = 100_000


async def _post(client, tenant_id: str, key: str, payload: dict):
    return await client.post(
        "/generate",
        headers={"X-Tenant-Id": tenant_id, "Idempotency-Key": key},
        json=payload,
    )


async def test_just_under_limit_allowed(client, make_tenant):
    tid = await make_tenant()
    r = await _post(
        client, tid, "under",
        {"usage_type": "api_call", "quantity": FREE_CALL_LIMIT - 1},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["used"] == 999
    assert body["limit"] == FREE_CALL_LIMIT
    assert body["deduplicated"] is False


async def test_exactly_at_limit_allowed(client, make_tenant, count_events):
    tid = await make_tenant()
    r1 = await _post(
        client, tid, "a",
        {"usage_type": "api_call", "quantity": FREE_CALL_LIMIT - 1},
    )
    r2 = await _post(
        client, tid, "b",
        {"usage_type": "api_call", "quantity": 1},  # lands exactly on 1000
    )
    assert r1.status_code == 200
    assert r2.status_code == 200
    assert r2.json()["used"] == FREE_CALL_LIMIT
    assert await count_events(tid) == 2  # both events persisted


async def test_over_limit_rejected_429_with_message(client, make_tenant, count_events):
    tid = await make_tenant()
    r1 = await _post(
        client, tid, "a",
        {"usage_type": "api_call", "quantity": FREE_CALL_LIMIT},
    )
    assert r1.status_code == 200

    r2 = await _post(client, tid, "b", {"usage_type": "api_call", "quantity": 1})
    assert r2.status_code == 429
    body = r2.json()
    assert body["code"] == "quota_exceeded"
    assert body["used"] == FREE_CALL_LIMIT
    assert body["limit"] == FREE_CALL_LIMIT
    assert "API-call" in body["detail"]
    assert "1000/1000" in body["detail"]
    assert await count_events(tid) == 1  # rejected request left NO row


async def test_single_request_that_alone_exceeds_limit_rejected(
    client, make_tenant, count_events
):
    tid = await make_tenant()
    r = await _post(
        client, tid, "big",
        {"usage_type": "api_call", "quantity": FREE_CALL_LIMIT + 1},
    )
    assert r.status_code == 429
    assert r.json()["code"] == "quota_exceeded"
    assert r.json()["used"] == 0  # nothing used before
    assert await count_events(tid) == 0


async def test_ai_token_boundary(client, make_tenant):
    tid = await make_tenant()
    r1 = await _post(
        client, tid, "a",
        {"usage_type": "ai_token", "token_category": "input", "quantity": FREE_TOKEN_LIMIT},
    )
    assert r1.status_code == 200
    assert r1.json()["used"] == FREE_TOKEN_LIMIT

    r2 = await _post(client, tid, "b", {"usage_type": "ai_token", "token_category": "input", "quantity": 1})
    assert r2.status_code == 429
    body = r2.json()
    assert body["code"] == "quota_exceeded"
    assert "AI-token" in body["detail"]
    assert body["used"] == FREE_TOKEN_LIMIT


async def test_api_and_token_quotas_are_independent(client, make_tenant):
    tid = await make_tenant()
    # Use up all API calls; tokens must still be allowed.
    await _post(client, tid, "a", {"usage_type": "api_call", "quantity": FREE_CALL_LIMIT})
    r = await _post(client, tid, "t", {"usage_type": "ai_token", "token_category": "output", "quantity": 1000})
    assert r.status_code == 200


async def test_402_when_subscription_not_active(client, make_tenant, count_events):
    tid = await make_tenant(status="canceled")
    r = await _post(client, tid, "k", {"usage_type": "api_call", "quantity": 1})
    assert r.status_code == 402
    body = r.json()
    assert body["code"] == "payment_required"
    assert "subscription" in body["detail"].lower()
    assert await count_events(tid) == 0


async def test_unknown_tenant_rejected_402(client):
    r = await client.post(
        "/generate",
        headers={"X-Tenant-Id": "00000000-0000-0000-0000-000000000000", "Idempotency-Key": "k"},
        json={"usage_type": "api_call", "quantity": 1},
    )
    assert r.status_code == 402
    assert r.json()["code"] == "payment_required"
