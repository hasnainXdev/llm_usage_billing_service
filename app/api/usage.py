from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Header, Request
from fastapi.responses import JSONResponse

from app.services.cost_service import CostService

router = APIRouter()


@router.get("/usage")
async def get_usage(request: Request, x_tenant_id: UUID = Header(...)):
    rollup = await CostService(request.app.state.pool).rollup(tenant_id=x_tenant_id)
    if rollup is None:
        return JSONResponse(
            status_code=404,
            content={"code": "tenant_not_found", "detail": "Tenant not found."},
        )
    return rollup.to_dict()
