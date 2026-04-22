import hashlib
import json
import logging
import secrets
from datetime import datetime, timedelta, timezone
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import bcrypt
import jwt
from fastapi import Response

from app.config import settings
from app.errors import APIError

logger = logging.getLogger(__name__)


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def verify_password(password: str, password_hash: str | None) -> bool:
    if not password_hash:
        return False
    return bcrypt.checkpw(password.encode(), password_hash.encode())


def create_access_token(user_id: str, role: str) -> str:
    payload = {
        "sub": user_id,
        "role": role,
        "exp": datetime.now(timezone.utc) + timedelta(minutes=settings.JWT_ACCESS_TOKEN_EXPIRE_MINUTES),
        "type": "access",
    }
    return jwt.encode(payload, settings.jwt_signing_key, algorithm="HS256")


def create_refresh_token(user_id: str) -> tuple[str, str]:
    raw_token = secrets.token_urlsafe(64)
    token_hash = hashlib.sha256(raw_token.encode()).hexdigest()
    return raw_token, token_hash


def decode_access_token(token: str) -> dict | None:
    try:
        payload = jwt.decode(token, settings.jwt_signing_key, algorithms=["HS256"])
        if payload.get("type") != "access":
            return None
        return payload
    except jwt.PyJWTError:
        return None


def generate_machine_token() -> tuple[str, str, str]:
    raw_token = secrets.token_urlsafe(48)
    token_hash = hashlib.sha256(raw_token.encode()).hexdigest()
    prefix = raw_token[:8]
    return raw_token, token_hash, prefix


def generate_csrf_token() -> str:
    return secrets.token_urlsafe(32)


def generate_oauth_state() -> str:
    return secrets.token_urlsafe(32)


def sanitize_redirect_target(target: str | None) -> str:
    if not target or not target.startswith("/") or target.startswith("//") or target.startswith("/api/"):
        return "/"
    return target


def set_github_oauth_cookies(response: Response, state: str, next_path: str | None) -> None:
    max_age = settings.GITHUB_OAUTH_STATE_EXPIRE_MINUTES * 60
    response.set_cookie(
        key="github_oauth_state",
        value=state,
        httponly=True,
        samesite="lax",
        secure=settings.COOKIE_SECURE,
        path="/api/auth",
        max_age=max_age,
    )
    response.set_cookie(
        key="github_oauth_next",
        value=sanitize_redirect_target(next_path),
        httponly=True,
        samesite="lax",
        secure=settings.COOKIE_SECURE,
        path="/api/auth",
        max_age=max_age,
    )


def clear_github_oauth_cookies(response: Response) -> None:
    response.delete_cookie(key="github_oauth_state", path="/api/auth")
    response.delete_cookie(key="github_oauth_next", path="/api/auth")


def build_github_authorize_url(state: str) -> str:
    if not settings.github_oauth_enabled:
        raise APIError(503, "GitHub login is not configured", "GITHUB_OAUTH_DISABLED")

    query = urlencode(
        {
            "client_id": settings.GITHUB_CLIENT_ID,
            "redirect_uri": settings.github_redirect_uri,
            "scope": "read:user user:email",
            "state": state,
        }
    )
    return f"https://github.com/login/oauth/authorize?{query}"


def _github_json_request(url: str, *, access_token: str | None = None, form_data: dict[str, str] | None = None) -> dict | list:
    headers = {
        "Accept": "application/json",
        "User-Agent": "Hive/0.1",
    }
    data: bytes | None = None

    if access_token:
        headers["Authorization"] = f"Bearer {access_token}"
        headers["X-GitHub-Api-Version"] = "2022-11-28"

    if form_data is not None:
        headers["Content-Type"] = "application/x-www-form-urlencoded"
        data = urlencode(form_data).encode()

    request = Request(url, data=data, headers=headers)
    try:
        with urlopen(request, timeout=10) as response:  # noqa: S310
            return json.loads(response.read().decode())
    except HTTPError as exc:
        raw_body = exc.read().decode(errors="replace")
        logger.warning("GitHub HTTP error for %s: %s %s", url, exc.code, raw_body[:500])
        try:
            payload = json.loads(raw_body)
        except json.JSONDecodeError:
            payload = None

        if isinstance(payload, dict):
            message = payload.get("error_description") or payload.get("message") or payload.get("error")
            if (
                url == "https://api.github.com/user/emails"
                and exc.code == 403
                and message == "Resource not accessible by integration"
            ):
                raise APIError(
                    400,
                    "GitHub cannot read your email addresses. Use a GitHub OAuth App, or grant the GitHub App the Account permission 'Email addresses: Read-only' and re-authorize it.",
                    "GITHUB_EMAIL_PERMISSION_MISSING",
                ) from exc
            if isinstance(message, str) and message:
                raise APIError(502, f"GitHub request failed: {message}", "GITHUB_HTTP_ERROR") from exc

        raise APIError(502, f"GitHub request failed with HTTP {exc.code}", "GITHUB_HTTP_ERROR") from exc
    except URLError as exc:
        logger.warning("GitHub network error for %s: %s", url, exc)
        raise APIError(502, "GitHub could not be reached", "GITHUB_NETWORK_ERROR") from exc


