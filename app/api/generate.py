from __future__ import annotations

import re
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Header, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from app.services.meter_service import Accepted, MeterService, Rejected

router = APIRouter()

IDEMPOTENCY_KEY_RE = re.compile(r"^[A-Za-z0-9._-]{1,128}$")


class GenerateRequest(BaseModel):
    usage_type: Literal["api_call", "ai_token"]
    quantity: int = Field(gt=0)
    token_category: Literal["input", "cached_input", "output", "reasoning"] | None = None


class GenerateResponse(BaseModel):
    usage_event_id: str
    tenant_id: str
    usage_type: str
    token_category: str | None
    quantity: int
    cost_micro: int
    used: int
    limit: int
    deduplicated: bool


@router.post("/generate", response_model=GenerateResponse)
async def generate(
    payload: GenerateRequest,
    request: Request,
    x_tenant_id: UUID = Header(...),
    idempotency_key: str = Header(...),
):
    if not IDEMPOTENCY_KEY_RE.match(idempotency_key):
        return JSONResponse(
            status_code=400,
            content={
                "code": "invalid_idempotency_key",
                "detail": "Idempotency-Key must be 1-128 characters of [A-Za-z0-9._-].",
            },
        )

    service = MeterService(request.app.state.pool)
    result = await service.record(
        tenant_id=x_tenant_id,
        usage_type=payload.usage_type,
        quantity=payload.quantity,
        token_category=payload.token_category,
        idempotency_key=idempotency_key,
    )

    if isinstance(result, Accepted):
        return result

    if result.reason == "quota_exceeded":
        return JSONResponse(
            status_code=429,
            content={
                "code": "quota_exceeded",
                "detail": result.message,
                "used": result.used,
                "limit": result.limit,
            },
        )

    return JSONResponse(
        status_code=402,
        content={"code": "payment_required", "detail": result.message},
    )
