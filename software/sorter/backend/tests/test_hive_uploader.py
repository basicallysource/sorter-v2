from collections import deque
import queue
import threading
import unittest

from server.hive_uploader import HiveUploader, SERVER_DOWN_BACKOFF_S, teacher_state_from_metadata


class HiveUploaderPurgeTests(unittest.TestCase):
    def _make_uploader(self) -> HiveUploader:
        uploader = HiveUploader.__new__(HiveUploader)
        uploader._queue = queue.Queue()
        uploader._lock = threading.Lock()
        uploader._active_jobs = {}
        uploader._recent_jobs = deque(maxlen=120)
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
        self.assertEqual("active-1", target["active_jobs"][0]["sample_id"])
        self.assertEqual("done-1", target["recent_jobs"][0]["sample_id"])


if __name__ == "__main__":
    unittest.main()
