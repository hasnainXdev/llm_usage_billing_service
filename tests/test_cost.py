"""Cost rollup tests with pinned expected totals (integer micro-units).

Pinned pricing (app/domain/pricing.py):
  api_call          100 micro / call
  ai_input          3,000  micro / 1K tokens   ($3.00/1M)
  ai_cached_input     300  micro / 1K tokens   ($0.30/1M, cheaper than fresh)
  ai_output        15,000  micro / 1K tokens   ($15.00/1M)
  ai_reasoning     15,000  micro / 1K tokens   (priced as output)
"""

from __future__ import annotations

from app.domain import pricing
from app.domain.periods import period_label, utc_month_start


async def _post(client, tenant_id: str, key: str, payload: dict):
    return await client.post(
        "/generate",
        headers={"X-Tenant-Id": tenant_id, "Idempotency-Key": key},
        json=payload,
    )


async def test_pinned_cost_math_matches_config(client, make_tenant):
    tid = await make_tenant(plan="pro")  # 10M token allowance fits this mix
    # 2 API calls + a mix of token categories.
    await _post(client, tid, "a", {"usage_type": "api_call", "quantity": 2})
    await _post(client, tid, "b", {"usage_type": "ai_token", "token_category": "input", "quantity": 100_000})
    await _post(client, tid, "c", {"usage_type": "ai_token", "token_category": "cached_input", "quantity": 100_000})
    await _post(client, tid, "d", {"usage_type": "ai_token", "token_category": "output", "quantity": 100_000})
    await _post(client, tid, "e", {"usage_type": "ai_token", "token_category": "reasoning", "quantity": 50_000})

    r = await client.get("/usage", headers={"X-Tenant-Id": tid})
    assert r.status_code == 200
    body = r.json()

    assert body["plan"] == "pro"
    assert body["period"] == period_label(utc_month_start())
    assert body["used"] == {"api_calls": 2, "ai_tokens": 350_000}
    assert body["limit"] == {"api_calls": 100_000, "ai_tokens": 10_000_000}

    cost = body["cost"]
    assert cost["api_calls_micro"] == 200
    assert cost["ai_input_micro"] == 300_000          # 100K x 3000 / 1000
    assert cost["ai_cached_input_micro"] == 30_000    # 100K x 300 / 1000
    assert cost["ai_output_micro"] == 1_500_000       # 100K x 15000 / 1000
    assert cost["ai_reasoning_micro"] == 750_000      # 50K x 15000 / 1000 (as output)
    assert cost["ai_tokens_micro"] == 2_580_000
    assert cost["total_micro"] == 2_580_200


async def test_cached_input_is_cheaper_than_fresh_input(client, make_tenant):
    tid = await make_tenant()
    await _post(client, tid, "a", {"usage_type": "ai_token", "token_category": "input", "quantity": 1_000})
    await _post(client, tid, "b", {"usage_type": "ai_token", "token_category": "cached_input", "quantity": 1_000})
    body = (await client.get("/usage", headers={"X-Tenant-Id": tid})).json()
    assert body["cost"]["ai_input_micro"] == 3_000
    assert body["cost"]["ai_cached_input_micro"] == 300
    assert body["cost"]["ai_input_micro"] > body["cost"]["ai_cached_input_micro"]


async def test_reasoning_is_priced_as_output(client, make_tenant):
    tid = await make_tenant()
    await _post(client, tid, "a", {"usage_type": "ai_token", "token_category": "reasoning", "quantity": 1_000})
    await _post(client, tid, "b", {"usage_type": "ai_token", "token_category": "output", "quantity": 1_000})
    body = (await client.get("/usage", headers={"X-Tenant-Id": tid})).json()
    assert body["cost"]["ai_reasoning_micro"] == 15_000
    assert body["cost"]["ai_output_micro"] == 15_000
    assert body["cost"]["ai_reasoning_micro"] == body["cost"]["ai_output_micro"]


async def test_token_categories_have_individual_rates(client, make_tenant):
    tid = await make_tenant()
    # 4,000 tokens: one of each category — a flat rate could not explain this.
    await _post(client, tid, "a", {"usage_type": "ai_token", "token_category": "input", "quantity": 1_000})
    await _post(client, tid, "b", {"usage_type": "ai_token", "token_category": "cached_input", "quantity": 1_000})
    await _post(client, tid, "c", {"usage_type": "ai_token", "token_category": "output", "quantity": 1_000})
    await _post(client, tid, "d", {"usage_type": "ai_token", "token_category": "reasoning", "quantity": 1_000})
    body = (await client.get("/usage", headers={"X-Tenant-Id": tid})).json()
    assert body["cost"]["ai_tokens_micro"] == 3_000 + 300 + 15_000 + 15_000
    assert body["cost"]["ai_tokens_micro"] == 33_300
    assert body["cost"]["total_micro"] == 33_300


async def test_usage_unknown_tenant_404(client):
    r = await client.get(
        "/usage", headers={"X-Tenant-Id": "00000000-0000-0000-0000-000000000000"}
    )
    assert r.status_code == 404
    assert r.json()["code"] == "tenant_not_found"


async def test_pinned_constants_are_what_the_math_uses():
    assert pricing.API_CALL_RATE_MICRO == 100
    assert pricing.AI_TOKEN_RATE_MICRO_PER_1K == {
        "ai_input": 3_000,
        "ai_cached_input": 300,
        "ai_output": 15_000,
        "ai_reasoning": 15_000,
    }
    assert pricing.cost_micro_for("api_call", 1_000) == 100_000
    assert pricing.cost_micro_for("ai_input", 100_000) == 300_000
    assert pricing.cost_micro_for("ai_cached_input", 100_000) == 30_000
    assert pricing.cost_micro_for("ai_output", 100_000) == 1_500_000
    assert pricing.cost_micro_for("ai_reasoning", 100_000) == 1_500_000
