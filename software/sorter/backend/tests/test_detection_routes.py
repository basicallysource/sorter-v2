import os
import tempfile
import unittest
from pathlib import Path

from fastapi import HTTPException

from server import shared_state
from server.routers import detection


class _FakeVisionManager:
    def __init__(self) -> None:
        self.calls: list[tuple[str, bool]] = []

    def debugFeederDetection(self, role: str, *, include_capture: bool = False):
        self.calls.append((role, include_capture))
        return {
            "camera": role,
            "algorithm": "gemini_sam",
            "found": False,
            "message": "No piece in frame.",
            "frame_resolution": [1280, 720],
            "candidate_bboxes": [],
            "bbox_count": 0,
            "bbox": None,
            "zone_bbox": None,
        }

    def getFeederOpenRouterModel(self) -> str:
        return "google/gemini-3-flash-preview"


class DetectionRouteTests(unittest.TestCase):
    def setUp(self) -> None:
        self._old_vision_manager = shared_state.vision_manager

    def tearDown(self) -> None:
        shared_state.vision_manager = self._old_vision_manager

    def test_debug_feeder_detection_accepts_classification_channel_role(self) -> None:
        fake_vision = _FakeVisionManager()
        shared_state.vision_manager = fake_vision

        payload = detection.debug_feeder_detection("carousel")

        self.assertTrue(payload["ok"])
        self.assertEqual("classification_channel", payload["camera"])
        self.assertEqual([("carousel", True)], fake_vision.calls)

    def test_debug_feeder_detection_rejects_unknown_role(self) -> None:
        shared_state.vision_manager = _FakeVisionManager()

        with self.assertRaises(HTTPException) as excinfo:
            detection.debug_feeder_detection("nope")

        self.assertEqual(400, excinfo.exception.status_code)
        self.assertEqual("Unsupported feeder role.", excinfo.exception.detail)


class _TrackDetailVision:
    """Minimal vision-manager stub: only getFeederTrackHistoryDetail."""

    def __init__(self, detail_by_gid: dict[int, dict | None] | None = None) -> None:
        self._details = detail_by_gid or {}
        self.calls: list[int] = []

    def getFeederTrackHistoryDetail(self, global_id: int):
        self.calls.append(int(global_id))
        return self._details.get(int(global_id))


class _FakeRuntimeStats:
    def __init__(self, data: dict | None = None) -> None:
        self._data = data or {}

    def lookupKnownObject(self, uuid: str):
        return self._data.get(uuid)


class _FakeGlobalConfig:
    def __init__(self, runtime_stats) -> None:
        self.runtime_stats = runtime_stats


