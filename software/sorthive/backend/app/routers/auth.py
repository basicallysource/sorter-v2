import hashlib
import logging
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode

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
from app.services.auth import (
    build_github_authorize_url,
    clear_github_oauth_cookies,
    clear_auth_cookies,
    create_access_token,
    create_refresh_token,
    exchange_github_code,
    fetch_github_identity,
    generate_csrf_token,
    generate_oauth_state,
    hash_password,
    sanitize_redirect_target,
    set_auth_cookies,
    set_github_oauth_cookies,
    verify_password,
)
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


def _oauth_error_redirect(message: str) -> RedirectResponse:
    response = RedirectResponse(url=_app_redirect_url(f"/login?{urlencode({'error': message})}"), status_code=303)
    clear_github_oauth_cookies(response)
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


@router.get("/github")
def github_login(next: str | None = Query(default=None)):
    if not settings.github_oauth_enabled:
        return _oauth_error_redirect("GitHub login is not configured")

    state = generate_oauth_state()
    response = RedirectResponse(url=build_github_authorize_url(state), status_code=302)
    set_github_oauth_cookies(response, state, next)
    return response


@router.get("/options")
def auth_options():
    return {"github_enabled": settings.github_oauth_enabled}


@router.get("/github/callback")
def github_callback(
    code: str | None = Query(default=None),
    state: str | None = Query(default=None),
    error: str | None = Query(default=None),
    error_description: str | None = Query(default=None),
    github_oauth_state: str | None = Cookie(default=None),
    github_oauth_next: str | None = Cookie(default=None),
    db: Session = Depends(get_db),
):
    if error:
        message = error_description or "GitHub login was cancelled"
        return _oauth_error_redirect(message)

    if not settings.github_oauth_enabled:
        return _oauth_error_redirect("GitHub login is not configured")

    if not code or not state or not github_oauth_state or state != github_oauth_state:
        return _oauth_error_redirect("GitHub login could not be verified")

    try:
        access_token = exchange_github_code(code, state)
        identity = fetch_github_identity(access_token)
    except APIError as exc:
        logger.warning("GitHub OAuth failed: %s (%s)", exc.error_message, exc.error_code)
        return _oauth_error_redirect(exc.error_message)
    except Exception:
        logger.exception("GitHub OAuth callback unexpected failure")
        return _oauth_error_redirect("GitHub login failed unexpectedly")

    github_id = identity["github_id"]
    email = identity["email"]

    if not isinstance(github_id, str) or not isinstance(email, str):
        return _oauth_error_redirect("GitHub login returned incomplete account data")

    user = db.query(User).filter(User.github_id == github_id).first()
    if user is None:
        user = db.query(User).filter(User.email == email).first()
        if user is not None and user.github_id and user.github_id != github_id:
            return _oauth_error_redirect("This email is already linked to a different GitHub account")
        if user is None:
            user = User(
                email=email,
                password_hash=None,
                display_name=identity["display_name"] if isinstance(identity["display_name"], str) else None,
                role="member",
                is_active=True,
                github_id=github_id,
                github_login=identity["github_login"] if isinstance(identity["github_login"], str) else None,
                avatar_url=identity["avatar_url"] if isinstance(identity["avatar_url"], str) else None,
            )
            db.add(user)
        else:
            user.github_id = github_id

    if not user.is_active:
        return _oauth_error_redirect("Account is deactivated")

    user.github_login = identity["github_login"] if isinstance(identity["github_login"], str) else user.github_login
    user.avatar_url = identity["avatar_url"] if isinstance(identity["avatar_url"], str) else user.avatar_url
    if not user.display_name and isinstance(identity["display_name"], str):
        user.display_name = identity["display_name"]

    db.commit()
    db.refresh(user)

    redirect_target = sanitize_redirect_target(github_oauth_next)
    response = RedirectResponse(url=_app_redirect_url(redirect_target), status_code=303)
    _issue_session(response, db, user)
    clear_github_oauth_cookies(response)
    return response


@router.patch("/me", response_model=UserResponse)
def update_profile(
    data: UpdateProfileRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    _csrf: None = Depends(verify_csrf),
):
    if data.display_name is not None:
        current_user.display_name = data.display_name

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
