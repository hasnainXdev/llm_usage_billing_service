"""Tenant isolation proofs - no tenant can see or collide with another's data.

Every query is scoped by the X-Tenant-Id header; the idempotency UNIQUE key is
(tenant_id, idempotency_key), so keys cannot collide across tenants.
"""

from __future__ import annotations


async def _post(client, tenant_id: str, key: str, payload: dict):
    return await client.post(
        "/generate",
        headers={"X-Tenant-Id": tenant_id, "Idempotency-Key": key},
        json=payload,
    )


async def test_usage_is_scoped_to_the_requesting_tenant(client, make_tenant):
    tid_a = await make_tenant()
    tid_b = await make_tenant(name="Tenant B")

    await _post(client, tid_a, "a", {"usage_type": "api_call", "quantity": 3})

    body_b = (await client.get("/usage", headers={"X-Tenant-Id": tid_b})).json()
    assert body_b["used"] == {"api_calls": 0, "ai_tokens": 0}

    body_a = (await client.get("/usage", headers={"X-Tenant-Id": tid_a})).json()
    assert body_a["used"] == {"api_calls": 3, "ai_tokens": 0}


async def test_same_idempotency_key_across_tenants_does_not_collide(
    client, make_tenant
):
    tid_a = await make_tenant()
    tid_b = await make_tenant(name="Tenant B")

    await _post(client, tid_a, "shared-key", {"usage_type": "api_call", "quantity": 1})
    await _post(client, tid_b, "shared-key", {"usage_type": "api_call", "quantity": 1})

    body_a = (await client.get("/usage", headers={"X-Tenant-Id": tid_a})).json()
    body_b = (await client.get("/usage", headers={"X-Tenant-Id": tid_b})).json()
    assert body_a["used"] == {"api_calls": 1, "ai_tokens": 0}
    assert body_b["used"] == {"api_calls": 1, "ai_tokens": 0}


async def test_plan_quota_is_per_tenant(client, make_tenant):
    tid_free = await make_tenant()  # 1,000 api calls/mo
    tid_pro = await make_tenant(plan="pro", name="Tenant B")  # 100,000 api calls/mo

    await _post(client, tid_free, "k", {"usage_type": "api_call", "quantity": 100_000})
    body_free = (await client.get("/usage", headers={"X-Tenant-Id": tid_free})).json()
    assert body_free["limit"]["api_calls"] == 1_000

    # The same quantity on the Pro tenant must not be affected by the Free tenant.
    await _post(client, tid_pro, "k", {"usage_type": "api_call", "quantity": 100_000})
    body_pro = (await client.get("/usage", headers={"X-Tenant-Id": tid_pro})).json()
    assert body_pro["limit"]["api_calls"] == 100_000
    assert body_pro["used"]["api_calls"] == 100_000
