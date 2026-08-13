from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from app.services.subscription_service import SubscriptionService
from app.stripe_integration.webhook import verify_signature

router = APIRouter()


@router.post("/webhooks/stripe")
async def stripe_webhook(request: Request):
    payload = await request.body()
    sig_header = request.headers.get("stripe-signature", "")
    event = verify_signature(payload, sig_header)
    if event is None:
        # Forged / malformed / missing signature: reject, change nothing.
        return JSONResponse(
            status_code=400,
            content={
                "code": "invalid_signature",
                "detail": "Webhook signature verification failed.",
            },
        )
    outcome = await SubscriptionService(request.app.state.pool).apply_event(event)
    return {"received": True, "outcome": outcome}
