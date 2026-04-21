"""Tests that ``FeederAnalysisThread`` (MOG2) is only started for roles whose
detection algorithm actually consumes it. Dynamic algorithms (``hive:*`` /
``gemini_sam``) drive detections from the tracker layer instead, and leaving
the MOG2 loop running in that case wastes CPU on a result nobody reads.
"""
import sys
import types
import unittest
from types import SimpleNamespace
from unittest import mock

import numpy as np

# Stub subsystems.feeder.analysis so VisionManager can be imported without
# pulling the hardware-facing dependency graph.
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

from vision.vision_manager import VisionManager  # noqa: E402


class _FakeLogger:
    def __init__(self) -> None:
        self.messages: list[tuple[str, str]] = []

    def info(self, msg: str) -> None:
        self.messages.append(("info", msg))

    def warning(self, msg: str) -> None:
        self.messages.append(("warning", msg))

    def warn(self, msg: str) -> None:
        self.messages.append(("warn", msg))


def _make_polygon(w: int = 120, h: int = 120) -> np.ndarray:
    return np.array([[10, 10], [w - 10, 10], [w - 10, h - 10], [10, h - 10]], dtype=np.int32)


def _make_vm_for_split(algorithms_by_role: dict[str, str]) -> VisionManager:
    vm = VisionManager.__new__(VisionManager)
    vm._camera_layout = "split_feeder"
    vm._per_channel_detectors = {}
    vm._per_channel_analysis = {}
    vm._feeder_detection_algorithm_by_role = dict(algorithms_by_role)
    vm._feeder_detection_algorithm = "mog2"
    vm._channel_angles = {"second": 0.0, "third": 0.0, "classification_channel": 0.0}
    vm._channel_polygons = {}
    vm._camera_service = None
    vm.gc = SimpleNamespace(
        logger=_FakeLogger(),
        profiler=SimpleNamespace(
            hit=lambda *a, **k: None,
            mark=lambda *a, **k: None,
            observeValue=lambda *a, **k: None,
            timer=lambda *a, **k: _NullCtx(),
        ),
    )
    # _usesClassificationChannelSetup: include carousel role.
    vm._usesClassificationChannelSetup = lambda: True
    # Capture properties expected by _initSplitFeederDetection — attach no-op
    # capture thread stubs that return a fresh frame so the init path can
    # scale polygons against a concrete camera resolution.
    raw = np.zeros((120, 120, 3), dtype=np.uint8)
    fake_frame = SimpleNamespace(raw=raw, timestamp=0.0)
    fake_capture = SimpleNamespace(latest_frame=fake_frame)

    # Properties are descriptor-based on the class. Bypass them by setting the
    # underlying ``_camera_service`` via a minimal stub that yields the same
    # capture for every role lookup.
    class _FakeCameraService:
        feeds: dict = {}

        def get_capture_thread_for_role(self, role: str):
            return fake_capture

        def get_feed(self, role: str):
            return None

    vm._camera_service = _FakeCameraService()
    return vm


class _NullCtx:
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class FeederAnalysisGatingTests(unittest.TestCase):
    def test_feeder_analysis_thread_not_started_when_algorithm_is_dynamic(self) -> None:
        vm = _make_vm_for_split({
            "c_channel_2": "gemini_sam",
            "c_channel_3": "mog2",
            "carousel": "gemini_sam",
        })

        polys = {
            "second_channel": _make_polygon(),
            "third_channel": _make_polygon(),
            "classification_channel": _make_polygon(),
        }

        def _fake_spawn(self, *, key, role, capture, polys, inner_polys, raw_arc_params, is_channel_rotating):
            self._per_channel_detectors[role] = object()
            self._per_channel_analysis[role] = object()
            return True

        with mock.patch.object(VisionManager, "_spawnSplitFeederMog2ForRole", _fake_spawn):
            ok = VisionManager._initSplitFeederDetection(
                vm,
                polys,
                inner_polys={},
                raw_arc_params={},
                channel_steppers={},
                is_channel_rotating=lambda _name: False,
            )

        self.assertTrue(ok)
        # Only the static-mog2 role should have spawned a detector/thread.
        self.assertIn("c_channel_3", vm._per_channel_analysis)
        self.assertNotIn("c_channel_2", vm._per_channel_analysis)
        self.assertNotIn("carousel", vm._per_channel_analysis)
        self.assertNotIn("c_channel_2", vm._per_channel_detectors)
        self.assertNotIn("carousel", vm._per_channel_detectors)

        log_lines = [msg for _lvl, msg in vm.gc.logger.messages if "Skipping MOG2 analysis thread" in msg]
        self.assertTrue(any("c_channel_2" in line for line in log_lines))
        self.assertTrue(any("carousel" in line for line in log_lines))

    def test_switch_from_mog2_to_dynamic_stops_and_drops_thread(self) -> None:
        vm = _make_vm_for_split({
            "c_channel_2": "mog2",
            "c_channel_3": "mog2",
            "carousel": "mog2",
        })
        stop_calls: list[str] = []

        class _FakeAnalysis:
            def __init__(self, name: str) -> None:
                self._name = name

            def stop(self) -> None:
                stop_calls.append(self._name)

        vm._per_channel_analysis = {
            "c_channel_2": _FakeAnalysis("c_channel_2"),
            "c_channel_3": _FakeAnalysis("c_channel_3"),
        }
        vm._per_channel_detectors = {
            "c_channel_2": object(),
            "c_channel_3": object(),
        }

        # Switch c_channel_2 to gemini_sam. Expect its detector + thread to go away.
        vm._feeder_detection_algorithm_by_role["c_channel_2"] = "gemini_sam"
        prev = {
            "c_channel_2": "mog2",
            "c_channel_3": "mog2",
            "carousel": "mog2",
        }
        VisionManager._syncSplitFeederMog2Threads(vm, prev)

        self.assertEqual(["c_channel_2"], stop_calls)
        self.assertNotIn("c_channel_2", vm._per_channel_analysis)
        self.assertNotIn("c_channel_2", vm._per_channel_detectors)
        self.assertIn("c_channel_3", vm._per_channel_analysis)

    def test_switch_dynamic_to_dynamic_is_noop(self) -> None:
        vm = _make_vm_for_split({
            "c_channel_2": "gemini_sam",
            "c_channel_3": "gemini_sam",
            "carousel": "gemini_sam",
        })
        # No MOG2 thread running in the first place.
        vm._per_channel_analysis = {}
        vm._per_channel_detectors = {}

        prev = {
            "c_channel_2": "gemini_sam",
            "c_channel_3": "gemini_sam",
            "carousel": "gemini_sam",
        }
        VisionManager._syncSplitFeederMog2Threads(vm, prev)

        self.assertEqual({}, vm._per_channel_analysis)
        self.assertEqual({}, vm._per_channel_detectors)


if __name__ == "__main__":
    unittest.main()
