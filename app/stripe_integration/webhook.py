"""Webhook signature verification. The whsec_ secret lives in .env (gitignored).

Returns the verified event as a plain dict, or None when the signature is
missing, malformed, or forged — a forged request must never touch the DB.
"""

from __future__ import annotations

import stripe

from app.config import settings


def verify_signature(payload: bytes, sig_header: str) -> dict | None:
    secret = settings.stripe_webhook_secret.strip()
    if not secret:
        return None
    try:
        event = stripe.Webhook.construct_event(payload, sig_header, secret)
        return event.to_dict(recursive=True)
    except (ValueError, stripe.error.SignatureVerificationError):
        return None
