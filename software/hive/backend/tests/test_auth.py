"""Tests for authentication endpoints."""

from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

import app.routers.auth as auth_router
from app.errors import APIError
from app.models.user import User
from app.models.user_identity import UserIdentity
from app.services.oauth_providers import OAuthIdentity, get_oauth_provider
from tests.conftest import _auth_headers, _login_user, _register_user


class TestRegister:
    def test_register_success(self, client: TestClient) -> None:
        resp = client.post(
            "/api/auth/register",
            json={
                "email": "new@test.com",
                "password": "StrongPass1!",
                "display_name": "New User",
            },
        )
        assert resp.status_code in (200, 201)
        data = resp.json()
        assert data["email"] == "new@test.com"
        assert data["display_name"] == "New User"
        assert "password" not in data
        assert "password_hash" not in data

    def test_register_duplicate_email(self, client: TestClient) -> None:
        _register_user(client, "dup@test.com", "StrongPass1!")
        resp = client.post(
            "/api/auth/register",
            json={"email": "dup@test.com", "password": "StrongPass1!"},
        )
        assert resp.status_code == 409 or resp.status_code == 400
        body = resp.json()
        assert "error" in body


class TestLogin:
    def test_login_success(self, client: TestClient) -> None:
        _register_user(client, "login@test.com", "StrongPass1!")
        resp = client.post(
            "/api/auth/login",
            json={"email": "login@test.com", "password": "StrongPass1!"},
        )
        assert resp.status_code == 200
        # Access and refresh tokens should be set as cookies
        assert "access_token" in client.cookies or "access_token" in resp.cookies
        assert "csrf_token" in client.cookies or "csrf_token" in resp.cookies

    def test_login_wrong_password(self, client: TestClient) -> None:
        _register_user(client, "wrong@test.com", "StrongPass1!")
        resp = client.post(
            "/api/auth/login",
            json={"email": "wrong@test.com", "password": "WrongPassword!"},
        )
        assert resp.status_code == 401
        body = resp.json()
        assert "error" in body


class TestTokenRefresh:
    def test_refresh_token(self, client: TestClient) -> None:
        _register_user(client, "refresh@test.com", "StrongPass1!")
        _login_user(client, "refresh@test.com", "StrongPass1!")
        headers = _auth_headers(client)
        resp = client.post("/api/auth/refresh", headers=headers)
        assert resp.status_code == 200


class TestLogout:
    def test_logout(self, client: TestClient) -> None:
        _register_user(client, "logout@test.com", "StrongPass1!")
        _login_user(client, "logout@test.com", "StrongPass1!")
        headers = _auth_headers(client)
        resp = client.post("/api/auth/logout", headers=headers)
        assert resp.status_code == 200 or resp.status_code == 204
        # After logout, /me should fail
        me_resp = client.get("/api/auth/me")
        assert me_resp.status_code == 401


class TestMe:
    def test_me_authenticated(self, client: TestClient, test_user: dict) -> None:
        resp = client.get("/api/auth/me")
        assert resp.status_code == 200
        data = resp.json()
        assert data["email"] == "member@test.com"

    def test_me_unauthenticated(self, client: TestClient) -> None:
        resp = client.get("/api/auth/me")
        assert resp.status_code == 401


class TestDeleteAccount:
    def test_delete_account_cascades(
        self, client: TestClient, test_user: dict, auth_headers: dict
    ) -> None:
        # Create a machine first
        machine_resp = client.post(
            "/api/machines",
            json={"name": "To Delete", "description": "Will be deleted"},
            headers=auth_headers,
        )
        assert machine_resp.status_code in (200, 201)

        # Delete account
        resp = client.delete("/api/auth/me", headers=auth_headers)
        assert resp.status_code in (200, 204)

        # Verify user can no longer authenticate
        login_resp = client.post(
            "/api/auth/login",
            json={"email": "member@test.com", "password": "Password123!"},
        )
        assert login_resp.status_code == 401


