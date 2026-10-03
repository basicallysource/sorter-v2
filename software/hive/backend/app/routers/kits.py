"""Kits, and the pictures a profile's rules and kits are shown by."""

from __future__ import annotations

import uuid
from uuid import UUID

from fastapi import APIRouter, Depends, File, Query, UploadFile
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.config import settings
from app.deps import (
    API_KEY_SCOPE_PROFILES_READ,
    API_KEY_SCOPE_PROFILES_WRITE,
    get_db,
    require_api_key_scopes,
    verify_csrf,
)
from app.errors import APIError
from app.models.kit import Kit
from app.models.user import User
from app.schemas.kit import (
    KitCreateRequest,
    KitFromBricklinkCsvRequest,
    KitFromSetRequest,
    KitResponse,
    KitSummaryResponse,
    KitUpdateRequest,
)
from app.services.kits import (
    can_use,
    describe_lines,
    line_warnings,
    lines_from_set,
    normalize_visibility,
    profiles_using,
    resolve_lines,
)
from app.services.profile_catalog import CUSTOM_SET_ANY_COLOR_ID, get_profile_catalog_service
from app.services.storage import serve_stored_file, validate_image
from app.services.storage_backend import get_backend

router = APIRouter(prefix="/api", tags=["kits"])

READ = Depends(require_api_key_scopes(API_KEY_SCOPE_PROFILES_READ))
WRITE = Depends(require_api_key_scopes(API_KEY_SCOPE_PROFILES_WRITE))
IMAGE_PREFIX = "profile-images"


def _owner(user: User) -> dict:
    return {
        "id": user.id,
        "display_name": user.display_name,
        "github_login": getattr(user, "github_login", None),
        "avatar_url": user.avatar_url,
    }


def _summary(kit: Kit, current_user: User) -> dict:
    parts = kit.parts or []
    return {
        "id": kit.id,
        "name": kit.name,
        "description": kit.description,
        "image_url": kit.image_url or (kit.set_meta or {}).get("img_url") or next((part.get("img_url") for part in parts if part.get("img_url")), None),
        "source": kit.source,
        "set_num": kit.set_num,
        "set_meta": kit.set_meta,
        "visibility": kit.visibility,
        "line_count": len(parts),
        "total_quantity": sum(int(part.get("quantity") or 0) for part in parts),
        "any_color_lines": sum(1 for part in parts if part.get("color_id") in (None, CUSTOM_SET_ANY_COLOR_ID)),
        "owner": _owner(kit.owner),
        "is_owner": kit.owner_id == current_user.id,
        "created_at": kit.created_at,
        "updated_at": kit.updated_at,
    }


def _detail(db: Session, kit: Kit, current_user: User) -> dict:
    catalog = get_profile_catalog_service()
    return {
        **_summary(kit, current_user),
        "parts": describe_lines(catalog, kit.parts or []),
        "warnings": line_warnings(kit.parts or []),
        "used_by": profiles_using(db, kit) if kit.owner_id == current_user.id else [],
    }


def _get_kit(db: Session, kit_id: UUID, current_user: User, *, edit: bool = False) -> Kit:
    kit = db.query(Kit).filter(Kit.id == kit_id).first()
    if kit is None or not can_use(kit, current_user.id):
        raise APIError(404, "Kit not found", "KIT_NOT_FOUND")
    if edit and kit.owner_id != current_user.id:
        raise APIError(403, "Only the kit's owner can change it", "KIT_EDIT_DENIED")
    return kit


@router.get("/kits", response_model=list[KitSummaryResponse])
def list_kits(
    scope: str = Query(default="mine", pattern="^(mine|public)$"),
    q: str = Query(default=""),
    db: Session = Depends(get_db),
    current_user: User = READ,
):
    query = db.query(Kit)
    query = query.filter(Kit.owner_id == current_user.id) if scope == "mine" else query.filter(Kit.visibility == "public")
    if q.strip():
        needle = f"%{q.strip().lower()}%"
        query = query.filter(or_(Kit.name.ilike(needle), Kit.set_num.ilike(needle)))
    return [_summary(kit, current_user) for kit in query.order_by(Kit.updated_at.desc()).limit(500).all()]


@router.post("/kits", response_model=KitResponse)
def create_kit(
    payload: KitCreateRequest,
    db: Session = Depends(get_db),
    current_user: User = WRITE,
    _csrf: None = Depends(verify_csrf),
):
    parts, _warnings = resolve_lines(get_profile_catalog_service(), payload.parts)
    kit = Kit(
        owner_id=current_user.id,
        name=payload.name.strip(),
        description=(payload.description or "").strip() or None,
        image_url=(payload.image_url or "").strip() or None,
        visibility=normalize_visibility(payload.visibility),
        source="custom",
        parts=parts,
    )
    db.add(kit)
    db.commit()
    db.refresh(kit)
    return _detail(db, kit, current_user)


