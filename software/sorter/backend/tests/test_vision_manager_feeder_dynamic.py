import unittest
import sys
import types
from types import SimpleNamespace
from unittest import mock

import numpy as np

analysis_stub = types.ModuleType("subsystems.feeder.analysis")
analysis_stub.parseSavedChannelArcZones = lambda *args, **kwargs: None
analysis_stub.zoneSectionsForChannel = lambda *args, **kwargs: (set(), set())
feeder_stub = types.ModuleType("subsystems.feeder")
feeder_stub.analysis = analysis_stub
subsystems_stub = types.ModuleType("subsystems")
subsystems_stub.feeder = feeder_stub
sys.modules.setdefault("subsystems", subsystems_stub)
sys.modules.setdefault("subsystems.feeder", feeder_stub)
sys.modules.setdefault("subsystems.feeder.analysis", analysis_stub)

from vision.vision_manager import VisionManager
from vision.detection_registry import DetectionResult
from vision.tracking.history import PieceHistoryBuffer, SectorSnapshot, TrackSegment


class VisionManagerFeederDynamicTests(unittest.TestCase):
    def test_get_feeder_dynamic_detection_does_not_force_gemini_from_live_render(self) -> None:
        vm = VisionManager.__new__(VisionManager)
        frame = SimpleNamespace(timestamp=123.0, raw=np.zeros((8, 8, 3), dtype=np.uint8))
        compute_calls: list[str] = []
        updates: list[tuple[str, float]] = []

        vm.getCaptureThreadForRole = lambda role: SimpleNamespace(latest_frame=frame)
        vm.getFeederDetectionAlgorithm = lambda role=None: "gemini_sam"
        vm._getCachedFeederDynamicDetection = lambda role, timestamp: None
        vm._computeFeederGeminiDetection = (
            lambda role, current_frame, force_call=False: compute_calls.append(role)
        )
        vm._feeder_dynamic_detection_cache = {}
        vm._feeder_track_cache = {}
        vm._updateFeederTracker = (
            lambda role, current_detection, timestamp, frame_bgr=None: updates.append(
                (role, float(timestamp))
            )
        )

        result = VisionManager._getFeederDynamicDetection(vm, "carousel", force=False)

        self.assertIsNone(result)
        self.assertEqual([], compute_calls)
        self.assertEqual([], updates)

    def test_get_feeder_dynamic_detection_updates_tracker_from_same_frame_cache(self) -> None:
        vm = VisionManager.__new__(VisionManager)
        frame = SimpleNamespace(timestamp=123.0, raw=np.zeros((8, 8, 3), dtype=np.uint8))
        detection = SimpleNamespace(bboxes=[(1, 1, 4, 4)], score=0.9)
        updates: list[tuple[str, object, float]] = []

        vm.getCaptureThreadForRole = lambda role: SimpleNamespace(latest_frame=frame)
        vm.getFeederDetectionAlgorithm = lambda role=None: "gemini_sam"
        vm._getCachedFeederDynamicDetection = lambda role, timestamp: detection
        vm._computeFeederGeminiDetection = lambda role, current_frame, force_call=False: None
        vm._feeder_dynamic_detection_cache = {"c_channel_2": (123.0, detection)}
        vm._feeder_track_cache = {}
        vm._updateFeederTracker = (
            lambda role, current_detection, timestamp, frame_bgr=None: updates.append(
                (role, current_detection, float(timestamp))
            )
        )

        result = VisionManager._getFeederDynamicDetection(vm, "c_channel_2", force=False)

        self.assertEqual(((1, 1, 4, 4),), result.bboxes)
        self.assertEqual((1, 1, 4, 4), result.bbox)
        self.assertEqual([("c_channel_2", result, 123.0)], updates)

    def test_refresh_auxiliary_detections_ticks_cached_trackers_and_refreshes_one_role_per_cycle(self) -> None:
        vm = VisionManager.__new__(VisionManager)
        raw = np.zeros((6, 6, 3), dtype=np.uint8)
        captures = {
            "c_channel_2": SimpleNamespace(latest_frame=SimpleNamespace(timestamp=10.0, raw=raw)),
            "c_channel_3": SimpleNamespace(latest_frame=SimpleNamespace(timestamp=11.0, raw=raw)),
            "carousel": SimpleNamespace(latest_frame=SimpleNamespace(timestamp=12.0, raw=raw)),
        }
        detections = {
            "c_channel_2": SimpleNamespace(bboxes=[(0, 0, 1, 1)], score=0.8),
            "carousel": SimpleNamespace(bboxes=[(1, 1, 2, 2)], score=0.7),
        }
        updates: list[tuple[str, float]] = []
        compute_calls: list[str] = []

        vm._feederTrackerRoles = lambda: ("c_channel_2", "c_channel_3", "carousel")
        vm.getFeederDetectionAlgorithm = lambda role=None: {
            "c_channel_2": "gemini_sam",
            "c_channel_3": "mog2",
            "carousel": "gemini_sam",
        }.get(role, "mog2")
        vm.getCaptureThreadForRole = lambda role: captures.get(role)
        vm._computeFeederGeminiDetection = (
            lambda role, frame, force_call=False: compute_calls.append(role) or detections[role]
        )
        vm._feeder_dynamic_detection_cache = {
            "c_channel_2": (10.0, detections["c_channel_2"]),
        }
        vm._feeder_track_cache = {}
        vm._aux_feeder_refresh_cursor = 0
        vm._updateFeederTracker = (
            lambda role, detection, timestamp, frame_bgr=None: updates.append(
                (role, float(timestamp))
            )
        )
        vm.getCarouselDetectionAlgorithm = lambda: "heatmap_diff"
        vm._carousel_capture = None

        VisionManager._refreshAuxiliaryDetections(vm)

        self.assertEqual(
            [("c_channel_2", 10.0), ("carousel", 12.0)],
            updates,
        )
        self.assertEqual(["carousel"], compute_calls)

    def test_filter_feeder_detection_result_discards_bboxes_outside_channel_mask(self) -> None:
        vm = VisionManager.__new__(VisionManager)
        mask = np.zeros((10, 10), dtype=np.uint8)
        mask[3:8, 3:8] = 255
        channel = SimpleNamespace(mask=mask)
        detection = DetectionResult(
            bbox=(0, 0, 2, 2),
            bboxes=((0, 0, 2, 2), (3, 3, 8, 8)),
            score=0.9,
            algorithm="gemini_sam",
            found=True,
        )

        vm._channelInfoForRole = lambda role: channel
        vm.getCaptureThreadForRole = lambda role: None

        filtered = VisionManager._filterFeederDetectionResultToChannel(vm, "c_channel_2", detection)

        self.assertEqual(((3, 3, 8, 8),), filtered.bboxes)
        self.assertEqual((3, 3, 8, 8), filtered.bbox)
        self.assertTrue(filtered.found)

    def test_filter_live_feeder_tracks_discards_tracks_outside_channel_mask(self) -> None:
        vm = VisionManager.__new__(VisionManager)
        mask = np.zeros((10, 10), dtype=np.uint8)
        mask[2:8, 2:8] = 255
        channel = SimpleNamespace(mask=mask)
        inside = SimpleNamespace(center=(4.0, 4.0))
        outside = SimpleNamespace(center=(9.0, 1.0))

        vm._channelInfoForRole = lambda role: channel

        filtered = VisionManager._filterLiveFeederTracksToChannel(
            vm,
            "carousel",
            [inside, outside],
        )

        self.assertEqual([inside], filtered)

    def test_filter_feeder_detection_result_discards_bboxes_inside_tracker_ghost_regions(self) -> None:
        vm = VisionManager.__new__(VisionManager)
        mask = np.ones((20, 20), dtype=np.uint8) * 255
        channel = SimpleNamespace(mask=mask)
        detection = DetectionResult(
            bbox=(0, 0, 10, 20),
            bboxes=((0, 0, 10, 20), (8, 2, 20, 18)),
            score=0.8,
            algorithm="hive:test",
            found=True,
        )

        vm._channelInfoForRole = lambda role: channel
        vm.getCaptureThreadForRole = lambda role: None
        vm._feeder_trackers = {
            "carousel": SimpleNamespace(
                is_detection_center_ignored=lambda center, timestamp=None: center[0] < 6
            )
        }

        filtered = VisionManager._filterFeederDetectionResultToChannel(vm, "carousel", detection)

        self.assertEqual(((8, 2, 20, 18),), filtered.bboxes)
        self.assertEqual((8, 2, 20, 18), filtered.bbox)

    def test_filter_live_feeder_tracks_discards_tracks_inside_tracker_ghost_regions(self) -> None:
        vm = VisionManager.__new__(VisionManager)
        mask = np.ones((20, 20), dtype=np.uint8) * 255
        channel = SimpleNamespace(mask=mask)
        ignored = SimpleNamespace(center=(3.0, 3.0), bbox=(1, 1, 5, 5), last_seen_ts=10.0)
        kept = SimpleNamespace(center=(12.0, 12.0), bbox=(10, 10, 14, 14), last_seen_ts=10.0)

        vm._channelInfoForRole = lambda role: channel
        vm.getCaptureThreadForRole = lambda role: None
        vm._feeder_trackers = {
            "carousel": SimpleNamespace(
                is_detection_center_ignored=lambda center, timestamp=None: center[0] < 6
            )
        }

        filtered = VisionManager._filterLiveFeederTracksToChannel(
            vm,
            "carousel",
            [ignored, kept],
        )

        self.assertEqual([kept], filtered)

    def test_feeder_ignored_overlay_includes_tracker_ghost_regions(self) -> None:
        vm = VisionManager.__new__(VisionManager)
        frame = np.zeros((100, 120, 3), dtype=np.uint8)
        vm.getCaptureThreadForRole = lambda role: SimpleNamespace(
            latest_frame=SimpleNamespace(raw=frame, timestamp=12.0)
        )
        vm._feeder_trackers = {
            "carousel": SimpleNamespace(
                get_ignored_static_regions=lambda timestamp=None: [
                    {
                        "center_px": (30.0, 40.0),
                        "radius_px": 10.0,
                        "persistent": True,
                    }
                ]
            )
        }

        data = VisionManager.getFeederIgnoredDetectionOverlayData(vm, "carousel")

        self.assertIn(
            {
                "label": "ghost",
                "bbox": [20, 30, 40, 50],
            },
            data,
        )

    def test_channel_detections_from_tracks_ignores_flaky_upstream_tracks(self) -> None:
        vm = VisionManager.__new__(VisionManager)
        channel = SimpleNamespace(channel_id=3)
        stable = SimpleNamespace(
            bbox=(10, 10, 20, 20),
            hit_count=2,
            coasting=False,
        )
        newborn = SimpleNamespace(
            bbox=(20, 20, 30, 30),
            hit_count=1,
            coasting=False,
        )
        coasting = SimpleNamespace(
            bbox=(30, 30, 40, 40),
            hit_count=9,
            coasting=True,
        )

        vm._channelInfoForRole = lambda role: channel

        detections = VisionManager._channelDetectionsFromTracks(
            vm,
            "c_channel_3",
            [stable, newborn, coasting],
        )

        self.assertEqual([(10, 10, 20, 20)], [det.bbox for det in detections])

    def test_channel_info_for_role_falls_back_to_saved_polygon_when_detector_missing(self) -> None:
        vm = VisionManager.__new__(VisionManager)
        vm._per_channel_detectors = {}
        vm._channel_angles = {"classification_channel": 12.5}
        vm._channelPolygonKeyForRole = lambda role: "classification_channel"
        vm._channelAngleKeyForPolygonKey = lambda key: "classification_channel"
        vm.getCaptureThreadForRole = lambda role: SimpleNamespace(
            latest_frame=SimpleNamespace(raw=np.zeros((20, 30, 3), dtype=np.uint8))
        )
        vm._loadSavedPolygon = lambda key, w, h: np.array(
            [[2, 2], [20, 2], [20, 18], [2, 18]],
            dtype=np.int32,
        )

        channel = VisionManager._channelInfoForRole(vm, "carousel")

        self.assertIsNotNone(channel)
        self.assertEqual(4, channel.channel_id)
        self.assertEqual((20, 30), channel.mask.shape)

    def test_filter_feeder_detection_result_discards_tiny_classification_edge_slivers(self) -> None:
        vm = VisionManager.__new__(VisionManager)
        mask = np.ones((20, 20), dtype=np.uint8) * 255
        channel = SimpleNamespace(mask=mask)
        detection = DetectionResult(
            bbox=(2, 18, 18, 20),
            bboxes=((2, 18, 18, 20),),
            score=0.31,
            algorithm="hive:test",
            found=True,
        )

        vm._channelInfoForRole = lambda role: channel
        vm.getCaptureThreadForRole = lambda role: None

        filtered = VisionManager._filterFeederDetectionResultToChannel(vm, "carousel", detection)

        self.assertEqual((), filtered.bboxes)
        self.assertIsNone(filtered.bbox)
        self.assertFalse(filtered.found)

    def test_list_feeder_track_history_keeps_live_classification_channel_tracks_even_below_min_sectors(self) -> None:
        vm = VisionManager.__new__(VisionManager)
        live_track = SimpleNamespace(
            global_id=9810,
            origin_seen_ts=10.0,
            last_seen_ts=12.0,
            source_role="carousel",
            handoff_from="c_channel_3",
            hit_count=4,
        )
        live_internal = SimpleNamespace(global_id=9810, sector_snapshots=[])
        tracker = SimpleNamespace(
            _tracks={1: live_internal},
            get_live_thumb=lambda global_id: "",
        )
        vm._piece_history = SimpleNamespace(list_summaries=lambda limit=None, min_sectors=0: [])
        vm._feeder_track_cache = {"carousel": (12.0, [live_track])}
        vm._feeder_trackers = {"carousel": tracker}

        items = VisionManager.listFeederTrackHistory(vm, limit=20, min_sectors=3)

        self.assertEqual(1, len(items))
        self.assertEqual(["carousel"], items[0]["roles"])

    def test_piece_history_keeps_classification_channel_entries_under_min_sector_filter(self) -> None:
        history = PieceHistoryBuffer(persist_dir=None)
        sparse_c3 = TrackSegment(
            source_role="c_channel_3",
            handoff_from=None,
            first_seen_ts=1.0,
            last_seen_ts=2.0,
            snapshot_jpeg_b64="",
            snapshot_width=0,
            snapshot_height=0,
            sector_snapshots=[
                SectorSnapshot(
                    sector_index=0,
                    start_angle_deg=0.0,
                    end_angle_deg=10.0,
                    captured_ts=1.5,
                    bbox_x=0,
                    bbox_y=0,
                    width=1,
                    height=1,
                    jpeg_b64="",
                )
            ],
        )
        sparse_classification = TrackSegment(
            source_role="classification_channel",
            handoff_from="c_channel_3",
            first_seen_ts=3.0,
            last_seen_ts=4.0,
            snapshot_jpeg_b64="",
            snapshot_width=0,
            snapshot_height=0,
            sector_snapshots=[],
        )
        history.record_segment(sparse_c3, global_id=1)
        history.record_segment(sparse_classification, global_id=2)

        items = history.list_summaries(min_sectors=3)

        self.assertEqual([2], [item["global_id"] for item in items])