class TestOAuth:
    """OAuth sign-in + account-link flows, exercised through the GitHub and
    Discord adapters with the provider network calls mocked out."""

    def _enable(self, monkeypatch: object, provider: str) -> None:
        monkeypatch.setattr(auth_router.settings, f"{provider.upper()}_CLIENT_ID", "test-client-id")
        monkeypatch.setattr(auth_router.settings, f"{provider.upper()}_CLIENT_SECRET", "test-client-secret")
        monkeypatch.setattr(auth_router.settings, "APP_BASE_URL", "http://localhost:5174")

    def _mock_identity(self, monkeypatch: object, provider: str, **overrides: object) -> None:
        adapter = get_oauth_provider(provider)
        defaults = {
            "provider": provider,
            "provider_user_id": "12345",
            "login": "octocat",
            "display_name": "The Octocat",
            "avatar_url": "https://avatars.example/octocat.png",
            "email": "octocat@example.com",
        }
        defaults.update(overrides)
        identity = OAuthIdentity(**defaults)
        monkeypatch.setattr(adapter, "exchange_code", lambda code, state: "provider-token")
        monkeypatch.setattr(adapter, "fetch_identity", lambda access_token: identity)

    def _run_callback(self, client: TestClient, provider: str, start_path: str | None = None):
        start_resp = client.get(start_path or f"/api/auth/{provider}", follow_redirects=False)
        assert start_resp.status_code == 302
        state = client.cookies.get(f"{provider}_oauth_state")
        assert state
        return client.get(
            f"/api/auth/{provider}/callback",
            params={"code": "oauth-code", "state": state},
            follow_redirects=False,
        )

    def test_github_login_creates_new_user(self, client: TestClient, db: Session, monkeypatch: object) -> None:
        self._enable(monkeypatch, "github")
        self._mock_identity(monkeypatch, "github")

        callback_resp = self._run_callback(client, "github")
        assert callback_resp.status_code == 303
        assert callback_resp.headers["location"] == "http://localhost:5174/"

        me_resp = client.get("/api/auth/me")
        assert me_resp.status_code == 200
        data = me_resp.json()
        assert data["email"] == "octocat@example.com"
        assert data["github_login"] == "octocat"
        assert data["has_password"] is False

        identity = db.query(UserIdentity).filter(UserIdentity.provider == "github").first()
        assert identity is not None
        assert identity.provider_user_id == "12345"

    def test_github_login_links_existing_user_by_email(
        self, client: TestClient, db: Session, monkeypatch: object
    ) -> None:
        self._enable(monkeypatch, "github")
        _register_user(client, "linkme@example.com", "StrongPass1!", "Link Me")
        logout_resp = client.post("/api/auth/logout", headers=_auth_headers(client))
        assert logout_resp.status_code == 200

        self._mock_identity(
            monkeypatch, "github", provider_user_id="98765", login="linkme", email="linkme@example.com"
        )
        callback_resp = self._run_callback(client, "github")
        assert callback_resp.status_code == 303

        user = db.query(User).filter(User.email == "linkme@example.com").first()
        assert user is not None
        assert user.password_hash is not None
        identity = db.query(UserIdentity).filter(UserIdentity.user_id == user.id).first()
        assert identity is not None
        assert identity.provider == "github"
        assert identity.provider_user_id == "98765"

        me_resp = client.get("/api/auth/me")
        assert me_resp.status_code == 200
        assert me_resp.json()["has_password"] is True

    def test_github_login_requires_verified_email(self, client: TestClient, monkeypatch: object) -> None:
        self._enable(monkeypatch, "github")
        adapter = get_oauth_provider("github")
        monkeypatch.setattr(adapter, "exchange_code", lambda code, state: "provider-token")
        monkeypatch.setattr(
            adapter,
            "fetch_identity",
            lambda access_token: (_ for _ in ()).throw(
                APIError(400, "GitHub account has no verified email address", "GITHUB_EMAIL_UNVERIFIED")
            ),
        )

        callback_resp = self._run_callback(client, "github")
        assert callback_resp.status_code == 303
        assert callback_resp.headers["location"].startswith("http://localhost:5174/login?error=")

    def test_discord_login_creates_new_user(self, client: TestClient, db: Session, monkeypatch: object) -> None:
        self._enable(monkeypatch, "discord")
        self._mock_identity(
            monkeypatch,
            "discord",
            provider_user_id="555001",
            login="brickfan",
            display_name="Brick Fan",
            email="brickfan@example.com",
            avatar_url=None,
        )

        callback_resp = self._run_callback(client, "discord")
        assert callback_resp.status_code == 303

        me_resp = client.get("/api/auth/me")
        assert me_resp.status_code == 200
        assert me_resp.json()["email"] == "brickfan@example.com"

        identity = db.query(UserIdentity).filter(UserIdentity.provider == "discord").first()
        assert identity is not None
        assert identity.provider_user_id == "555001"
        assert identity.provider_login == "brickfan"

    def test_discord_login_returning_user_ignores_email_change(
        self, client: TestClient, db: Session, monkeypatch: object
    ) -> None:
        """Second sign-in resolves by identity, not email — a changed Discord
        email must not create a second account."""
        self._enable(monkeypatch, "discord")
        self._mock_identity(monkeypatch, "discord", provider_user_id="555002", email="original@example.com")
        assert self._run_callback(client, "discord").status_code == 303
        client.post("/api/auth/logout", headers=_auth_headers(client))

        self._mock_identity(monkeypatch, "discord", provider_user_id="555002", email="changed@example.com")
        assert self._run_callback(client, "discord").status_code == 303

        assert db.query(User).filter(User.email == "changed@example.com").first() is None
        me_resp = client.get("/api/auth/me")
        assert me_resp.json()["email"] == "original@example.com"

    def test_link_flow_attaches_identity_to_logged_in_user(
        self, client: TestClient, db: Session, monkeypatch: object
    ) -> None:
        self._enable(monkeypatch, "discord")
        _register_user(client, "owner@example.com", "StrongPass1!", "Owner")

        self._mock_identity(monkeypatch, "discord", provider_user_id="777001", login="ownerdiscord")
        callback_resp = self._run_callback(client, "discord", start_path="/api/auth/discord/link")
        assert callback_resp.status_code == 303
        assert callback_resp.headers["location"] == "http://localhost:5174/settings"

        user = db.query(User).filter(User.email == "owner@example.com").first()
        identity = db.query(UserIdentity).filter(UserIdentity.user_id == user.id).first()
        assert identity is not None
        assert identity.provider == "discord"
        assert identity.provider_user_id == "777001"

        listing = client.get("/api/auth/identities")
        assert listing.status_code == 200
        providers = [i["provider"] for i in listing.json()]
        assert providers == ["discord"]

    def test_link_flow_rejects_identity_owned_by_other_account(
        self, client: TestClient, db: Session, monkeypatch: object
    ) -> None:
        self._enable(monkeypatch, "discord")
        # First user claims the Discord account via sign-in.
        self._mock_identity(monkeypatch, "discord", provider_user_id="888001", email="first@example.com")
        assert self._run_callback(client, "discord").status_code == 303
        client.post("/api/auth/logout", headers=_auth_headers(client))

        # Second user tries to link the same Discord account.
        _register_user(client, "second@example.com", "StrongPass1!", "Second")
        self._mock_identity(monkeypatch, "discord", provider_user_id="888001", email="first@example.com")
        callback_resp = self._run_callback(client, "discord", start_path="/api/auth/discord/link")
        assert callback_resp.status_code == 303
        assert callback_resp.headers["location"].startswith("http://localhost:5174/settings?error=")

        second = db.query(User).filter(User.email == "second@example.com").first()
        assert db.query(UserIdentity).filter(UserIdentity.user_id == second.id).count() == 0

    def test_link_flow_requires_session(self, client: TestClient, monkeypatch: object) -> None:
        self._enable(monkeypatch, "discord")
        self._mock_identity(monkeypatch, "discord", provider_user_id="999001")

        callback_resp = self._run_callback(client, "discord", start_path="/api/auth/discord/link")
        assert callback_resp.status_code == 303
        assert callback_resp.headers["location"].startswith("http://localhost:5174/settings?error=")

    def test_unlink_guard_blocks_removing_last_sign_in_method(
        self, client: TestClient, db: Session, monkeypatch: object
    ) -> None:
        self._enable(monkeypatch, "discord")
        self._mock_identity(monkeypatch, "discord", provider_user_id="111222", email="solo@example.com")
        assert self._run_callback(client, "discord").status_code == 303

        # OAuth-only account: unlinking the only identity would strand it.
        resp = client.delete("/api/auth/identities/discord", headers=_auth_headers(client))
        assert resp.status_code == 400
        assert resp.json()["code"] == "LAST_SIGN_IN_METHOD"

    def test_unlink_succeeds_when_password_exists(
        self, client: TestClient, db: Session, monkeypatch: object
    ) -> None:
        self._enable(monkeypatch, "discord")
        _register_user(client, "haspass@example.com", "StrongPass1!", "Has Pass")
        self._mock_identity(monkeypatch, "discord", provider_user_id="333444")
        assert self._run_callback(client, "discord", start_path="/api/auth/discord/link").status_code == 303

        resp = client.delete("/api/auth/identities/discord", headers=_auth_headers(client))
        assert resp.status_code == 200
        assert client.get("/api/auth/identities").json() == []

    def test_options_reports_enabled_providers(self, client: TestClient, monkeypatch: object) -> None:
        self._enable(monkeypatch, "discord")
        resp = client.get("/api/auth/options")
        assert resp.status_code == 200
        data = resp.json()
        assert data["discord_enabled"] is True
        assert data["github_enabled"] is False
