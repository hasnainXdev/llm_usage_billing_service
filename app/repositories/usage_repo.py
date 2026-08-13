from __future__ import annotations

import asyncpg

AI_TOKEN_TYPES: tuple[str, ...] = (
    "ai_input",
    "ai_cached_input",
    "ai_output",
    "ai_reasoning",
)

API_CALL_TYPE = "api_call"


async def insert_event(
    conn: asyncpg.Connection,
    *,
    tenant_id,
    usage_type: str,
    quantity: int,
    idempotency_key: str,
    cost_micro: int,
) -> asyncpg.Record | None:
    """Idempotent insert. Returns the new row, or None when the (tenant, key)
    pair already exists. The UNIQUE constraint is the dedup authority."""
    return await conn.fetchrow(
        """
        INSERT INTO usage_events (tenant_id, usage_type, quantity, idempotency_key, cost_micro)
        VALUES ($1, $2, $3, $4, $5)
        ON CONFLICT (tenant_id, idempotency_key) DO NOTHING
        RETURNING id, tenant_id, usage_type, quantity, idempotency_key, cost_micro, created_at
        """,
        tenant_id,
        usage_type,
        quantity,
        idempotency_key,
        cost_micro,
    )


async def get_event_by_key(
    conn: asyncpg.Connection, *, tenant_id, idempotency_key: str
) -> asyncpg.Record | None:
    return await conn.fetchrow(
        """
        SELECT id, tenant_id, usage_type, quantity, idempotency_key, cost_micro, created_at
        FROM usage_events
        WHERE tenant_id = $1 AND idempotency_key = $2
        """,
        tenant_id,
        idempotency_key,
    )


async def sum_dimension_usage(
    conn: asyncpg.Connection, *, tenant_id, usage_types, since
) -> int:
    """Total quantity of events of the given usage types since `since`."""
    return await conn.fetchval(
        """
        SELECT COALESCE(SUM(quantity), 0)::bigint
        FROM usage_events
        WHERE tenant_id = $1 AND usage_type = ANY($2::text[]) AND created_at >= $3
        """,
        tenant_id,
        list(usage_types),
        since,
    )


async def usage_by_type_since(conn: asyncpg.Connection, *, tenant_id, since):
    return await conn.fetch(
        """
        SELECT usage_type,
               COALESCE(SUM(quantity), 0)::bigint   AS qty,
               COALESCE(SUM(cost_micro), 0)::bigint AS cost
        FROM usage_events
        WHERE tenant_id = $1 AND created_at >= $2
        GROUP BY usage_type
        """,
        tenant_id,
        since,
    )
