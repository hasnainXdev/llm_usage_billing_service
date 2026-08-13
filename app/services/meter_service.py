"""MeterService - the single write path for billable actions.

Per the fixed architecture:

    MeterService.record(tenant, type, qty, idempotencyKey)
    ├─ duplicate key? → return original result (no new event)
    ├─ store usage_event
    └─ Quota Check → allowed
                    └─ limit exceeded → rejected (429 / 402 downstream)

Business logic only: no HTTP types, no Stripe SDK. The database is the dedup
authority (UNIQUE (tenant_id, idempotency_key)); the per-tenant subscription row
lock serializes concurrent writes so quota checks cannot race.
"""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

import asyncpg

from app.domain import pricing
from app.domain.periods import utc_month_start
from app.repositories import subscription_repo, usage_repo
from app.repositories.usage_repo import API_CALL_TYPE, AI_TOKEN_TYPES
from app.services.quota_service import (
    QuotaExceeded,
    QuotaExceededError,
    QuotaService,
    quota_exceeded_message,
)


class PaymentRequiredError(Exception):
    """Tenant has no billable subscription (mirrors Stripe status)."""


@dataclass(frozen=True)
class Accepted:
    usage_event_id: str
    tenant_id: str
    usage_type: str
    token_category: str | None
    quantity: int
    cost_micro: int
    used: int
    limit: int
    deduplicated: bool


@dataclass(frozen=True)
class Rejected:
    reason: str  # "quota_exceeded" | "payment_required"
    message: str
    used: int | None = None
    requested: int | None = None
    limit: int | None = None


class MeterService:
    def __init__(self, pool: asyncpg.Pool):
        self.pool = pool
        self._quota = QuotaService()

    async def record(
        self,
        *,
        tenant_id: UUID,
        usage_type: str,
        quantity: int,
        token_category: str | None,
        idempotency_key: str,
    ) -> Accepted | Rejected:
        stored = pricing.stored_usage_type(usage_type, token_category)
        cost_micro = pricing.cost_micro_for(stored, quantity)
        month_start = utc_month_start()
        dimension = "api_calls" if stored == API_CALL_TYPE else "ai_tokens"
        dimension_types = (API_CALL_TYPE,) if dimension == "api_calls" else AI_TOKEN_TYPES

        async with self.pool.acquire() as conn:
            try:
                async with conn.transaction():
                    sub = await subscription_repo.lock_subscription_with_plan(
                        conn, tenant_id
                    )
                    if sub is None or sub["status"] not in subscription_repo.BILLABLE_STATUSES:
                        raise PaymentRequiredError()

                    row = await usage_repo.insert_event(
                        conn,
                        tenant_id=tenant_id,
                        usage_type=stored,
                        quantity=quantity,
                        idempotency_key=idempotency_key,
                        cost_micro=cost_micro,
                    )

                    if row is None:
                        # Duplicate key: return the ORIGINAL stored result, no new
                        # event, no quota check.
                        original = await usage_repo.get_event_by_key(
                            conn, tenant_id=tenant_id, idempotency_key=idempotency_key
                        )
                        ctype, category = pricing.client_usage_type(original["usage_type"])
                        used = await usage_repo.sum_dimension_usage(
                            conn,
                            tenant_id=tenant_id,
                            usage_types=dimension_types,
                            since=month_start,
                        )
                        limit = self._limit_for(sub, original["usage_type"])
                        return Accepted(
                            usage_event_id=str(original["id"]),
                            tenant_id=str(tenant_id),
                            usage_type=ctype,
                            token_category=category,
                            quantity=original["quantity"],
                            cost_micro=original["cost_micro"],
                            used=used,
                            limit=limit,
                            deduplicated=True,
                        )

                    # Fresh event claimed the key. Quota check now; the sum includes
                    # this new row. Over limit → raise → transaction rolls back →
                    # no event persists and the request is retryable.
                    used_after = await usage_repo.sum_dimension_usage(
                        conn,
                        tenant_id=tenant_id,
                        usage_types=dimension_types,
                        since=month_start,
                    )
                    limit = self._limit_for(sub, stored)
                    self._quota.check(
                        dimension=dimension,
                        used_after=used_after,
                        requested=quantity,
                        limit=limit,
                    )

                    ctype, category = pricing.client_usage_type(stored)
                    return Accepted(
                        usage_event_id=str(row["id"]),
                        tenant_id=str(tenant_id),
                        usage_type=ctype,
                        token_category=category,
                        quantity=quantity,
                        cost_micro=cost_micro,
                        used=used_after,
                        limit=limit,
                        deduplicated=False,
                    )
            except QuotaExceededError as exc:
                return Rejected(
                    reason="quota_exceeded",
                    message=quota_exceeded_message(exc.quota),
                    used=exc.quota.used,
                    requested=exc.quota.requested,
                    limit=exc.quota.limit,
                )
            except PaymentRequiredError:
                return Rejected(
                    reason="payment_required",
                    message=(
                        "Active subscription required to generate. "
                        "Subscribe to a plan to continue."
                    ),
                    requested=quantity,
                )

    @staticmethod
    def _limit_for(sub, stored: str) -> int:
        return sub["api_call_limit"] if stored == API_CALL_TYPE else sub["ai_token_limit"]
