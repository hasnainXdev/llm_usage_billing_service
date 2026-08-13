from __future__ import annotations

import asyncpg

from app.config import settings


async def create_pool(dsn: str | None = None) -> asyncpg.Pool:
    return await asyncpg.create_pool(
        dsn=dsn or settings.database_url, min_size=1, max_size=10
    )
