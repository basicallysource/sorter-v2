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
        assert data["sample_payload"]["sample"]["local_sample_id"] == "sample-001"

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

    def test_upload_preserves_canonical_sample_payload(
        self, client: TestClient, machine_token: str, upload_dir: str
    ) -> None:
        metadata = json.dumps(
            {
                "source_session_id": "sess-payload",
                "local_sample_id": "sample-payload",
                "source_role": "classification_chamber",
                "capture_reason": "live_classification",
                "sample_payload": {
                    "schema_version": "hive_sample_v1",
                    "sample": {
                        "source_session_id": "sess-payload",
                        "local_sample_id": "sample-payload",
                        "source_role": "classification_chamber",
                        "capture_reason": "live_classification",
                        "capture_scope": "classification",
                    },
                    "assets": {},
                    "analyses": [
                        {
                            "analysis_id": "det_primary",
                            "kind": "detection",
                            "stage": "primary_detection",
                            "provider": "gemini_sam",
                            "status": "completed",
                            "input_asset_ids": ["img_primary"],
                            "artifact_asset_ids": [],
                            "outputs": {
                                "found": True,
                                "primary_box_index": 0,
                                "boxes": [{"box_px": [1, 2, 30, 40], "score": 0.88}],
                            },
                        }
                    ],
                    "annotations": {},
                    "provenance": {"session_name": "payload-test"},
                },
            }
        )
        image = make_test_image()
        resp = client.post(
            "/api/machine/upload",
            headers={"Authorization": f"Bearer {machine_token}"},
            data={"metadata": metadata},
            files={"image": ("test.png", image, "image/png")},
        )
        assert resp.status_code in (200, 201), resp.text
        data = resp.json()
        assert data["sample_payload"]["sample"]["capture_scope"] == "classification"
        assert data["sample_payload"]["analyses"][0]["provider"] == "gemini_sam"
        assert data["detection_algorithm"] == "gemini_sam"
        assert data["detection_count"] == 1

    def test_upload_preserves_condition_sample_payload(
        self, client: TestClient, machine_token: str, upload_dir: str
    ) -> None:
        metadata = json.dumps(
            {
                "source_session_id": "sess-condition",
                "local_sample_id": "sample-condition",
                "source_role": "piece_crop",
                "capture_reason": "piece_condition_teacher",
                "sample_payload": {
                    "schema_version": "hive_sample_v1",
                    "sample": {
                        "source_session_id": "sess-condition",
                        "local_sample_id": "sample-condition",
                        "source_role": "piece_crop",
                        "capture_reason": "piece_condition_teacher",
                        "capture_scope": "condition",
                    },
                    "assets": {},
                    "analyses": [
                        {
                            "analysis_id": "cond_primary",
                            "kind": "condition",
                            "stage": "part_condition_quality",
                            "provider": "gemini_condition",
                            "model": "google/gemini-3.1-flash-lite-preview",
                            "status": "completed",
                            "input_asset_ids": ["img_primary"],
                            "artifact_asset_ids": [],
                            "outputs": {
                                "composition": "multi_part",
                                "condition": "dirty",
                                "part_count_estimate": 2,
                                "flags": {
                                    "single_part": False,
                                    "compound_part": False,
                                    "multiple_parts": True,
                                    "clean": False,
                                    "dirty": True,
                                    "damaged": False,
                                    "trash_candidate": False,
                                },
                                "issues": ["visible residue"],
                                "visible_evidence": "Two separable pieces and residue are visible.",
                                "confidence": 0.84,
                            },
                            "metadata": {"schema_version": "piece_condition_v1"},
                        }
                    ],
                    "annotations": {},
                    "provenance": {
                        "condition_sample": {
                            "enabled": True,
                            "source": "piece_crop_archive",
                            "condition_source_crop_path": "piece_crops/abc123def456/seg0/wedge_000.jpg",
                        }
                    },
                },
            }
        )
        resp = client.post(
            "/api/machine/upload",
            headers={"Authorization": f"Bearer {machine_token}"},
            data={"metadata": metadata},
            files={"image": ("test.png", make_test_image(), "image/png")},
        )

        assert resp.status_code in (200, 201), resp.text
        data = resp.json()
        assert data["sample_payload"]["sample"]["capture_scope"] == "condition"
        condition = data["sample_payload"]["analyses"][0]
        assert condition["kind"] == "condition"
        assert condition["outputs"]["composition"] == "multi_part"
        assert condition["outputs"]["condition"] == "dirty"
        assert (
            data["sample_payload"]["provenance"]["condition_sample"]["condition_source_crop_path"]
            == "piece_crops/abc123def456/seg0/wedge_000.jpg"
        )

    def test_patch_sample_merges_payload_and_extra_metadata(
        self, client: TestClient, machine_token: str, upload_dir: str
    ) -> None:
        headers = {"Authorization": f"Bearer {machine_token}"}
        create_metadata = json.dumps(
            {
                "source_session_id": "sess-patch",
                "local_sample_id": "sample-patch",
                "source_role": "classification_chamber",
                "capture_reason": "live_classification",
            }
        )
        create_resp = client.post(
            "/api/machine/upload",
            headers=headers,
            data={"metadata": create_metadata},
            files={"image": ("test.png", make_test_image(), "image/png")},
        )
        assert create_resp.status_code in (200, 201), create_resp.text

        patch_metadata = json.dumps(
            {
                "source_session_id": "sess-patch",
                "local_sample_id": "sample-patch",
                "extra_metadata": {
                    "classification_result": {
                        "provider": "brickognize",
                        "status": "completed",
                        "part_id": "3001",
                        "item_name": "Brick 2 x 4",
                        "color_name": "Red",
                        "confidence": 0.91,
                        "source_view": "top",
                    }
                },
                "sample_payload": {
                    "schema_version": "hive_sample_v1",
                    "sample": {
                        "source_session_id": "sess-patch",
                        "local_sample_id": "sample-patch",
                        "source_role": "classification_chamber",
                        "capture_reason": "live_classification",
                        "capture_scope": "classification",
                    },
                    "assets": {},
                    "analyses": [
                        {
                            "analysis_id": "cls_primary",
                            "kind": "classification",
                            "stage": "part_classification",
                            "provider": "brickognize",
                            "status": "completed",
                            "input_asset_ids": ["img_primary"],
                            "artifact_asset_ids": [],
                            "outputs": {
                                "best_candidate_index": 0,
                                "candidates": [
                                    {
                                        "part_id": "3001",
                                        "item_name": "Brick 2 x 4",
                                        "color_name": "Red",
                                        "confidence": 0.91,
                                    }
                                ],
                                "source_view": "top",
                            },
                        }
                    ],
                    "annotations": {},
                    "provenance": {},
                },
            }
        )
        patch_resp = client.patch(
            "/api/machine/upload/sess-patch/sample-patch",
            headers=headers,
            data={"metadata": patch_metadata},
        )
        assert patch_resp.status_code == 200, patch_resp.text
        patched = patch_resp.json()
        assert patched["extra_metadata"]["classification_result"]["part_id"] == "3001"
        assert any(
            analysis.get("analysis_id") == "cls_primary"
            for analysis in patched["sample_payload"]["analyses"]
        )

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
