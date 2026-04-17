"""Tests for detection model catalog endpoints."""

from __future__ import annotations

import hashlib
import io
import json
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models.detection_model import DetectionModel, DetectionModelVariant
from app.models.user import User
from tests.conftest import _auth_headers, _login_user, _register_user


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


class TestCreateModel:
    def test_create_requires_admin(
        self, client: TestClient, test_user: dict, auth_headers: dict[str, str]
    ) -> None:
        resp = client.post(
            "/api/models",
            json={"slug": "foo", "name": "Foo", "model_family": "yolo"},
            headers=auth_headers,
        )
        assert resp.status_code == 403

    def test_create_bumps_version(
        self, client: TestClient, admin_headers: dict[str, str]
    ) -> None:
        payload = {"slug": "foo", "name": "Foo v1", "model_family": "yolo"}
        r1 = client.post("/api/models", json=payload, headers=admin_headers)
        assert r1.status_code == 200, r1.text
        assert r1.json()["version"] == 1

        r2 = client.post("/api/models", json={**payload, "name": "Foo v2"}, headers=admin_headers)
        assert r2.status_code == 200
        assert r2.json()["version"] == 2
        assert r2.json()["id"] != r1.json()["id"]


class TestVariantUpload:
    def _create_model(self, client, admin_headers) -> str:
        r = client.post(
            "/api/models",
            json={"slug": "chamber", "name": "Chamber", "model_family": "yolo"},
            headers=admin_headers,
        )
        return r.json()["id"]

    def test_upload_variant_records_sha256(
        self, client: TestClient, admin_headers: dict[str, str]
    ) -> None:
        mid = self._create_model(client, admin_headers)
        blob = b"hello-model" * 64
        expected_sha = hashlib.sha256(blob).hexdigest()
        resp = client.post(
            f"/api/models/{mid}/variants",
            headers=admin_headers,
            data={"runtime": "onnx"},
            files={"file": ("best.onnx", io.BytesIO(blob), "application/octet-stream")},
        )
        assert resp.status_code == 200, resp.text
        j = resp.json()
        assert j["sha256"] == expected_sha
        assert j["file_size"] == len(blob)
        assert j["runtime"] == "onnx"

    def test_upload_rejects_unknown_runtime(
        self, client: TestClient, admin_headers: dict[str, str]
    ) -> None:
        mid = self._create_model(client, admin_headers)
        resp = client.post(
            f"/api/models/{mid}/variants",
            headers=admin_headers,
            data={"runtime": "tflite"},
            files={"file": ("m.bin", io.BytesIO(b"x"), "application/octet-stream")},
        )
        assert resp.status_code == 400

    def test_upload_replaces_existing_variant(
        self, client: TestClient, admin_headers: dict[str, str]
    ) -> None:
        mid = self._create_model(client, admin_headers)
        for content in (b"v1-content", b"v2-content-longer"):
            resp = client.post(
                f"/api/models/{mid}/variants",
                headers=admin_headers,
                data={"runtime": "onnx"},
                files={"file": ("best.onnx", io.BytesIO(content), "application/octet-stream")},
            )
            assert resp.status_code == 200, resp.text

        detail = client.get(f"/api/models/{mid}", headers=admin_headers).json()
        onnx_variants = [v for v in detail["variants"] if v["runtime"] == "onnx"]
        assert len(onnx_variants) == 1
        assert onnx_variants[0]["sha256"] == hashlib.sha256(b"v2-content-longer").hexdigest()


