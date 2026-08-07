from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.deps import get_current_machine
from app.errors import APIError
from app.models.machine import Machine
from app.services.profile_catalog import get_profile_catalog_service

router = APIRouter(prefix="/api/machine/parts", tags=["machine-parts"])

# bricklink-colors lives directly under /api/machine so it doesn't collide with
# the /{part_num} path param on the parts router.
catalog_router = APIRouter(prefix="/api/machine", tags=["machine-parts"])


class PricePair(BaseModel):
    part_num: str
    color_id: int | None = None


class BatchPriceRequest(BaseModel):
    pairs: list[PricePair]


@router.post("/prices")
def batch_part_prices(payload: BatchPriceRequest, _machine: Machine = Depends(get_current_machine)):
    pairs: list[dict[str, Any]] = [{"part_num": p.part_num, "color_id": p.color_id} for p in payload.pairs]
    return {"prices": get_profile_catalog_service().batch_piece_prices(pairs)}


@router.get("/{part_num}")
def get_part_metadata(
    part_num: str,
    color_id: int | None = None,
    _machine: Machine = Depends(get_current_machine),
):
    result = get_profile_catalog_service().piece_metadata(part_num, color_id)
    if result is None:
        raise APIError(404, "Part not found", "part_not_found")
    return result


@catalog_router.get("/bricklink-colors")
def list_bricklink_colors(_machine: Machine = Depends(get_current_machine)):
    return {"results": get_profile_catalog_service().list_bricklink_colors()}
