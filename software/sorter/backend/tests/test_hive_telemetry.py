import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import hive_telemetry
from hive_telemetry import (
    HiveTelemetryClient,
    TELEMETRY_FIELDS,
    TelemetryBlocked,
    defaultTelemetrySettings,
    getTargetTelemetrySettings,
    normalizeTelemetrySettings,
    resetTargetTelemetrySettings,
    setTargetTelemetrySettings,
    telemetryAllows,
    telemetryFieldList,
)

BACKEND_ROOT = Path(__file__).resolve().parent.parent

UPLOAD_ENDPOINT_MARKERS = (
    "/api/machine/upload",
    "/api/machine/sync",
    "/api/machine/set-progress",
    "/api/machine/heartbeat",
)

CHOKE_POINT_ALLOWLIST = {
    Path("hive_telemetry.py"),
    Path("tests/test_hive_telemetry.py"),
}


class _FakeResponse:
    def __init__(self, payload: dict) -> None:
        self._payload = payload
        self.status_code = 200

    def raise_for_status(self) -> None:
        pass

    def json(self) -> dict:
        return self._payload


class _RecordingSession:
    def __init__(self, payload: dict) -> None:
        self.payload = payload
        self.calls: list[dict] = []
        self.headers: dict = {}

    def request(self, method: str, url: str, **kwargs) -> _FakeResponse:
        self.calls.append({"method": method, "url": url, **kwargs})
        return _FakeResponse(self.payload)


def _client_with_session(payload: dict | None = None) -> tuple[HiveTelemetryClient, _RecordingSession]:
    client = HiveTelemetryClient("https://hive.example", "token", "target-a")
    session = _RecordingSession(payload or {"max_local_id": 1})
    client._session = session  # type: ignore[assignment]
    return client, session


def _settings(**overrides: bool) -> dict[str, bool]:
    settings = defaultTelemetrySettings()
    settings.update(overrides)
    return settings


class _InMemoryHiveConfig:
    def __init__(self, config: dict) -> None:
        self.config = config

    def get(self) -> dict:
        return self.config

    def set(self, config: dict) -> None:
        self.config = config


class TelemetrySettingsTests(unittest.TestCase):
    def setUp(self) -> None:
        store = _InMemoryHiveConfig(
            {
                "targets": [
                    {"id": "target-a", "url": "https://a.example", "api_token": "t", "enabled": True},
                    {"id": "target-b", "url": "https://b.example", "api_token": "t", "enabled": True},
                ],
                "primary_target_id": "target-a",
            }
        )
        import local_state

        self._patchers = [
            patch.object(local_state, "get_hive_config", store.get),
            patch.object(local_state, "set_hive_config", store.set),
        ]
        for patcher in self._patchers:
            patcher.start()

    def tearDown(self) -> None:
        for patcher in self._patchers:
            patcher.stop()

    def test_defaults_match_registry(self) -> None:
        defaults = defaultTelemetrySettings()
        self.assertEqual(
            {field["key"] for field in TELEMETRY_FIELDS},
            set(defaults.keys()),
        )
        self.assertTrue(all(defaults.values()))
        self.assertNotIn("machine_status", defaults)

    def test_normalize_ignores_junk(self) -> None:
        normalized = normalizeTelemetrySettings(
            {"detection_images": False, "full_frames": "yes", "bogus": True}
        )
        self.assertFalse(normalized["detection_images"])
        self.assertTrue(normalized["full_frames"])
        self.assertNotIn("bogus", normalized)

    def test_unknown_target_gets_defaults(self) -> None:
        self.assertEqual(defaultTelemetrySettings(), getTargetTelemetrySettings("nope"))

    def test_set_and_get_are_per_target(self) -> None:
        setTargetTelemetrySettings("target-a", {"detection_images": False})
        self.assertFalse(telemetryAllows("target-a", "detection_images"))
        self.assertTrue(telemetryAllows("target-b", "detection_images"))
        self.assertTrue(telemetryAllows("target-a", "piece_metadata"))

    def test_set_rejects_unknown_fields(self) -> None:
        with self.assertRaises(ValueError):
            setTargetTelemetrySettings("target-a", {"nope": True})

    def test_set_rejects_unknown_target(self) -> None:
        with self.assertRaises(ValueError):
            setTargetTelemetrySettings("nope", {"detection_images": False})

    def test_reset_restores_defaults(self) -> None:
        setTargetTelemetrySettings("target-a", {"detection_images": False, "full_frames": False})
        settings = resetTargetTelemetrySettings("target-a")
        self.assertEqual(defaultTelemetrySettings(), settings)
        self.assertEqual(defaultTelemetrySettings(), getTargetTelemetrySettings("target-a"))

    def test_field_list_is_registry(self) -> None:
        fields = telemetryFieldList()
        self.assertEqual([f["key"] for f in TELEMETRY_FIELDS], [f["key"] for f in fields])
        for field in fields:
            self.assertTrue(field["label"])
            self.assertTrue(field["description"])
            self.assertNotIn("enabled", field)


