"""Training samples: what a sample carries, the store that keeps them, the
limits Hive sets, and how the sync worker sends them."""

import importlib
import json
import os
import tempfile
import threading
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np
import requests

from irl.config import IRLConfig, mkCameraConfig
from vision import camera_service
from vision.camera import CaptureThread

JPEG = b"\xff\xd8\xff" + b"\x00" * 64


def _reload(*names):
    modules = []
    for name in names:
        module = importlib.import_module(name)
        modules.append(importlib.reload(module))
    return modules


class _StateTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        os.environ["LOCAL_STATE_DB_PATH"] = os.path.join(self._tmp.name, "state.sqlite")
        self.local_state, self.hive_limits, self.sample_store = _reload("local_state", "hive_limits", "sample_store")

    def tearDown(self) -> None:
        os.environ.pop("LOCAL_STATE_DB_PATH", None)
        self._tmp.cleanup()
        _reload("local_state", "hive_limits", "sample_store")

    def _targets(self, *ids: str) -> None:
        self.local_state.set_hive_config(
            {
                "targets": [
                    {"id": target_id, "url": f"https://{target_id}.example", "api_token": "t", "enabled": True}
                    for target_id in ids
                ]
            }
        )

    def _write(self, n: int = 1, camera: str = "classification_channel", nbytes: int = len(JPEG)) -> None:
        for _ in range(n):
            data = JPEG + b"\x00" * max(0, nbytes - len(JPEG))
            self.sample_store._writeSample(data, {"camera": camera, "captured_at": time.time(), "width": 6, "height": 4, "meta": {"detection": {"algorithm": "raw_capture"}}})


class HiveLimitsTests(_StateTestCase):
    def test_no_reply_means_defaults(self) -> None:
        self.assertEqual(self.hive_limits.DEFAULT_LIMITS, self.hive_limits.targetLimits("a"))

    def test_reply_is_stored_and_junk_falls_back(self) -> None:
        self.hive_limits.setTargetLimits("a", {"sample_burst_interval_s": 30, "upload_files_per_minute": -1, "sample_floor_interval_s": 5})
        limits = self.hive_limits.targetLimits("a")
        self.assertEqual(30.0, limits["sample_burst_interval_s"])
        self.assertEqual(self.hive_limits.DEFAULT_LIMITS["upload_files_per_minute"], limits["upload_files_per_minute"])
        self.assertEqual(30.0, limits["sample_floor_interval_s"])  # never under the burst

    def test_reply_without_limits_keeps_the_stored_ones(self) -> None:
        self.hive_limits.setTargetLimits("a", {"sample_burst_interval_s": 30})
        self.assertIsNone(self.hive_limits.setTargetLimits("a", None))
        self.assertEqual(30.0, self.hive_limits.targetLimits("a")["sample_burst_interval_s"])

    def test_machine_limits_take_the_strictest_enabled_target(self) -> None:
        self._targets("a", "b")
        self.hive_limits.setTargetLimits("a", {"sample_burst_interval_s": 30, "sample_store_max_bytes": 500})
        self.hive_limits.setTargetLimits("b", {"sample_burst_interval_s": 20, "sample_store_max_bytes": 900})
        self.hive_limits.setTargetLimits("disabled", {"sample_store_max_bytes": 1})
        limits = self.hive_limits.machineLimits()
        self.assertEqual(30.0, limits["sample_burst_interval_s"])
        self.assertEqual(500, limits["sample_store_max_bytes"])


