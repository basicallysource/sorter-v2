import os
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
    getTelemetrySettings,
    normalizeTelemetrySettings,
    setTelemetrySettings,
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
    client = HiveTelemetryClient("https://hive.example", "token")
    session = _RecordingSession(payload or {"max_local_id": 1})
    client._session = session  # type: ignore[assignment]
    return client, session


def _settings(**overrides: bool) -> dict[str, bool]:
    settings = defaultTelemetrySettings()
    settings.update(overrides)
    return settings


class TelemetrySettingsTests(unittest.TestCase):
    def setUp(self) -> None:
        self._old_db = os.environ.get("LOCAL_STATE_DB_PATH")
        self._tmpdir = tempfile.TemporaryDirectory()
        os.environ["LOCAL_STATE_DB_PATH"] = str(Path(self._tmpdir.name) / "state.sqlite")

    def tearDown(self) -> None:
        if self._old_db is None:
            os.environ.pop("LOCAL_STATE_DB_PATH", None)
        else:
            os.environ["LOCAL_STATE_DB_PATH"] = self._old_db
        self._tmpdir.cleanup()

    def test_defaults_match_registry(self) -> None:
        defaults = defaultTelemetrySettings()
        self.assertEqual(
            {field["key"] for field in TELEMETRY_FIELDS},
            set(defaults.keys()),
        )
        self.assertFalse(defaults["machine_status"])
        self.assertTrue(defaults["detection_images"])

    def test_normalize_ignores_junk(self) -> None:
        normalized = normalizeTelemetrySettings(
            {"detection_images": False, "full_frames": "yes", "bogus": True}
        )
        self.assertFalse(normalized["detection_images"])
        self.assertEqual(normalized["full_frames"], defaultTelemetrySettings()["full_frames"])
        self.assertNotIn("bogus", normalized)

    def test_set_and_get_roundtrip(self) -> None:
        setTelemetrySettings({"detection_images": False, "machine_status": True})
        settings = getTelemetrySettings()
        self.assertFalse(settings["detection_images"])
        self.assertTrue(settings["machine_status"])
        self.assertFalse(telemetryAllows("detection_images"))
        self.assertTrue(telemetryAllows("piece_metadata"))

    def test_set_rejects_unknown_fields(self) -> None:
        with self.assertRaises(ValueError):
            setTelemetrySettings({"nope": True})

    def test_field_list_reflects_settings(self) -> None:
        setTelemetrySettings({"full_frames": False})
        by_key = {field["key"]: field for field in telemetryFieldList()}
        self.assertFalse(by_key["full_frames"]["enabled"])
        self.assertTrue(by_key["detection_images"]["enabled"])
        for field in by_key.values():
            self.assertTrue(field["label"])
            self.assertTrue(field["description"])


class TelemetryClientGatingTests(unittest.TestCase):
    def test_push_piece_records_blocked(self) -> None:
        client, session = _client_with_session()
        with patch.object(hive_telemetry, "getTelemetrySettings", return_value=_settings(piece_metadata=False)):
            with self.assertRaises(TelemetryBlocked) as ctx:
                client.pushPieceRecords([{"piece_uuid": "x"}])
        self.assertEqual("piece_metadata", ctx.exception.field)
        self.assertEqual([], session.calls)

    def test_push_piece_image_blocked(self) -> None:
        client, session = _client_with_session()
        with patch.object(hive_telemetry, "getTelemetrySettings", return_value=_settings(detection_images=False)):
            with self.assertRaises(TelemetryBlocked):
                client.pushPieceImage({"piece_uuid": "x"}, None)
        self.assertEqual([], session.calls)

    def test_push_set_progress_blocked(self) -> None:
        client, session = _client_with_session()
        with patch.object(hive_telemetry, "getTelemetrySettings", return_value=_settings(piece_metadata=False)):
            with self.assertRaises(TelemetryBlocked):
                client.pushSetProgress({"version_id": "v"})
        self.assertEqual([], session.calls)

    def test_upload_sample_blocked_without_detection_images(self) -> None:
        client, session = _client_with_session()
        with tempfile.TemporaryDirectory() as tmp:
            image = Path(tmp) / "crop.jpg"
            image.write_bytes(b"jpg")
            with patch.object(hive_telemetry, "getTelemetrySettings", return_value=_settings(detection_images=False)):
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
            with patch.object(hive_telemetry, "getTelemetrySettings", return_value=_settings(full_frames=False)):
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
            with patch.object(hive_telemetry, "getTelemetrySettings", return_value=_settings()):
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
        with patch.object(hive_telemetry, "getTelemetrySettings", return_value=all_off):
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
