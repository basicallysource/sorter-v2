from collections import deque
import json
import queue
import tempfile
import threading
import unittest
from pathlib import Path

import cv2
import numpy as np

from server.hive_uploader import (
    HiveUploader,
    SERVER_DOWN_BACKOFF_S,
    sample_type_from_metadata,
    teacher_state_from_metadata,
)


def _write_test_image(path: Path, value: int = 128) -> None:
    image = np.full((48, 64, 3), value, dtype=np.uint8)
    ok, encoded = cv2.imencode(".jpg", image)
    assert ok
    path.write_bytes(encoded.tobytes())


class HiveUploaderPurgeTests(unittest.TestCase):
    def _make_uploader(self) -> HiveUploader:
        uploader = HiveUploader.__new__(HiveUploader)
        uploader._queue = queue.Queue()
        uploader._lock = threading.Lock()
        uploader._active_jobs = {}
        uploader._recent_jobs = deque(maxlen=120)
        uploader._queued_job_keys = set()
        uploader._targets = {
            "target-a": {
                "id": "target-a",
                "name": "Target A",
                "url": "http://hive-a.test",
                "machine_id": "machine-a",
                "enabled": True,
                "server_reachable": True,
                "queued": 2,
                "uploaded": 0,
                "failed": 0,
                "requeued": 0,
                "retry_after": 30.0,
                "backoff_s": 45.0,
                "last_error": "Retrying sample sync: boom",
                "client": object(),
            },
            "target-b": {
                "id": "target-b",
                "name": "Target B",
                "url": "http://hive-b.test",
                "machine_id": "machine-b",
                "enabled": True,
                "server_reachable": True,
                "queued": 1,
                "uploaded": 0,
                "failed": 0,
                "requeued": 0,
                "retry_after": 0.0,
                "backoff_s": SERVER_DOWN_BACKOFF_S,
                "last_error": None,
                "client": object(),
            },
        }
        return uploader

    def test_purge_removes_only_requested_target_jobs(self) -> None:
        uploader = self._make_uploader()
        uploader._queue.put({"target_id": "target-a", "sample_id": "sample-1"})
        uploader._queue.put({"target_id": "target-b", "sample_id": "sample-2"})
        uploader._queue.put({"target_id": "target-a", "sample_id": "sample-3"})

        result = uploader.purge(target_ids=["target-a"])

        self.assertTrue(result["ok"])
        self.assertEqual(2, result["purged"])
        self.assertEqual(0, result["remaining"])
        self.assertEqual({"target-a": 2}, result["purged_by_target"])
        self.assertEqual(0, uploader._targets["target-a"]["queued"])
        self.assertEqual(0.0, uploader._targets["target-a"]["retry_after"])
        self.assertEqual(SERVER_DOWN_BACKOFF_S, uploader._targets["target-a"]["backoff_s"])
        self.assertIsNone(uploader._targets["target-a"]["last_error"])
        self.assertEqual(1, uploader._targets["target-b"]["queued"])

        remaining_job = uploader._queue.get_nowait()
        self.assertEqual("target-b", remaining_job["target_id"])
        self.assertTrue(uploader._queue.empty())

    def test_purge_all_clears_remaining_jobs(self) -> None:
        uploader = self._make_uploader()
        uploader._queue.put({"target_id": "target-a", "sample_id": "sample-1"})
        uploader._queue.put({"target_id": "target-b", "sample_id": "sample-2"})

        result = uploader.purge()

        self.assertTrue(result["ok"])
        self.assertEqual(2, result["purged"])
        self.assertEqual(1, result["remaining"])
        self.assertEqual({"target-a": 1, "target-b": 1}, result["purged_by_target"])
        self.assertEqual(2, result["target_count"])
        self.assertTrue(uploader._queue.empty())
        self.assertEqual(1, uploader._targets["target-a"]["queued"])
        self.assertEqual(0, uploader._targets["target-b"]["queued"])

    def test_enqueue_skips_teacher_sample_without_gemini_labels(self) -> None:
        uploader = self._make_uploader()
        metadata = {
            "source": "live_aux_teacher_capture",
            "capture_reason": "rt_periodic_interval",
            "detection_algorithm": "hive:c-channel-yolo11n-320",
            "source_role": "classification_channel",
            "teacher_capture_crop_mode": "polygon_masked_zone",
            "teacher_capture_crop_signal": {"mean_gray": 42.0, "nonblack_ratio": 0.5},
        }

        uploader.enqueue(
            session_id="session-1",
            session_name="Session",
            sample_id="sample-1",
            metadata=metadata,
            image_path="/tmp/sample.jpg",
            target_ids=["target-a"],
        )

        self.assertTrue(uploader._queue.empty())
        self.assertEqual(2, uploader._targets["target-a"]["queued"])
        self.assertEqual("needs_gemini", teacher_state_from_metadata(metadata)["state"])

    def test_enqueue_deduplicates_waiting_upload_for_same_target_sample(self) -> None:
        uploader = self._make_uploader()
        metadata = {
            "source": "live_aux_teacher_capture",
            "source_role": "classification_channel",
            "detection_algorithm": "gemini_sam",
            "detection_bbox_count": 1,
            "teacher_capture_crop_mode": "polygon_masked_zone",
            "teacher_capture_crop_signal": {"mean_gray": 50.0, "nonblack_ratio": 0.25},
        }

        first = uploader.enqueue(
            session_id="session-1",
            session_name="Session",
            sample_id="sample-1",
            metadata=metadata,
            image_path="/tmp/sample.jpg",
            target_ids=["target-a"],
        )
        second = uploader.enqueue(
            session_id="session-1",
            session_name="Session",
            sample_id="sample-1",
            metadata=metadata,
            image_path="/tmp/sample.jpg",
            target_ids=["target-a"],
        )

        self.assertEqual(1, first)
        self.assertEqual(0, second)
        self.assertEqual(1, uploader._queue.qsize())
        self.assertEqual(3, uploader._targets["target-a"]["queued"])

    def test_backfill_skips_sample_marked_uploaded_for_target(self) -> None:
        uploader = self._make_uploader()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            session = root / "session-1"
            image = session / "dataset" / "images" / "sample-1.jpg"
            metadata_path = session / "metadata" / "sample-1.json"
            image.parent.mkdir(parents=True)
            metadata_path.parent.mkdir(parents=True)
            _write_test_image(image, value=128)
            metadata_path.write_text(
                json.dumps(
                    {
                        "sample_id": "sample-1",
                        "input_image": str(image),
                        "source": "live_aux_teacher_capture",
                        "source_role": "classification_channel",
                        "detection_algorithm": "gemini_sam",
                        "detection_bbox_count": 1,
                        "teacher_capture_crop_mode": "polygon_masked_zone",
                        "teacher_capture_crop_signal": {"mean_gray": 50.0, "nonblack_ratio": 0.25},
                        "hive_uploads": {
                            "target-a": {"status": "uploaded"},
                        },
                    }
                )
            )

            result = uploader.backfill(root, target_ids=["target-a"])

        self.assertTrue(result["ok"])
        self.assertEqual(0, result["queued"])
        self.assertTrue(uploader._queue.empty())

    def test_backfill_skips_black_primary_image(self) -> None:
        uploader = self._make_uploader()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            session = root / "session-1"
            image = session / "dataset" / "images" / "sample-1.jpg"
            metadata_path = session / "metadata" / "sample-1.json"
            image.parent.mkdir(parents=True)
            metadata_path.parent.mkdir(parents=True)
            _write_test_image(image, value=0)
            metadata_path.write_text(
                json.dumps(
                    {
                        "sample_id": "sample-1",
                        "input_image": str(image),
                        "source": "settings_detection_test",
                        "source_role": "c_channel_2",
                        "detection_algorithm": "hive:c-channel-yolo11n-320",
                        "detection_bbox_count": 1,
                    }
                )
            )

            result = uploader.backfill(root, target_ids=["target-a"])

        self.assertTrue(result["ok"])
        self.assertEqual(0, result["queued"])
        self.assertEqual(1, result["dark_image_sample"])
        self.assertTrue(uploader._queue.empty())

    def test_backfill_filters_by_sample_type_and_limit(self) -> None:
        uploader = self._make_uploader()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            session = root / "session-1"
            image_dir = session / "dataset" / "images"
            metadata_dir = session / "metadata"
            image_dir.mkdir(parents=True)
            metadata_dir.mkdir(parents=True)

            for sample_id, metadata in (
                (
                    "teacher-1",
                    {
                        "source": "live_aux_teacher_capture",
                        "source_role": "classification_channel",
                        "detection_algorithm": "gemini_sam",
                        "detection_bbox_count": 1,
                        "teacher_capture_crop_mode": "polygon_masked_zone",
                        "teacher_capture_crop_signal": {"mean_gray": 50.0, "nonblack_ratio": 0.25},
                    },
                ),
                (
                    "condition-1",
                    {
                        "source": "piece_condition_teacher_capture",
                        "source_role": "piece_crop",
                        "capture_reason": "piece_condition_teacher",
                        "condition_sample": True,
                    },
                ),
                (
                    "condition-2",
                    {
                        "source": "piece_condition_teacher_capture",
                        "source_role": "piece_crop",
                        "capture_reason": "piece_condition_teacher",
                        "condition_sample": True,
                    },
                ),
            ):
                image = image_dir / f"{sample_id}.jpg"
                _write_test_image(image, value=128)
                metadata["sample_id"] = sample_id
                metadata["input_image"] = str(image)
                (metadata_dir / f"{sample_id}.json").write_text(json.dumps(metadata))

            result = uploader.backfill(
                root,
                target_ids=["target-a"],
                max_samples=1,
                sample_type="condition",
            )

        self.assertTrue(result["ok"])
        self.assertEqual("condition", result["sample_type"])
        self.assertEqual(1, result["queued"])
        queued_job = uploader._queue.get_nowait()
        self.assertEqual("condition", sample_type_from_metadata(queued_job["metadata"]))

    def test_process_job_marks_metadata_uploaded(self) -> None:
        class _FakeClient:
            def upload_sample(self, **_kwargs):
                return {"id": "remote-sample-1"}

        uploader = self._make_uploader()
        uploader._targets["target-a"]["client"] = _FakeClient()
        uploader._targets["target-a"]["queued"] = 1
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            image = root / "sample-1.jpg"
            metadata_path = root / "sample-1.json"
            _write_test_image(image, value=128)
            metadata = {
                "sample_id": "sample-1",
                "source": "live_aux_teacher_capture",
                "source_role": "classification_channel",
                "detection_algorithm": "gemini_sam",
                "detection_bbox_count": 1,
                "teacher_capture_crop_mode": "polygon_masked_zone",
                "teacher_capture_crop_signal": {"mean_gray": 50.0, "nonblack_ratio": 0.25},
            }
            metadata_path.write_text(json.dumps(metadata))
            job = {
                "operation": "upload",
                "target_id": "target-a",
                "session_id": "session-1",
                "session_name": "Session",
                "sample_id": "sample-1",
                "metadata": metadata,
                "image_path": str(image),
                "metadata_path": str(metadata_path),
                "queued_at": 1.0,
            }
            uploader._queued_job_keys.add(("upload", "target-a", "session-1", "sample-1"))

            uploader._process_job(job)

            updated = json.loads(metadata_path.read_text())

        self.assertEqual("uploaded", updated["hive_uploads"]["target-a"]["status"])
        self.assertEqual("remote-sample-1", updated["hive_uploads"]["target-a"]["remote_sample_id"])
        self.assertEqual(0, uploader._targets["target-a"]["queued"])
        self.assertFalse(uploader._queued_job_keys)

    def test_process_job_skips_black_primary_image(self) -> None:
        class _FakeClient:
            def upload_sample(self, **_kwargs):  # pragma: no cover - should not be called
                raise AssertionError("black image should not upload")

        uploader = self._make_uploader()
        uploader._targets["target-a"]["client"] = _FakeClient()
        uploader._targets["target-a"]["queued"] = 1
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            image = root / "sample-1.jpg"
            _write_test_image(image, value=0)
            job = {
                "operation": "upload",
                "target_id": "target-a",
                "session_id": "session-1",
                "session_name": "Session",
                "sample_id": "sample-1",
                "metadata": {"sample_id": "sample-1"},
                "image_path": str(image),
                "queued_at": 1.0,
            }
            uploader._queued_job_keys.add(("upload", "target-a", "session-1", "sample-1"))

            uploader._process_job(job)

        self.assertEqual(0, uploader._targets["target-a"]["queued"])
        self.assertEqual("skipped", uploader._recent_jobs[0]["status"])
        self.assertIn("too dark", uploader._recent_jobs[0]["message"])
        self.assertFalse(uploader._queued_job_keys)

    def test_teacher_sample_with_unmasked_crop_is_bad(self) -> None:
        metadata = {
            "source": "live_aux_teacher_capture",
            "source_role": "classification_channel",
            "detection_algorithm": "gemini_sam",
            "detection_bbox_count": 1,
            "teacher_capture_crop_mode": "detector_apply_zone",
            "teacher_capture_crop_signal": {"mean_gray": 120.0, "nonblack_ratio": 0.9},
        }

        state = teacher_state_from_metadata(metadata)

        self.assertEqual("bad_teacher_sample", state["state"])
        self.assertIn("polygon-masked", state["reason"])

    def test_teacher_sample_with_low_signal_is_bad(self) -> None:
        metadata = {
            "source": "live_aux_teacher_capture",
            "source_role": "classification_channel",
            "detection_algorithm": "gemini_sam",
            "detection_bbox_count": 1,
            "teacher_capture_crop_mode": "polygon_masked_zone",
            "teacher_capture_crop_signal": {"mean_gray": 0.5, "nonblack_ratio": 0.001},
        }

        state = teacher_state_from_metadata(metadata)

        self.assertEqual("bad_teacher_sample", state["state"])
        self.assertIn("too dark", state["reason"])

    def test_teacher_sample_with_clean_gemini_crop_is_ready(self) -> None:
        metadata = {
            "source": "live_aux_teacher_capture",
            "source_role": "classification_channel",
            "detection_algorithm": "gemini_sam",
            "detection_bbox_count": 1,
            "teacher_capture_crop_mode": "polygon_masked_zone",
            "teacher_capture_crop_signal": {"mean_gray": 50.0, "nonblack_ratio": 0.25},
        }

        self.assertEqual("teacher_ready", teacher_state_from_metadata(metadata)["state"])

    def test_teacher_negative_sample_with_clean_crop_is_ready(self) -> None:
        metadata = {
            "source": "live_aux_teacher_capture",
            "source_role": "classification_channel",
            "detection_algorithm": "gemini_sam",
            "detection_found": False,
            "detection_bbox_count": 0,
            "teacher_capture_negative": True,
            "teacher_capture_crop_mode": "polygon_masked_zone",
            "teacher_capture_crop_signal": {"mean_gray": 50.0, "nonblack_ratio": 0.25},
        }

        state = teacher_state_from_metadata(metadata)

        self.assertEqual("teacher_ready", state["state"])
        self.assertEqual("Gemini negative", state["label"])

    def test_gemini_detection_sample_type_is_teacher_detection(self) -> None:
        metadata = {
            "source_role": "classification_channel",
            "capture_reason": "rt_move_completed",
            "detection_algorithm": "gemini_sam",
            "detection_bbox_count": 1,
        }

        self.assertEqual("teacher_detection", sample_type_from_metadata(metadata))

    def test_gemini_zero_box_without_negative_marker_is_blocked(self) -> None:
        metadata = {
            "source": "live_aux_teacher_capture",
            "source_role": "classification_channel",
            "detection_algorithm": "gemini_sam",
            "detection_found": False,
            "detection_bbox_count": 0,
            "teacher_capture_crop_mode": "polygon_masked_zone",
            "teacher_capture_crop_signal": {"mean_gray": 50.0, "nonblack_ratio": 0.25},
        }

        self.assertEqual("no_teacher_detection", teacher_state_from_metadata(metadata)["state"])

    def test_queue_details_lists_waiting_jobs_with_teacher_state(self) -> None:
        uploader = self._make_uploader()
        uploader._queue.put(
            {
                "operation": "upload",
                "target_id": "target-a",
                "session_id": "session-1",
                "session_name": "Session",
                "sample_id": "sample-1",
                "metadata": {
                    "source": "live_aux_teacher_capture",
                    "source_role": "classification_channel",
                    "capture_reason": "rt_periodic_interval",
                    "detection_algorithm": "gemini_sam",
                    "detection_bbox_count": 2,
                    "teacher_capture_crop_mode": "polygon_masked_zone",
                    "teacher_capture_crop_signal": {
                        "mean_gray": 42.0,
                        "nonblack_ratio": 0.5,
                    },
                },
                "image_path": "/tmp/sample.jpg",
                "queued_at": 10.0,
            }
        )
        uploader._active_jobs["target-a"] = {
            "target_id": "target-a",
            "sample_id": "active-1",
            "status": "uploading",
        }
        uploader._recent_jobs.appendleft(
            {
                "target_id": "target-a",
                "sample_id": "done-1",
                "status": "uploaded",
            }
        )

        details = uploader.queue_details(target_ids=["target-a"], limit=10)

        self.assertEqual(1, len(details["targets"]))
        target = details["targets"][0]
        self.assertEqual("target-a", target["id"])
        self.assertEqual("sample-1", target["queued_jobs"][0]["sample_id"])
        self.assertEqual("teacher_ready", target["queued_jobs"][0]["teacher_state"])
        self.assertEqual("teacher_detection", target["queued_jobs"][0]["sample_type"])
        self.assertEqual("active-1", target["active_jobs"][0]["sample_id"])
        self.assertEqual("done-1", target["recent_jobs"][0]["sample_id"])


if __name__ == "__main__":
    unittest.main()
