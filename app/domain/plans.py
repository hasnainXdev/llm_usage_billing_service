"""Pinned plan definitions. Single source of truth for the seed step.

Exactly 2 plans (scope lock). Limits are monthly; price is integer micro-units.
"""

from __future__ import annotations

from app.domain.money import require_int

PLAN_CODES: tuple[str, ...] = ("free", "pro")

PLANS: dict[str, dict[str, int]] = {
    "free": {
        "api_call_limit": 1_000,  # 1,000 API calls / month
        "ai_token_limit": 100_000,  # 100,000 AI tokens / month
        "price_micro": 0,  # $0.00
    },
    "pro": {
        "api_call_limit": 100_000,  # 100,000 API calls / month
        "ai_token_limit": 10_000_000,  # 10,000,000 AI tokens / month
        "price_micro": 20_000_000,  # $20.00 / month
    },
}


def plan_limits(plan_code: str) -> dict[str, int]:
    if plan_code not in PLANS:
        raise ValueError(f"unknown plan: {plan_code}")
    return dict(PLANS[plan_code])


def validate_plan_numbers(plan_code: str) -> None:
    """Guard: every money/limit field in a plan must be a positive int."""
    for key, value in PLANS[plan_code].items():
        require_int(value, f"plans.{plan_code}.{key}")
        if value < 0:
            raise ValueError(f"plans.{plan_code}.{key} must be >= 0")