class TrackedPieceDetailRouteTests(unittest.TestCase):
    """Phase 5: GET /api/tracked/pieces(/{uuid}) DB-first behavior."""

    def setUp(self) -> None:
        self._old_machine_params = os.environ.get("MACHINE_SPECIFIC_PARAMS_PATH")
        self._old_local_state_db = os.environ.get("LOCAL_STATE_DB_PATH")
        self._tmpdir = tempfile.TemporaryDirectory()
        tmp_dir = Path(self._tmpdir.name)
        self.machine_params_path = tmp_dir / "machine_params.toml"
        self.local_state_db_path = tmp_dir / "local_state.sqlite"
        self.machine_params_path.write_text(
            "[machine]\nnickname = \"DetailBench\"\n",
            encoding="utf-8",
        )
        os.environ["MACHINE_SPECIFIC_PARAMS_PATH"] = str(self.machine_params_path)
        os.environ["LOCAL_STATE_DB_PATH"] = str(self.local_state_db_path)

        self._old_vision_manager = shared_state.vision_manager
        self._old_gc_ref = shared_state.gc_ref
        shared_state.vision_manager = None
        shared_state.gc_ref = None

        # Fresh SQLite + active session for every test.
        from local_state import initialize_local_state, start_new_sorting_session

        initialize_local_state()
        start_new_sorting_session(reason="tracked_detail_tests")

    def tearDown(self) -> None:
        shared_state.vision_manager = self._old_vision_manager
        shared_state.gc_ref = self._old_gc_ref

        if self._old_machine_params is None:
            os.environ.pop("MACHINE_SPECIFIC_PARAMS_PATH", None)
        else:
            os.environ["MACHINE_SPECIFIC_PARAMS_PATH"] = self._old_machine_params
        if self._old_local_state_db is None:
            os.environ.pop("LOCAL_STATE_DB_PATH", None)
        else:
            os.environ["LOCAL_STATE_DB_PATH"] = self._old_local_state_db

        self._tmpdir.cleanup()

    def _seed_piece(
        self,
        piece_uuid: str,
        tracked_global_id: int,
        *,
        segment_count: int = 0,
    ) -> None:
        from local_state import remember_piece_dossier, remember_piece_segment

        remember_piece_dossier(
            {
                "uuid": piece_uuid,
                "tracked_global_id": tracked_global_id,
                "created_at": 100.0,
                "updated_at": 110.0,
                "stage": "created",
                "classification_status": "pending",
            }
        )
        for seq in range(segment_count):
            remember_piece_segment(
                piece_uuid,
                "c_channel_3" if seq == 0 else "carousel",
                seq,
                {
                    "tracked_global_id": tracked_global_id,
                    "first_seen_ts": 100.0 + seq,
                    "last_seen_ts": 105.0 + seq,
                    "hit_count": 4 + seq,
                    "path": [[100.0 + seq, 300.0, 240.0]],
                    "sector_snapshots": [
                        {
                            "captured_ts": 100.5 + seq,
                            "start_angle_deg": seq * 10.0,
                            "end_angle_deg": seq * 10.0 + 20.0,
                            "jpeg_path": f"piece_crops/{piece_uuid}/seg{seq}/wedge_000.jpg",
                            "piece_jpeg_path": f"piece_crops/{piece_uuid}/seg{seq}/piece_000.jpg",
                            "bbox": {"x": seq, "y": seq, "w": 10, "h": 10},
                        }
                    ],
                    "recognize_result": None,
                },
            )

    def test_tracked_piece_detail_serves_persisted_segments_after_restart(self) -> None:
        """Dossier + segments in DB; vision manager knows nothing (restart)."""
        from server.api import get_tracked_piece_detail

        self._seed_piece("piece-persisted", 4242, segment_count=2)
        # Simulate restart: no live detail for this gid.
        shared_state.vision_manager = _TrackDetailVision({4242: None})

        resp = get_tracked_piece_detail("piece-persisted")

        self.assertEqual("piece-persisted", resp.get("uuid"))
        self.assertIn("track_detail", resp)
        track_detail = resp["track_detail"]
        self.assertFalse(track_detail["live"])
        self.assertEqual(2, len(track_detail["segments"]))
        self.assertEqual([0, 1], [seg["sequence"] for seg in track_detail["segments"]])

    def test_tracked_piece_detail_merges_live_tracker_detail_when_available(self) -> None:
        from server.api import get_tracked_piece_detail

        self._seed_piece("piece-live", 7777, segment_count=1)
        live_detail = {
            "global_id": 7777,
            "live": True,
            "segments": [
                {
                    "source_role": "c_channel_3",
                    "sequence": 0,
                    "first_seen_ts": 100.0,
                    "last_seen_ts": 108.0,
                    "hit_count": 9,
                },
                {
                    "source_role": "carousel",
                    "sequence": 1,
                    "first_seen_ts": 109.0,
                    "last_seen_ts": 112.0,
                    "hit_count": 5,
                },
            ],
            "roles": ["c_channel_3", "carousel"],
            "segment_count": 2,
            "finished_at": 112.0,
        }
        shared_state.vision_manager = _TrackDetailVision({7777: live_detail})

        resp = get_tracked_piece_detail("piece-live")

        self.assertIn("track_detail", resp)
        merged = resp["track_detail"]
        self.assertTrue(merged["live"])
        # Live detail's segments win on merge.
        self.assertEqual(2, merged["segment_count"])
        self.assertEqual(112.0, merged["finished_at"])
        self.assertEqual(["c_channel_3", "carousel"], merged["roles"])

    def test_tracked_piece_detail_falls_back_to_lookup_when_no_dossier(self) -> None:
        from server.api import get_tracked_piece_detail

        # No DB dossier — hit the runtime-LRU fallback.
        shared_state.gc_ref = _FakeGlobalConfig(
            runtime_stats=_FakeRuntimeStats(
                {"piece-lru": {"uuid": "piece-lru", "tracked_global_id": 123}}
            )
        )
        shared_state.vision_manager = _TrackDetailVision({123: None})

        resp = get_tracked_piece_detail("piece-lru")

        self.assertEqual("piece-lru", resp.get("uuid"))
        self.assertEqual(123, resp.get("tracked_global_id"))
        # No DB segments — track_detail is absent for bare-LRU hits.
        self.assertNotIn("track_detail", resp)

    def test_tracked_piece_detail_returns_404_when_truly_unknown(self) -> None:
        from server.api import get_tracked_piece_detail

        shared_state.gc_ref = _FakeGlobalConfig(runtime_stats=_FakeRuntimeStats({}))
        shared_state.vision_manager = _TrackDetailVision({})

        with self.assertRaises(HTTPException) as excinfo:
            get_tracked_piece_detail("definitely-not-there")

        self.assertEqual(404, excinfo.exception.status_code)

    def test_tracked_pieces_list_has_track_segments_flag(self) -> None:
        from server.api import get_tracked_pieces

        self._seed_piece("piece-has-segs", 501, segment_count=3)
        self._seed_piece("piece-no-segs", 502, segment_count=0)

        resp = get_tracked_pieces()
        items = resp.get("items", [])
        flags = {
            item.get("uuid"): item.get("has_track_segments")
            for item in items
            if isinstance(item, dict)
        }
        self.assertIn("piece-has-segs", flags)
        self.assertIn("piece-no-segs", flags)
        self.assertTrue(flags["piece-has-segs"])
        self.assertFalse(flags["piece-no-segs"])


if __name__ == "__main__":
    unittest.main()
