"""Set instances: a user's physical set copies and what has been found for them."""

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from fastapi.responses import Response
from sqlalchemy.orm import Session

from app.deps import get_current_user, get_db, verify_csrf
from app.models.set_instance import SetInstance
from app.models.user import User
from app.schemas.set_instance import (
    SetInstanceCreateRequest,
    SetInstanceDetailResponse,
    SetInstancePartAdjustRequest,
    SetInstancePartResponse,
    SetInstanceSummaryResponse,
    SetInstanceUpdateRequest,
)
from app.services import set_instances as service
from app.services.profile_catalog import get_profile_catalog_service

router = APIRouter(prefix="/api/set-instances", tags=["set-instances"])


def _summary(catalog: Any, instance: SetInstance) -> dict[str, Any]:
    cached = catalog.cached_set(instance.set_num) or {}
    totals = service.progress_totals(instance.progress)
    return {
        "id": instance.id,
        "set_source": instance.set_source,
        "set_num": instance.set_num,
        "label": instance.label,
        "status": instance.status,
        "include_spares": instance.include_spares,
        "notes": instance.notes,
        "created_at": instance.created_at,
        "updated_at": instance.updated_at,
        "set_meta": {
            "name": cached.get("name"),
            "year": cached.get("year"),
            "num_parts": cached.get("num_parts"),
            "img_url": cached.get("set_img_url"),
        },
        "part_count": totals["part_count"],
        "total_needed": totals["total_needed"],
        "total_found": totals["total_found"],
        "pct": totals["pct"],
        "progress_updated_at": totals["updated_at"],
    }


def _detail(catalog: Any, instance: SetInstance) -> dict[str, Any]:
    return {**_summary(catalog, instance), "parts": service.part_details(catalog, instance)}


@router.get("", response_model=list[SetInstanceSummaryResponse])
def list_set_instances(
    include_archived: bool = Query(False),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    catalog = get_profile_catalog_service()
    return [_summary(catalog, instance) for instance in service.list_instances(db, current_user, include_archived=include_archived)]


@router.post("", response_model=SetInstanceDetailResponse, status_code=201)
def create_set_instance(
    payload: SetInstanceCreateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    _csrf: None = Depends(verify_csrf),
):
    catalog = get_profile_catalog_service()
    instance = service.create_instance(
        db,
        current_user,
        catalog,
        set_num=payload.set_num.strip(),
        label=payload.label,
        include_spares=payload.include_spares,
        notes=payload.notes,
    )
    return _detail(catalog, instance)


@router.get("/{instance_id}", response_model=SetInstanceDetailResponse)
def get_set_instance(
    instance_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    instance = service.get_owned_instance(db, current_user, instance_id)
    return _detail(get_profile_catalog_service(), instance)


@router.patch("/{instance_id}", response_model=SetInstanceSummaryResponse)
def update_set_instance(
    instance_id: UUID,
    payload: SetInstanceUpdateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    _csrf: None = Depends(verify_csrf),
):
    instance = service.get_owned_instance(db, current_user, instance_id)
    instance = service.update_instance(db, instance, label=payload.label, notes=payload.notes, status=payload.status)
    return _summary(get_profile_catalog_service(), instance)


@router.post("/{instance_id}/archive", response_model=SetInstanceSummaryResponse)
def archive_set_instance(
    instance_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    _csrf: None = Depends(verify_csrf),
):
    instance = service.get_owned_instance(db, current_user, instance_id)
    return _summary(get_profile_catalog_service(), service.archive_instance(db, instance))


@router.put("/{instance_id}/parts/{part_num}/{color_id}", response_model=SetInstancePartResponse)
def adjust_set_instance_part(
    instance_id: UUID,
    part_num: str,
    color_id: int,
    payload: SetInstancePartAdjustRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    _csrf: None = Depends(verify_csrf),
):
    instance = service.get_owned_instance(db, current_user, instance_id)
    service.set_part_found(db, instance, part_num=part_num, color_id=color_id, quantity_found=payload.quantity_found)
    parts = service.part_details(get_profile_catalog_service(), instance)
    return next(part for part in parts if part["part_num"] == part_num and part["color_id"] == color_id)


@router.get("/{instance_id}/missing", response_model=list[SetInstancePartResponse])
def get_set_instance_missing(
    instance_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    instance = service.get_owned_instance(db, current_user, instance_id)
    return service.missing_parts(service.part_details(get_profile_catalog_service(), instance))


@router.get("/{instance_id}/wanted-list.xml")
def get_set_instance_wanted_list(
    instance_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    instance = service.get_owned_instance(db, current_user, instance_id)
    missing = service.missing_parts(service.part_details(get_profile_catalog_service(), instance))
    filename = f"wanted-{instance.set_num}.xml"
    return Response(
        content=service.wanted_list_xml(missing),
        media_type="application/xml",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
