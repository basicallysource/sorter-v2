"""Tests for the samples browsing and management endpoints."""

from __future__ import annotations

import json

import pytest
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
    detection_count: int | None = None,
    detection_score: float | None = None,
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
    if detection_count is not None:
        meta["detection_count"] = detection_count
    if detection_score is not None:
        meta["detection_score"] = detection_score
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
        assert data["source_role_counts"]["classification_chamber"] == 1
        assert data["source_role_counts"]["c_channel_2"] == 1
        assert "live_classification" in data["capture_reasons"]
        assert "channel_move_complete" in data["capture_reasons"]


class TestSampleDiversity:
    def test_diversity_groups_by_capture_reason(
        self,
        client: TestClient,
        test_user: dict,
        auth_headers: dict,
        machine_token: str,
        upload_dir: str,
    ) -> None:
        _upload_sample(client, machine_token, "sess-d1", "s1",
                       source_role="c_channel_2", capture_reason="rt_move_completed",
                       detection_count=0, detection_score=0.9)
        _upload_sample(client, machine_token, "sess-d1", "s2",
                       source_role="c_channel_2", capture_reason="rt_move_completed",
                       detection_count=3, detection_score=0.95)
        _upload_sample(client, machine_token, "sess-d1", "s3",
                       source_role="c_channel_3", capture_reason="rt_move_completed",
                       detection_count=15, detection_score=0.99)
        _upload_sample(client, machine_token, "sess-d1", "s4",
                       source_role="c_channel_2", capture_reason="manual_capture",
                       detection_count=7, detection_score=0.88)

        resp = client.get("/api/samples/diversity", headers=auth_headers)
        assert resp.status_code == 200, resp.text
        data = resp.json()

        assert data["total"] == 4
        reasons = {g["capture_reason"]: g for g in data["groups"]}
        assert set(reasons.keys()) == {"rt_move_completed", "manual_capture"}

        rt = reasons["rt_move_completed"]
        assert rt["total"] == 3
        assert rt["buckets"]["0"] == 1
        assert rt["buckets"]["3"] == 1
        assert rt["buckets"]["13+"] == 1
        assert rt["avg_score"] is not None
        assert 0.0 < rt["coverage"] <= 1.0
        assert isinstance(rt["coverage_trend"], list)
        assert len(rt["coverage_trend"]) >= 1
        assert all(0.0 <= v <= 1.0 for v in rt["coverage_trend"])
        assert rt["coverage_trend"] == sorted(rt["coverage_trend"])  # cumulative -> non-decreasing
        assert "bucket_fills" in rt and 0.0 <= (rt["bucket_fills"]["0"] or 0) <= 1.0
        # Balanced view: group coverage equals mean of role coverages
        role_coverages = [r["coverage"] for r in rt["by_source_role"]]
        assert abs(rt["coverage"] - sum(role_coverages) / len(role_coverages)) < 1e-9
        assert {r["source_role"] for r in rt["by_source_role"]} == {"c_channel_2", "c_channel_3"}
        assert data["default_target_per_bucket"] == 50
        assert data["bucket_keys"][0] == "0"
        assert data["bucket_keys"][-1] == "13+"
        # c_channel_2/3 use default targets — no n/a buckets
        for role in rt["by_source_role"]:
            assert all(role["bucket_targets"][k] == 50 for k in data["bucket_keys"])

        manual = reasons["manual_capture"]
        assert manual["total"] == 1
        assert manual["buckets"]["7"] == 1

    def test_diversity_role_specific_targets(
        self,
        client: TestClient,
        test_user: dict,
        auth_headers: dict,
        machine_token: str,
        upload_dir: str,
    ) -> None:
        # classification_channel: 9-12 and 13+ are out-of-scope (target 0). 6-8 have lower target.
        _upload_sample(client, machine_token, "sess-r1", "s1",
                       source_role="classification_channel", capture_reason="rt_move_completed",
                       detection_count=15)
        _upload_sample(client, machine_token, "sess-r1", "s2",
                       source_role="classification_channel", capture_reason="rt_move_completed",
                       detection_count=2)

        resp = client.get(
            "/api/samples/diversity",
            params={"capture_reason": "rt_move_completed"},
            headers=auth_headers,
        )
        assert resp.status_code == 200
        data = resp.json()
        role = data["groups"][0]["by_source_role"][0]
        assert role["source_role"] == "classification_channel"
        # 13+ is out-of-scope -> target 0, fill is null
        assert role["bucket_targets"]["13+"] == 0
        assert role["bucket_targets"]["9-12"] == 0
        assert role["bucket_fills"]["13+"] is None
        assert role["bucket_fills"]["9-12"] is None
        # 6-8 use lower target of 25
        assert role["bucket_targets"]["7"] == 25
        # Coverage averages only over relevant buckets — sample at count=15 must not contribute
        # Bucket "2" should have 1 sample / 50 = 0.02 fill.
        assert role["bucket_fills"]["2"] == pytest.approx(0.02)


    def test_diversity_filtered_by_capture_reason(
        self,
        client: TestClient,
        test_user: dict,
        auth_headers: dict,
        machine_token: str,
        upload_dir: str,
    ) -> None:
        _upload_sample(client, machine_token, "sess-d2", "s1",
                       capture_reason="rt_move_completed", detection_count=2)
        _upload_sample(client, machine_token, "sess-d2", "s2",
                       capture_reason="manual_capture", detection_count=10)

        resp = client.get(
            "/api/samples/diversity",
            params={"capture_reason": "rt_move_completed"},
            headers=auth_headers,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 1
        assert len(data["groups"]) == 1
        assert data["groups"][0]["capture_reason"] == "rt_move_completed"


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
        payload_saved = detail.json()["sample_payload"]["annotations"]["manual_regions"]
        assert payload_saved["version"] == "hive-annotorious-v1"
        assert payload_saved["annotations"][0]["source"] == "manual"


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
        payload_saved = detail.json()["sample_payload"]["annotations"]["manual_classification"]
        assert payload_saved["version"] == "hive-classification-v1"
        assert payload_saved["part_id"] == "3001"

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
