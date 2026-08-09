import hashlib
import logging
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode
from uuid import UUID

from fastapi import APIRouter, Cookie, Depends, Query, Request, Response
from fastapi.responses import RedirectResponse
from slowapi import Limiter
from slowapi.util import get_remote_address
from sqlalchemy.orm import Session

from app.config import settings
from app.deps import get_current_user, get_db, verify_csrf
from app.errors import APIError
from app.models.refresh_token import RefreshToken
from app.models.user import User
from app.schemas.auth import LoginRequest, RegisterRequest, UpdateProfileRequest, UserResponse
from app.models.user_identity import UserIdentity
from app.services.auth import (
    clear_auth_cookies,
    clear_oauth_cookies,
    create_access_token,
    create_refresh_token,
    decode_access_token,
    generate_csrf_token,
    generate_oauth_state,
    hash_password,
    sanitize_redirect_target,
    set_auth_cookies,
    set_oauth_cookies,
    verify_password,
)
from app.services.oauth_providers import OAuthIdentity, enabled_oauth_providers, get_oauth_provider
from app.services.secrets import encrypt_secret
from app.services.storage import delete_machine_files

router = APIRouter(prefix="/api/auth", tags=["auth"])
limiter = Limiter(key_func=get_remote_address)
logger = logging.getLogger(__name__)


def _issue_session(response: Response, db: Session, user: User, revoke_token: RefreshToken | None = None) -> None:
    if revoke_token is not None:
        revoke_token.revoked_at = datetime.now(timezone.utc)

    access_token = create_access_token(str(user.id), user.role)
    raw_refresh, refresh_hash = create_refresh_token(str(user.id))
    csrf_token = generate_csrf_token()

    db_refresh = RefreshToken(
        user_id=user.id,
        token_hash=refresh_hash,
        expires_at=datetime.now(timezone.utc) + timedelta(days=settings.JWT_REFRESH_TOKEN_EXPIRE_DAYS),
    )
    db.add(db_refresh)
    db.commit()

    set_auth_cookies(response, access_token, raw_refresh, csrf_token)


def _app_redirect_url(path: str) -> str:
    return f"{settings.public_app_url}{path}"


def _oauth_error_redirect(provider: str, message: str, intent: str = "login") -> RedirectResponse:
    target = "/settings" if intent == "link" else "/login"
    response = RedirectResponse(url=_app_redirect_url(f"{target}?{urlencode({'error': message})}"), status_code=303)
    clear_oauth_cookies(response, provider)
    return response


@router.post("/register", response_model=UserResponse)
@limiter.limit("5/minute")
def register(request: Request, request_obj: RegisterRequest, response: Response, db: Session = Depends(get_db)):
    existing = db.query(User).filter(User.email == request_obj.email).first()
    if existing:
        raise APIError(409, "Email already registered", "EMAIL_TAKEN")

    user = User(
        email=request_obj.email,
        password_hash=hash_password(request_obj.password),
        display_name=request_obj.display_name,
        role="member",
    )
    db.add(user)
    db.commit()
    db.refresh(user)

    _issue_session(response, db, user)
    return user


@router.post("/login", response_model=UserResponse)
@limiter.limit("5/minute")
def login(request: Request, request_obj: LoginRequest, response: Response, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.email == request_obj.email).first()
    if not user or not verify_password(request_obj.password, user.password_hash):
        raise APIError(401, "Invalid email or password", "INVALID_CREDENTIALS")
    if not user.is_active:
        raise APIError(403, "Account is deactivated", "ACCOUNT_INACTIVE")

    _issue_session(response, db, user)
    return user


@router.post("/refresh")
def refresh(
    response: Response,
    db: Session = Depends(get_db),
    refresh_token: str | None = Cookie(default=None),
    _csrf: None = Depends(verify_csrf),
):
    if not refresh_token:
        raise APIError(401, "No refresh token", "NO_REFRESH_TOKEN")

    token_hash = hashlib.sha256(refresh_token.encode()).hexdigest()
    db_token = (
        db.query(RefreshToken)
        .filter(
            RefreshToken.token_hash == token_hash,
            RefreshToken.revoked_at.is_(None),
            RefreshToken.expires_at > datetime.now(timezone.utc),
        )
        .first()
    )

    if not db_token:
        raise APIError(401, "Invalid or expired refresh token", "INVALID_REFRESH_TOKEN")

    user = db.query(User).filter(User.id == db_token.user_id).first()
    if not user or not user.is_active:
        raise APIError(401, "User not found or inactive", "USER_INACTIVE")

    _issue_session(response, db, user, revoke_token=db_token)
    return {"ok": True}


@router.post("/logout")
def logout(
    response: Response,
    db: Session = Depends(get_db),
    refresh_token: str | None = Cookie(default=None),
    _csrf: None = Depends(verify_csrf),
):
    if refresh_token:
        token_hash = hashlib.sha256(refresh_token.encode()).hexdigest()
        db_token = db.query(RefreshToken).filter(RefreshToken.token_hash == token_hash).first()
        if db_token:
            db_token.revoked_at = datetime.now(timezone.utc)
            db.commit()

    clear_auth_cookies(response)
    return {"ok": True}


