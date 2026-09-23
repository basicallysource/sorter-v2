"""Tests for the default model per (purpose, runtime) served to fresh installs."""

from __future__ import annotations

import hashlib
import io
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models.model_default import ModelDefault
from app.models.user import User
from tests.conftest import _auth_headers, _login_user, _register_user

BLOB = b"rknn-model-bytes" * 64


def _promote(db: Session, email: str, role: str) -> None:
    user = db.query(User).filter(User.email == email).first()
    assert user is not None
    user.role = role
    db.commit()


@pytest.fixture()
def admin_headers(client: TestClient, db: Session) -> dict[str, str]:
    _register_user(client, "admin@test.com", "Password123!", "Admin")
    _login_user(client, "admin@test.com", "Password123!")
    _promote(db, "admin@test.com", "admin")
    return _auth_headers(client)


def _publish(
    client: TestClient,
    headers: dict[str, str],
    *,
    slug: str = "chamber",
    runtime: str = "rknn",
    purpose: str = "detection",
    public: bool = True,
    blob: bytes = BLOB,
) -> tuple[str, str]:
    r = client.post(
        "/api/models",
        json={
            "slug": slug,
            "name": slug.title(),
            "model_family": "yolo",
            "purpose": purpose,
            "scopes": ["classification_chamber"],
            "is_public": public,
            "training_metadata": {"imgsz": 320},
        },
        headers=headers,
    )
    assert r.status_code == 200, r.text
    mid = r.json()["id"]
    v = client.post(
        f"/api/models/{mid}/variants",
        headers=headers,
        data={"runtime": runtime},
        files={"file": (f"best.{runtime}", io.BytesIO(blob), "application/octet-stream")},
    )
    assert v.status_code == 200, v.text
    return mid, v.json()["id"]


def _set(client, headers, mid, vid, purpose="detection", runtime="rknn"):
    return client.put(
        f"/api/model-defaults/{purpose}/{runtime}",
        json={"model_id": mid, "variant_id": vid},
        headers=headers,
    )


class TestAnonymousReads:
    def test_unset_is_404(self, client: TestClient) -> None:
        assert client.get("/api/model-defaults").json() == {"items": []}
        for path in ("/api/model-defaults/detection/rknn", "/api/model-defaults/detection/rknn/download"):
            r = client.get(path)
            assert r.status_code == 404
            assert r.json()["code"] == "MODEL_DEFAULT_NOT_SET"

    def test_set_then_read_without_any_credential(
        self, client: TestClient, admin_headers: dict[str, str]
    ) -> None:
        mid, vid = _publish(client, admin_headers)
        r = _set(client, admin_headers, mid, vid)
        assert r.status_code == 200, r.text
        assert r.json()["variant"]["id"] == vid

        client.cookies.clear()

        listed = client.get("/api/model-defaults")
        assert listed.status_code == 200
        assert [(i["purpose"], i["runtime"]) for i in listed.json()["items"]] == [("detection", "rknn")]

        item = client.get("/api/model-defaults/detection/rknn")
        assert item.status_code == 200, item.text
        body = item.json()
        assert body["download_path"] == "/api/model-defaults/detection/rknn/download"
        assert body["model"]["id"] == mid
        assert body["model"]["purpose"] == "detection"
        assert body["model"]["model_family"] == "yolo"
        assert body["model"]["scopes"] == ["classification_chamber"]
        assert body["model"]["training_metadata"] == {"imgsz": 320}
        assert body["model"]["codename"] and body["model"]["codename_color"]
        assert body["variant"]["runtime"] == "rknn"
        assert body["variant"]["sha256"] == hashlib.sha256(BLOB).hexdigest()
        assert body["variant"]["file_size"] == len(BLOB)
        assert body["updated_at"]

        dl = client.get(body["download_path"])
        assert dl.status_code == 200
        assert dl.content == BLOB
        assert dl.headers["X-Model-SHA256"] == hashlib.sha256(BLOB).hexdigest()
        assert dl.headers["X-Model-Size"] == str(len(BLOB))
        assert "chamber_v1_" in dl.headers["content-disposition"]

    def test_model_gone_private_is_not_served(
        self, client: TestClient, admin_headers: dict[str, str]
    ) -> None:
        mid, vid = _publish(client, admin_headers)
        assert _set(client, admin_headers, mid, vid).status_code == 200
        r = client.patch(f"/api/models/{mid}", json={"is_public": False}, headers=admin_headers)
        assert r.status_code == 200, r.text
        assert client.get(f"/api/models/{mid}", headers=admin_headers).json()["default_for"] == []

        client.cookies.clear()
        assert client.get("/api/model-defaults").json() == {"items": []}
        r = client.get("/api/model-defaults/detection/rknn")
        assert r.status_code == 404
        assert r.json()["code"] == "MODEL_DEFAULT_NOT_SET"
        assert client.get("/api/model-defaults/detection/rknn/download").status_code == 404


