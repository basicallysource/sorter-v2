import unittest
import sys
import types
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

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


class _OverlayFeed:
    def __init__(self) -> None:
        self.overlays: list[object] = []
        self.pinned_ts_provider = None

    def clear_overlays(self) -> None:
        self.overlays.clear()

    def add_overlay(self, overlay: object) -> None:
        self.overlays.append(overlay)

    def set_pinned_ts_provider(self, provider) -> None:
        self.pinned_ts_provider = provider


class VisionManagerFeederDynamicTests(unittest.TestCase):
    def test_init_overlays_registers_classification_channel_feed_alias(self) -> None:
        vm = VisionManager.__new__(VisionManager)
        carousel_feed = _OverlayFeed()
        classification_feed = _OverlayFeed()
        camera_service = SimpleNamespace(
            feeds={
                "carousel": carousel_feed,
                "classification_channel": classification_feed,
            },
            get_feed=lambda role: {
                "carousel": carousel_feed,
                "classification_channel": classification_feed,
            }.get(role),
        )

        vm._camera_service = camera_service
        vm._camera_layout = "split_feeder"
        vm._region_provider = object()
        vm._usesClassificationChannelSetup = lambda: True
        vm._feederTrackerRoles = lambda: ("carousel",)
        vm.getFeederDetectionAlgorithm = lambda role=None: "gemini_sam"
        vm._isDynamicDetectionAlgorithm = lambda algorithm: True
        vm.getCaptureThreadForRole = lambda role: None
        vm._getFeederDynamicDetection = lambda role, force=False: None
        vm.getFeederTracks = lambda role: []
        vm.getFeederIgnoredDetectionOverlayData = lambda role: []
        vm._feeder_dynamic_detection_cache = {}
        vm._per_channel_detectors = {}
        vm._per_channel_analysis = {}

        VisionManager._initOverlays(vm)

        carousel_overlay_names = [type(overlay).__name__ for overlay in carousel_feed.overlays]
        classification_overlay_names = [
            type(overlay).__name__ for overlay in classification_feed.overlays
        ]
        # The raw-YOLO DynamicDetectionOverlay was removed from the carousel
        # feed (it doubled up with TrackOverlay). The tracker layer is the
        # source of truth for piece identity / state on the carousel feed.
        self.assertIn("ChannelRegionOverlay", carousel_overlay_names)
        self.assertIn("TrackOverlay", carousel_overlay_names)
        self.assertNotIn("DynamicDetectionOverlay", carousel_overlay_names)
        self.assertIn("ChannelRegionOverlay", classification_overlay_names)
        self.assertIn("TrackOverlay", classification_overlay_names)
        self.assertNotIn("DynamicDetectionOverlay", classification_overlay_names)
        # The encode path must be pinned to the latest detection's frame_ts
        # so overlay bboxes match the frame the detector ran on. Wiring the
        # provider is what gives feed.get_frame() access to the timestamp.
        self.assertIsNotNone(carousel_feed.pinned_ts_provider)
        self.assertIsNotNone(classification_feed.pinned_ts_provider)

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

    def test_bundled_feeder_model_runs_local_model_detection_path(self) -> None:
        vm = VisionManager.__new__(VisionManager)
        frame = SimpleNamespace(timestamp=123.0, raw=np.zeros((8, 8, 3), dtype=np.uint8))
        detection = DetectionResult(
            bbox=(1, 1, 4, 4),
            bboxes=((1, 1, 4, 4),),
            score=0.9,
            algorithm="bundled:c-channel",
            found=True,
        )
        infer_calls: list[tuple[str, str, str]] = []
        updates: list[tuple[str, object, float]] = []

        vm.getCaptureThreadForRole = lambda role: SimpleNamespace(latest_frame=frame)
        vm.getFeederDetectionAlgorithm = lambda role=None: "bundled:c-channel"
        vm._feeder_dynamic_detection_cache = {}
        vm._filterFeederDetectionResultToChannel = lambda role, current_detection: current_detection
        vm._runHiveDetection = (
            lambda algorithm, raw, scope, role: infer_calls.append((algorithm, scope, role))
            or detection
        )
        vm._updateFeederTracker = (
            lambda role, current_detection, timestamp, frame_bgr=None: updates.append(
                (role, current_detection, float(timestamp))
            )
        )

        result = VisionManager._getFeederDynamicDetection(vm, "c_channel_2", force=False)

        self.assertIs(result, detection)
        self.assertEqual([("bundled:c-channel", "feeder", "c_channel_2")], infer_calls)
        self.assertEqual([("c_channel_2", detection, 123.0)], updates)

    def test_get_or_build_hive_processor_accepts_bundled_registry_entries(self) -> None:
        vm = VisionManager.__new__(VisionManager)
        vm._hive_ml_processors = {}
        vm.gc = SimpleNamespace(logger=SimpleNamespace(warning=lambda *_a, **_k: None))
        definition = SimpleNamespace(
            kind="bundled",
            model_path=Path("/tmp/bundled.onnx"),
            model_family="yolo",
            runtime="onnx",
            imgsz=320,
        )
        processor = object()

        with (
            patch("vision.detection_registry.detection_algorithm_definition", return_value=definition),
            patch("vision.ml.create_processor", return_value=processor) as create_processor,
        ):
            result = VisionManager._getOrBuildHiveProcessor(vm, "bundled:c-channel")

        self.assertIs(result, processor)
        self.assertIs(vm._hive_ml_processors["bundled:c-channel"], processor)
        create_processor.assert_called_once()

    def test_refresh_auxiliary_detections_runs_all_dynamic_roles_per_tick(self) -> None:
        """The aux loop is the dedicated detection-cache warmer. Each tick
        it must call the per-role detection entry for every dynamic-detection
        role (gemini_sam / local-model ids) and skip non-dynamic roles. The actual
        inference dedup happens inside the detection functions via their
        per-role throttle, so we just verify the cache-warmer fan-out here.
        """
        vm = VisionManager.__new__(VisionManager)
        feeder_calls: list[str] = []
        carousel_calls: list[int] = []

        vm._feederTrackerRoles = lambda: ("c_channel_2", "c_channel_3", "carousel")
        vm.getFeederDetectionAlgorithm = lambda role=None: {
            "c_channel_2": "gemini_sam",
            "c_channel_3": "mog2",
            "carousel": "hive:carousel_v1",
        }.get(role, "mog2")
        vm._feederRoleUsesDynamicDetection = lambda role: VisionManager._isDynamicDetectionAlgorithm(
            vm.getFeederDetectionAlgorithm(role)
        )
        vm._getFeederDynamicDetection = (
            lambda role, force=False: feeder_calls.append(role) or None
        )
        vm.getCarouselDetectionAlgorithm = lambda: "hive:carousel_v1"
        vm._isDynamicDetectionAlgorithm = VisionManager._isDynamicDetectionAlgorithm
        vm._camera_service = SimpleNamespace(
            get_capture_thread_for_role=lambda _role: SimpleNamespace(latest_frame=None)
        )
        vm._getCarouselDynamicDetection = (
            lambda force=False: carousel_calls.append(1) or None
        )
        vm.gc = SimpleNamespace(logger=SimpleNamespace(warning=lambda *_a, **_k: None))

        VisionManager._refreshAuxiliaryDetections(vm)

        # Dynamic roles fan out; mog2 role is skipped.
        self.assertEqual(["c_channel_2", "carousel"], feeder_calls)
        # Carousel hive driven independently of the feeder fan-out.
        self.assertEqual([1], carousel_calls)

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
            source_role="carousel",
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


if __name__ == "__main__":
    unittest.main()
