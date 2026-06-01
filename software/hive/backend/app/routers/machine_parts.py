from fastapi import APIRouter, Depends

from app.deps import get_current_machine
from app.errors import APIError
from app.models.machine import Machine
from app.services.profile_catalog import get_profile_catalog_service

router = APIRouter(prefix="/api/machine/parts", tags=["machine-parts"])


@router.get("/{part_num}")
def get_part_metadata(part_num: str, _machine: Machine = Depends(get_current_machine)):
    result = get_profile_catalog_service().admin_get_part(part_num)
    if result is None:
        raise APIError(404, "Part not found", "part_not_found")
    return result
