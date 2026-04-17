import math
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from fastapi.responses import FileResponse
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
from app.services.storage import get_model_variant_file

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
    db: Session = Depends(get_db),
    _machine: Machine = Depends(get_current_machine),
):
    query = db.query(DetectionModel).filter(DetectionModel.is_public.is_(True))
    if family:
        query = query.filter(DetectionModel.model_family == family)
    if q:
        like = f"%{q}%"
        query = query.filter(or_(DetectionModel.name.ilike(like), DetectionModel.slug.ilike(like)))
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


@router.get("/{model_id}", response_model=DetectionModelDetail)
def get_model_machine(
    model_id: UUID,
    db: Session = Depends(get_db),
    _machine: Machine = Depends(get_current_machine),
):
    model = (
        db.query(DetectionModel)
        .filter(DetectionModel.id == model_id, DetectionModel.is_public.is_(True))
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
    _machine: Machine = Depends(get_current_machine),
):
    model = (
        db.query(DetectionModel)
        .filter(DetectionModel.id == model_id, DetectionModel.is_public.is_(True))
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
    path = get_model_variant_file(variant.file_path)
    return FileResponse(
        path,
        filename=variant.file_name,
        headers={
            "X-Model-SHA256": variant.sha256,
            "Content-Length": str(variant.file_size),
        },
        media_type="application/octet-stream",
    )
