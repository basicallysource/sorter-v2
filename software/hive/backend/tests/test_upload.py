"""Tests for the machine upload endpoint."""

from __future__ import annotations

import json

from fastapi.testclient import TestClient

from tests.conftest import make_test_image


class TestUploadSample:
    def test_upload_sample_success(
        self, client: TestClient, machine_token: str, upload_dir: str
    ) -> None:
        metadata = json.dumps(
            {
                "source_session_id": "sess-001",
                "local_sample_id": "sample-001",
                "source_role": "classification",
                "capture_reason": "carousel_snap",
            }
        )
        image = make_test_image()
        resp = client.post(
            "/api/machine/upload",
            headers={"Authorization": f"Bearer {machine_token}"},
            data={"metadata": metadata},
            files={"image": ("test.png", image, "image/png")},
        )
        assert resp.status_code in (200, 201)
        data = resp.json()
        assert "id" in data
        assert data.get("local_sample_id") == "sample-001"

    def test_upload_creates_session(
        self, client: TestClient, machine_token: str, upload_dir: str
    ) -> None:
        metadata = json.dumps(
            {
                "source_session_id": "sess-new",
                "local_sample_id": "sample-001",
            }
        )
        image = make_test_image()
        resp = client.post(
            "/api/machine/upload",
            headers={"Authorization": f"Bearer {machine_token}"},
            data={"metadata": metadata},
            files={"image": ("test.png", image, "image/png")},
        )
        assert resp.status_code in (200, 201)
        data = resp.json()
        assert "upload_session_id" in data or "upload_session" in data

    def test_upload_idempotent(
        self, client: TestClient, machine_token: str, upload_dir: str
    ) -> None:
        """Uploading the same session+sample combo should return the existing sample."""
        metadata = json.dumps(
            {
                "source_session_id": "sess-idem",
                "local_sample_id": "sample-idem",
            }
        )
        headers = {"Authorization": f"Bearer {machine_token}"}

        image1 = make_test_image()
        resp1 = client.post(
            "/api/machine/upload",
            headers=headers,
            data={"metadata": metadata},
            files={"image": ("test.png", image1, "image/png")},
        )
        assert resp1.status_code in (200, 201)
        id1 = resp1.json()["id"]

        image2 = make_test_image()
        resp2 = client.post(
            "/api/machine/upload",
            headers=headers,
            data={"metadata": metadata},
            files={"image": ("test.png", image2, "image/png")},
        )
        assert resp2.status_code in (200, 201)
        id2 = resp2.json()["id"]

        assert id1 == id2

    def test_upload_invalid_token(
        self, client: TestClient, upload_dir: str
    ) -> None:
        metadata = json.dumps(
            {
                "source_session_id": "sess-bad",
                "local_sample_id": "sample-bad",
            }
        )
        image = make_test_image()
        resp = client.post(
            "/api/machine/upload",
            headers={"Authorization": "Bearer bad-token"},
            data={"metadata": metadata},
            files={"image": ("test.png", image, "image/png")},
        )
        assert resp.status_code == 401

    def test_upload_invalid_image_format(
        self, client: TestClient, machine_token: str, upload_dir: str
    ) -> None:
        metadata = json.dumps(
            {
                "source_session_id": "sess-fmt",
                "local_sample_id": "sample-fmt",
            }
        )
        import io

        bad_file = io.BytesIO(b"this is not an image")
        resp = client.post(
            "/api/machine/upload",
            headers={"Authorization": f"Bearer {machine_token}"},
            data={"metadata": metadata},
            files={"image": ("test.txt", bad_file, "text/plain")},
        )
        assert resp.status_code in (400, 415, 422)

    def test_upload_too_large(
        self, client: TestClient, machine_token: str, upload_dir: str
    ) -> None:
        """Upload exceeding max size should be rejected."""
        metadata = json.dumps(
            {
                "source_session_id": "sess-big",
                "local_sample_id": "sample-big",
            }
        )
        import io

        # Create a file with valid PNG header but oversized body
        # The server should enforce a 10 MB limit; we send ~11 MB
        big = io.BytesIO(b"\x89PNG\r\n\x1a\n" + b"\x00" * (11 * 1024 * 1024))
        resp = client.post(
            "/api/machine/upload",
            headers={"Authorization": f"Bearer {machine_token}"},
            data={"metadata": metadata},
            files={"image": ("big.png", big, "image/png")},
        )
        assert resp.status_code in (400, 413, 422)

    def test_upload_rejects_path_traversal_sample_id(
        self, client: TestClient, machine_token: str, upload_dir: str
    ) -> None:
        metadata = json.dumps(
            {
                "source_session_id": "sess-traversal",
                "local_sample_id": "../escape",
            }
        )
        image = make_test_image()
        resp = client.post(
            "/api/machine/upload",
            headers={"Authorization": f"Bearer {machine_token}"},
            data={"metadata": metadata},
            files={"image": ("test.png", image, "image/png")},
        )
        assert resp.status_code in (400, 422)
