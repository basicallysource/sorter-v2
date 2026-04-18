import hashlib
import secrets
from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.deps import get_current_user, get_db, normalize_api_key_scopes, require_role, verify_csrf
from app.errors import APIError
from app.models.user import User
from app.models.user_api_key import UserApiKey
from app.schemas.api_key import (
    ApiKeyCreateRequest,
    ApiKeyCreateResponse,
    ApiKeySummary,
)

router = APIRouter(prefix="/api/auth/api-keys", tags=["api-keys"])

TOKEN_PREFIX = "hv_"
RAW_TOKEN_BYTES = 32


def _generate_token() -> tuple[str, str, str]:
    raw_secret = secrets.token_urlsafe(RAW_TOKEN_BYTES)
    raw_token = f"{TOKEN_PREFIX}{raw_secret}"
    token_hash = hashlib.sha256(raw_token.encode()).hexdigest()
    token_prefix_display = raw_token[: len(TOKEN_PREFIX) + 6]
    return raw_token, token_hash, token_prefix_display


def _apply_visibility(query, current_user: User):
    return query.filter(UserApiKey.user_id == current_user.id)


@router.get("", response_model=list[ApiKeySummary])
def list_api_keys(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    keys = (
        _apply_visibility(db.query(UserApiKey), current_user)
        .order_by(UserApiKey.created_at.desc())
        .all()
    )
    return [ApiKeySummary.model_validate(k) for k in keys]


@router.post("", response_model=ApiKeyCreateResponse)
def create_api_key(
    payload: ApiKeyCreateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("admin")),
    _csrf: None = Depends(verify_csrf),
):
    raw_token, token_hash, token_prefix = _generate_token()
    scopes = normalize_api_key_scopes(payload.scopes)
    key = UserApiKey(
        user_id=current_user.id,
        name=payload.name.strip(),
        token_prefix=token_prefix,
        token_hash=token_hash,
        scopes=scopes,
    )
    db.add(key)
    db.commit()
    db.refresh(key)
    return ApiKeyCreateResponse(
        summary=ApiKeySummary.model_validate(key),
        raw_token=raw_token,
    )


@router.delete("/{key_id}")
def revoke_api_key(
    key_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    _csrf: None = Depends(verify_csrf),
):
    key = (
        _apply_visibility(db.query(UserApiKey), current_user)
        .filter(UserApiKey.id == key_id)
        .first()
    )
    if key is None:
        raise APIError(404, "API key not found", "API_KEY_NOT_FOUND")
    if key.revoked_at is None:
        key.revoked_at = datetime.now(timezone.utc)
        db.add(key)
        db.commit()
    return {"ok": True}
