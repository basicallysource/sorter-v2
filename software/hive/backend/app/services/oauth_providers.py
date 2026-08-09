"""OAuth sign-in providers.

Each provider adapter exposes the same three steps of the dance —
authorize-URL, code exchange, identity fetch — and normalizes the result into
an OAuthIdentity. Router code (app/routers/auth.py) is provider-agnostic: it
looks identities up in user_identities and never touches provider APIs
directly. Adding a provider means adding an adapter here plus its settings.
"""

import json
import logging
from dataclasses import dataclass
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from app.config import settings
from app.errors import APIError
from app.services.auth import (
    build_github_authorize_url,
    exchange_github_code,
    fetch_github_identity,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class OAuthIdentity:
    provider: str
    provider_user_id: str
    login: str | None
    display_name: str | None
    avatar_url: str | None
    email: str | None  # verified email only; None if the provider can't vouch for one


class GitHubOAuthProvider:
    name = "github"

    @property
    def enabled(self) -> bool:
        return settings.github_oauth_enabled

    def build_authorize_url(self, state: str) -> str:
        return build_github_authorize_url(state)

    def exchange_code(self, code: str, state: str) -> str:
        return exchange_github_code(code, state)

    def fetch_identity(self, access_token: str) -> OAuthIdentity:
        raw = fetch_github_identity(access_token)
        return OAuthIdentity(
            provider=self.name,
            provider_user_id=str(raw["github_id"]),
            login=raw["github_login"],
            display_name=raw["display_name"],
            avatar_url=raw["avatar_url"],
            email=raw["email"],
        )


def _discord_json_request(url: str, *, access_token: str | None = None, form_data: dict[str, str] | None = None) -> dict:
    headers = {"Accept": "application/json", "User-Agent": "Hive/0.1"}
    data: bytes | None = None

    if access_token:
        headers["Authorization"] = f"Bearer {access_token}"
    if form_data is not None:
        headers["Content-Type"] = "application/x-www-form-urlencoded"
        data = urlencode(form_data).encode()

    request = Request(url, data=data, headers=headers)
    try:
        with urlopen(request, timeout=10) as response:  # noqa: S310
            payload = json.loads(response.read().decode())
    except HTTPError as exc:
        raw_body = exc.read().decode(errors="replace")
        logger.warning("Discord HTTP error for %s: %s %s", url, exc.code, raw_body[:500])
        message: str | None = None
        try:
            body = json.loads(raw_body)
            if isinstance(body, dict):
                message = body.get("error_description") or body.get("message") or body.get("error")
        except json.JSONDecodeError:
            pass
        if isinstance(message, str) and message:
            raise APIError(502, f"Discord request failed: {message}", "DISCORD_HTTP_ERROR") from exc
        raise APIError(502, f"Discord request failed with HTTP {exc.code}", "DISCORD_HTTP_ERROR") from exc
    except URLError as exc:
        logger.warning("Discord network error for %s: %s", url, exc)
        raise APIError(502, "Discord could not be reached", "DISCORD_NETWORK_ERROR") from exc

    if not isinstance(payload, dict):
        raise APIError(502, "Unexpected Discord response", "DISCORD_RESPONSE_INVALID")
    return payload


class DiscordOAuthProvider:
    name = "discord"

    @property
    def enabled(self) -> bool:
        return settings.discord_oauth_enabled

    def build_authorize_url(self, state: str) -> str:
        if not self.enabled:
            raise APIError(503, "Discord login is not configured", "DISCORD_OAUTH_DISABLED")
        query = urlencode(
            {
                "client_id": settings.DISCORD_CLIENT_ID,
                "redirect_uri": settings.discord_redirect_uri,
                "response_type": "code",
                "scope": "identify email",
                "state": state,
            }
        )
        return f"https://discord.com/oauth2/authorize?{query}"

    def exchange_code(self, code: str, state: str) -> str:
        if not self.enabled:
            raise APIError(503, "Discord login is not configured", "DISCORD_OAUTH_DISABLED")
        payload = _discord_json_request(
            "https://discord.com/api/oauth2/token",
            form_data={
                "client_id": settings.DISCORD_CLIENT_ID or "",
                "client_secret": settings.DISCORD_CLIENT_SECRET or "",
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": settings.discord_redirect_uri,
            },
        )
        access_token = payload.get("access_token")
        if not isinstance(access_token, str) or not access_token:
            raise APIError(502, "Discord did not return an access token", "DISCORD_TOKEN_MISSING")
        return access_token

    def fetch_identity(self, access_token: str) -> OAuthIdentity:
        payload = _discord_json_request("https://discord.com/api/v10/users/@me", access_token=access_token)

        discord_id = payload.get("id")
        if not isinstance(discord_id, str) or not discord_id:
            raise APIError(502, "Discord user id missing", "DISCORD_ID_MISSING")

        username = payload.get("username") if isinstance(payload.get("username"), str) else None
        global_name = payload.get("global_name") if isinstance(payload.get("global_name"), str) else None
        avatar_hash = payload.get("avatar") if isinstance(payload.get("avatar"), str) else None
        avatar_url = (
            f"https://cdn.discordapp.com/avatars/{discord_id}/{avatar_hash}.png" if avatar_hash else None
        )
        email = payload.get("email")
        verified = payload.get("verified")
        verified_email = email if isinstance(email, str) and email and verified is True else None

        return OAuthIdentity(
            provider=self.name,
            provider_user_id=discord_id,
            login=username,
            display_name=global_name or username,
            avatar_url=avatar_url,
            email=verified_email,
        )


_PROVIDERS = {p.name: p for p in (GitHubOAuthProvider(), DiscordOAuthProvider())}


def get_oauth_provider(name: str):
    return _PROVIDERS.get(name)


def enabled_oauth_providers() -> dict[str, bool]:
    return {name: provider.enabled for name, provider in _PROVIDERS.items()}
