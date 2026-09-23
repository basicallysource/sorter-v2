"""The default model per (purpose, runtime), for installs with no account.

A freshly installed sorter is linked to nobody, so it holds no credential and
cannot browse the catalog. It asks by compatibility instead, and the reads
here are deliberately anonymous: they only ever serve a public model.

A separate prefix from /api/models so no path here can collide with the
/api/models/{model_id} routes.
"""

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Response
from sqlalchemy.orm import Session

from app.deps import API_KEY_SCOPE_MODELS_WRITE, get_db, require_api_key_scopes, require_role_flex, verify_csrf
from app.errors import APIError
from app.models.detection_model import DetectionModel, DetectionModelVariant
from app.models.model_default import ModelDefault
from app.models.user import User
from app.routers.models import _summary
from app.schemas.model import (
    DetectionModelVariantDetail,
    ModelDefaultItem,
    ModelDefaultListResponse,
    ModelDefaultSetRequest,
)
from app.services.storage import build_download_filename, serve_model_variant

router = APIRouter(prefix="/api/model-defaults", tags=["model-defaults"])


def _served(db: Session):
    # A default whose model has gone private stays on file but is not served.
    return db.query(ModelDefault).join(ModelDefault.model).filter(DetectionModel.is_public.is_(True))


def _get_served(db: Session, purpose: str, runtime: str) -> ModelDefault:
    row = _served(db).filter(ModelDefault.purpose == purpose, ModelDefault.runtime == runtime).first()
    if row is None:
        raise APIError(404, "No default model is set for this purpose and runtime", "MODEL_DEFAULT_NOT_SET")
    return row


def _item(row: ModelDefault) -> ModelDefaultItem:
    return ModelDefaultItem(
        purpose=row.purpose,
        runtime=row.runtime,
        model=_summary(row.model),
        variant=DetectionModelVariantDetail.model_validate(row.variant),
        download_path=f"/api/model-defaults/{row.purpose}/{row.runtime}/download",
        updated_at=row.updated_at,
    )


@router.get("", response_model=ModelDefaultListResponse)
def list_defaults(db: Session = Depends(get_db)):
    rows = _served(db).order_by(ModelDefault.purpose, ModelDefault.runtime).all()
    return ModelDefaultListResponse(items=[_item(r) for r in rows])


@router.get("/{purpose}/{runtime}", response_model=ModelDefaultItem)
def get_default(purpose: str, runtime: str, db: Session = Depends(get_db)):
    return _item(_get_served(db, purpose, runtime))


@router.get("/{purpose}/{runtime}/download")
def download_default(purpose: str, runtime: str, db: Session = Depends(get_db)):
    row = _get_served(db, purpose, runtime)
    return serve_model_variant(
        row.variant.file_path,
        filename=build_download_filename(row.model, row.variant),
        sha256=row.variant.sha256,
        file_size=row.variant.file_size,
    )


@router.put("/{purpose}/{runtime}", response_model=ModelDefaultItem)
def set_default(
    purpose: str,
    runtime: str,
    payload: ModelDefaultSetRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role_flex("admin")),
    _scope_guard: User = Depends(require_api_key_scopes(API_KEY_SCOPE_MODELS_WRITE)),
    _csrf: None = Depends(verify_csrf),
):
    model = db.query(DetectionModel).filter(DetectionModel.id == payload.model_id).first()
    if model is None:
        raise APIError(404, "Model not found", "MODEL_NOT_FOUND")
    variant = (
        db.query(DetectionModelVariant)
        .filter(DetectionModelVariant.id == payload.variant_id, DetectionModelVariant.model_id == model.id)
        .first()
    )
    if variant is None:
        raise APIError(404, "Variant not found", "VARIANT_NOT_FOUND")
    if model.purpose != purpose:
        raise APIError(400, f"Model is a {model.purpose} model, not {purpose}", "PURPOSE_MISMATCH")
    if variant.runtime != runtime:
        raise APIError(400, f"Variant is for {variant.runtime}, not {runtime}", "RUNTIME_MISMATCH")
    if not model.is_public:
        raise APIError(409, "A default is served without sign-in, so its model must be public", "MODEL_NOT_PUBLIC")

    row = db.get(ModelDefault, (purpose, runtime))
    if row is None:
        row = ModelDefault(purpose=purpose, runtime=runtime)
        db.add(row)
    row.model_id = model.id
    row.variant_id = variant.id
    row.updated_by_id = current_user.id
    row.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(row)
    return _item(row)


@router.delete("/{purpose}/{runtime}", status_code=204)
def clear_default(
    purpose: str,
    runtime: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role_flex("admin")),
    _scope_guard: User = Depends(require_api_key_scopes(API_KEY_SCOPE_MODELS_WRITE)),
    _csrf: None = Depends(verify_csrf),
):
    db.query(ModelDefault).filter(ModelDefault.purpose == purpose, ModelDefault.runtime == runtime).delete()
    db.commit()
    return Response(status_code=204)
