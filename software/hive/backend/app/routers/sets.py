from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.deps import get_current_user, get_db
from app.errors import APIError
from app.models.user import User
from app.services.profile_catalog import get_profile_catalog_service
from app.services.set_inventory import search_sets
from app.config import settings

router = APIRouter(prefix="/api/sets", tags=["sets"])


@router.get("/search")
def search_lego_sets(
    q: str = Query(..., min_length=1),
    current_user: User = Depends(get_current_user),
):
    """Search Rebrickable for LEGO sets."""
    results = search_sets(settings.REBRICKABLE_API_KEY, q)
    return {"results": results}


@router.get("/{set_num}")
def get_set_detail(
    set_num: str,
    current_user: User = Depends(get_current_user),
):
    """Get set info and inventory, fetching from Rebrickable if not cached."""
    catalog = get_profile_catalog_service()
    cached = catalog.cached_set(set_num)
    if cached is None:
        catalog.fetch_set(set_num)
        cached = catalog.cached_set(set_num)
    if cached is None:
        raise APIError(404, "Set not found", "SET_NOT_FOUND")
    inventory = catalog.cached_set_inventory(set_num)
    return {"set": cached, "inventory": inventory}


@router.post("/{set_num}/sync")
def sync_set(
    set_num: str,
    current_user: User = Depends(get_current_user),
):
    """Force re-fetch set inventory from Rebrickable."""
    catalog = get_profile_catalog_service()
    catalog.fetch_set(set_num)
    cached = catalog.cached_set(set_num)
    inventory = catalog.cached_set_inventory(set_num)
    return {"set": cached, "inventory": inventory}
