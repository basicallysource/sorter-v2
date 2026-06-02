from fastapi import APIRouter, Depends, Query

from app.deps import require_role
from app.errors import APIError
from app.models.user import User
from app.services.profile_catalog import get_profile_catalog_service

router = APIRouter(prefix="/api/admin/parts-db", tags=["admin"])


@router.get("/overview")
def parts_db_overview(_admin: User = Depends(require_role("admin"))):
    return get_profile_catalog_service().admin_overview()


@router.get("/parts")
def parts_db_list_parts(
    q: str = "",
    cat_id: int | None = None,
    missing: str | None = None,
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    _admin: User = Depends(require_role("admin")),
):
    return get_profile_catalog_service().admin_list_parts(q, cat_id, missing, limit, offset)


@router.get("/parts/{part_num}")
def parts_db_get_part(part_num: str, _admin: User = Depends(require_role("admin"))):
    result = get_profile_catalog_service().admin_get_part(part_num)
    if result is None:
        raise APIError(404, "Part not found", "part_not_found")
    return result


@router.get("/categories")
def parts_db_categories(_admin: User = Depends(require_role("admin"))):
    return {"results": get_profile_catalog_service().admin_list_categories()}


@router.get("/colors")
def parts_db_colors(_admin: User = Depends(require_role("admin"))):
    return {"results": get_profile_catalog_service().list_colors()}