@router.post("/kits/from-set", response_model=KitResponse)
def create_kit_from_set(
    payload: KitFromSetRequest,
    db: Session = Depends(get_db),
    current_user: User = WRITE,
    _csrf: None = Depends(verify_csrf),
):
    details, parts = lines_from_set(get_profile_catalog_service(), payload.set_num.strip(), payload.include_spares)
    if not parts:
        raise APIError(404, f"Set {payload.set_num} has no parts in the catalog", "KIT_SET_EMPTY")
    kit = Kit(
        owner_id=current_user.id,
        name=(payload.name or details.get("name") or payload.set_num).strip(),
        source="set",
        set_num=details.get("set_num") or payload.set_num.strip(),
        set_meta=details,
        include_spares=payload.include_spares,
        image_url=details.get("img_url"),
        visibility="private",
        parts=parts,
    )
    db.add(kit)
    db.commit()
    db.refresh(kit)
    return _detail(db, kit, current_user)


@router.post("/kits/from-bricklink-csv", response_model=KitResponse)
def create_kit_from_bricklink_csv(
    payload: KitFromBricklinkCsvRequest,
    db: Session = Depends(get_db),
    current_user: User = WRITE,
    _csrf: None = Depends(verify_csrf),
):
    result = get_profile_catalog_service().import_bricklink_csv(payload.csv_content, filename=payload.filename)
    kit = Kit(
        owner_id=current_user.id,
        name=(payload.name or result.get("suggested_name") or "Imported kit").strip(),
        source="bricklink",
        visibility="private",
        parts=result["parts"],
    )
    db.add(kit)
    db.commit()
    db.refresh(kit)
    detail = _detail(db, kit, current_user)
    detail["warnings"] = [*detail["warnings"], *result.get("warnings", [])]
    return detail


@router.get("/kits/{kit_id}", response_model=KitResponse)
def get_kit(kit_id: UUID, db: Session = Depends(get_db), current_user: User = READ):
    return _detail(db, _get_kit(db, kit_id, current_user), current_user)


@router.patch("/kits/{kit_id}", response_model=KitResponse)
def update_kit(
    kit_id: UUID,
    payload: KitUpdateRequest,
    db: Session = Depends(get_db),
    current_user: User = WRITE,
    _csrf: None = Depends(verify_csrf),
):
    kit = _get_kit(db, kit_id, current_user, edit=True)
    if payload.name is not None:
        kit.name = payload.name.strip() or kit.name
    if payload.description is not None:
        kit.description = payload.description.strip() or None
    if payload.image_url is not None:
        kit.image_url = payload.image_url.strip() or None
    if payload.visibility is not None:
        kit.visibility = normalize_visibility(payload.visibility)
    if payload.parts is not None:
        parts, _warnings = resolve_lines(get_profile_catalog_service(), payload.parts)
        kit.parts = parts
        if kit.source == "set":
            # Edited lines are no longer the set's inventory.
            kit.source = "custom"
    db.commit()
    db.refresh(kit)
    return _detail(db, kit, current_user)


@router.delete("/kits/{kit_id}")
def delete_kit(
    kit_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = WRITE,
    _csrf: None = Depends(verify_csrf),
):
    kit = _get_kit(db, kit_id, current_user, edit=True)
    used_by = profiles_using(db, kit)
    if used_by:
        names = ", ".join(profile["name"] for profile in used_by)
        raise APIError(409, f"Profiles use this kit: {names}. Remove its rule from them first.", "KIT_IN_USE", details=used_by)
    db.delete(kit)
    db.commit()
    return {"ok": True}


@router.post("/profile-images")
def upload_profile_image(
    file: UploadFile = File(...),
    current_user: User = WRITE,
    _csrf: None = Depends(verify_csrf),
):
    """Store a picture for a rule or a kit; set the returned url as its image_url."""
    suffix = validate_image(file)
    name = f"{uuid.uuid4().hex}{suffix}"
    file.file.seek(0)
    get_backend().write_stream(f"{IMAGE_PREFIX}/{name}", file.file, content_type=file.content_type)
    return {"url": f"{settings.public_app_url}/api/profile-images/{name}"}


@router.get("/profile-images/{name}")
def get_profile_image(name: str):
    # Names are random, so a picture is as private as the profile showing it.
    stem, _, suffix = name.partition(".")
    if len(stem) != 32 or not all(char in "0123456789abcdef" for char in stem) or suffix not in ("jpg", "png"):
        raise APIError(404, "Image not found", "PROFILE_IMAGE_NOT_FOUND")
    return serve_stored_file(
        f"{IMAGE_PREFIX}/{name}",
        media_type="image/png" if suffix == "png" else "image/jpeg",
        headers={"Cache-Control": "public, max-age=31536000, immutable"},
    )
