import base64
import os
import tempfile
import time
import unittest

import piece_image_store


FAKE_JPEG = b"\xff\xd8\xff\xe0" + b"x" * 200 + b"\xff\xd9"
FAKE_JPEG_B64 = base64.b64encode(FAKE_JPEG).decode("utf-8")


def makePayload(piece_uuid: str, n_images: int) -> dict:
    return {
        "uuid": piece_uuid,
        "recognition_image_set": [
            {
                "image": FAKE_JPEG_B64,
                "source": "c4_burst",
                "channel": 4,
                "ts": 1000.0 + i,
                "created_at": 1000.0 + i,
                "sharpness": 50.0 + i,
            }
            for i in range(n_images)
        ],
    }


class PieceImageStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self._old_db = os.environ.get("LOCAL_STATE_DB_PATH")
        self._tmpdir = tempfile.TemporaryDirectory()
        os.environ["LOCAL_STATE_DB_PATH"] = os.path.join(self._tmpdir.name, "state.sqlite")
        piece_image_store._initialized = False
        # Keep the background worker out of tests: mark it started so enqueue
        # never spawns it, then drain the queue synchronously via drainQueue().
        piece_image_store._worker_started.set()
        with piece_image_store._seen_lock:
            piece_image_store._seen_counts.clear()
            piece_image_store._seen_order.clear()
            piece_image_store._flags_done.clear()

    def tearDown(self) -> None:
        if self._old_db is None:
            os.environ.pop("LOCAL_STATE_DB_PATH", None)
        else:
            os.environ["LOCAL_STATE_DB_PATH"] = self._old_db
        piece_image_store._initialized = False
        self._tmpdir.cleanup()

    def drainQueue(self) -> None:
        while True:
            try:
                kind, piece_uuid, payload = piece_image_store._queue.get_nowait()
            except Exception:
                return
            if kind == "image":
                seq, item = payload
                piece_image_store._writeImage(piece_uuid, seq, item)
            elif kind == "flags":
                piece_image_store._updateImageFlags(piece_uuid, payload)

    def test_writes_files_and_rows(self) -> None:
        piece_image_store.enqueueKnownObjectImages(makePayload("piece-a", 3))
        self.drainQueue()

        rows = piece_image_store.listPieceImages("piece-a")
        self.assertEqual(len(rows), 3)
        self.assertEqual([r["seq"] for r in rows], [0, 1, 2])
        self.assertTrue(all(r["available_locally"] for r in rows))
        self.assertTrue(all(not r["synced"] for r in rows))
        self.assertEqual(rows[0]["bytes"], len(FAKE_JPEG))

        path = piece_image_store.getImageFile("piece-a", rows[0]["id"])
        assert path is not None
        self.assertEqual(path.read_bytes(), FAKE_JPEG)

    def test_cumulative_observations_write_each_image_once(self) -> None:
        piece_image_store.enqueueKnownObjectImages(makePayload("piece-b", 2))
        piece_image_store.enqueueKnownObjectImages(makePayload("piece-b", 2))
        piece_image_store.enqueueKnownObjectImages(makePayload("piece-b", 5))
        self.drainQueue()

        rows = piece_image_store.listPieceImages("piece-b")
        self.assertEqual(len(rows), 5)
        self.assertEqual([r["seq"] for r in rows], [0, 1, 2, 3, 4])

    def test_retention_evicts_oldest_and_keeps_rows(self) -> None:
        for i in range(4):
            payload = makePayload(f"piece-{i}", 1)
            payload["recognition_image_set"][0]["created_at"] = 1000.0 + i
            piece_image_store.enqueueKnownObjectImages(payload)
        self.drainQueue()

        old_cap = piece_image_store._MAX_TOTAL_BYTES
        piece_image_store._MAX_TOTAL_BYTES = len(FAKE_JPEG) * 2
        try:
            piece_image_store._retentionSweep()
        finally:
            piece_image_store._MAX_TOTAL_BYTES = old_cap

        live = [
            r
            for i in range(4)
            for r in piece_image_store.listPieceImages(f"piece-{i}")
            if r["available_locally"]
        ]
        evicted = [
            r
            for i in range(4)
            for r in piece_image_store.listPieceImages(f"piece-{i}")
            if not r["available_locally"]
        ]
        self.assertEqual(len(live), 2)
        self.assertEqual(len(evicted), 2)
        self.assertEqual(sorted(r["created_at"] for r in evicted), [1000.0, 1001.0])
        for r in evicted:
            self.assertIsNone(piece_image_store.getImageFile(r["piece_uuid"], r["id"]))

    def test_retention_prefers_synced_files(self) -> None:
        for i in range(3):
            payload = makePayload(f"piece-{i}", 1)
            payload["recognition_image_set"][0]["created_at"] = 1000.0 + i
            piece_image_store.enqueueKnownObjectImages(payload)
        self.drainQueue()

        # Mark the NEWEST as synced; it should be evicted before older unsynced.
        newest = piece_image_store.listPieceImages("piece-2")[0]
        with piece_image_store._connection() as conn:
            conn.execute(
                "UPDATE piece_images SET synced_at = ?, hive_image_id = 'h1' WHERE id = ?",
                (time.time(), newest["id"]),
            )
            conn.commit()

        old_cap = piece_image_store._MAX_TOTAL_BYTES
        piece_image_store._MAX_TOTAL_BYTES = len(FAKE_JPEG) * 2
        try:
            piece_image_store._retentionSweep()
        finally:
            piece_image_store._MAX_TOTAL_BYTES = old_cap

        synced_row = piece_image_store.listPieceImages("piece-2")[0]
        self.assertFalse(synced_row["available_locally"])
        self.assertTrue(synced_row["synced"])
        self.assertTrue(piece_image_store.listPieceImages("piece-0")[0]["available_locally"])
        self.assertTrue(piece_image_store.listPieceImages("piece-1")[0]["available_locally"])

    def test_flags_settle_after_classification(self) -> None:
        payload = makePayload("piece-f", 3)
        piece_image_store.enqueueKnownObjectImages(payload)
        self.drainQueue()
        rows = piece_image_store.listPieceImages("piece-f")
        self.assertTrue(all(not r["used"] and not r["excluded_from_result"] for r in rows))

        payload["recognition_image_set"][0]["used"] = True
        payload["recognition_image_set"][1]["excluded_from_result"] = True
        payload["recognition_image_set"][1]["score"] = 0.87
        piece_image_store.enqueueKnownObjectImages(payload)
        self.drainQueue()

        rows = piece_image_store.listPieceImages("piece-f")
        self.assertEqual(len(rows), 3)
        self.assertTrue(rows[0]["used"])
        self.assertTrue(rows[1]["excluded_from_result"])
        self.assertAlmostEqual(rows[1]["score"], 0.87)
        self.assertFalse(rows[2]["used"])

        # Flags flush once per piece — a later observation doesn't re-enqueue.
        piece_image_store.enqueueKnownObjectImages(payload)
        self.assertTrue(piece_image_store._queue.empty())

    def test_stats(self) -> None:
        piece_image_store.enqueueKnownObjectImages(makePayload("piece-s", 2))
        self.drainQueue()
        stats = piece_image_store.getStats()
        self.assertEqual(stats["live_files"], 2)
        self.assertEqual(stats["live_bytes"], len(FAKE_JPEG) * 2)
        self.assertEqual(stats["total_rows"], 2)

    def test_ignores_malformed_payloads(self) -> None:
        piece_image_store.enqueueKnownObjectImages({})
        piece_image_store.enqueueKnownObjectImages({"uuid": "x", "recognition_image_set": None})
        piece_image_store.enqueueKnownObjectImages(
            {"uuid": "y", "recognition_image_set": [{"image": ""}, "not-a-dict"]}
        )
        self.drainQueue()
        self.assertEqual(piece_image_store.listPieceImages("x"), [])
        self.assertEqual(piece_image_store.listPieceImages("y"), [])


if __name__ == "__main__":
    unittest.main()