@router.get("/me", response_model=UserResponse)
def me(current_user: User = Depends(get_current_user)):
    return current_user


@router.get("/options")
def auth_options():
    providers = enabled_oauth_providers()
    return {f"{name}_enabled": enabled for name, enabled in providers.items()}


def _oauth_start(provider_name: str, next_path: str | None, intent: str) -> RedirectResponse:
    provider = get_oauth_provider(provider_name)
    if provider is None or not provider.enabled:
        return _oauth_error_redirect(provider_name, f"{provider_name.capitalize()} login is not configured", intent)

    state = generate_oauth_state()
    response = RedirectResponse(url=provider.build_authorize_url(state), status_code=302)
    set_oauth_cookies(response, provider_name, state, next_path, intent)
    return response


def _cookie_session_user(request: Request, db: Session) -> User | None:
    """Resolve the logged-in user from the access-token cookie without raising.

    Callbacks arrive as top-level redirects, so a 401 JSON body would strand
    the browser — link-flow failures redirect with an error message instead.
    """
    token = request.cookies.get("access_token")
    if not token:
        return None
    payload = decode_access_token(token)
    if payload is None:
        return None
    try:
        user_id = UUID(str(payload["sub"]))
    except (KeyError, TypeError, ValueError):
        return None
    user = db.query(User).filter(User.id == user_id).first()
    if user is None or not user.is_active:
        return None
    return user


def _apply_identity_profile(user: User, identity: OAuthIdentity, row: UserIdentity) -> None:
    row.provider_login = identity.login or row.provider_login
    row.avatar_url = identity.avatar_url or row.avatar_url
    if not user.avatar_url and identity.avatar_url:
        user.avatar_url = identity.avatar_url
    if not user.display_name and identity.display_name:
        user.display_name = identity.display_name


def _oauth_callback(
    provider_name: str,
    request: Request,
    db: Session,
    code: str | None,
    state: str | None,
    error: str | None,
    error_description: str | None,
):
    intent = request.cookies.get(f"{provider_name}_oauth_intent") or "login"
    display = provider_name.capitalize()

    if error:
        return _oauth_error_redirect(provider_name, error_description or f"{display} login was cancelled", intent)

    provider = get_oauth_provider(provider_name)
    if provider is None or not provider.enabled:
        return _oauth_error_redirect(provider_name, f"{display} login is not configured", intent)

    cookie_state = request.cookies.get(f"{provider_name}_oauth_state")
    if not code or not state or not cookie_state or state != cookie_state:
        return _oauth_error_redirect(provider_name, f"{display} login could not be verified", intent)

    try:
        access_token = provider.exchange_code(code, state)
        identity = provider.fetch_identity(access_token)
    except APIError as exc:
        logger.warning("%s OAuth failed: %s (%s)", display, exc.error_message, exc.error_code)
        return _oauth_error_redirect(provider_name, exc.error_message, intent)
    except Exception:
        logger.exception("%s OAuth callback unexpected failure", display)
        return _oauth_error_redirect(provider_name, f"{display} login failed unexpectedly", intent)

    existing = (
        db.query(UserIdentity)
        .filter(
            UserIdentity.provider == provider_name,
            UserIdentity.provider_user_id == identity.provider_user_id,
        )
        .first()
    )
    next_cookie = request.cookies.get(f"{provider_name}_oauth_next")

    if intent == "link":
        current_user = _cookie_session_user(request, db)
        if current_user is None:
            return _oauth_error_redirect(provider_name, f"Sign in before connecting {display}", intent)
        if existing is not None and existing.user_id != current_user.id:
            return _oauth_error_redirect(
                provider_name, f"That {display} account is already linked to a different Hive account", intent
            )
        row = existing or current_user.identity_for(provider_name)
        if row is not None and row.provider_user_id != identity.provider_user_id:
            return _oauth_error_redirect(
                provider_name, f"A different {display} account is already connected — disconnect it first", intent
            )
        if row is None:
            row = UserIdentity(
                user_id=current_user.id,
                provider=provider_name,
                provider_user_id=identity.provider_user_id,
            )
            db.add(row)
        _apply_identity_profile(current_user, identity, row)
        db.commit()

        redirect_target = sanitize_redirect_target(next_cookie) if next_cookie else "/settings"
        response = RedirectResponse(url=_app_redirect_url(redirect_target), status_code=303)
        clear_oauth_cookies(response, provider_name)
        return response

    # Sign-in flow
    if existing is not None:
        user = db.query(User).filter(User.id == existing.user_id).first()
        if user is None:
            return _oauth_error_redirect(provider_name, f"{display} login failed unexpectedly", intent)
        row = existing
    else:
        if not identity.email:
            return _oauth_error_redirect(provider_name, f"{display} account has no verified email address", intent)
        user = db.query(User).filter(User.email == identity.email).first()
        if user is not None and user.identity_for(provider_name) is not None:
            return _oauth_error_redirect(
                provider_name, f"This email is already linked to a different {display} account", intent
            )
        if user is None:
            user = User(
                email=identity.email,
                password_hash=None,
                display_name=identity.display_name,
                role="member",
                is_active=True,
                avatar_url=identity.avatar_url,
            )
            db.add(user)
            db.flush()
        row = UserIdentity(
            user_id=user.id,
            provider=provider_name,
            provider_user_id=identity.provider_user_id,
        )
        db.add(row)

    if not user.is_active:
        return _oauth_error_redirect(provider_name, "Account is deactivated", intent)

    _apply_identity_profile(user, identity, row)
    db.commit()
    db.refresh(user)

    redirect_target = sanitize_redirect_target(next_cookie)
    response = RedirectResponse(url=_app_redirect_url(redirect_target), status_code=303)
    _issue_session(response, db, user)
    clear_oauth_cookies(response, provider_name)
    return response