class SampleStoreTests(_StateTestCase):
    def test_enqueue_writes_a_row_and_its_file(self) -> None:
        self.assertTrue(self.sample_store.enqueue(JPEG, {"camera": "c_channel_3", "captured_at": 1.5, "width": 6, "height": 4, "meta": {"lamp": {"output": "x"}}}))
        deadline = time.time() + 5
        while self.sample_store.getMaxSampleId() == 0 and time.time() < deadline:
            time.sleep(0.02)
        rows = self.sample_store.listSamplesAfter(0, 10)
        self.assertEqual(1, len(rows))
        self.assertEqual("c_channel_3", rows[0]["camera"])
        self.assertEqual({"lamp": {"output": "x"}}, rows[0]["meta"])
        self.assertEqual(JPEG, self.sample_store.getSampleFileById(rows[0]["id"]).read_bytes())

    def test_low_disk_skips_the_sample(self) -> None:
        with patch.object(self.sample_store, "_freeBytes", return_value=self.sample_store.MIN_FREE_BYTES - 1):
            self.assertFalse(self.sample_store.enqueue(JPEG, {"camera": "classification_channel"}))
        self.assertEqual(1, self.sample_store.stats()["skipped_low_disk"])

    def test_retention_keeps_the_store_under_its_cap_evicting_sent_samples_first(self) -> None:
        # The cap counts what files take on the card: whole 4 KB blocks.
        self._write(4, nbytes=1000)
        self.sample_store.markSyncedUpTo(2, time.time())
        self.sample_store.setLocalCapBytes(2 * 4096 + 500)
        self.sample_store._retentionSweep()
        rows = {row["id"]: row for row in self.sample_store.listSamplesAfter(0, 10)}
        self.assertTrue(rows[1]["evicted_locally"])
        self.assertTrue(rows[2]["evicted_locally"])
        self.assertFalse(rows[3]["evicted_locally"])
        self.assertEqual(2 * 4096, self.sample_store.stats()["stored_bytes"])

    def test_hive_limit_caps_the_store_below_the_local_setting(self) -> None:
        self._targets("a")
        self.hive_limits.setTargetLimits("a", {"sample_store_max_bytes": 1500})
        self.sample_store.setLocalCapBytes(10_000)
        self.assertEqual(1500, self.sample_store.capBytes())

    def test_purge_all_deletes_every_file_and_keeps_the_cursor(self) -> None:
        self._write(3)
        self.assertEqual(3, self.sample_store.purgeAll()["deleted"])
        self.assertEqual(0, self.sample_store.stats()["stored"])
        self.assertEqual(3, self.sample_store.getMaxSampleId())


class _Capture:
    def __init__(self, rotation: int = 0) -> None:
        self.rotation = rotation

    def getPictureSettings(self):
        return SimpleNamespace(rotation=self.rotation, flip_horizontal=False, flip_vertical=False)

    def getDeviceSettings(self):
        return {"auto_exposure": True, "exposure": 64.0}

    def getTelemetrySnapshot(self):
        return {"resolution": (6, 4), "fps": 30.0}

    def describeDeviceControls(self):
        return [], {"exposure": 120.0}


class BuildSampleTests(_StateTestCase):
    def setUp(self) -> None:
        super().setUp()
        (self.sample_ingest,) = _reload("sample_ingest")
        self.gc = SimpleNamespace(logger=SimpleNamespace(warning=lambda *a: None))
        self.frame = SimpleNamespace(raw=np.zeros((4, 6, 3), np.uint8), raw_jpeg=JPEG, timestamp=12.5)
        self.local_state.set_led_state({"assignments": {"classification_channel": "out:6", "c_channel_3": "out:6"}, "brightness": {"out:6": 80}})

    def _build(self, capture: _Capture, geometry: dict | None):
        with patch("channel_geometry_payload.buildChannelGeometryForRole", return_value=geometry), patch.object(
            self.sample_ingest, "_softwareInfo", return_value={"version": "test"}
        ):
            return self.sample_ingest.buildSample(self.gc, "classification_channel", capture, self.frame, annotate=False)

    def test_the_cameras_own_jpeg_with_camera_lamp_and_outline(self) -> None:
        jpeg, meta = self._build(_Capture(), {"frame_width": 6, "frame_height": 4})
        self.assertEqual(JPEG, jpeg)
        info = meta["meta"]
        self.assertEqual("camera_jpeg", info["camera"]["image"])
        self.assertEqual({"exposure": 120.0}, info["camera"]["reported_settings"])
        self.assertEqual({"auto_exposure": True, "exposure": 64.0}, info["camera"]["applied_settings"])
        self.assertEqual(80, info["lamp"]["brightness_percent"])
        self.assertEqual(["c_channel_3", "classification_channel"], info["lamp"]["channels_on_output"])
        self.assertTrue(info["channel_geometry_matches_frame"])
        self.assertEqual(12.5, meta["captured_at"])
        self.assertEqual((6, 4), (meta["width"], meta["height"]))

    def test_rotated_camera_sends_the_rotated_frame(self) -> None:
        jpeg, meta = self._build(_Capture(rotation=90), {"frame_width": 3, "frame_height": 3})
        self.assertNotEqual(JPEG, jpeg)
        self.assertTrue(jpeg.startswith(b"\xff\xd8"))
        self.assertEqual("reencoded_after_picture_settings", meta["meta"]["camera"]["image"])
        self.assertFalse(meta["meta"]["channel_geometry_matches_frame"])

    def test_camera_without_a_teacher_zone_is_not_sampled(self) -> None:
        self.assertIsNone(self.sample_ingest.buildSample(self.gc, "feeder", _Capture(), self.frame, annotate=False))


