from __future__ import annotations

import asyncpg


async def get_plan_id(conn: asyncpg.Connection, code: str):
    return await conn.fetchval("SELECT id FROM plans WHERE code = $1", code)
