"""Tests for the samples browsing and management endpoints."""

from __future__ import annotations

import json

from fastapi.testclient import TestClient

from tests.conftest import (
    _auth_headers,
    _login_user,
    _register_user,
    make_test_image,
)


def _upload_sample(
    client: TestClient,
    machine_token: str,
    session_id: str = "sess-001",
    sample_id: str = "sample-001",
    source_role: str | None = None,
    capture_reason: str | None = None,
) -> dict:
    """Helper to upload a sample and return the response data."""
    meta: dict = {
        "source_session_id": session_id,
        "local_sample_id": sample_id,
    }
    if source_role:
        meta["source_role"] = source_role
    if capture_reason:
        meta["capture_reason"] = capture_reason
    metadata = json.dumps(meta)
    image = make_test_image()
    resp = client.post(
        "/api/machine/upload",
        headers={"Authorization": f"Bearer {machine_token}"},
        data={"metadata": metadata},
        files={"image": ("test.png", image, "image/png")},
    )
    assert resp.status_code in (200, 201), resp.text
    return resp.json()


class TestListSamples:
    def test_list_samples(
        self,
        client: TestClient,
        test_user: dict,
        auth_headers: dict,
        machine_token: str,
        upload_dir: str,
    ) -> None:
        _upload_sample(client, machine_token, "sess-list", "s1")
        _upload_sample(client, machine_token, "sess-list", "s2")

        resp = client.get("/api/samples", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        items = data if isinstance(data, list) else data.get("items", [])
        assert len(items) >= 2

    def test_list_samples_filtered(
        self,
        client: TestClient,
        test_user: dict,
        auth_headers: dict,
        machine_token: str,
        upload_dir: str,
    ) -> None:
        _upload_sample(
            client,
            machine_token,
            "sess-f1",
            "s1",
            source_role="classification_chamber",
            capture_reason="live_classification",
        )
        _upload_sample(
            client,
            machine_token,
            "sess-f2",
            "s1",
            source_role="c_channel_3",
            capture_reason="channel_move_complete",
        )

        # Filter by source_role
        resp = client.get(
            "/api/samples",
            params={"source_role": "classification_chamber"},
            headers=auth_headers,
        )
        assert resp.status_code == 200
        data = resp.json()
        items = data if isinstance(data, list) else data.get("items", [])
        assert all(s.get("source_role") == "classification_chamber" for s in items)

        # Filter by capture_reason
        resp_capture = client.get(
            "/api/samples",
            params={"capture_reason": "channel_move_complete"},
            headers=auth_headers,
        )
        assert resp_capture.status_code == 200
        capture_data = resp_capture.json()
        capture_items = capture_data if isinstance(capture_data, list) else capture_data.get("items", [])
        assert capture_items
        assert all(s.get("capture_reason") == "channel_move_complete" for s in capture_items)

        # Filter by review_status
        resp2 = client.get(
            "/api/samples",
            params={"review_status": "unreviewed"},
            headers=auth_headers,
        )
        assert resp2.status_code == 200

    def test_filter_options(
        self,
        client: TestClient,
        test_user: dict,
        auth_headers: dict,
        machine_token: str,
        upload_dir: str,
    ) -> None:
        _upload_sample(
            client,
            machine_token,
            "sess-o1",
            "s1",
            source_role="classification_chamber",
            capture_reason="live_classification",
        )
        _upload_sample(
            client,
            machine_token,
            "sess-o2",
            "s1",
            source_role="c_channel_2",
            capture_reason="channel_move_complete",
        )

        resp = client.get("/api/samples/filter-options", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert "classification_chamber" in data["source_roles"]
        assert "c_channel_2" in data["source_roles"]
        assert "live_classification" in data["capture_reasons"]
        assert "channel_move_complete" in data["capture_reasons"]


class TestSampleDetail:
    def test_sample_detail(
        self,
        client: TestClient,
        test_user: dict,
        auth_headers: dict,
        machine_token: str,
        upload_dir: str,
    ) -> None:
        sample = _upload_sample(client, machine_token, "sess-det", "s1")
        sample_id = sample["id"]

        resp = client.get(f"/api/samples/{sample_id}", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["id"] == sample_id
        assert data["local_sample_id"] == "s1"


class TestSampleAssets:
    def test_sample_asset_image(
        self,
        client: TestClient,
        test_user: dict,
        auth_headers: dict,
        machine_token: str,
        upload_dir: str,
    ) -> None:
        sample = _upload_sample(client, machine_token, "sess-asset", "s1")
        sample_id = sample["id"]

        resp = client.get(
            f"/api/samples/{sample_id}/assets/image", headers=auth_headers
        )
        assert resp.status_code == 200
        assert "image" in resp.headers.get("content-type", "")


class TestSampleAuthorization:
    def test_member_cannot_access_other_users_samples(
        self,
        client: TestClient,
        test_user: dict,
        auth_headers: dict,
        machine_token: str,
        upload_dir: str,
    ) -> None:
        sample = _upload_sample(client, machine_token, "sess-auth", "s1")
        sample_id = sample["id"]

        _register_user(client, "other@test.com", "Password123!", "Other User")
        _login_user(client, "other@test.com", "Password123!")
        other_headers = _auth_headers(client)

        listing = client.get("/api/samples", headers=other_headers)
        assert listing.status_code == 200
        items = listing.json().get("items", [])
        assert all(item["id"] != sample_id for item in items)

        detail = client.get(f"/api/samples/{sample_id}", headers=other_headers)
        assert detail.status_code == 404

        asset = client.get(f"/api/samples/{sample_id}/assets/image", headers=other_headers)
        assert asset.status_code == 404

        annotations = client.put(
            f"/api/samples/{sample_id}/annotations",
            headers=other_headers,
            json={"annotations": []},
        )
        assert annotations.status_code == 404

    def test_reviewer_can_access_other_users_samples(
        self,
        client: TestClient,
        test_user: dict,
        machine_token: str,
        test_reviewer: dict,
        upload_dir: str,
    ) -> None:
        sample = _upload_sample(client, machine_token, "sess-reviewer", "s1")
        sample_id = sample["id"]

        reviewer_headers = _auth_headers(client)
        detail = client.get(f"/api/samples/{sample_id}", headers=reviewer_headers)
        assert detail.status_code == 200
        assert detail.json()["id"] == sample_id


class TestSampleAnnotations:
    def test_save_annotations(
        self,
        client: TestClient,
        test_user: dict,
        auth_headers: dict,
        machine_token: str,
        upload_dir: str,
    ) -> None:
        sample = _upload_sample(client, machine_token, "sess-ann", "s1")
        sample_id = sample["id"]

        resp = client.put(
            f"/api/samples/{sample_id}/annotations",
            headers=auth_headers,
            json={
                "annotations": [
                    {
                        "id": "annotation-1",
                        "source": "manual",
                        "shape_type": "RECTANGLE",
                        "geometry": {
                            "x": 10,
                            "y": 12,
                            "w": 28,
                            "h": 16,
                            "bounds": {
                                "minX": 10,
                                "minY": 12,
                                "maxX": 38,
                                "maxY": 28,
                            },
                        },
                        "bodies": [],
                    }
                ]
            },
        )
        assert resp.status_code == 200, resp.text
        payload = resp.json()
        assert payload["ok"] is True
        assert payload["annotation_count"] == 1
        assert payload["data"]["annotations"][0]["id"] == "annotation-1"

        detail = client.get(f"/api/samples/{sample_id}", headers=auth_headers)
        assert detail.status_code == 200, detail.text
        saved = detail.json()["extra_metadata"]["manual_annotations"]
        assert saved["version"] == "hive-annotorious-v1"
        assert saved["annotations"][0]["source"] == "manual"
        assert saved["updated_by_display_name"] == "Member User"


class TestSampleClassification:
    def test_save_manual_classification(
        self,
        client: TestClient,
        test_user: dict,
        auth_headers: dict,
        machine_token: str,
        upload_dir: str,
    ) -> None:
        sample = _upload_sample(
            client,
            machine_token,
            "sess-class",
            "s1",
            source_role="classification_chamber",
            capture_reason="live_classification",
        )
        sample_id = sample["id"]

        resp = client.put(
            f"/api/samples/{sample_id}/classification",
            headers=auth_headers,
            json={
                "part_id": "3001",
                "item_name": "Brick 2 x 4",
            },
        )
        assert resp.status_code == 200, resp.text
        payload = resp.json()
        assert payload["ok"] is True
        assert payload["cleared"] is False
        assert payload["data"]["part_id"] == "3001"
        assert payload["data"]["item_name"] == "Brick 2 x 4"

        detail = client.get(f"/api/samples/{sample_id}", headers=auth_headers)
        assert detail.status_code == 200, detail.text
        saved = detail.json()["extra_metadata"]["manual_classification"]
        assert saved["version"] == "hive-classification-v1"
        assert saved["part_id"] == "3001"
        assert saved["updated_by_display_name"] == "Member User"

    def test_save_manual_classification_rejects_non_classification_sample(
        self,
        client: TestClient,
        test_user: dict,
        auth_headers: dict,
        machine_token: str,
        upload_dir: str,
    ) -> None:
        sample = _upload_sample(
            client,
            machine_token,
            "sess-non-class",
            "s1",
            source_role="c_channel_2",
            capture_reason="channel_move_complete",
        )
        sample_id = sample["id"]

        resp = client.put(
            f"/api/samples/{sample_id}/classification",
            headers=auth_headers,
            json={
                "part_id": "3001",
            },
        )
        assert resp.status_code == 400, resp.text
        assert resp.json()["code"] == "UNSUPPORTED_SAMPLE_TYPE"


class TestDeleteSample:
    def test_delete_own_sample(
        self,
        client: TestClient,
        test_user: dict,
        auth_headers: dict,
        machine_token: str,
        upload_dir: str,
    ) -> None:
        sample = _upload_sample(client, machine_token, "sess-del", "s1")
        sample_id = sample["id"]

        resp = client.delete(
            f"/api/samples/{sample_id}", headers=auth_headers
        )
        assert resp.status_code in (200, 204)

        # Verify it's gone
        detail = client.get(f"/api/samples/{sample_id}", headers=auth_headers)
        assert detail.status_code == 404

    def test_delete_other_sample_forbidden(
        self,
        client: TestClient,
        test_user: dict,
        auth_headers: dict,
        machine_token: str,
        upload_dir: str,
    ) -> None:
        sample = _upload_sample(client, machine_token, "sess-forbid", "s1")
        sample_id = sample["id"]

        # Register and log in as a different user
        _register_user(client, "other@test.com", "Password123!", "Other User")
        _login_user(client, "other@test.com", "Password123!")
        other_headers = _auth_headers(client)

        resp = client.delete(
            f"/api/samples/{sample_id}", headers=other_headers
        )
        assert resp.status_code == 403
