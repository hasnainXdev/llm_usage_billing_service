"""SubscriptionService - keeps the DB a mirror of Stripe's truth.

Called only from the webhook path with already-verified, already-deduplicated
events. The dedup insert and the state update happen in ONE transaction, so a
replayed event can never apply twice. Never imports the Stripe SDK.
"""

from __future__ import annotations

from datetime import datetime, timezone

import asyncpg

from app.repositories import plan_repo, subscription_repo


class SubscriptionService:
    def __init__(self, pool: asyncpg.Pool):
        self.pool = pool

    async def apply_event(self, event: dict) -> str:
        """Returns "applied", "duplicate", or "unhandled"."""
        event_id = event.get("id")
        event_type = event.get("type")
        data = (event.get("data") or {}).get("object") or {}

        async with self.pool.acquire() as conn:
            async with conn.transaction():
                recorded = await self._record_event(conn, event_id, event_type)
                if not recorded:
                    return "duplicate"  # seen before; effect was already applied
                applied = await self._apply(conn, event_type, data)
                return "applied" if applied else "unhandled"

    @staticmethod
    async def _record_event(conn: asyncpg.Connection, event_id: str, event_type: str) -> bool:
        row = await conn.fetchrow(
            """
            INSERT INTO stripe_events (stripe_event_id, event_type)
            VALUES ($1, $2)
            ON CONFLICT (stripe_event_id) DO NOTHING
            RETURNING id
            """,
            event_id,
            event_type,
        )
        return row is not None

    async def _apply(self, conn: asyncpg.Connection, event_type: str, data: dict) -> bool:
        if event_type == "checkout.session.completed":
            return await self._apply_checkout_completed(conn, data)
        if event_type == "customer.subscription.updated":
            return await self._apply_subscription_updated(conn, data)
        if event_type == "customer.subscription.deleted":
            return await self._apply_subscription_deleted(conn, data)
        return False  # event type we do not act on

    async def _apply_checkout_completed(self, conn: asyncpg.Connection, session: dict) -> bool:
        tenant_id = session.get("client_reference_id") or (
            session.get("metadata") or {}
        ).get("tenant_id")
        if not tenant_id:
            return False  # cannot attribute the session to a tenant
        sub = await subscription_repo.lock_subscription_with_plan(conn, tenant_id)
        if sub is None:
            return False
        pro_plan_id = await plan_repo.get_plan_id(conn, "pro")
        await subscription_repo.update_subscription(
            conn,
            tenant_id=tenant_id,
            plan_id=pro_plan_id,
            status="active",
            stripe_customer_id=session.get("customer"),
            stripe_subscription_id=session.get("subscription"),
        )
        return True

    async def _apply_subscription_updated(self, conn: asyncpg.Connection, sub: dict) -> bool:
        tenant_id = await self._tenant_for_subscription(conn, sub)
        if tenant_id is None:
            return False
        status = sub.get("status")
        period_end = sub.get("current_period_end")
        current_period_end = (
            datetime.fromtimestamp(period_end, tz=timezone.utc) if period_end else None
        )
        plan_id = None
        items = (sub.get("items") or {}).get("data") or []
        for item in items:
            app_plan = (item.get("price") or {}).get("metadata", {}).get("app_plan")
            if app_plan:
                plan_id = await plan_repo.get_plan_id(conn, app_plan)
                break
        await subscription_repo.update_subscription(
            conn,
            tenant_id=tenant_id,
            status=status,
            stripe_customer_id=sub.get("customer"),
            stripe_subscription_id=sub.get("id"),
            current_period_end=current_period_end,
            plan_id=plan_id,
        )
        return True

    async def _apply_subscription_deleted(self, conn: asyncpg.Connection, sub: dict) -> bool:
        tenant_id = await self._tenant_for_subscription(conn, sub)
        if tenant_id is None:
            return False
        await subscription_repo.update_subscription(conn, tenant_id=tenant_id, status="canceled")
        return True

    async def _tenant_for_subscription(self, conn: asyncpg.Connection, sub: dict):
        tenant_id = (sub.get("metadata") or {}).get("tenant_id")
        if tenant_id:
            return tenant_id
        row = await subscription_repo.get_by_stripe_subscription_id(conn, sub.get("id"))
        return row["tenant_id"] if row else None