def exchange_github_code(code: str, state: str) -> str:
    if not settings.github_oauth_enabled:
        raise APIError(503, "GitHub login is not configured", "GITHUB_OAUTH_DISABLED")

    payload = _github_json_request(
        "https://github.com/login/oauth/access_token",
        form_data={
            "client_id": settings.GITHUB_CLIENT_ID or "",
            "client_secret": settings.GITHUB_CLIENT_SECRET or "",
            "code": code,
            "redirect_uri": settings.github_redirect_uri,
            "state": state,
        },
    )

    if not isinstance(payload, dict):
        raise APIError(502, "Unexpected GitHub token response", "GITHUB_TOKEN_INVALID")

    error_description = payload.get("error_description")
    error_name = payload.get("error")
    if isinstance(error_description, str) and error_description:
        raise APIError(502, f"GitHub token exchange failed: {error_description}", "GITHUB_TOKEN_EXCHANGE_FAILED")
    if isinstance(error_name, str) and error_name:
        raise APIError(502, f"GitHub token exchange failed: {error_name}", "GITHUB_TOKEN_EXCHANGE_FAILED")

    access_token = payload.get("access_token")
    if not isinstance(access_token, str) or not access_token:
        raise APIError(502, "GitHub did not return an access token", "GITHUB_TOKEN_MISSING")

    return access_token


def fetch_github_identity(access_token: str) -> dict[str, str | None]:
    user_payload = _github_json_request("https://api.github.com/user", access_token=access_token)
    emails_payload = _github_json_request("https://api.github.com/user/emails", access_token=access_token)

    if not isinstance(user_payload, dict):
        raise APIError(502, "Unexpected GitHub user response", "GITHUB_USER_INVALID")
    if not isinstance(emails_payload, list):
        raise APIError(502, "Unexpected GitHub email response", "GITHUB_EMAIL_INVALID")

    verified_email: str | None = None
    primary_verified: str | None = None

    for entry in emails_payload:
        if not isinstance(entry, dict):
            continue
        email = entry.get("email")
        verified = entry.get("verified")
        primary = entry.get("primary")
        if isinstance(email, str) and verified is True:
            if primary is True:
                primary_verified = email
                break
            if verified_email is None:
                verified_email = email

    email = primary_verified or verified_email
    if not email:
        raise APIError(400, "GitHub account has no verified email address", "GITHUB_EMAIL_UNVERIFIED")

    github_id = user_payload.get("id")
    github_login = user_payload.get("login")
    avatar_url = user_payload.get("avatar_url")
    display_name = user_payload.get("name") or github_login or email.split("@")[0]

    if github_id is None:
        raise APIError(502, "GitHub user id missing", "GITHUB_ID_MISSING")

    return {
        "github_id": str(github_id),
        "github_login": github_login if isinstance(github_login, str) else None,
        "avatar_url": avatar_url if isinstance(avatar_url, str) else None,
        "display_name": display_name if isinstance(display_name, str) else email.split("@")[0],
        "email": email,
    }


def set_auth_cookies(response: Response, access_token: str, refresh_token: str, csrf_token: str) -> None:
    response.set_cookie(
        key="access_token",
        value=access_token,
        httponly=True,
        samesite="lax",
        secure=settings.COOKIE_SECURE,
        path="/",
        max_age=settings.JWT_ACCESS_TOKEN_EXPIRE_MINUTES * 60,
    )
    response.set_cookie(
        key="refresh_token",
        value=refresh_token,
        httponly=True,
        samesite="lax",
        secure=settings.COOKIE_SECURE,
        path="/api/auth",
        max_age=settings.JWT_REFRESH_TOKEN_EXPIRE_DAYS * 24 * 60 * 60,
    )
    response.set_cookie(
        key="csrf_token",
        value=csrf_token,
        httponly=False,
        samesite="lax",
        secure=settings.COOKIE_SECURE,
        path="/",
        max_age=settings.JWT_REFRESH_TOKEN_EXPIRE_DAYS * 24 * 60 * 60,
    )


def clear_auth_cookies(response: Response) -> None:
    response.delete_cookie(key="access_token", path="/")
    response.delete_cookie(key="refresh_token", path="/api/auth")
    response.delete_cookie(key="csrf_token", path="/")
