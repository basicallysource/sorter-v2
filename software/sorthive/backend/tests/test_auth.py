"""Tests for authentication endpoints."""

from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

import app.routers.auth as auth_router
from app.errors import APIError
from app.models.user import User
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


class TestGitHubOAuth:
    def _enable_github(self, monkeypatch: object) -> None:
        monkeypatch.setattr(auth_router.settings, "GITHUB_CLIENT_ID", "test-client-id")
        monkeypatch.setattr(auth_router.settings, "GITHUB_CLIENT_SECRET", "test-client-secret")
        monkeypatch.setattr(auth_router.settings, "APP_BASE_URL", "http://localhost:5174")
        monkeypatch.setattr(
            auth_router.settings,
            "GITHUB_REDIRECT_URI",
            "http://localhost:8001/api/auth/github/callback",
        )

    def test_github_login_creates_new_user(self, client: TestClient, monkeypatch: object) -> None:
        self._enable_github(monkeypatch)
        monkeypatch.setattr(auth_router, "exchange_github_code", lambda code, state: "github-token")
        monkeypatch.setattr(
            auth_router,
            "fetch_github_identity",
            lambda access_token: {
                "github_id": "12345",
                "github_login": "octocat",
                "avatar_url": "https://avatars.example/octocat.png",
                "display_name": "The Octocat",
                "email": "octocat@example.com",
            },
        )

        start_resp = client.get("/api/auth/github", follow_redirects=False)
        assert start_resp.status_code == 302
        state = client.cookies.get("github_oauth_state")
        assert state

        callback_resp = client.get(
            "/api/auth/github/callback",
            params={"code": "oauth-code", "state": state},
            follow_redirects=False,
        )
        assert callback_resp.status_code == 303
        assert callback_resp.headers["location"] == "http://localhost:5174/"

        me_resp = client.get("/api/auth/me")
        assert me_resp.status_code == 200
        data = me_resp.json()
        assert data["email"] == "octocat@example.com"
        assert data["github_login"] == "octocat"
        assert data["has_password"] is False

    def test_github_login_links_existing_user(
        self, client: TestClient, db: Session, monkeypatch: object
    ) -> None:
        self._enable_github(monkeypatch)
        _register_user(client, "linkme@example.com", "StrongPass1!", "Link Me")
        logout_resp = client.post("/api/auth/logout", headers=_auth_headers(client))
        assert logout_resp.status_code == 200

        monkeypatch.setattr(auth_router, "exchange_github_code", lambda code, state: "github-token")
        monkeypatch.setattr(
            auth_router,
            "fetch_github_identity",
            lambda access_token: {
                "github_id": "98765",
                "github_login": "linkme",
                "avatar_url": None,
                "display_name": "Link Me",
                "email": "linkme@example.com",
            },
        )

        client.get("/api/auth/github", follow_redirects=False)
        state = client.cookies.get("github_oauth_state")
        callback_resp = client.get(
            "/api/auth/github/callback",
            params={"code": "oauth-code", "state": state},
            follow_redirects=False,
        )
        assert callback_resp.status_code == 303

        user = db.query(User).filter(User.email == "linkme@example.com").first()
        assert user is not None
        assert user.github_id == "98765"
        assert user.password_hash is not None

        me_resp = client.get("/api/auth/me")
        assert me_resp.status_code == 200
        assert me_resp.json()["has_password"] is True

    def test_github_login_requires_verified_email(self, client: TestClient, monkeypatch: object) -> None:
        self._enable_github(monkeypatch)
        monkeypatch.setattr(auth_router, "exchange_github_code", lambda code, state: "github-token")
        monkeypatch.setattr(
            auth_router,
            "fetch_github_identity",
            lambda access_token: (_ for _ in ()).throw(
                APIError(400, "GitHub account has no verified email address", "GITHUB_EMAIL_UNVERIFIED")
            ),
        )

        client.get("/api/auth/github", follow_redirects=False)
        state = client.cookies.get("github_oauth_state")

        callback_resp = client.get(
            "/api/auth/github/callback",
            params={"code": "oauth-code", "state": state},
            follow_redirects=False,
        )
        assert callback_resp.status_code == 303
        assert callback_resp.headers["location"].startswith("http://localhost:5174/login?error=")