class CollectorCaptureTests(_StateTestCase):
    """A cycle saves one sample per physical camera, under the role the lamp
    state and channel geometry know it by."""

    def setUp(self) -> None:
        super().setUp()
        self.sample_ingest, self.sample_collector = _reload("sample_ingest", "sample_collector")
        self.local_state.set_led_state({"assignments": {"classification_channel": "out:6"}, "brightness": {"out:6": 80}})
        self.saved: list[tuple[bytes, dict]] = []
        for patcher in (
            patch.object(self.sample_collector.sample_store, "enqueue", side_effect=lambda jpeg, meta: self.saved.append((jpeg, meta)) or True),
            patch("channel_geometry_payload.buildChannelGeometryForRole", return_value=None),
            patch.object(self.sample_ingest, "_softwareInfo", return_value={}),
            patch.object(CaptureThread, "describeDeviceControls", return_value=([], {})),
            patch("machine_specs.v4l2CameraModel", side_effect=lambda index: f"model-{index}"),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)

    def _cycle(self, c_channel_3=None) -> dict[str, dict]:
        config = IRLConfig()
        config.c_channel_2_camera = mkCameraConfig(device_index=0)
        config.c_channel_3_camera = c_channel_3 or mkCameraConfig(device_index=1)
        config.carousel_camera = mkCameraConfig(device_index=2, width=1280, height=720)
        gc = SimpleNamespace(logger=SimpleNamespace(info=lambda *a: None, warning=lambda *a: None))
        with patch.object(camera_service, "list_v4l2_modes", return_value=[]):
            service = camera_service.CameraService(config, gc)
        frame = SimpleNamespace(raw=np.zeros((4, 6, 3), np.uint8), raw_jpeg=JPEG, timestamp=12.5)
        for device in service._unique_devices():
            device.capture_thread.latest_frame = frame
        # The classification camera is registered under both of its names.
        self.assertEqual(4, len(service.feeds))
        self.sample_collector.SampleCollector(gc, service)._captureOnce()
        return {meta["camera"]: meta for _, meta in self.saved}

    def test_each_physical_camera_is_sampled_once_under_its_canonical_role(self) -> None:
        by_role = self._cycle()
        self.assertEqual(3, len(self.saved))
        self.assertEqual({"c_channel_2", "c_channel_3", "classification_channel"}, set(by_role))
        self.assertEqual({"c_channel_2": 2, "c_channel_3": 3, "classification_channel": 4}, {role: meta["meta"]["camera"]["channel"] for role, meta in by_role.items()})

    def test_the_classification_sample_has_its_lamp_and_its_camera(self) -> None:
        info = self._cycle()["classification_channel"]["meta"]
        self.assertEqual("out:6", info["lamp"]["output"])
        self.assertEqual(80, info["lamp"]["brightness_percent"])
        self.assertEqual(2, info["camera"]["device_index"])
        self.assertEqual("model-2", info["camera"]["model"])
        self.assertEqual((1280, 720), (info["camera"]["capture_mode"]["width"], info["camera"]["capture_mode"]["height"]))

    def test_a_network_camera_is_never_identified_by_its_address(self) -> None:
        by_role = self._cycle(mkCameraConfig(url="rtsp://operator:hunter2@192.0.2.9/stream"))
        camera = by_role["c_channel_3"]["meta"]["camera"]
        self.assertEqual(3, camera["channel"])
        self.assertIsNone(camera["device_index"])
        self.assertIsNone(camera["model"])
        self.assertNotIn("hunter2", json.dumps(by_role))
        self.assertNotIn("192.0.2.9", json.dumps(by_role))


