import hashlib
from datetime import datetime, timezone
from uuid import UUID
from typing import Generator

from fastapi import Cookie, Depends, Header, HTTPException, Request
from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.models.device import Device
from app.models.machine import Machine
from app.models.user import User
from app.models.user_api_key import UserApiKey
from app.services.auth import decode_access_token

API_KEY_PREFIX = "hv_"
API_KEY_SCOPE_MODELS_READ = "models:read"
API_KEY_SCOPE_MODELS_WRITE = "models:write"
API_KEY_SCOPE_SAMPLES_READ = "samples:read"
API_KEY_SCOPE_SAMPLES_WRITE = "samples:write"
API_KEY_SCOPE_KEYS_MANAGE = "keys:manage"
VALID_API_KEY_SCOPES = frozenset(
    {
        API_KEY_SCOPE_MODELS_READ,
        API_KEY_SCOPE_MODELS_WRITE,
        API_KEY_SCOPE_SAMPLES_READ,
        API_KEY_SCOPE_SAMPLES_WRITE,
        API_KEY_SCOPE_KEYS_MANAGE,
    }
)


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def get_current_user(
    db: Session = Depends(get_db),
    access_token: str | None = Cookie(default=None),
) -> User:
    if not access_token:
        raise HTTPException(status_code=401, detail="Not authenticated")
    payload = decode_access_token(access_token)
    if payload is None:
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    try:
        user_id = UUID(str(payload["sub"]))
    except (TypeError, ValueError):
        raise HTTPException(status_code=401, detail="Invalid token subject") from None
    user = db.query(User).filter(User.id == user_id).first()
    if user is None or not user.is_active:
        raise HTTPException(status_code=401, detail="User not found or inactive")
    # Stamp explicitly: User instances can be shared across requests via the
    # session identity map, so every auth path must set the credential's
    # machine constraint rather than assume a fresh instance (None = cookie
    # session, unconstrained).
    user._api_key_machine_ids = None
    return user


def get_current_machine(
    db: Session = Depends(get_db),
    authorization: str = Header(...),
) -> Machine:
    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Invalid authorization header")
    raw_token = authorization[7:]
    token_hash = hashlib.sha256(raw_token.encode()).hexdigest()
    machine = db.query(Machine).filter(Machine.token_hash == token_hash, Machine.is_active.is_(True)).first()
    if machine is None:
        raise HTTPException(status_code=401, detail="Invalid machine token")
    return machine


def get_current_device(
    db: Session = Depends(get_db),
    authorization: str = Header(...),
) -> Device:
    """Auth for the hosted-services layer (silently enrolled sorters). Same
    bearer scheme as machines but against the devices table — a machine token
    does not grant device endpoints, and vice versa."""
    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Invalid authorization header")
    raw_token = authorization[7:]
    token_hash = hashlib.sha256(raw_token.encode()).hexdigest()
    device = db.query(Device).filter(Device.token_hash == token_hash, Device.is_active.is_(True)).first()
    if device is None:
        raise HTTPException(status_code=401, detail="Invalid device token")
    return device


def require_role(*roles: str):
    def dependency(current_user: User = Depends(get_current_user)) -> User:
        if current_user.role not in roles:
            raise HTTPException(status_code=403, detail="Insufficient permissions")
        return current_user
    return dependency


def verify_csrf(
    request: Request,
    x_csrf_token: str | None = Header(default=None),
    csrf_token: str | None = Cookie(default=None),
    authorization: str | None = Header(default=None),
) -> None:
    if request.method in ("GET", "HEAD", "OPTIONS"):
        return
    # Bearer API keys are self-authenticating — CSRF only applies to cookie auth.
    if authorization and authorization.startswith("Bearer "):
        return
    if not x_csrf_token or not csrf_token:
        raise HTTPException(status_code=403, detail="CSRF token missing")
    if x_csrf_token != csrf_token:
        raise HTTPException(status_code=403, detail="CSRF token mismatch")


def normalize_api_key_scopes(scopes: list[str] | None) -> list[str] | None:
    if not scopes:
        return None

    normalized: list[str] = []
    seen: set[str] = set()
    for raw_scope in scopes:
        if not isinstance(raw_scope, str):
            raise HTTPException(status_code=400, detail="API key scopes must be strings")
        scope = raw_scope.strip().lower()
        if not scope:
            continue
        if scope not in VALID_API_KEY_SCOPES:
            raise HTTPException(status_code=400, detail=f"Unknown API key scope: {raw_scope}")
        if scope in seen:
            continue
        seen.add(scope)
        normalized.append(scope)

    return normalized or None