class TelemetryClientGatingTests(unittest.TestCase):
    def test_push_piece_records_blocked(self) -> None:
        client, session = _client_with_session()
        with patch.object(hive_telemetry, "getTargetTelemetrySettings", return_value=_settings(piece_metadata=False)):
            with self.assertRaises(TelemetryBlocked) as ctx:
                client.pushPieceRecords([{"piece_uuid": "x"}])
        self.assertEqual("piece_metadata", ctx.exception.field)
        self.assertEqual([], session.calls)

    def test_push_piece_image_blocked(self) -> None:
        client, session = _client_with_session()
        with patch.object(hive_telemetry, "getTargetTelemetrySettings", return_value=_settings(detection_images=False)):
            with self.assertRaises(TelemetryBlocked):
                client.pushPieceImage({"piece_uuid": "x"}, None)
        self.assertEqual([], session.calls)

    def test_push_set_progress_blocked(self) -> None:
        client, session = _client_with_session()
        with patch.object(hive_telemetry, "getTargetTelemetrySettings", return_value=_settings(piece_metadata=False)):
            with self.assertRaises(TelemetryBlocked):
                client.pushSetProgress({"version_id": "v"})
        self.assertEqual([], session.calls)

    def test_upload_sample_blocked_without_detection_images(self) -> None:
        client, session = _client_with_session()
        with tempfile.TemporaryDirectory() as tmp:
            image = Path(tmp) / "crop.jpg"
            image.write_bytes(b"jpg")
            with patch.object(hive_telemetry, "getTargetTelemetrySettings", return_value=_settings(detection_images=False)):
                with self.assertRaises(TelemetryBlocked):
                    client.uploadSample(
                        source_session_id="s",
                        local_sample_id="a",
                        image_path=image,
                    )
        self.assertEqual([], session.calls)

    def test_upload_sample_strips_full_frames_when_disabled(self) -> None:
        client, session = _client_with_session(payload={"ok": True})
        with tempfile.TemporaryDirectory() as tmp:
            image = Path(tmp) / "crop.jpg"
            frame = Path(tmp) / "frame.jpg"
            overlay = Path(tmp) / "overlay.jpg"
            for path in (image, frame, overlay):
                path.write_bytes(b"jpg")
            with patch.object(hive_telemetry, "getTargetTelemetrySettings", return_value=_settings(full_frames=False)):
                client.uploadSample(
                    source_session_id="s",
                    local_sample_id="a",
                    image_path=image,
                    full_frame_path=frame,
                    overlay_path=overlay,
                )
        self.assertEqual(1, len(session.calls))
        files = session.calls[0]["files"]
        self.assertIn("image", files)
        self.assertNotIn("full_frame", files)
        self.assertNotIn("overlay", files)

    def test_upload_sample_includes_full_frames_when_enabled(self) -> None:
        client, session = _client_with_session(payload={"ok": True})
        with tempfile.TemporaryDirectory() as tmp:
            image = Path(tmp) / "crop.jpg"
            frame = Path(tmp) / "frame.jpg"
            for path in (image, frame):
                path.write_bytes(b"jpg")
            with patch.object(hive_telemetry, "getTargetTelemetrySettings", return_value=_settings()):
                client.uploadSample(
                    source_session_id="s",
                    local_sample_id="a",
                    image_path=image,
                    full_frame_path=frame,
                )
        files = session.calls[0]["files"]
        self.assertIn("image", files)
        self.assertIn("full_frame", files)

    def test_get_sync_state_is_not_gated(self) -> None:
        client, session = _client_with_session(payload={"piece_records": {"max_local_id": 0}})
        all_off = {key: False for key in defaultTelemetrySettings()}
        with patch.object(hive_telemetry, "getTargetTelemetrySettings", return_value=all_off):
            client.getSyncState()
        self.assertEqual(1, len(session.calls))


class ChokePointTests(unittest.TestCase):
    def test_upload_endpoints_only_referenced_in_hive_telemetry(self) -> None:
        offenders: list[str] = []
        for path in BACKEND_ROOT.rglob("*.py"):
            relative = path.relative_to(BACKEND_ROOT)
            if relative in CHOKE_POINT_ALLOWLIST:
                continue
            if relative.parts and relative.parts[0] in (".venv", "venv", "__pycache__"):
                continue
            try:
                source = path.read_text()
            except (OSError, UnicodeDecodeError):
                continue
            for marker in UPLOAD_ENDPOINT_MARKERS:
                if marker in source:
                    offenders.append(f"{relative}: {marker}")
        self.assertEqual(
            [],
            offenders,
            "Hive upload endpoints must only be called through hive_telemetry.HiveTelemetryClient "
            "so telemetry settings cannot be bypassed. Move these requests behind the choke point: "
            + "; ".join(offenders),
        )


if __name__ == "__main__":
    unittest.main()
