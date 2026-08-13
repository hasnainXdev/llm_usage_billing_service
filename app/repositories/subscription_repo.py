from __future__ import annotations

import asyncpg

# Stripe statuses under which a tenant may use billable endpoints.
BILLABLE_STATUSES: tuple[str, ...] = ("active", "trialing")


async def lock_subscription_with_plan(
    conn: asyncpg.Connection, tenant_id
) -> asyncpg.Record | None:
    """The tenant's subscription + plan limits, locked FOR UPDATE so concurrent
    writes for one tenant serialize (quota checks cannot race)."""
    return await conn.fetchrow(
        """
        SELECT s.id, s.tenant_id, s.status, s.plan_id,
               p.code          AS plan_code,
               p.api_call_limit,
               p.ai_token_limit
        FROM subscriptions s
        JOIN plans p ON p.id = s.plan_id
        WHERE s.tenant_id = $1
        FOR UPDATE
        """,
        tenant_id,
    )


async def get_subscription_with_plan(
    conn: asyncpg.Connection, tenant_id
) -> asyncpg.Record | None:
    return await conn.fetchrow(
        """
        SELECT s.id, s.tenant_id, s.status, s.plan_id,
               p.code          AS plan_code,
               p.api_call_limit,
               p.ai_token_limit
        FROM subscriptions s
        JOIN plans p ON p.id = s.plan_id
        WHERE s.tenant_id = $1
        """,
        tenant_id,
    )
