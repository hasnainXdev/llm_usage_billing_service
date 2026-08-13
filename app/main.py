from __future__ import annotations

from contextlib import asynccontextmanager

import asyncpg
from fastapi import FastAPI

from app.api import checkout, generate, usage, webhooks
from app.repositories.db import create_pool


def create_app(pool: asyncpg.Pool | None = None) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        owns_pool = False
        if app.state.pool is None:
            app.state.pool = await create_pool()
            owns_pool = True
        try:
            yield
        finally:
            if owns_pool:
                await app.state.pool.close()

    app = FastAPI(
        title="flyrank-capstone-metering-billing",
        description="LLM usage metering + billing service (test-mode Stripe only).",
        lifespan=lifespan,
    )
    # Set eagerly so callers that never run lifespan (e.g. ASGI test clients)
    # still see a pool. Production leaves it None and lifespan provisions it.
    app.state.pool = pool
    app.include_router(generate.router)
    app.include_router(usage.router)
    app.include_router(checkout.router)
    app.include_router(webhooks.router)

    @app.get("/health")
    async def health():
        return {"status": "ok"}

    return app


app = create_app()
