"""The media retention sweeps must never hold the SQLite write lock while they
touch the filesystem. Regression tests for the starvation where one sweep
pinned the lock for 10-20 minutes and every other writer of
local_state.sqlite (including the control loop) timed out."""

import base64
import os
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import channel_crop_store
import piece_image_store


FAKE_JPEG = b"\xff\xd8\xff\xe0" + b"x" * 200 + b"\xff\xd9"
FAKE_JPEG_B64 = base64.b64encode(FAKE_JPEG).decode("utf-8")


def _lockProbingUnlink(db_path: str, results: list[bool]):
    # Wraps Path.unlink: at the moment of each unlink, try to take the write
    # lock from a second connection with no busy timeout. True means the lock
    # was free, i.e. the sweep is not inside a transaction while deleting.
    original = Path.unlink

    def unlink(self: Path, missing_ok: bool = False) -> None:
        conn = sqlite3.connect(db_path, timeout=0)
        try:
            conn.execute("PRAGMA busy_timeout = 0")
            try:
                conn.execute("BEGIN IMMEDIATE")
                conn.execute("ROLLBACK")
                results.append(True)
            except sqlite3.OperationalError:
                results.append(False)
        finally:
            conn.close()
        return original(self, missing_ok=missing_ok)

    return unlink


class _TempStateDb(unittest.TestCase):
    def setUp(self) -> None:
        self._old_db = os.environ.get("LOCAL_STATE_DB_PATH")
        self._tmpdir = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self._tmpdir.name, "state.sqlite")
        os.environ["LOCAL_STATE_DB_PATH"] = self.db_path
        piece_image_store._initialized = False
        piece_image_store._worker_started.set()
        channel_crop_store._initialized = False
        channel_crop_store._worker_started.set()

    def tearDown(self) -> None:
        if self._old_db is None:
            os.environ.pop("LOCAL_STATE_DB_PATH", None)
        else:
            os.environ["LOCAL_STATE_DB_PATH"] = self._old_db
        piece_image_store._initialized = False
        channel_crop_store._initialized = False
        self._tmpdir.cleanup()


class ChannelCropSweepTests(_TempStateDb):
    def _seed(self, n: int) -> None:
        for i in range(n):
            channel_crop_store._writeCrop(
                FAKE_JPEG,
                {"channel": 3, "ts": 1000.0 + i, "created_at": 1000.0 + i, "track_id": i,
                 "bbox": (0, 0, 10, 10), "zone_code": 2, "sharpness": 50.0},
            )

    def _sweepWithCap(self, cap_files: int, probe: list[bool] | None = None) -> None:
        old_cap = channel_crop_store._MAX_TOTAL_BYTES
        channel_crop_store._MAX_TOTAL_BYTES = len(FAKE_JPEG) * cap_files
        try:
            if probe is None:
                channel_crop_store._retentionSweep()
            else:
                with mock.patch.object(Path, "unlink", _lockProbingUnlink(self.db_path, probe)):
                    channel_crop_store._retentionSweep()
        finally:
            channel_crop_store._MAX_TOTAL_BYTES = old_cap

    def test_write_lock_is_free_while_files_are_unlinked(self) -> None:
        self._seed(4)
        probe: list[bool] = []
        self._sweepWithCap(2, probe)
        self.assertEqual(probe, [True, True])
        rows = channel_crop_store.listCropsAfter(0, 10)
        self.assertEqual([r["evicted_locally"] for r in rows], [True, True, False, False])
        self.assertIsNone(channel_crop_store.getCropFileById(rows[0]["id"]))
        self.assertIsNotNone(channel_crop_store.getCropFileById(rows[3]["id"]))

    def test_rows_whose_file_is_already_gone_are_still_tombstoned(self) -> None:
        self._seed(3)
        oldest = channel_crop_store.listCropsAfter(0, 1)[0]
        channel_crop_store.getCropFileById(oldest["id"]).unlink()
        self._sweepWithCap(2)
        rows = channel_crop_store.listCropsAfter(0, 10)
        self.assertEqual([r["evicted_locally"] for r in rows], [True, False, False])


class PieceImageSweepTests(_TempStateDb):
    def _seed(self, n: int) -> None:
        for i in range(n):
            piece_image_store._writeImage(
                f"piece-{i}", 0,
                {"image": FAKE_JPEG_B64, "source": "c4_burst", "channel": 4,
                 "ts": 1000.0 + i, "created_at": 1000.0 + i, "sharpness": 50.0},
            )

    def _sweepWithCap(self, cap_files: int, probe: list[bool] | None = None) -> None:
        old_cap = piece_image_store._MAX_TOTAL_BYTES
        piece_image_store._MAX_TOTAL_BYTES = len(FAKE_JPEG) * cap_files
        try:
            if probe is None:
                piece_image_store._retentionSweep()
            else:
                with mock.patch.object(Path, "unlink", _lockProbingUnlink(self.db_path, probe)):
                    piece_image_store._retentionSweep()
        finally:
            piece_image_store._MAX_TOTAL_BYTES = old_cap

    def _available(self, n: int) -> list[bool]:
        return [piece_image_store.listPieceImages(f"piece-{i}")[0]["available_locally"] for i in range(n)]

    def test_write_lock_is_free_while_files_are_unlinked(self) -> None:
        self._seed(4)
        probe: list[bool] = []
        self._sweepWithCap(2, probe)
        self.assertEqual(probe, [True, True])
        self.assertEqual(self._available(4), [False, False, True, True])
        evicted = piece_image_store.listPieceImages("piece-0")[0]
        self.assertIsNone(piece_image_store.getImageFile("piece-0", evicted["id"]))

    def test_rows_whose_file_is_already_gone_are_still_tombstoned(self) -> None:
        self._seed(3)
        oldest = piece_image_store.listPieceImages("piece-0")[0]
        piece_image_store.getImageFile("piece-0", oldest["id"]).unlink()
        self._sweepWithCap(2)
        self.assertEqual(self._available(3), [False, True, True])


if __name__ == "__main__":
    unittest.main()
