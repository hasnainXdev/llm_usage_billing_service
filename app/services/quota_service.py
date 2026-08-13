"""Quota enforcement.

Domain rule (documented in README): a request that lands usage exactly on the
monthly limit is allowed; only a request that would push usage past the limit is
rejected. Raising aborts the surrounding transaction so a rejected request never
persists an event.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class QuotaExceeded:
    dimension: str  # "api_calls" | "ai_tokens"
    used: int  # already-used quantity in the current month (before this request)
    requested: int
    limit: int


class QuotaExceededError(Exception):
    def __init__(self, quota: QuotaExceeded):
        self.quota = quota
        super().__init__(str(quota))


class QuotaService:
    def check(self, *, dimension: str, used_after: int, requested: int, limit: int) -> None:
        # used_after already includes this request; allow exactly-at-limit.
        if used_after > limit:
            raise QuotaExceededError(
                QuotaExceeded(
                    dimension=dimension,
                    used=used_after - requested,
                    requested=requested,
                    limit=limit,
                )
            )


def quota_exceeded_message(quota: QuotaExceeded) -> str:
    label = (
        "API-call"
        if quota.dimension == "api_calls"
        else "AI-token"
    )
    return (
        f"Monthly {label} quota exceeded: {quota.used}/{quota.limit} already used, "
        f"and this request needs {quota.requested} more. "
        f"Resets at the start of next month. Upgrade to Pro for higher limits."
    )
