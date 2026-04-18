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
    scopes: list[str] | None = None,
) -> str:
    payload: dict[str, object] = {"name": name}
    if scopes is not None:
        payload["scopes"] = scopes
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

    def test_unscoped_api_key_remains_full_access_for_existing_clients(
        self,
        client: TestClient,
        db: Session,
    ) -> None:
        admin_headers = _login_admin(client, db)
        token = _create_api_key(client, admin_headers, name="legacy-full-access")
        key_headers = {"Authorization": f"Bearer {token}"}

        response = client.post(
            "/api/models",
            json={"slug": "legacy-key-model", "name": "Legacy Key", "model_family": "yolo"},
            headers=key_headers,
        )
        assert response.status_code == 200, response.text
