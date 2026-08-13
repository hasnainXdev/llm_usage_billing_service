"""Apply pending SQL migrations in app/db/migrations in filename order.

Each migration runs in its own transaction and is recorded in
schema_migrations so it applies exactly once. Run with:
    uv run python -m app.db.migrate
"""

from __future__ import annotations

import asyncio
import glob
import os

import asyncpg

from app.config import settings

MIGRATIONS_DIR = os.path.join(os.path.dirname(__file__), "migrations")


async def migrate(dsn: str) -> list[str]:
    conn = await asyncpg.connect(dsn)
    applied_now: list[str] = []
    try:
        await conn.execute(
            """
            CREATE TABLE IF NOT EXISTS schema_migrations (
                version    TEXT PRIMARY KEY,
                applied_at TIMESTAMPTZ NOT NULL DEFAULT now()
            )
            """
        )
        rows = await conn.fetch("SELECT version FROM schema_migrations")
        applied = {r["version"] for r in rows}

        for path in sorted(glob.glob(os.path.join(MIGRATIONS_DIR, "*.sql"))):
            version = os.path.basename(path)
            if version in applied:
                continue
            with open(path, encoding="utf-8") as fh:
                sql = fh.read()
            async with conn.transaction():
                await conn.execute(sql)
                await conn.execute(
                    "INSERT INTO schema_migrations (version) VALUES ($1)", version
                )
            applied_now.append(version)
    finally:
        await conn.close()
    return applied_now


async def main() -> None:
    applied = await migrate(settings.database_url)
    if applied:
        for version in applied:
            print(f"applied {version}")
    else:
        print("no pending migrations")


if __name__ == "__main__":
    asyncio.run(main())