@router.get("/github")
def github_login(next: str | None = Query(default=None)):
    return _oauth_start("github", next, "login")


@router.get("/github/link")
def github_link(next: str | None = Query(default=None)):
    return _oauth_start("github", next or "/settings", "link")


@router.get("/github/callback")
def github_callback(
    request: Request,
    code: str | None = Query(default=None),
    state: str | None = Query(default=None),
    error: str | None = Query(default=None),
    error_description: str | None = Query(default=None),
    db: Session = Depends(get_db),
):
    return _oauth_callback("github", request, db, code, state, error, error_description)


@router.get("/discord")
def discord_login(next: str | None = Query(default=None)):
    return _oauth_start("discord", next, "login")


@router.get("/discord/link")
def discord_link(next: str | None = Query(default=None)):
    return _oauth_start("discord", next or "/settings", "link")


@router.get("/discord/callback")
def discord_callback(
    request: Request,
    code: str | None = Query(default=None),
    state: str | None = Query(default=None),
    error: str | None = Query(default=None),
    error_description: str | None = Query(default=None),
    db: Session = Depends(get_db),
):
    return _oauth_callback("discord", request, db, code, state, error, error_description)


@router.get("/identities")
def list_identities(current_user: User = Depends(get_current_user)):
    return [
        {
            "provider": identity.provider,
            "provider_login": identity.provider_login,
            "avatar_url": identity.avatar_url,
            "created_at": identity.created_at,
        }
        for identity in current_user.identities
    ]


@router.delete("/identities/{provider}")
def unlink_identity(
    provider: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    _csrf: None = Depends(verify_csrf),
):
    identity = current_user.identity_for(provider)
    if identity is None:
        raise APIError(404, "No linked account for that provider", "IDENTITY_NOT_FOUND")

    remaining_sign_in_methods = (1 if current_user.password_hash else 0) + len(current_user.identities) - 1
    if remaining_sign_in_methods < 1:
        raise APIError(
            400,
            "Set a password or connect another sign-in method before disconnecting this one",
            "LAST_SIGN_IN_METHOD",
        )

    db.delete(identity)
    db.commit()
    return {"ok": True}


@router.patch("/me", response_model=UserResponse)
def update_profile(
    data: UpdateProfileRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    _csrf: None = Depends(verify_csrf),
):
    if data.display_name is not None:
        current_user.display_name = data.display_name

    if data.clear_openrouter_api_key:
        current_user.openrouter_api_key_encrypted = None

    if data.openrouter_api_key is not None:
        normalized_key = data.openrouter_api_key.strip()
        current_user.openrouter_api_key_encrypted = encrypt_secret(normalized_key) if normalized_key else None

    if data.clear_perceptron_api_key:
        current_user.perceptron_api_key_encrypted = None

    if data.perceptron_api_key is not None:
        normalized_key = data.perceptron_api_key.strip()
        current_user.perceptron_api_key_encrypted = encrypt_secret(normalized_key) if normalized_key else None

    if data.preferred_ai_model is not None:
        normalized_model = data.preferred_ai_model.strip()
        current_user.preferred_ai_model = normalized_model or None

    if data.preferred_teacher_model is not None:
        normalized_teacher = data.preferred_teacher_model.strip()
        current_user.preferred_teacher_model = normalized_teacher or None

    if data.new_password is not None:
        if len(data.new_password) < 8:
            raise APIError(400, "New password must be at least 8 characters", "PASSWORD_TOO_SHORT")
        if current_user.password_hash:
            if not data.current_password:
                raise APIError(400, "Current password is required to change password", "CURRENT_PASSWORD_REQUIRED")
            if not verify_password(data.current_password, current_user.password_hash):
                raise APIError(400, "Current password is incorrect", "WRONG_PASSWORD")
        current_user.password_hash = hash_password(data.new_password)

    db.commit()
    db.refresh(current_user)
    return current_user


@router.delete("/me")
def delete_account(
    response: Response,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    _csrf: None = Depends(verify_csrf),
):
    # Delete machine files from disk
    for machine in current_user.machines:
        delete_machine_files(str(machine.id))

    db.delete(current_user)
    db.commit()
    clear_auth_cookies(response)
    return {"ok": True}