def _parse_key_machine_ids(raw: object) -> frozenset[str] | None:
    """Machine whitelist stored on the key row. None = unconstrained; an empty
    or malformed list collapses to an impossible constraint rather than
    silently widening access."""
    if raw is None:
        return None
    if not isinstance(raw, list):
        return frozenset()
    return frozenset(str(v) for v in raw if isinstance(v, str) and v)


def _resolve_api_key(db: Session, raw_token: str) -> tuple[User, frozenset[str], frozenset[str] | None]:
    token_hash = hashlib.sha256(raw_token.encode()).hexdigest()
    key = (
        db.query(UserApiKey)
        .filter(UserApiKey.token_hash == token_hash)
        .first()
    )
    if key is None or key.revoked_at is not None:
        raise HTTPException(status_code=401, detail="Invalid or revoked API key")
    expires_at = key.expires_at
    if expires_at is not None:
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)
        if expires_at <= datetime.now(timezone.utc):
            raise HTTPException(status_code=401, detail="API key expired")
    user = db.query(User).filter(User.id == key.user_id, User.is_active.is_(True)).first()
    if user is None:
        raise HTTPException(status_code=401, detail="Invalid or revoked API key")
    key.last_used_at = datetime.now(timezone.utc)
    db.add(key)
    db.commit()
    # Deny-by-default: a key grants exactly its stored scopes; a key with no
    # scopes (legacy rows) grants nothing.
    return (
        user,
        frozenset(normalize_api_key_scopes(key.scopes) or []),
        _parse_key_machine_ids(key.machine_ids),
    )


def get_current_user_or_api_key(
    request: Request,
    db: Session = Depends(get_db),
    access_token: str | None = Cookie(default=None),
    authorization: str | None = Header(default=None),
) -> User:
    """Resolve a user from either the session cookie or an Authorization Bearer `hv_*` API key.

    Machine tokens (raw hex) are rejected here — this dep is for human users only.

    API keys are deny-by-default: any endpoint that accepts them MUST also
    declare its required scopes via ``require_api_key_scopes`` — this dep alone
    only authenticates; without the scope guard a key-authed request will be
    rejected by ``require_api_key_scopes`` elsewhere or silently over-granted
    here, so keep the pair together.
    """
    request.state.auth_via_api_key = False
    request.state.api_key_scopes = frozenset()

    if authorization and authorization.startswith("Bearer "):
        raw = authorization[7:].strip()
        if raw.startswith(API_KEY_PREFIX):
            user, scopes, machine_ids = _resolve_api_key(db, raw)
            request.state.auth_via_api_key = True
            request.state.api_key_scopes = scopes
            # Transient, request-scoped attribute read by the access helpers in
            # services/access_window.py — the credential's machine whitelist
            # rides with the user object so every visibility check sees it.
            user._api_key_machine_ids = machine_ids
            return user
    if not access_token:
        raise HTTPException(status_code=401, detail="Not authenticated")
    payload = decode_access_token(access_token)
    if payload is None:
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    try:
        user_id = UUID(str(payload["sub"]))
    except (TypeError, ValueError):
        raise HTTPException(status_code=401, detail="Invalid token subject") from None
    user = db.query(User).filter(User.id == user_id).first()
    if user is None or not user.is_active:
        raise HTTPException(status_code=401, detail="User not found or inactive")
    user._api_key_machine_ids = None
    return user


def require_role_flex(*roles: str):
    """Like ``require_role`` but accepts either cookie or API-key auth."""

    def dependency(current_user: User = Depends(get_current_user_or_api_key)) -> User:
        if current_user.role not in roles:
            raise HTTPException(status_code=403, detail="Insufficient permissions")
        return current_user

    return dependency


def require_api_key_scopes(*required_scopes: str):
    normalized_required = tuple(
        scope
        for scope in (normalize_api_key_scopes(list(required_scopes)) or [])
        if isinstance(scope, str)
    )

    def dependency(
        request: Request,
        current_user: User = Depends(get_current_user_or_api_key),
    ) -> User:
        if not getattr(request.state, "auth_via_api_key", False):
            return current_user

        granted_scopes: frozenset[str] = getattr(request.state, "api_key_scopes", frozenset()) or frozenset()
        missing = [scope for scope in normalized_required if scope not in granted_scopes]
        if missing:
            raise HTTPException(
                status_code=403,
                detail=f"API key is missing required scopes: {', '.join(missing)}",
            )
        return current_user

    return dependency
