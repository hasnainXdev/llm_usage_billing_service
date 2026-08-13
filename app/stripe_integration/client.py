"""Stripe client - the ONLY place that imports the Stripe SDK.

Checkout is test-mode only, forever. Money crosses this boundary as integer
cents (Stripe's minor unit), converted from integer micro-units via
money.micro_to_cents - never a float.
"""

from __future__ import annotations

import stripe

from app.config import settings
from app.domain import money
from app.domain.plans import PLANS

PRO_PLAN_CODE = "pro"
PRO_PRICE_CURRENCY = "usd"
PRO_PRICE_IDEMPOTENCY_KEY = "flyrank-capstone-pro-monthly-v1"
PRO_PRICE_METADATA = {"app_plan": PRO_PLAN_CODE}


class StripeNotConfigured(RuntimeError):
    """Raised when Stripe test-mode credentials are missing."""


def _client() -> stripe.StripeClient:
    key = settings.stripe_secret_key.strip()
    if not key:
        raise StripeNotConfigured("STRIPE_SECRET_KEY is not set (test mode required).")
    return stripe.StripeClient(api_key=key)


def ensure_pro_price() -> str:
    """Idempotently create the Pro monthly Price in test mode.

    The idempotency key makes this deterministic per account: the same Price is
    returned on every call, so nothing needs to be stored in our DB.
    """
    client = _client()
    price = client.v1.prices.create(
        params={
            "currency": PRO_PRICE_CURRENCY,
            "unit_amount": money.micro_to_cents(PLANS[PRO_PLAN_CODE]["price_micro"]),
            "recurring": {"interval": "month"},
            "product_data": {"name": "Pro"},
            "metadata": PRO_PRICE_METADATA,
        },
        options={"idempotency_key": PRO_PRICE_IDEMPOTENCY_KEY},
    )
    return price.id


def create_checkout_session(*, tenant_id: str, success_url: str, cancel_url: str) -> dict:
    """Create a test-mode Checkout Session that upgrades `tenant_id` to Pro.

    `client_reference_id` + `metadata.tenant_id` let the webhook handler
    attribute checkout.session.completed back to the right tenant.
    """
    client = _client()
    price_id = ensure_pro_price()
    session = client.v1.checkout.sessions.create(
        params={
            "mode": "subscription",
            "line_items": [{"price": price_id, "quantity": 1}],
            "client_reference_id": tenant_id,
            "metadata": {"tenant_id": tenant_id},
            "success_url": success_url,
            "cancel_url": cancel_url,
            "subscription_data": {"metadata": {"tenant_id": tenant_id}},
        }
    )
    return {
        "checkout_session_id": session.id,
        "url": session.url,
        "price_id": price_id,
    }