class CollectorScheduleTests(_StateTestCase):
    def _collector(self):
        (sample_collector,) = _reload("sample_collector")
        gc = SimpleNamespace(logger=SimpleNamespace(info=lambda *a: None, warning=lambda *a: None))
        return sample_collector.SampleCollector(gc, None)

    def test_hive_burst_is_the_fastest_allowed(self) -> None:
        self._targets("a")
        self.hive_limits.setTargetLimits("a", {"sample_burst_interval_s": 30})
        collector = self._collector()
        collector.setDecayConfig(burst_interval_s=5.0)
        status = collector.status()
        self.assertEqual(30.0, status["burst_interval_s"])
        self.assertEqual(5.0, status["local_settings"]["burst_interval_s"])

    def test_slower_local_settings_win_and_null_follows_hive_again(self) -> None:
        collector = self._collector()
        collector.setDecayConfig(burst_interval_s=60.0)
        self.assertEqual(60.0, collector.status()["burst_interval_s"])
        collector.setDecayConfig(burst_interval_s=None)
        self.assertEqual(10.0, collector.status()["burst_interval_s"])

    def test_values_the_old_version_saved_by_default_follow_hive(self) -> None:
        self.local_state.set_sample_collection_state({"enabled": True, "burst_interval_s": 10.0, "floor_interval_s": 3600.0, "ramp_hours": 72.0})
        self._targets("a")
        self.hive_limits.setTargetLimits("a", {"sample_floor_interval_s": 7200})
        status = self._collector().status()
        self.assertIsNone(status["local_settings"]["floor_interval_s"])
        self.assertEqual(7200.0, status["floor_interval_s"])


def _http_error(status: int, headers: dict | None = None) -> requests.HTTPError:
    response = requests.Response()
    response.status_code = status
    response.headers.update(headers or {})
    return requests.HTTPError(response=response)


class _FakeClient:
    def __init__(self, error: Exception | None = None) -> None:
        self.pushed: list[dict] = []
        self.error = error

    def pushSample(self, meta: dict, file_path: Path) -> int:
        if self.error is not None:
            raise self.error
        self.pushed.append(meta)
        return int(meta["local_id"])


