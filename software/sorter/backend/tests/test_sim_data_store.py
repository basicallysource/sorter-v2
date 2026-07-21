import gzip
import importlib
import json
import os
import tempfile
import unittest
from pathlib import Path


class SimDataStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        os.environ["LOCAL_STATE_DB_PATH"] = os.path.join(self._tmp.name, "state.sqlite")
        import local_state
        import sim_data_store

        importlib.reload(local_state)
        importlib.reload(sim_data_store)
        self.store = sim_data_store

    def tearDown(self) -> None:
        self.store.endSegment()
        os.environ.pop("LOCAL_STATE_DB_PATH", None)
        self._tmp.cleanup()
        import local_state
        import sim_data_store

        importlib.reload(local_state)
        importlib.reload(sim_data_store)

    def test_record_without_segment_is_noop(self) -> None:
        self.store.record({"type": "state", "ch": 2})
        self.assertEqual(self.store.getMaxSegmentId(), 0)
        self.assertFalse(self.store.segmentOpen())

    def test_segment_roundtrip(self) -> None:
        meta = {
            "t": 123.0,
            "machine_setup": "classification_channel",
            "feeder_mode": "PULSE_PERCEPTION_REV01",
            "classification_mode": "TWO_PIECE_STATE_MACHINE_REV01",
            "autotune": {"mode": "background"},
        }
        self.assertTrue(self.store.beginSegment(meta))
        self.assertFalse(self.store.beginSegment(meta))
        self.store.record({"type": "state", "ch": 2, "pieces": [[1.5, 3, 1, 0, 0, 10, 10, 7]]})
        self.store.record({"type": "cmd", "stepper": "stepper_1", "deg": 30.0})
        segment_id = self.store.endSegment()
        self.assertEqual(segment_id, 1)
        self.assertIsNone(self.store.endSegment())

        rows = self.store.listSegmentsAfter(0, 10)
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row["records"], 3)
        self.assertEqual(row["machine_setup"], "classification_channel")
        self.assertEqual(row["feeder_mode"], "PULSE_PERCEPTION_REV01")
        self.assertEqual(row["autotune_mode"], "background")
        self.assertFalse(row["evicted_locally"])

        path = self.store.getSegmentFileById(segment_id)
        self.assertIsNotNone(path)
        with gzip.open(path, "rt", encoding="utf-8") as handle:
            lines = [json.loads(line) for line in handle]
        self.assertEqual(len(lines), 3)
        self.assertEqual(lines[0]["type"], "meta")
        self.assertEqual(lines[0]["feeder_mode"], "PULSE_PERCEPTION_REV01")
        self.assertEqual(lines[1]["type"], "state")
        self.assertEqual(lines[2]["type"], "cmd")

        self.assertEqual(self.store.getMaxSegmentId(), 1)
        self.store.markSyncedUpTo(1, 999.0)
        self.assertEqual(self.store.listSegmentsAfter(1, 10), [])

    def test_orphan_recovery(self) -> None:
        self.store.beginSegment({"t": 1.0, "feeder_mode": "PULSE_PERCEPTION_REV01"})
        self.store.record({"type": "state", "ch": 3})
        self.store.flush()
        # Simulate a crash: forget the active segment without closing it.
        with self.store._write_lock:
            handle = self.store._active_file
            self.store._active_file = None
            self.store._active_path = None
        handle.close()

        recovered = self.store.recoverOrphanedSegments()
        self.assertEqual(recovered, 1)
        rows = self.store.listSegmentsAfter(0, 10)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["feeder_mode"], "PULSE_PERCEPTION_REV01")
        self.assertEqual(rows[0]["records"], 2)
        self.assertFalse(any(Path(self.store._active_dir()).glob("seg_*.jsonl")))


if __name__ == "__main__":
    unittest.main()
