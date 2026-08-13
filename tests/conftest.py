from __future__ import annotations

import uuid

import asyncpg
import pytest
from httpx import ASGITransport, AsyncClient

from app.config import settings
from app.db.migrate import migrate
from app.db.seed import seed_plans
from app.main import create_app

TEST_DB_NAME = "flyrank_test"


def _test_dsn() -> str:
    return settings.database_url.rsplit("/", 1)[0] + "/" + TEST_DB_NAME


async def _ensure_test_db() -> None:
    conn = await asyncpg.connect(settings.database_url)
    try:
        exists = await conn.fetchval(
            "SELECT 1 FROM pg_database WHERE datname = $1", TEST_DB_NAME
        )
        if not exists:
            await conn.execute(f'CREATE DATABASE "{TEST_DB_NAME}"')
    finally:
        await conn.close()


@pytest.fixture(scope="session")
async def pool():
    await _ensure_test_db()
    dsn = _test_dsn()
    await migrate(dsn)
    p = await asyncpg.create_pool(dsn=dsn, min_size=1, max_size=20)
    async with p.acquire() as conn:
        await seed_plans(conn)
    yield p
    await p.close()


@pytest.fixture(autouse=True)
async def _clean_db(pool):
    async with pool.acquire() as conn:
        await conn.execute(
            "TRUNCATE tenants, subscriptions, usage_events, stripe_events "
            "RESTART IDENTITY CASCADE"
        )
    yield


@pytest.fixture
async def client(pool):
    app = create_app(pool=pool)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


@pytest.fixture
def make_tenant(pool):
    async def _make(*, name: str = "Demo Tenant", plan: str = "free", status: str = "active") -> str:
        async with pool.acquire() as conn:
            tid = await conn.fetchval(
                "INSERT INTO tenants (name) VALUES ($1) RETURNING id", name
            )
            pid = await conn.fetchval("SELECT id FROM plans WHERE code = $1", plan)
            await conn.execute(
                "INSERT INTO subscriptions (tenant_id, plan_id, status) VALUES ($1, $2, $3)",
                tid,
                pid,
                status,
            )
        return str(tid)

    return _make


@pytest.fixture
def count_events(pool):
    async def _count(tenant_id: str) -> int:
        async with pool.acquire() as conn:
            return await conn.fetchval(
                "SELECT count(*) FROM usage_events WHERE tenant_id = $1",
                uuid.UUID(tenant_id),
            )

    return _count