class SegmentArchivalTests(unittest.TestCase):
    """Phase 3: ``VisionManager._archive_segment_to_dossier`` side-channel."""

    def _make_vm(self) -> SimpleNamespace:
        # The archival callback uses ``self.gc.logger`` for WARNINGs; give
        # it a no-op logger so errors don't explode during the tests.
        vm = VisionManager.__new__(VisionManager)
        vm.gc = SimpleNamespace(
            logger=SimpleNamespace(warning=lambda *a, **k: None, info=lambda *a, **k: None)
        )
        vm._piece_transport = None
        return vm

    def _make_segment(self, *, sector_count: int = 2) -> TrackSegment:
        # "ffd8ffe0" is a minimal JPEG SOI+APP0 header; the tests only ever
        # decode these back to bytes, so the payload doesn't need to be a
        # valid image — just non-empty and round-trippable via b64.
        import base64

        wedge_b64 = base64.b64encode(b"\xff\xd8\xff\xe0wedge").decode("ascii")
        piece_b64 = base64.b64encode(b"\xff\xd8\xff\xe0piece").decode("ascii")
        snapshots = [
            SectorSnapshot(
                sector_index=i,
                start_angle_deg=float(i * 10),
                end_angle_deg=float(i * 10 + 9),
                captured_ts=100.0 + i,
                bbox_x=i,
                bbox_y=i,
                width=4,
                height=4,
                jpeg_b64=wedge_b64,
                r_inner=50.0,
                r_outer=100.0,
                piece_jpeg_b64=piece_b64,
            )
            for i in range(sector_count)
        ]
        return TrackSegment(
            source_role="c_channel_3",
            handoff_from=None,
            first_seen_ts=100.0,
            last_seen_ts=105.0,
            snapshot_jpeg_b64="",
            snapshot_width=640,
            snapshot_height=480,
            hit_count=sector_count,
            channel_center_x=320.0,
            channel_center_y=240.0,
            channel_radius_inner=50.0,
            channel_radius_outer=100.0,
            sector_count=sector_count,
            sector_snapshots=snapshots,
        )

    def test_segment_archival_writes_crops_and_dossier(self) -> None:
        vm = self._make_vm()
        transport_calls: list[int] = []
        transport = SimpleNamespace(
            get_piece_uuid_for_tracked_global_id=lambda gid: (
                transport_calls.append(int(gid)) or "test-uuid"
            ),
            bindStubPieceUuid=lambda *a, **k: True,
        )
        vm._piece_transport = transport

        write_calls: list[tuple] = []
        segment_calls: list[dict] = []

        def _fake_write(piece_uuid, sequence, kind, idx, jpeg_bytes):
            write_calls.append(
                (piece_uuid, int(sequence), kind, int(idx), bytes(jpeg_bytes))
            )
            return f"piece_crops/{piece_uuid}/seg{int(sequence)}/{kind}_{int(idx):03d}.jpg"

        def _fake_segment(*, piece_uuid, role, sequence, payload):
            segment_calls.append(
                {
                    "piece_uuid": piece_uuid,
                    "role": role,
                    "sequence": int(sequence),
                    "payload": payload,
                }
            )

        segment = self._make_segment(sector_count=2)

        with mock.patch("blob_manager.write_piece_crop", side_effect=_fake_write), \
             mock.patch("local_state.remember_piece_segment", side_effect=_fake_segment), \
             mock.patch("local_state.remember_piece_dossier"):
            VisionManager._archive_segment_to_dossier(vm, 42, segment)

        self.assertEqual([42], transport_calls)
        # 2 wedges + 2 piece crops = 4 total. No snapshot (empty b64).
        self.assertEqual(4, len(write_calls))
        kinds = [call[2] for call in write_calls]
        self.assertEqual(sorted(kinds), ["piece", "piece", "wedge", "wedge"])
        self.assertEqual(1, len(segment_calls))
        call = segment_calls[0]
        self.assertEqual("test-uuid", call["piece_uuid"])
        self.assertEqual("c_channel_3", call["role"])
        sectors = call["payload"]["sector_snapshots"]
        self.assertEqual(2, len(sectors))
        for entry in sectors:
            self.assertIn("jpeg_path", entry)
            self.assertIn("piece_jpeg_path", entry)
            self.assertNotIn("jpeg_b64", entry)
            self.assertNotIn("piece_jpeg_b64", entry)
            self.assertTrue(str(entry["jpeg_path"]).startswith("piece_crops/test-uuid/"))

    def test_segment_archival_creates_stub_dossier_for_unknown_gid(self) -> None:
        vm = self._make_vm()
        bind_calls: list[tuple] = []
        transport = SimpleNamespace(
            get_piece_uuid_for_tracked_global_id=lambda gid: None,
            bindStubPieceUuid=lambda gid, uuid: (
                bind_calls.append((int(gid), str(uuid))) or True
            ),
        )
        vm._piece_transport = transport

        dossier_calls: list[dict] = []
        segment_calls: list[dict] = []

        def _fake_dossier(obj):
            dossier_calls.append(dict(obj))

        def _fake_segment(*, piece_uuid, role, sequence, payload):
            segment_calls.append({"piece_uuid": piece_uuid, "sequence": sequence})

        segment = self._make_segment(sector_count=1)

        with mock.patch(
            "blob_manager.write_piece_crop", side_effect=lambda *a, **k: "rel.jpg"
        ), mock.patch(
            "local_state.remember_piece_dossier", side_effect=_fake_dossier
        ), mock.patch(
            "local_state.remember_piece_segment", side_effect=_fake_segment
        ):
            VisionManager._archive_segment_to_dossier(vm, 99, segment)

        self.assertEqual(1, len(dossier_calls))
        new_uuid = dossier_calls[0]["uuid"]
        self.assertTrue(isinstance(new_uuid, str) and new_uuid)
        self.assertEqual("created", dossier_calls[0]["stage"])
        self.assertEqual("pending", dossier_calls[0]["classification_status"])
        self.assertEqual(99, dossier_calls[0]["tracked_global_id"])

        self.assertEqual(1, len(bind_calls))
        self.assertEqual((99, new_uuid), bind_calls[0])

        self.assertEqual(1, len(segment_calls))
        self.assertEqual(new_uuid, segment_calls[0]["piece_uuid"])

    def test_archival_callback_never_raises_on_write_error(self) -> None:
        vm = self._make_vm()
        transport = SimpleNamespace(
            get_piece_uuid_for_tracked_global_id=lambda gid: "x-uuid",
            bindStubPieceUuid=lambda *a, **k: True,
        )
        vm._piece_transport = transport

        segment_calls: list[dict] = []

        def _return_none(*args, **kwargs):
            # In prod ``write_piece_crop`` maps OSError -> None internally
            # (see blob_manager). The archival callback then persists a
            # segment row with ``jpeg_path=None``. This simulates that
            # degraded path.
            return None

        def _capture(*, piece_uuid, role, sequence, payload):
            segment_calls.append({"piece_uuid": piece_uuid, "payload": payload})

        segment = self._make_segment(sector_count=1)

        with mock.patch(
            "blob_manager.write_piece_crop", side_effect=_return_none
        ), mock.patch(
            "local_state.remember_piece_segment", side_effect=_capture
        ), mock.patch(
            "local_state.remember_piece_dossier"
        ):
            try:
                VisionManager._archive_segment_to_dossier(vm, 7, segment)
            except Exception as exc:  # noqa: BLE001
                self.fail(
                    f"_archive_segment_to_dossier must never raise, got: {exc!r}"
                )

        # remember_piece_segment still fires — just with empty crop paths.
        # The SQLite row lets the UI know the segment existed even when
        # disk writes were rejected.
        self.assertEqual(1, len(segment_calls))
        sectors = segment_calls[0]["payload"]["sector_snapshots"]
        self.assertEqual(1, len(sectors))
        self.assertIsNone(sectors[0]["jpeg_path"])
        self.assertIsNone(sectors[0]["piece_jpeg_path"])

    def test_segment_archival_reuses_db_dossier_for_known_gid(self) -> None:
        """Transport cache misses must fall back to the SQLite dossier
        index before minting a fresh uuid. When ``tracked_global_id`` is
        already persisted (C3 early-bind), the archival callback must
        reuse that uuid and push it back into the transport map."""

        vm = self._make_vm()
        bind_calls: list[tuple] = []
        transport = SimpleNamespace(
            get_piece_uuid_for_tracked_global_id=lambda gid: None,
            bindStubPieceUuid=lambda gid, uuid: (
                bind_calls.append((int(gid), str(uuid))) or True
            ),
        )
        vm._piece_transport = transport

        existing_uuid = "persisted-uuid-42"
        dossier_calls: list[dict] = []
        segment_calls: list[dict] = []

        def _fake_dossier(obj):
            dossier_calls.append(dict(obj))

        def _fake_segment(*, piece_uuid, role, sequence, payload):
            segment_calls.append({"piece_uuid": piece_uuid, "sequence": sequence})

        segment = self._make_segment(sector_count=2)

        with mock.patch(
            "blob_manager.write_piece_crop", side_effect=lambda *a, **k: "rel.jpg"
        ), mock.patch(
            "local_state.remember_piece_dossier", side_effect=_fake_dossier
        ), mock.patch(
            "local_state.remember_piece_segment", side_effect=_fake_segment
        ), mock.patch(
            "local_state.get_piece_dossier_by_tracked_global_id",
            return_value={"uuid": existing_uuid, "tracked_global_id": 42},
        ):
            VisionManager._archive_segment_to_dossier(vm, 42, segment)

        # No new dossier should have been minted; the persisted uuid wins.
        self.assertEqual([], dossier_calls)
        # Transport binding must have been refreshed with the reused uuid.
        self.assertEqual([(42, existing_uuid)], bind_calls)
        # Segment persistence targets the reused uuid.
        self.assertEqual(1, len(segment_calls))
        self.assertEqual(existing_uuid, segment_calls[0]["piece_uuid"])

    def test_segment_archival_skips_stationary_ghost(self) -> None:
        """Segments whose sector snapshots barely cover a couple of
        degrees (static apparatus ghost that clipped past the early-bind
        filter) must not produce a stub dossier or segment row."""

        vm = self._make_vm()
        transport = SimpleNamespace(
            get_piece_uuid_for_tracked_global_id=lambda gid: None,
            bindStubPieceUuid=lambda *a, **k: True,
        )
        vm._piece_transport = transport

        import base64

        wedge_b64 = base64.b64encode(b"\xff\xd8\xff\xe0wedge").decode("ascii")
        piece_b64 = base64.b64encode(b"\xff\xd8\xff\xe0piece").decode("ascii")
        # Two snapshots, both parked in the same ~1° sliver — angular
        # span ≈ 1.0° which is below the 3° motion-gate.
        snapshots = [
            SectorSnapshot(
                sector_index=0,
                start_angle_deg=45.0,
                end_angle_deg=45.5,
                captured_ts=100.0,
                bbox_x=0,
                bbox_y=0,
                width=4,
                height=4,
                jpeg_b64=wedge_b64,
                r_inner=50.0,
                r_outer=100.0,
                piece_jpeg_b64=piece_b64,
            ),
            SectorSnapshot(
                sector_index=0,
                start_angle_deg=45.2,
                end_angle_deg=46.0,
                captured_ts=101.0,
                bbox_x=0,
                bbox_y=0,
                width=4,
                height=4,
                jpeg_b64=wedge_b64,
                r_inner=50.0,
                r_outer=100.0,
                piece_jpeg_b64=piece_b64,
            ),
        ]
        segment = TrackSegment(
            source_role="c_channel_3",
            handoff_from=None,
            first_seen_ts=100.0,
            last_seen_ts=105.0,
            snapshot_jpeg_b64="",
            snapshot_width=640,
            snapshot_height=480,
            hit_count=2,
            channel_center_x=320.0,
            channel_center_y=240.0,
            channel_radius_inner=50.0,
            channel_radius_outer=100.0,
            sector_count=2,
            sector_snapshots=snapshots,
        )

        dossier_calls: list[dict] = []
        segment_calls: list[dict] = []

        with mock.patch(
            "blob_manager.write_piece_crop", side_effect=lambda *a, **k: "rel.jpg"
        ), mock.patch(
            "local_state.remember_piece_dossier",
            side_effect=lambda obj: dossier_calls.append(dict(obj)),
        ), mock.patch(
            "local_state.remember_piece_segment",
            side_effect=lambda **kw: segment_calls.append(kw),
        ), mock.patch(
            "local_state.get_piece_dossier_by_tracked_global_id",
            return_value=None,
        ):
            VisionManager._archive_segment_to_dossier(vm, 777, segment)

        # Nothing persisted — the motion-gate refused the stub.
        self.assertEqual([], dossier_calls)
        self.assertEqual([], segment_calls)

    def test_archival_callback_swallows_exceptions_from_write_piece_crop(self) -> None:
        """Defence in depth: even if ``write_piece_crop`` (wrongly) leaks an
        OSError, the archival callback must not propagate it upstream to
        the tracker thread that produced the segment."""
        vm = self._make_vm()
        vm._piece_transport = SimpleNamespace(
            get_piece_uuid_for_tracked_global_id=lambda gid: "x-uuid",
            bindStubPieceUuid=lambda *a, **k: True,
        )

        def _boom(*args, **kwargs):
            raise OSError("simulated disk full")

        segment = self._make_segment(sector_count=1)
        with mock.patch("blob_manager.write_piece_crop", side_effect=_boom), \
             mock.patch("local_state.remember_piece_segment"), \
             mock.patch("local_state.remember_piece_dossier"):
            try:
                VisionManager._archive_segment_to_dossier(vm, 7, segment)
            except Exception as exc:  # noqa: BLE001
                self.fail(
                    f"_archive_segment_to_dossier must never raise, got: {exc!r}"
                )


if __name__ == "__main__":
    unittest.main()
