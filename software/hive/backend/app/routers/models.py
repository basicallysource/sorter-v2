import math
from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, Query, UploadFile
from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from app.config import settings
from app.deps import (
    API_KEY_SCOPE_MODELS_READ,
    API_KEY_SCOPE_MODELS_WRITE,
    get_db,
    require_api_key_scopes,
    require_role_flex,
    verify_csrf,
)
from app.errors import APIError
from app.models.detection_model import DetectionModel, DetectionModelVariant
from app.models.user import User
from app.schemas.model import (
    DetectionModelCreateRequest,
    DetectionModelCreateResponse,
    DetectionModelDetail,
    DetectionModelListResponse,
    DetectionModelSummary,
    DetectionModelVariantDetail,
    DetectionModelVariantUploadResponse,
)
from app.services.storage import (
    delete_model_files,
    delete_stored_file,
    save_model_variant,
    serve_model_variant,
)

router = APIRouter(prefix="/api/models", tags=["models"])


def _summary(model: DetectionModel) -> DetectionModelSummary:
    data = DetectionModelSummary.model_validate(model)
    data.variant_runtimes = sorted(v.runtime for v in model.variants)
    return data


def _detail(model: DetectionModel) -> DetectionModelDetail:
    data = DetectionModelDetail.model_validate(model)
    data.variant_runtimes = sorted(v.runtime for v in model.variants)
    data.variants = [DetectionModelVariantDetail.model_validate(v) for v in model.variants]
    return data


def _apply_visibility(query, current_user: User):
    if current_user.role in {"reviewer", "admin"}:
        return query
    return query.filter(DetectionModel.is_public.is_(True))


@router.get("", response_model=DetectionModelListResponse)
def list_models(
    page: int = Query(1, ge=1),
    page_size: int = Query(30, ge=1, le=100),
    scope: str | None = None,
    runtime: str | None = None,
    family: str | None = None,
    q: str | None = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_api_key_scopes(API_KEY_SCOPE_MODELS_READ)),
):
    query = _apply_visibility(db.query(DetectionModel), current_user)
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
def get_model(
    model_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_api_key_scopes(API_KEY_SCOPE_MODELS_READ)),
):
    model = _apply_visibility(db.query(DetectionModel), current_user).filter(DetectionModel.id == model_id).first()
    if model is None:
        raise APIError(404, "Model not found", "MODEL_NOT_FOUND")
    return _detail(model)


@router.get("/{model_id}/variants/{variant_id}/download")
def download_model_variant(
    model_id: UUID,
    variant_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_api_key_scopes(API_KEY_SCOPE_MODELS_READ)),
):
    model = _apply_visibility(db.query(DetectionModel), current_user).filter(DetectionModel.id == model_id).first()
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
        filename=variant.file_name,
        sha256=variant.sha256,
        file_size=variant.file_size,
    )


@router.post("", response_model=DetectionModelCreateResponse)
def create_model(
    payload: DetectionModelCreateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role_flex("admin")),
    _scope_guard: User = Depends(require_api_key_scopes(API_KEY_SCOPE_MODELS_WRITE)),
    _csrf: None = Depends(verify_csrf),
):
    prev = (
        db.query(func.max(DetectionModel.version))
        .filter(DetectionModel.slug == payload.slug)
        .scalar()
    )
    next_version = (prev or 0) + 1
    model = DetectionModel(
        owner_id=current_user.id,
        slug=payload.slug,
        version=next_version,
        name=payload.name,
        description=payload.description,
        model_family=payload.model_family,
        scopes=payload.scopes or [],
        training_metadata=payload.training_metadata,
        is_public=payload.is_public,
    )
    db.add(model)
    db.commit()
    db.refresh(model)
    return DetectionModelCreateResponse(id=model.id, slug=model.slug, version=model.version)


@router.post("/{model_id}/variants", response_model=DetectionModelVariantUploadResponse)
def upload_variant(
    model_id: UUID,
    runtime: str = Form(...),
    file: UploadFile = File(...),
    format_meta: str | None = Form(default=None),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role_flex("admin")),
    _scope_guard: User = Depends(require_api_key_scopes(API_KEY_SCOPE_MODELS_WRITE)),
    _csrf: None = Depends(verify_csrf),
):
    model = db.query(DetectionModel).filter(DetectionModel.id == model_id).first()
    if model is None:
        raise APIError(404, "Model not found", "MODEL_NOT_FOUND")
    if runtime not in settings.ALLOWED_MODEL_RUNTIMES:
        raise APIError(400, "Unsupported runtime", "UNSUPPORTED_RUNTIME")

    file_name = file.filename or f"{runtime}.bin"
    relative_path, sha256, size = save_model_variant(model.id, runtime, file, file_name)

    import json as _json

    format_meta_data: dict | None = None
    if format_meta:
        try:
            format_meta_data = _json.loads(format_meta)
        except _json.JSONDecodeError:
            raise APIError(400, "Invalid format_meta", "INVALID_FORMAT_META") from None

    existing = (
        db.query(DetectionModelVariant)
        .filter(DetectionModelVariant.model_id == model_id, DetectionModelVariant.runtime == runtime)
        .first()
    )
    if existing:
        old_file_path = existing.file_path
        existing.file_path = relative_path
        existing.file_name = file_name
        existing.file_size = size
        existing.sha256 = sha256
        existing.format_meta = format_meta_data
        existing.uploaded_at = datetime.now(timezone.utc)
        variant = existing
        if old_file_path and old_file_path != relative_path:
            delete_stored_file(old_file_path)
    else:
        variant = DetectionModelVariant(
            model_id=model.id,
            runtime=runtime,
            file_path=relative_path,
            file_name=file_name,
            file_size=size,
            sha256=sha256,
            format_meta=format_meta_data,
        )
        db.add(variant)
    model.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(variant)
    return DetectionModelVariantUploadResponse(
        id=variant.id,
        runtime=variant.runtime,
        file_name=variant.file_name,
        file_size=variant.file_size,
        sha256=variant.sha256,
    )


@router.delete("/{model_id}")
def delete_model(
    model_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role_flex("admin")),
    _scope_guard: User = Depends(require_api_key_scopes(API_KEY_SCOPE_MODELS_WRITE)),
    _csrf: None = Depends(verify_csrf),
):
    model = db.query(DetectionModel).filter(DetectionModel.id == model_id).first()
    if model is None:
        raise APIError(404, "Model not found", "MODEL_NOT_FOUND")
    delete_model_files(model.id)
    db.delete(model)
    db.commit()
    return {"ok": True}
