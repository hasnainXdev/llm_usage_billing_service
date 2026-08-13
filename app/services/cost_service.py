"""CostService - monthly cost rollup per tenant.

Rolls up a tenant's usage_events into { used, limit, cost }. Costs are summed
from the integer cost_micro locked on each event at record time; token
categories keep their own rates and are never flattened onto one rate.
"""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

import asyncpg

from app.domain.periods import period_label, utc_month_start
from app.repositories import subscription_repo, tenant_repo, usage_repo
from app.repositories.usage_repo import API_CALL_TYPE, AI_TOKEN_TYPES

COST_KEYS = (
    "api_calls_micro",
    "ai_input_micro",
    "ai_cached_input_micro",
    "ai_output_micro",
    "ai_reasoning_micro",
    "ai_tokens_micro",
    "total_micro",
)


@dataclass(frozen=True)
class UsageRollup:
    tenant_id: str
    plan_code: str
    period: str
    used: dict[str, int]  # {"api_calls": int, "ai_tokens": int}
    limit: dict[str, int]  # {"api_calls": int, "ai_tokens": int}
    cost: dict[str, int]  # integer micro-units

    def to_dict(self) -> dict:
        return {
            "tenant_id": self.tenant_id,
            "plan": self.plan_code,
            "period": self.period,
            "used": self.used,
            "limit": self.limit,
            "cost": self.cost,
        }


class CostService:
    def __init__(self, pool: asyncpg.Pool):
        self.pool = pool

    async def rollup(self, *, tenant_id: UUID) -> UsageRollup | None:
        month_start = utc_month_start()
        async with self.pool.acquire() as conn:
            tenant = await tenant_repo.get_tenant(conn, tenant_id)
            if tenant is None:
                return None
            sub = await subscription_repo.get_subscription_with_plan(conn, tenant_id)
            rows = await usage_repo.usage_by_type_since(
                conn, tenant_id=tenant_id, since=month_start
            )

        used = {"api_calls": 0, "ai_tokens": 0}
        cost = {
            "api_calls_micro": 0,
            "ai_input_micro": 0,
            "ai_cached_input_micro": 0,
            "ai_output_micro": 0,
            "ai_reasoning_micro": 0,
        }
        for r in rows:
            t = r["usage_type"]
            if t == API_CALL_TYPE:
                used["api_calls"] += r["qty"]
                cost["api_calls_micro"] += r["cost"]
            elif t in AI_TOKEN_TYPES:
                used["ai_tokens"] += r["qty"]
                cost[f"{t}_micro"] += r["cost"]

        cost["ai_tokens_micro"] = (
            cost["ai_input_micro"]
            + cost["ai_cached_input_micro"]
            + cost["ai_output_micro"]
            + cost["ai_reasoning_micro"]
        )
        cost["total_micro"] = cost["api_calls_micro"] + cost["ai_tokens_micro"]

        limit = {"api_calls": 0, "ai_tokens": 0}
        if sub is not None:
            limit = {
                "api_calls": sub["api_call_limit"],
                "ai_tokens": sub["ai_token_limit"],
            }

        return UsageRollup(
            tenant_id=str(tenant_id),
            plan_code=sub["plan_code"] if sub else "none",
            period=period_label(month_start),
            used=used,
            limit=limit,
            cost=cost,
        )
