from __future__ import annotations

import json

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models.user import User
from tests.conftest import _auth_headers, _login_user, _register_user, make_test_image


def _promote(db: Session, email: str, role: str) -> None:
    user = db.query(User).filter(User.email == email).first()
    assert user is not None
    user.role = role
    db.commit()


def _login_admin(client: TestClient, db: Session) -> dict[str, str]:
    _register_user(client, "admin-scopes@test.com", "Password123!", "Admin")
    _login_user(client, "admin-scopes@test.com", "Password123!")
    _promote(db, "admin-scopes@test.com", "admin")
    _login_user(client, "admin-scopes@test.com", "Password123!")
    return _auth_headers(client)


def _create_api_key(
    client: TestClient,
    headers: dict[str, str],
    *,
    name: str,
    scopes: list[str],
    expires_in_days: int | None = None,
) -> str:
    payload: dict[str, object] = {"name": name, "scopes": scopes}
    if expires_in_days is not None:
        payload["expires_in_days"] = expires_in_days
    response = client.post("/api/auth/api-keys", json=payload, headers=headers)
    assert response.status_code == 200, response.text
    return response.json()["raw_token"]


def _upload_sample(client: TestClient, machine_token: str, sample_id: str = "sample-001") -> str:
    metadata = json.dumps(
        {
            "source_session_id": "sess-api-key",
            "local_sample_id": sample_id,
            "source_role": "classification_chamber",
            "capture_reason": "live_classification",
        }
    )
    response = client.post(
        "/api/machine/upload",
        headers={"Authorization": f"Bearer {machine_token}"},
        data={"metadata": metadata},
        files={"image": ("sample.png", make_test_image(), "image/png")},
    )
    assert response.status_code in (200, 201), response.text
    return response.json()["id"]


