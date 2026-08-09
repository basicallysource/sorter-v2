import hashlib
import secrets
from datetime import datetime, timedelta, timezone
from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.deps import (
    API_KEY_SCOPE_KEYS_MANAGE,
    get_db,
    normalize_api_key_scopes,
    require_api_key_scopes,
    require_role_flex,
    verify_csrf,
)
from app.errors import APIError
from app.models.machine import Machine
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
    current_user: User = Depends(require_api_key_scopes(API_KEY_SCOPE_KEYS_MANAGE)),
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
    current_user: User = Depends(require_role_flex("admin")),
    _scope_guard: User = Depends(require_api_key_scopes(API_KEY_SCOPE_KEYS_MANAGE)),
    _csrf: None = Depends(verify_csrf),
):
    scopes = normalize_api_key_scopes(payload.scopes)
    if not scopes:
        raise APIError(400, "API key must have at least one scope", "API_KEY_SCOPES_REQUIRED")
    machine_ids: list[str] | None = None
    if payload.machine_ids is not None:
        requested = {str(machine_id) for machine_id in payload.machine_ids}
        if not requested:
            raise APIError(400, "Machine list may not be empty — omit it for an unrestricted key", "API_KEY_MACHINES_EMPTY")
        owned = {
            str(machine_id)
            for (machine_id,) in db.query(Machine.id)
            .filter(Machine.owner_id == current_user.id, Machine.id.in_(payload.machine_ids))
            .all()
        }
        unknown = requested - owned
        if unknown:
            raise APIError(400, "API key can only be scoped to machines you own", "API_KEY_MACHINES_NOT_OWNED")
        machine_ids = sorted(requested)
    expires_at = None
    if payload.expires_in_days is not None:
        expires_at = datetime.now(timezone.utc) + timedelta(days=payload.expires_in_days)
    raw_token, token_hash, token_prefix = _generate_token()
    key = UserApiKey(
        user_id=current_user.id,
        name=payload.name.strip(),
        token_prefix=token_prefix,
        token_hash=token_hash,
        scopes=scopes,
        machine_ids=machine_ids,
        expires_at=expires_at,
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
    current_user: User = Depends(require_api_key_scopes(API_KEY_SCOPE_KEYS_MANAGE)),
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
