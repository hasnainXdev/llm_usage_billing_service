"""Metering tests - the Definition-of-Done "no double-counting" proofs."""

from __future__ import annotations

import asyncio


async def _post(client, tenant_id: str, key: str, payload: dict):
    return await client.post(
        "/generate",
        headers={"X-Tenant-Id": tenant_id, "Idempotency-Key": key},
        json=payload,
    )


async def test_billable_action_creates_exactly_one_event(client, make_tenant, count_events):
    tid = await make_tenant()
    r = await _post(client, tid, "key-1", {"usage_type": "api_call", "quantity": 5})
    assert r.status_code == 200
    body = r.json()
    assert body["deduplicated"] is False
    assert body["cost_micro"] == 500  # 5 calls x 100 micro
    assert body["used"] == 5
    assert body["limit"] == 1000
    assert await count_events(tid) == 1


async def test_retry_returns_original_result_without_double_counting(
    client, make_tenant, count_events
):
    tid = await make_tenant()
    first = await _post(
        client, tid, "same-key",
        {"usage_type": "ai_token", "token_category": "input", "quantity": 1000},
    )
    # Same idempotency key but a DIFFERENT body - must return the original result.
    retry = await _post(
        client, tid, "same-key",
        {"usage_type": "ai_token", "token_category": "output", "quantity": 999_999},
    )
    assert first.status_code == retry.status_code == 200
    f, r = first.json(), retry.json()
    assert f["usage_event_id"] == r["usage_event_id"]
    assert r["cost_micro"] == f["cost_micro"] == 3000  # original stored cost, not recomputed
    assert r["quantity"] == 1000  # original quantity echoed, not the retry's
    assert r["token_category"] == "input"
    assert r["deduplicated"] is True
    assert await count_events(tid) == 1


async def test_concurrent_duplicate_delivery_creates_one_row(
    client, make_tenant, count_events
):
    tid = await make_tenant()
    payload = {"usage_type": "api_call", "quantity": 1}
    responses = await asyncio.gather(
        *[_post(client, tid, "conc-key", payload) for _ in range(8)]
    )
    assert all(r.status_code == 200 for r in responses)
    assert [r.json()["deduplicated"] for r in responses].count(True) == 7
    assert await count_events(tid) == 1  # THE double-counting proof


async def test_different_keys_are_independent_events(client, make_tenant, count_events):
    tid = await make_tenant()
    await _post(client, tid, "a", {"usage_type": "api_call", "quantity": 1})
    await _post(client, tid, "b", {"usage_type": "api_call", "quantity": 1})
    assert await count_events(tid) == 2


async def test_invalid_idempotency_key_rejected(client, make_tenant):
    tid = await make_tenant()
    r = await client.post(
        "/generate",
        headers={"X-Tenant-Id": tid, "Idempotency-Key": "bad key!! spaces"},
        json={"usage_type": "api_call", "quantity": 1},
    )
    assert r.status_code == 400
    assert r.json()["code"] == "invalid_idempotency_key"