class TestSetDefault:
    def test_anonymous_cannot_set(self, client: TestClient, admin_headers: dict[str, str]) -> None:
        mid, vid = _publish(client, admin_headers)
        client.cookies.clear()
        assert _set(client, {}, mid, vid).status_code == 401

    def test_member_cannot_set(self, client: TestClient, admin_headers: dict[str, str]) -> None:
        mid, vid = _publish(client, admin_headers)
        client.cookies.clear()
        _register_user(client, "member@test.com", "Password123!", "Member")
        _login_user(client, "member@test.com", "Password123!")
        r = _set(client, _auth_headers(client), mid, vid)
        assert r.status_code == 403

    def test_cookie_session_needs_csrf(self, client: TestClient, admin_headers: dict[str, str]) -> None:
        mid, vid = _publish(client, admin_headers)
        assert _set(client, {}, mid, vid).status_code == 403
        assert client.delete("/api/model-defaults/detection/rknn").status_code == 403

    def test_read_only_key_cannot_set(self, client: TestClient, admin_headers: dict[str, str]) -> None:
        mid, vid = _publish(client, admin_headers)
        key = client.post(
            "/api/auth/api-keys", json={"name": "ro", "scopes": ["models:read"]}, headers=admin_headers
        ).json()["raw_token"]
        client.cookies.clear()
        r = _set(client, {"Authorization": f"Bearer {key}"}, mid, vid)
        assert r.status_code == 403
        assert "models:write" in r.json()["error"]

    def test_rejects_runtime_mismatch(self, client: TestClient, admin_headers: dict[str, str]) -> None:
        mid, vid = _publish(client, admin_headers, runtime="onnx")
        r = _set(client, admin_headers, mid, vid, runtime="rknn")
        assert r.status_code == 400
        assert r.json()["code"] == "RUNTIME_MISMATCH"

    def test_rejects_wrong_purpose(self, client: TestClient, admin_headers: dict[str, str]) -> None:
        mid, vid = _publish(client, admin_headers, purpose="piece_link", runtime="onnx")
        r = _set(client, admin_headers, mid, vid, runtime="onnx")
        assert r.status_code == 400
        assert r.json()["code"] == "PURPOSE_MISMATCH"

    def test_rejects_private_model(self, client: TestClient, admin_headers: dict[str, str]) -> None:
        mid, vid = _publish(client, admin_headers, public=False)
        r = _set(client, admin_headers, mid, vid)
        assert r.status_code == 409
        assert r.json()["code"] == "MODEL_NOT_PUBLIC"

    def test_rejects_variant_of_another_model(
        self, client: TestClient, admin_headers: dict[str, str]
    ) -> None:
        mid, _ = _publish(client, admin_headers, slug="one")
        _, other_vid = _publish(client, admin_headers, slug="two")
        r = _set(client, admin_headers, mid, other_vid)
        assert r.status_code == 404
        assert r.json()["code"] == "VARIANT_NOT_FOUND"

    def test_put_replaces_the_default(
        self, client: TestClient, db: Session, admin_headers: dict[str, str]
    ) -> None:
        first_mid, first_vid = _publish(client, admin_headers, slug="first")
        second_mid, second_vid = _publish(client, admin_headers, slug="second")
        assert _set(client, admin_headers, first_mid, first_vid).status_code == 200
        assert _set(client, admin_headers, second_mid, second_vid).status_code == 200

        assert client.get("/api/model-defaults/detection/rknn").json()["model"]["id"] == second_mid
        assert db.query(ModelDefault).count() == 1
        assert client.get(f"/api/models/{first_mid}", headers=admin_headers).json()["default_for"] == []
        assert client.get(f"/api/models/{second_mid}", headers=admin_headers).json()["default_for"] == ["rknn"]


class TestClearDefault:
    def test_delete_clears(self, client: TestClient, admin_headers: dict[str, str]) -> None:
        mid, vid = _publish(client, admin_headers)
        assert _set(client, admin_headers, mid, vid).status_code == 200
        r = client.delete("/api/model-defaults/detection/rknn", headers=admin_headers)
        assert r.status_code == 204
        assert client.get("/api/model-defaults/detection/rknn").status_code == 404
        assert client.get(f"/api/models/{mid}", headers=admin_headers).json()["default_for"] == []

    def test_member_cannot_clear(self, client: TestClient, admin_headers: dict[str, str]) -> None:
        mid, vid = _publish(client, admin_headers)
        assert _set(client, admin_headers, mid, vid).status_code == 200
        client.cookies.clear()
        _register_user(client, "member@test.com", "Password123!", "Member")
        _login_user(client, "member@test.com", "Password123!")
        r = client.delete("/api/model-defaults/detection/rknn", headers=_auth_headers(client))
        assert r.status_code == 403
        assert client.get("/api/model-defaults/detection/rknn").status_code == 200

    def test_deleting_the_model_takes_its_default_with_it(
        self, client: TestClient, db: Session, admin_headers: dict[str, str]
    ) -> None:
        mid, vid = _publish(client, admin_headers)
        assert _set(client, admin_headers, mid, vid).status_code == 200
        assert client.delete(f"/api/models/{mid}", headers=admin_headers).status_code == 200
        assert db.query(ModelDefault).filter(ModelDefault.model_id == UUID(mid)).count() == 0
        assert client.get("/api/model-defaults/detection/rknn").status_code == 404


def test_default_for_on_model_detail(client: TestClient, admin_headers: dict[str, str]) -> None:
    mid, vid = _publish(client, admin_headers)
    assert client.get(f"/api/models/{mid}", headers=admin_headers).json()["default_for"] == []
    assert _set(client, admin_headers, mid, vid).status_code == 200
    assert client.get(f"/api/models/{mid}", headers=admin_headers).json()["default_for"] == ["rknn"]
