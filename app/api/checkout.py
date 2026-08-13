from __future__ import annotations

import asyncio
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Header, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from app.config import settings
from app.stripe_integration import client as stripe_client
from app.stripe_integration.client import StripeNotConfigured

router = APIRouter()


class CheckoutRequest(BaseModel):
    plan: Literal["pro"] = "pro"


@router.post("/billing/checkout")
async def create_checkout(
    payload: CheckoutRequest,
    request: Request,
    x_tenant_id: UUID = Header(...),
):
    # Stripe requires the session id placeholder in the success URL.
    base = settings.app_base_url
    success_url = f"{base}/billing/checkout/success?session_id={{CHECKOUT_SESSION_ID}}"
    cancel_url = f"{base}/billing/checkout/cancel"
    try:
        # Blocking Stripe SDK call → off the event loop.
        result = await asyncio.to_thread(
            stripe_client.create_checkout_session,
            tenant_id=str(x_tenant_id),
            success_url=success_url,
            cancel_url=cancel_url,
        )
    except StripeNotConfigured:
        return JSONResponse(
            status_code=503,
            content={
                "code": "stripe_not_configured",
                "detail": "Stripe test-mode credentials are not configured.",
            },
        )
    return result
