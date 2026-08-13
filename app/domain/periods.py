"""Billing-period helpers. The monthly window is the current UTC month."""

from __future__ import annotations

from datetime import datetime, timezone


def utc_month_start(now: datetime | None = None) -> datetime:
    now = now or datetime.now(timezone.utc)
    return now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


def period_label(month_start: datetime) -> str:
    return month_start.strftime("%Y-%m")
