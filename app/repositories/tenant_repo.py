from __future__ import annotations

import asyncpg


async def get_tenant(conn: asyncpg.Connection, tenant_id) -> asyncpg.Record | None:
    return await conn.fetchrow(
        "SELECT id, name, created_at FROM tenants WHERE id = $1", tenant_id
    )