class TestBrowseAndDownload:
    def _seed(self, db: Session, client: TestClient, admin_headers: dict[str, str], *, public: bool = True) -> tuple[str, str, bytes]:
        r = client.post(
            "/api/models",
            json={
                "slug": "chamber",
                "name": "Chamber",
                "model_family": "yolo",
                "scopes": ["classification_chamber"],
                "is_public": public,
            },
            headers=admin_headers,
        )
        mid = r.json()["id"]
        blob = b"bytes-for-download" * 10
        resp = client.post(
            f"/api/models/{mid}/variants",
            headers=admin_headers,
            data={"runtime": "onnx"},
            files={"file": ("best.onnx", io.BytesIO(blob), "application/octet-stream")},
        )
        vid = resp.json()["id"]
        return mid, vid, blob

    def test_member_sees_public_only(
        self,
        client: TestClient,
        db: Session,
        admin_headers: dict[str, str],
    ) -> None:
        self._seed(db, client, admin_headers, public=True)
        self._seed_private = None
        # Create private model too by new admin flow
        r = client.post(
            "/api/models",
            json={"slug": "private-m", "name": "P", "model_family": "yolo", "is_public": False},
            headers=admin_headers,
        )
        assert r.status_code == 200

        # switch auth to member
        client.cookies.clear()
        _register_user(client, "member2@test.com", "Password123!", "M2")
        _login_user(client, "member2@test.com", "Password123!")
        resp = client.get("/api/models")
        assert resp.status_code == 200
        slugs = {item["slug"] for item in resp.json()["items"]}
        assert "chamber" in slugs
        assert "private-m" not in slugs

    def test_download_returns_sha_header(
        self,
        client: TestClient,
        db: Session,
        admin_headers: dict[str, str],
    ) -> None:
        mid, vid, blob = self._seed(db, client, admin_headers)
        expected = hashlib.sha256(blob).hexdigest()
        resp = client.get(f"/api/models/{mid}/variants/{vid}/download")
        assert resp.status_code == 200
        assert resp.headers.get("X-Model-SHA256") == expected
        assert resp.content == blob

    def test_scope_filter(
        self,
        client: TestClient,
        db: Session,
        admin_headers: dict[str, str],
    ) -> None:
        self._seed(db, client, admin_headers)
        client.post(
            "/api/models",
            json={
                "slug": "other",
                "name": "Other",
                "model_family": "yolo",
                "scopes": ["feeder"],
            },
            headers=admin_headers,
        )
        resp = client.get("/api/models", params={"scope": "classification_chamber"})
        assert resp.status_code == 200
        slugs = {item["slug"] for item in resp.json()["items"]}
        assert slugs == {"chamber"}


class TestMachineEndpoints:
    def test_machine_list_restricted_to_public(
        self,
        client: TestClient,
        db: Session,
        machine_token: str,
    ) -> None:
        _register_user(client, "admin@test.com", "Password123!", "Admin")
        _login_user(client, "admin@test.com", "Password123!")
        _promote(db, "admin@test.com", "admin")
        _login_user(client, "admin@test.com", "Password123!")
        admin_headers = _auth_headers(client)
        rp = client.post(
            "/api/models",
            json={"slug": "pub", "name": "Pub", "model_family": "yolo", "is_public": True},
            headers=admin_headers,
        )
        assert rp.status_code == 200, rp.text
        rpriv = client.post(
            "/api/models",
            json={"slug": "priv", "name": "Priv", "model_family": "yolo", "is_public": False},
            headers=admin_headers,
        )
        assert rpriv.status_code == 200, rpriv.text
        client.cookies.clear()
        resp = client.get(
            "/api/machine/models",
            headers={"Authorization": f"Bearer {machine_token}"},
        )
        assert resp.status_code == 200
        slugs = {item["slug"] for item in resp.json()["items"]}
        assert slugs == {"pub"}

    def test_machine_download_requires_bearer(self, client: TestClient) -> None:
        resp = client.get("/api/machine/models")
        assert resp.status_code in (401, 422)


class TestDeleteModel:
    def test_delete_cascades(
        self, client: TestClient, db: Session, admin_headers: dict[str, str]
    ) -> None:
        r = client.post(
            "/api/models",
            json={"slug": "gone", "name": "Gone", "model_family": "yolo"},
            headers=admin_headers,
        )
        mid = r.json()["id"]
        client.post(
            f"/api/models/{mid}/variants",
            headers=admin_headers,
            data={"runtime": "onnx"},
            files={"file": ("g.onnx", io.BytesIO(b"x" * 32), "application/octet-stream")},
        )
        resp = client.delete(f"/api/models/{mid}", headers=admin_headers)
        assert resp.status_code == 200
        mid_uuid = UUID(mid)
        assert db.query(DetectionModel).filter(DetectionModel.id == mid_uuid).first() is None
        assert (
            db.query(DetectionModelVariant)
            .filter(DetectionModelVariant.model_id == mid_uuid)
            .first()
            is None
        )
