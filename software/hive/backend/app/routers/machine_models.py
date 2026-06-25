import math
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.deps import get_current_machine, get_db
from app.errors import APIError
from app.models.detection_model import DetectionModel, DetectionModelVariant
from app.models.machine import Machine
from app.schemas.model import (
    DetectionModelDetail,
    DetectionModelListResponse,
    DetectionModelSummary,
    DetectionModelVariantDetail,
)
from app.services.storage import build_download_filename, serve_model_variant

router = APIRouter(prefix="/api/machine/models", tags=["machine-models"])


def _summary(model: DetectionModel) -> DetectionModelSummary:
    data = DetectionModelSummary.model_validate(model)
    data.variant_runtimes = sorted(v.runtime for v in model.variants)
    return data


def _detail(model: DetectionModel) -> DetectionModelDetail:
    data = DetectionModelDetail.model_validate(model)
    data.variant_runtimes = sorted(v.runtime for v in model.variants)
    data.variants = [DetectionModelVariantDetail.model_validate(v) for v in model.variants]
    return data


@router.get("", response_model=DetectionModelListResponse)
def list_models_machine(
    page: int = Query(1, ge=1),
    page_size: int = Query(30, ge=1, le=100),
    scope: str | None = None,
    runtime: str | None = None,
    family: str | None = None,
    q: str | None = None,
    include_experimental: bool = Query(
        False,
        description="Include experimental models. Hidden by default so a sorter doesn't install a test model by accident.",
    ),
    db: Session = Depends(get_db),
    machine: Machine = Depends(get_current_machine),
):
    # Machines see all public models plus the private models owned by the same
    # account they were registered under. Keeps a user's private work usable
    # from their own sorter without making it visible to other tenants.
    query = db.query(DetectionModel).filter(
        or_(
            DetectionModel.is_public.is_(True),
            DetectionModel.owner_id == machine.owner_id,
        )
    )
    if not include_experimental:
        query = query.filter(DetectionModel.experimental.is_(False))
    if family:
        query = query.filter(DetectionModel.model_family == family)
    if q:
        like = f"%{q}%"
        query = query.filter(
            or_(
                DetectionModel.name.ilike(like),
                DetectionModel.slug.ilike(like),
                DetectionModel.codename.ilike(like),
            )
        )
    if runtime:
        query = query.filter(
            DetectionModel.variants.any(DetectionModelVariant.runtime == runtime)
        )

    query = query.order_by(DetectionModel.published_at.desc())
    models = query.all()

    if scope:
        models = [m for m in models if isinstance(m.scopes, list) and scope in m.scopes]

    total = len(models)
    pages = math.ceil(total / page_size) if total > 0 else 1
    start = (page - 1) * page_size
    end = start + page_size
    items = models[start:end]
    return DetectionModelListResponse(
        items=[_summary(m) for m in items],
        total=total,
        page=page,
        page_size=page_size,
        pages=pages,
    )


def _visible_to_machine(query, machine: Machine):
    """Visibility filter shared by the list/detail/download routes."""
    return query.filter(
        or_(
            DetectionModel.is_public.is_(True),
            DetectionModel.owner_id == machine.owner_id,
        )
    )


@router.get("/{model_id}", response_model=DetectionModelDetail)
def get_model_machine(
    model_id: UUID,
    db: Session = Depends(get_db),
    machine: Machine = Depends(get_current_machine),
):
    model = (
        _visible_to_machine(db.query(DetectionModel), machine)
        .filter(DetectionModel.id == model_id)
        .first()
    )
    if model is None:
        raise APIError(404, "Model not found", "MODEL_NOT_FOUND")
    return _detail(model)


@router.get("/{model_id}/variants/{variant_id}/download")
def download_model_variant_machine(
    model_id: UUID,
    variant_id: UUID,
    db: Session = Depends(get_db),
    machine: Machine = Depends(get_current_machine),
):
    model = (
        _visible_to_machine(db.query(DetectionModel), machine)
        .filter(DetectionModel.id == model_id)
        .first()
    )
    if model is None:
        raise APIError(404, "Model not found", "MODEL_NOT_FOUND")
    variant = (
        db.query(DetectionModelVariant)
        .filter(DetectionModelVariant.id == variant_id, DetectionModelVariant.model_id == model_id)
        .first()
    )
    if variant is None:
        raise APIError(404, "Variant not found", "VARIANT_NOT_FOUND")
    return serve_model_variant(
        variant.file_path,
        filename=build_download_filename(model, variant),
        sha256=variant.sha256,
        file_size=variant.file_size,
    )