class SyncSamplesTests(_StateTestCase):
    def setUp(self) -> None:
        super().setUp()
        (self.hive_sync,) = _reload("server.hive_sync")

    def _syncer(self, client: _FakeClient, wm: int = 0):
        hs = self.hive_sync
        syncer = hs._TargetSyncer.__new__(hs._TargetSyncer)
        syncer._gc = None
        syncer._id = "a"
        syncer._name = "test hive"
        syncer._client = client
        syncer._gate = hs._ConcurrencyGate(1, 1, lambda: False)
        syncer._stop = threading.Event()
        syncer._paused_until = {data_type: 0.0 for data_type in hs.DATA_TYPES}
        syncer._paused_why = {}
        syncer._budget_wait_s = None
        syncer._state_ok = True
        syncer._backoff_s = hs.SERVER_DOWN_BACKOFF_S
        syncer._last_error = None
        syncer._budget = hs._UploadBudget()
        syncer._budget.setLimits(10_000_000, 1000)
        syncer._wm = {data_type: 0 for data_type in hs.DATA_TYPES}
        syncer._wm[hs.DATA_TYPE_SAMPLES] = wm
        return syncer

    def _drain(self, syncer) -> bool:
        with patch.object(self.hive_sync, "telemetryAllows", return_value=True), patch.object(self.hive_sync, "_machineBusy", return_value=False):
            return syncer._drainSamples()

    def test_sends_in_order_with_camera_lamp_and_outline(self) -> None:
        self._write(2)
        client = _FakeClient()
        syncer = self._syncer(client)
        self.assertTrue(self._drain(syncer))
        self.assertEqual([1, 2], [meta["local_id"] for meta in client.pushed])
        self.assertEqual("classification_channel", client.pushed[0]["source_role"])
        self.assertEqual("sample-capture", client.pushed[0]["source_session_id"])
        self.assertEqual(2, syncer._wm[self.hive_sync.DATA_TYPE_SAMPLES])

    def test_evicted_samples_are_passed_over(self) -> None:
        self._write(2)
        self.sample_store.purgeAll()
        client = _FakeClient()
        syncer = self._syncer(client)
        self._drain(syncer)
        self.assertEqual([], client.pushed)
        self.assertEqual(2, syncer._wm[self.hive_sync.DATA_TYPE_SAMPLES])

    def test_backlog_is_cut_from_the_oldest_end(self) -> None:
        with patch.object(self.hive_sync, "SAMPLES_BACKLOG_MAX", 3):
            self._write(8)
            client = _FakeClient()
            syncer = self._syncer(client)
            while self._drain(syncer):
                pass
        self.assertEqual([6, 7, 8], [meta["local_id"] for meta in client.pushed])

    def test_backlog_is_cut_evenly_across_cameras(self) -> None:
        # The carousel camera takes most samples; a backlog cut keeps an even
        # share of each camera instead of starving the others.
        with patch.object(self.hive_sync, "SAMPLES_BACKLOG_MAX", 4):
            self._write(6, camera="classification_channel")  # ids 1-6
            self._write(1, camera="c_channel_2")  # id 7
            self._write(2, camera="c_channel_3")  # ids 8-9
            client = _FakeClient()
            syncer = self._syncer(client)
            while self._drain(syncer):
                pass
        self.assertEqual([5, 6, 7, 9], [meta["local_id"] for meta in client.pushed])
        self.assertEqual(9, syncer._wm[self.hive_sync.DATA_TYPE_SAMPLES])

    def test_even_drops_give_a_small_cameras_leftover_share_to_the_others(self) -> None:
        drops = self.hive_sync._evenDrops({"c4": 100, "c2": 3, "c3": 10}, 30)
        self.assertEqual({"c4": 83}, drops)
        self.assertEqual({}, self.hive_sync._evenDrops({"c4": 10, "c2": 3}, 30))

    def test_spent_budget_waits_for_the_refill(self) -> None:
        self._write(3, nbytes=1000)
        client = _FakeClient()
        syncer = self._syncer(client)
        syncer._budget = self.hive_sync._UploadBudget()
        syncer._budget.setLimits(10_000_000, 2)
        while self._drain(syncer):
            pass
        self.assertEqual(2, len(client.pushed))
        # The loop learns how long until the next file can go (one file at
        # two a minute: 30 s) instead of spinning.
        self.assertAlmostEqual(30.0, syncer._budget_wait_s, delta=1.0)

    def test_hive_without_the_route_turns_the_leg_off_for_a_while(self) -> None:
        hs = self.hive_sync
        self._write(1)
        syncer = self._syncer(_FakeClient(error=_http_error(404)))
        with self.assertRaises(requests.HTTPError) as caught:
            self._drain(syncer)
        self.assertTrue(syncer._pauseLeg(hs.DATA_TYPE_SAMPLES, caught.exception))
        self.assertGreater(syncer._paused_until[hs.DATA_TYPE_SAMPLES], time.monotonic() + hs.UNSUPPORTED_RETRY_S - 5)
        self.assertEqual([hs.DATA_TYPE_SAMPLES], syncer.status()["unsupported"])
        # A 5xx or a 429 is about the whole target: it backs off instead.
        self.assertFalse(syncer._pauseLeg(hs.DATA_TYPE_SAMPLES, _http_error(503)))
        self.assertFalse(syncer._pauseLeg(hs.DATA_TYPE_SAMPLES, _http_error(429)))

    def test_retry_after_sets_the_backoff(self) -> None:
        syncer = self._syncer(_FakeClient())
        syncer._backoff_s = self.hive_sync.SERVER_DOWN_BACKOFF_S
        syncer._state_ok = True
        syncer._noteBackoff(_http_error(429, {"Retry-After": "300"}))
        self.assertEqual(300.0, syncer._backoff_s)


class UploadBudgetTests(unittest.TestCase):
    def test_a_file_bigger_than_a_minute_still_goes_when_the_bucket_is_full(self) -> None:
        from server.hive_sync import _UploadBudget

        budget = _UploadBudget()
        budget.setLimits(1000, 10)
        self.assertTrue(budget.take(5000))
        self.assertFalse(budget.take(10))


if __name__ == "__main__":
    unittest.main()
