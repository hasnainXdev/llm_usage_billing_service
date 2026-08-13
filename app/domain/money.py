"""Integer-only money handling.

Hard rule: money is always an integer (micro-units). No float ever touches a
money column, a money variable, or a money calculation. `require_int` is the
guard every money value passes through.
"""

from __future__ import annotations

MICRO_PER_USD: int = 1_000_000  # 1 USD = 1,000,000 micro-units
CENTS_PER_USD: int = 100
MICRO_PER_CENT: int = MICRO_PER_USD // CENTS_PER_USD  # 10,000 micro = 1 cent


def require_int(value: object, name: str) -> int:
    """Reject any non-int flowing into a money value. Floats are refused."""
    if not isinstance(value, int):
        raise TypeError(
            f"{name} must be an int (money is integer-only micro-units), "
            f"got {type(value).__name__}"
        )
    return value


def micro_to_cents(amount_micro: int) -> int:
    """Stripe expects integer cents. 1 cent = 10,000 micro-units."""
    require_int(amount_micro, "amount_micro")
    return amount_micro // MICRO_PER_CENT


def ceil_div(numerator: int, denominator: int) -> int:
    """Ceiling of an integer division - the only rounding money ever uses.

    Deterministic, integer-only, and never loses a fraction to a float.
    """
    require_int(numerator, "numerator")
    require_int(denominator, "denominator")
    if denominator <= 0:
        raise ValueError("denominator must be > 0")
    return -(-numerator // denominator)
