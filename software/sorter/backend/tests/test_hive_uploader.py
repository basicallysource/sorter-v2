import queue
import threading
import unittest

from server.hive_uploader import HiveUploader, SERVER_DOWN_BACKOFF_S


class HiveUploaderPurgeTests(unittest.TestCase):
    def _make_uploader(self) -> HiveUploader:
        uploader = HiveUploader.__new__(HiveUploader)
        uploader._queue = queue.Queue()
        uploader._lock = threading.Lock()
        uploader._targets = {
            "target-a": {
                "id": "target-a",
                "name": "Target A",
                "queued": 2,
                "retry_after": 30.0,
                "backoff_s": 45.0,
                "last_error": "Retrying sample sync: boom",
            },
            "target-b": {
                "id": "target-b",
                "name": "Target B",
                "queued": 1,
                "retry_after": 0.0,
                "backoff_s": SERVER_DOWN_BACKOFF_S,
                "last_error": None,
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


if __name__ == "__main__":
    unittest.main()
