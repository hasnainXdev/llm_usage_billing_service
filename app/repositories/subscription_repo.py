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


async def get_by_stripe_subscription_id(
    conn: asyncpg.Connection, stripe_subscription_id: str
) -> asyncpg.Record | None:
    return await conn.fetchrow(
        "SELECT id, tenant_id, status FROM subscriptions "
        "WHERE stripe_subscription_id = $1",
        stripe_subscription_id,
    )


async def update_subscription(
    conn: asyncpg.Connection, *, tenant_id, **fields
) -> None:
    """Update a tenant's subscription. `fields` keys are column names from this
    module's own code (whitelisted, never user input). None values are skipped.
    """
    sets: list[str] = []
    values: list[object] = []
    for col, val in fields.items():
        if val is None:
            continue
        sets.append(f"{col} = ${len(values) + 1}")
        values.append(val)
    if not sets:
        return
    sets.append("updated_at = now()")
    values.append(tenant_id)
    await conn.execute(
        f"UPDATE subscriptions SET {', '.join(sets)} WHERE tenant_id = ${len(values)}",
        *values,
    )
