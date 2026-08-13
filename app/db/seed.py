"""Seed plans (single source of truth: app/domain/plans.py) plus a demo tenant.

Idempotent — safe to run repeatedly. Run with:
    uv run python -m app.db.seed
"""

from __future__ import annotations

import asyncio

import asyncpg

from app.config import settings
from app.domain.plans import PLANS

PLAN_NAMES = {"free": "Free", "pro": "Pro"}


async def seed_plans(conn: asyncpg.Connection) -> list[str]:
    codes: list[str] = []
    for code, cfg in PLANS.items():
        await conn.execute(
            """
            INSERT INTO plans (code, name, api_call_limit, ai_token_limit, price_micro)
            VALUES ($1, $2, $3, $4, $5)
            ON CONFLICT (code) DO UPDATE SET
                name           = EXCLUDED.name,
                api_call_limit = EXCLUDED.api_call_limit,
                ai_token_limit = EXCLUDED.ai_token_limit,
                price_micro    = EXCLUDED.price_micro
            """,
            code,
            PLAN_NAMES[code],
            cfg["api_call_limit"],
            cfg["ai_token_limit"],
            cfg["price_micro"],
        )
        codes.append(code)
    return codes


async def seed(dsn: str | None = None) -> dict:
    conn = await asyncpg.connect(dsn or settings.database_url)
    try:
        plans = await seed_plans(conn)
        tenant = await conn.fetchrow("SELECT id FROM tenants WHERE name = 'Demo Tenant'")
        if tenant is None:
            tenant_id = await conn.fetchval(
                "INSERT INTO tenants (name) VALUES ('Demo Tenant') RETURNING id"
            )
            plan_id = await conn.fetchval("SELECT id FROM plans WHERE code = 'free'")
            await conn.execute(
                """
                INSERT INTO subscriptions (tenant_id, plan_id, status)
                VALUES ($1, $2, 'active')
                ON CONFLICT (tenant_id) DO NOTHING
                """,
                tenant_id,
                plan_id,
            )
        else:
            tenant_id = tenant["id"]
        return {"plans": plans, "tenant_id": str(tenant_id)}
    finally:
        await conn.close()


async def main() -> None:
    result = await seed()
    print(f"seeded plans: {result['plans']}")
    print(f"demo tenant id: {result['tenant_id']}")


if __name__ == "__main__":
    asyncio.run(main())
