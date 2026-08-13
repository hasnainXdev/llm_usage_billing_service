"""Pinned pricing constants and integer-only cost math.

All money is integer micro-units (1 USD = 1,000,000 micro). Prices are pinned
here and covered by tests; they are the single source of truth for cost.

AI-token pricing rules (per the brief, encoded precisely):
  - cached input tokens are cheaper than fresh input tokens;
  - reasoning tokens are priced as output tokens, never their own category;
  - each token category has its own rate - categories are never summed at one
    flat rate.
"""

from __future__ import annotations

from app.domain.money import ceil_div, require_int

# One billable API call.
API_CALL_RATE_MICRO: int = 100  # $0.0001 per call

# AI-token rates pinned as integer micro-units per 1,000 tokens.
AI_TOKEN_RATE_MICRO_PER_1K: dict[str, int] = {
    "ai_input": 3_000,  # $3.00 / 1M fresh input tokens
    "ai_cached_input": 300,  # $0.30 / 1M cached input tokens (cheaper)
    "ai_output": 15_000,  # $15.00 / 1M output tokens
    "ai_reasoning": 15_000,  # reasoning priced as output - same rate, own key
}

AI_TOKEN_CATEGORIES: tuple[str, ...] = tuple(AI_TOKEN_RATE_MICRO_PER_1K)
AI_TOKEN_CATEGORY_NAMES: dict[str, str] = {
    "ai_input": "input",
    "ai_cached_input": "cached_input",
    "ai_output": "output",
    "ai_reasoning": "reasoning",
}

# Client-facing usage types (the 2 types from the brief) vs stored granular type.
CLIENT_USAGE_TYPE_API_CALL = "api_call"
CLIENT_USAGE_TYPE_AI_TOKEN = "ai_token"


def stored_usage_type(usage_type: str, token_category: str | None) -> str:
    """Map the client-facing (usage_type, token_category) to the stored type."""
    if usage_type == CLIENT_USAGE_TYPE_API_CALL:
        return "api_call"
    if usage_type == CLIENT_USAGE_TYPE_AI_TOKEN:
        category = token_category or "input"
        by_name = {v: k for k, v in AI_TOKEN_CATEGORY_NAMES.items()}
        if category not in by_name:
            raise ValueError(
                f"token_category must be one of "
                f"{sorted(by_name)} for usage_type='ai_token'"
            )
        return by_name[category]
    raise ValueError(f"usage_type must be '{CLIENT_USAGE_TYPE_API_CALL}' or '{CLIENT_USAGE_TYPE_AI_TOKEN}'")


def client_usage_type(stored: str) -> tuple[str, str | None]:
    """Inverse of stored_usage_type, for echoing stored events back to clients."""
    if stored == "api_call":
        return CLIENT_USAGE_TYPE_API_CALL, None
    if stored in AI_TOKEN_CATEGORY_NAMES:
        return CLIENT_USAGE_TYPE_AI_TOKEN, AI_TOKEN_CATEGORY_NAMES[stored]
    raise ValueError(f"unknown stored usage type: {stored}")


def cost_micro_for(usage_type: str, quantity: int) -> int:
    """Integer cost in micro-units for one event. Never returns a float."""
    require_int(quantity, "quantity")
    if quantity <= 0:
        raise ValueError("quantity must be > 0")
    if usage_type == "api_call":
        return quantity * API_CALL_RATE_MICRO
    if usage_type in AI_TOKEN_RATE_MICRO_PER_1K:
        # Per-token rate = pinned-per-1K rate / 1000. Round the product up to the
        # nearest whole micro-unit with integer math only.
        return ceil_div(quantity * AI_TOKEN_RATE_MICRO_PER_1K[usage_type], 1_000)
    raise ValueError(f"unknown usage_type: {usage_type}")