class TestApiKeyScopes:
    def test_create_rejects_unknown_scope(self, client: TestClient, db: Session) -> None:
        admin_headers = _login_admin(client, db)
        response = client.post(
            "/api/auth/api-keys",
            json={"name": "bad-scope", "scopes": ["totally:unknown"]},
            headers=admin_headers,
        )
        assert response.status_code == 400
        assert "Unknown API key scope" in response.json()["error"]

    def test_models_read_scope_allows_reads_but_blocks_writes(
        self,
        client: TestClient,
        db: Session,
    ) -> None:
        admin_headers = _login_admin(client, db)
        create_response = client.post(
            "/api/models",
            json={"slug": "scope-model", "name": "Scope Model", "model_family": "yolo"},
            headers=admin_headers,
        )
        assert create_response.status_code == 200, create_response.text

        token = _create_api_key(
            client,
            admin_headers,
            name="models-read-only",
            scopes=["models:read"],
        )
        key_headers = {"Authorization": f"Bearer {token}"}

        list_response = client.get("/api/models", headers=key_headers)
        assert list_response.status_code == 200

        write_response = client.post(
            "/api/models",
            json={"slug": "blocked-write", "name": "Blocked", "model_family": "yolo"},
            headers=key_headers,
        )
        assert write_response.status_code == 403
        assert "models:write" in write_response.json()["error"]

    def test_samples_read_scope_blocks_mutations(
        self,
        client: TestClient,
        db: Session,
        machine_token: str,
        upload_dir: str,
    ) -> None:
        sample_id = _upload_sample(client, machine_token)
        admin_headers = _login_admin(client, db)
        token = _create_api_key(
            client,
            admin_headers,
            name="samples-read-only",
            scopes=["samples:read"],
        )
        key_headers = {"Authorization": f"Bearer {token}"}

        list_response = client.get("/api/samples", headers=key_headers)
        assert list_response.status_code == 200
        assert any(item["id"] == sample_id for item in list_response.json()["items"])

        annotate_response = client.put(
            f"/api/samples/{sample_id}/annotations",
            headers=key_headers,
            json={"annotations": []},
        )
        assert annotate_response.status_code == 403
        assert "samples:write" in annotate_response.json()["error"]

    def test_create_requires_at_least_one_scope(
        self,
        client: TestClient,
        db: Session,
    ) -> None:
        admin_headers = _login_admin(client, db)
        response = client.post(
            "/api/auth/api-keys",
            json={"name": "no-scopes"},
            headers=admin_headers,
        )
        assert response.status_code == 422

        response = client.post(
            "/api/auth/api-keys",
            json={"name": "empty-scopes", "scopes": []},
            headers=admin_headers,
        )
        assert response.status_code == 422

    def test_legacy_scopeless_key_grants_nothing(
        self,
        client: TestClient,
        db: Session,
    ) -> None:
        import hashlib

        from app.models.user_api_key import UserApiKey

        admin_headers = _login_admin(client, db)
        user = db.query(User).filter(User.email == "admin-scopes@test.com").first()
        assert user is not None
        raw_token = "hv_legacy-scopeless-token"
        db.add(
            UserApiKey(
                user_id=user.id,
                name="legacy",
                token_prefix=raw_token[:9],
                token_hash=hashlib.sha256(raw_token.encode()).hexdigest(),
                scopes=None,
            )
        )
        db.commit()

        response = client.get(
            "/api/models",
            headers={"Authorization": f"Bearer {raw_token}"},
        )
        assert response.status_code == 403
        assert "models:read" in response.json()["error"]

    def test_expired_key_is_rejected(
        self,
        client: TestClient,
        db: Session,
    ) -> None:
        from datetime import datetime, timedelta, timezone

        from app.models.user_api_key import UserApiKey

        admin_headers = _login_admin(client, db)
        token = _create_api_key(
            client,
            admin_headers,
            name="short-lived",
            scopes=["models:read"],
            expires_in_days=1,
        )
        key_headers = {"Authorization": f"Bearer {token}"}
        assert client.get("/api/models", headers=key_headers).status_code == 200

        key = db.query(UserApiKey).filter(UserApiKey.name == "short-lived").first()
        assert key is not None
        assert key.expires_at is not None
        key.expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
        db.commit()

        response = client.get("/api/models", headers=key_headers)
        assert response.status_code == 401
        assert "expired" in response.json()["error"].lower()

    def test_keys_manage_scope_lets_bots_mint_and_revoke_keys(
        self,
        client: TestClient,
        db: Session,
    ) -> None:
        admin_headers = _login_admin(client, db)
        bot_token = _create_api_key(
            client,
            admin_headers,
            name="key-minter",
            scopes=["keys:manage"],
        )
        bot_headers = {"Authorization": f"Bearer {bot_token}"}

        create_response = client.post(
            "/api/auth/api-keys",
            json={"name": "minted-by-bot", "scopes": ["models:read"]},
            headers=bot_headers,
        )
        assert create_response.status_code == 200, create_response.text
        minted_id = create_response.json()["summary"]["id"]

        list_response = client.get("/api/auth/api-keys", headers=bot_headers)
        assert list_response.status_code == 200
        assert any(item["id"] == minted_id for item in list_response.json())

        revoke_response = client.delete(f"/api/auth/api-keys/{minted_id}", headers=bot_headers)
        assert revoke_response.status_code == 200
        list_after = client.get("/api/auth/api-keys", headers=bot_headers)
        minted = next(item for item in list_after.json() if item["id"] == minted_id)
        assert minted["revoked_at"] is not None

    def test_key_without_keys_manage_cannot_touch_keys_api(
        self,
        client: TestClient,
        db: Session,
    ) -> None:
        admin_headers = _login_admin(client, db)
        token = _create_api_key(
            client,
            admin_headers,
            name="models-only",
            scopes=["models:read"],
        )
        key_headers = {"Authorization": f"Bearer {token}"}

        assert client.get("/api/auth/api-keys", headers=key_headers).status_code == 403
        response = client.post(
            "/api/auth/api-keys",
            json={"name": "sneaky", "scopes": ["models:read"]},
            headers=key_headers,
        )
        assert response.status_code == 403
