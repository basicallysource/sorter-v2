from __future__ import annotations

import os
import tempfile
import unittest
from dataclasses import dataclass
from pathlib import Path
from unittest import mock

import numpy as np

import blob_manager
from local_state import (
    get_piece_dossier,
    initialize_local_state,
    start_new_sorting_session,
)
from rt.perception.matrix_shot import MatrixShotConfig, MatrixShotRecorder


@dataclass
class _Frame:
    raw: np.ndarray
    timestamp: float


class _Capture:
    def __init__(self, frames: list[_Frame]) -> None:
        self._frames = frames

    def drain_ring_buffer(self, max_frames: int) -> list[_Frame]:
        if max_frames <= 0:
            return []
        return self._frames[-max_frames:]


class _CameraService:
    def __init__(self, captures: dict[str, _Capture]) -> None:
        self._captures = captures

    def get_capture_thread_for_role(self, role: str) -> _Capture | None:
        return self._captures.get(role)


class MatrixShotTests(unittest.TestCase):
    def setUp(self) -> None:
        self._old_machine_params = os.environ.get("MACHINE_SPECIFIC_PARAMS_PATH")
        self._old_local_state_db = os.environ.get("LOCAL_STATE_DB_PATH")
        self._tmpdir = tempfile.TemporaryDirectory()
        tmp_dir = Path(self._tmpdir.name)
        self._blob_dir = tmp_dir / "blob"
        self._machine_params_path = tmp_dir / "machine_params.toml"
        self._local_state_db_path = tmp_dir / "local_state.sqlite"
        self._machine_params_path.write_text(
            '[machine]\nnickname = "MatrixShotBench"\n',
            encoding="utf-8",
        )
        os.environ["MACHINE_SPECIFIC_PARAMS_PATH"] = str(self._machine_params_path)
        os.environ["LOCAL_STATE_DB_PATH"] = str(self._local_state_db_path)
        self._blob_patch = mock.patch.object(blob_manager, "BLOB_DIR", self._blob_dir)
        self._blob_patch.start()
        initialize_local_state()
        start_new_sorting_session(reason="matrix_shot_test")

    def tearDown(self) -> None:
        self._blob_patch.stop()
        if self._old_machine_params is None:
            os.environ.pop("MACHINE_SPECIFIC_PARAMS_PATH", None)
        else:
            os.environ["MACHINE_SPECIFIC_PARAMS_PATH"] = self._old_machine_params
        if self._old_local_state_db is None:
            os.environ.pop("LOCAL_STATE_DB_PATH", None)
        else:
            os.environ["LOCAL_STATE_DB_PATH"] = self._old_local_state_db
        self._tmpdir.cleanup()

    def test_capture_now_persists_matrix_shot_manifest_and_jpegs(self) -> None:
        trigger = 1_000.0
        # Present on purpose: default Matrix-Shot must ignore C3 and use C4 only.
        c3_frames = [
            _Frame(
                np.full((80, 160, 3), 40 + idx, dtype=np.uint8),
                trigger - 1.5 + idx * 0.25,
            )
            for idx in range(7)
        ]
        c4_frames = [
            _Frame(
                np.full((60, 120, 3), 120 + idx, dtype=np.uint8),
                trigger - 0.9 + idx * 0.2,
            )
            for idx in range(6)
        ]
        service = _CameraService(
            {
                "c_channel_3": _Capture(c3_frames),
                "carousel": _Capture(c4_frames),
            }
        )
        recorder = MatrixShotRecorder(
            service,
            config=MatrixShotConfig(
                max_frames_per_role=3,
                max_width_px=64,
            ),
        )
        try:
            manifest = recorder.capture_now(
                piece_uuid="piece-matrix",
                trigger_wall_ts=trigger,
            )
        finally:
            recorder.close()

        self.assertIsNotNone(manifest)
        assert manifest is not None
        self.assertEqual("captured", manifest["status"])
        self.assertEqual(3, manifest["frame_count"])
        frames = manifest["frames"]
        self.assertEqual(
            sorted(frame["captured_ts"] for frame in frames),
            [frame["captured_ts"] for frame in frames],
        )
        self.assertEqual({"carousel"}, {frame["role"] for frame in frames})
        for frame in frames:
            jpeg_path = frame["jpeg_path"]
            self.assertIn("/matrix_", jpeg_path)
            self.assertTrue((self._blob_dir / jpeg_path).is_file())
            self.assertLessEqual(frame["width"], 64)

        dossier = get_piece_dossier("piece-matrix")
        self.assertIsNotNone(dossier)
        assert dossier is not None
        self.assertEqual("Matrix-Shot", dossier["matrix_shot"]["name"])
        self.assertEqual(frames, dossier["matrix_shot"]["frames"])


if __name__ == "__main__":
    unittest.main()
