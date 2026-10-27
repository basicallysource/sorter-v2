import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import requests

import hive_uploads
import sharing
from hive_uploads import HiveUploads, StreamBlocked

BACKEND_ROOT = Path(__file__).resolve().parent.parent

UPLOAD_ENDPOINT_MARKERS = (
    "/api/machine/upload",
    "/api/machine/sync",
    "/api/machine/set-progress",
    "/api/machine/heartbeat",
)

CHOKE_POINT_ALLOWLIST = {
    Path("hive_uploads.py"),
    Path("tests/test_hive_uploads.py"),
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


def _client_with_session(payload: dict | None = None) -> tuple[HiveUploads, _RecordingSession]:
    client = HiveUploads("https://hive.example", "token", "target-a")
    session = _RecordingSession(payload or {"max_local_id": 1})
    client._session = session  # type: ignore[assignment]
    return client, session


def _allowing(**overrides: bool):
    """streamAllowed with every stream on but those named."""
    def allowed(_target_id: str, stream: str) -> bool:
        return overrides.get(stream, True)
    return patch.object(sharing, "streamAllowed", allowed)


class TelemetryClientGatingTests(unittest.TestCase):
    def test_push_piece_records_blocked(self) -> None:
        client, session = _client_with_session()
        with _allowing(piece_records=False):
            with self.assertRaises(StreamBlocked) as ctx:
                client.pushPieceRecords([{"piece_uuid": "x"}])
        self.assertEqual("piece_records", ctx.exception.stream)
        self.assertEqual([], session.calls)

    def test_push_piece_image_blocked(self) -> None:
        client, session = _client_with_session()
        with _allowing(piece_images=False):
            with self.assertRaises(StreamBlocked):
                client.pushPieceImage({"piece_uuid": "x"}, None)
        self.assertEqual([], session.calls)

    def test_push_set_progress_blocked(self) -> None:
        client, session = _client_with_session()
        with _allowing(piece_records=False):
            with self.assertRaises(StreamBlocked):
                client.pushSetProgress({"version_id": "v"})
        self.assertEqual([], session.calls)

    def test_push_sample_blocked_without_full_frames(self) -> None:
        client, session = _client_with_session()
        with tempfile.TemporaryDirectory() as tmp:
            image = Path(tmp) / "1.jpg"
            image.write_bytes(b"\xff\xd8\xff" + b"jpg")
            with _allowing(camera_frames=False):
                with self.assertRaises(StreamBlocked) as ctx:
                    client.pushSample({"local_id": 1}, image)
        self.assertEqual("camera_frames", ctx.exception.stream)
        self.assertEqual([], session.calls)

    def test_push_sample_sends_its_image(self) -> None:
        client, session = _client_with_session(payload={"max_local_id": 7})
        with tempfile.TemporaryDirectory() as tmp:
            image = Path(tmp) / "7.jpg"
            image.write_bytes(b"\xff\xd8\xff" + b"jpg")
            with _allowing():
                self.assertEqual(7, client.pushSample({"local_id": 7, "bytes": 6}, image))
        call = session.calls[0]
        self.assertTrue(call["url"].endswith("/api/machine/sync/sample"))
        self.assertIn("image", call["files"])

    def test_push_sample_without_a_readable_image_sends_nothing(self) -> None:
        client, session = _client_with_session(payload={"max_local_id": 7})
        with tempfile.TemporaryDirectory() as tmp:
            image = Path(tmp) / "7.jpg"
            image.write_bytes(b"not a jpeg")
            with _allowing():
                with self.assertRaises(FileNotFoundError):
                    client.pushSample({"local_id": 7}, image)
        self.assertEqual([], session.calls)

    def test_get_sync_state_is_not_gated(self) -> None:
        client, session = _client_with_session(payload={"piece_records": {"max_local_id": 0}})
        with patch.object(sharing, "streamAllowed", lambda _t, _s: False):
            client.getSyncState()
        self.assertEqual(1, len(session.calls))

    def test_push_telemetry_rides_machine_telemetry(self) -> None:
        client, session = _client_with_session(payload={"max_local_id": 3})
        with _allowing():
            self.assertEqual(3, client.pushTelemetry([{"local_id": 3, "kind": "stepper_load"}]))
        call = session.calls[0]
        self.assertTrue(call["url"].endswith("/api/machine/sync/telemetry"))
        self.assertEqual(len(call["data"]), client.last_body_bytes)
        with _allowing(machine_telemetry=False):
            with self.assertRaises(StreamBlocked):
                client.pushTelemetry([{"local_id": 4}])


class ChokePointTests(unittest.TestCase):
    def test_upload_endpoints_only_referenced_in_hive_uploads(self) -> None:
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
            "Hive upload endpoints must only be called through hive_uploads.HiveUploads "
            "so sharing choices cannot be bypassed. Move these requests behind the choke point: "
            + "; ".join(offenders),
        )




_JPEG = b"\xff\xd8\xff" + b"\x00" * 16 + b"\xff\xd9"


class _StatusResponse(_FakeResponse):
    def __init__(self, payload: dict, status: int) -> None:
        super().__init__(payload)
        self.status_code = status

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise requests.HTTPError(str(self.status_code), response=self)  # type: ignore[arg-type]


class _RefusingSession(_RecordingSession):
    """Answers `status` to requests that carry a file (or to every request)."""

    def __init__(self, payload: dict, status: int, refuse_all: bool = False) -> None:
        super().__init__(payload)
        self.status = status
        self.refuse_all = refuse_all

    def request(self, method: str, url: str, **kwargs) -> _FakeResponse:
        self.calls.append({"method": method, "url": url, **kwargs})
        if self.refuse_all or kwargs.get("files"):
            return _StatusResponse(self.payload, self.status)
        return _FakeResponse(self.payload)


class SyncFileGuardTests(unittest.TestCase):
    def _push_image(self, client: HiveUploads, content: bytes | None = None, *, recorded: int | None = None, sparse: int | None = None) -> int:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "00_c4_burst.jpg"
            if sparse is not None:
                with open(path, "wb") as handle:
                    handle.truncate(sparse)
            else:
                path.write_bytes(content or b"")
            size = path.stat().st_size
            meta = {"local_id": 7, "bytes": size if recorded is None else recorded}
            with _allowing():
                return client.pushPieceImage(meta, path)

    def test_valid_jpeg_is_uploaded(self) -> None:
        client, session = _client_with_session()
        self._push_image(client, _JPEG)
        self.assertEqual(_JPEG, session.calls[0]["files"]["image"][1])

    def test_file_over_the_limit_is_not_read(self) -> None:
        client, session = _client_with_session()
        with patch.object(hive_uploads, "open", side_effect=AssertionError("must not read"), create=True):
            self._push_image(client, sparse=hive_uploads.MAX_SYNC_IMAGE_BYTES + 1)
        self.assertEqual(1, len(session.calls))
        self.assertIsNone(session.calls[0]["files"])

    def test_size_differing_from_recorded_is_sent_metadata_only(self) -> None:
        client, session = _client_with_session()
        self._push_image(client, _JPEG, recorded=len(_JPEG) + 3)
        self.assertIsNone(session.calls[0]["files"])

    def test_non_jpeg_contents_are_sent_metadata_only(self) -> None:
        client, session = _client_with_session()
        self._push_image(client, b"\x00\x13garbage from a bad card")
        self.assertIsNone(session.calls[0]["files"])
        self.assertIn("metadata", session.calls[0]["data"])

    def test_missing_file_is_sent_metadata_only(self) -> None:
        client, session = _client_with_session()
        with _allowing():
            client.pushPieceImage({"local_id": 7, "bytes": 10}, Path("/nonexistent/00_c4_burst.jpg"))
        self.assertIsNone(session.calls[0]["files"])

    def test_refused_file_is_resent_metadata_only(self) -> None:
        for status in (400, 413):
            client = HiveUploads("https://hive.example", "token", "target-a")
            session = _RefusingSession({"max_local_id": 7}, status)
            client._session = session  # type: ignore[assignment]
            self.assertEqual(7, self._push_image(client, _JPEG))
            self.assertEqual(2, len(session.calls))
            self.assertIsNotNone(session.calls[0]["files"])
            self.assertIsNone(session.calls[1]["files"])

    def test_refused_metadata_still_raises(self) -> None:
        client = HiveUploads("https://hive.example", "token", "target-a")
        client._session = _RefusingSession({"max_local_id": 7}, 400, refuse_all=True)  # type: ignore[assignment]
        with self.assertRaises(requests.HTTPError):
            self._push_image(client, _JPEG)

    def test_other_errors_are_not_retried(self) -> None:
        client = HiveUploads("https://hive.example", "token", "target-a")
        session = _RefusingSession({"max_local_id": 7}, 500)
        client._session = session  # type: ignore[assignment]
        with self.assertRaises(requests.HTTPError):
            self._push_image(client, _JPEG)
        self.assertEqual(1, len(session.calls))

    def test_control_data_needs_gzip_contents(self) -> None:
        for content, uploaded in ((b"\x1f\x8b\x08rest", True), (b"not gzip", False)):
            client, session = _client_with_session()
            with tempfile.TemporaryDirectory() as tmp:
                path = Path(tmp) / "segment.jsonl.gz"
                path.write_bytes(content)
                with _allowing():
                    client.pushControlDataSegment({"local_id": 3, "bytes": len(content)}, path)
            self.assertEqual(uploaded, session.calls[0]["files"] is not None)

    def test_segment_may_exceed_the_image_limit(self) -> None:
        client, session = _client_with_session()
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "segment.jsonl.gz"
            with open(path, "wb") as handle:
                handle.write(b"\x1f\x8b\x08")
                handle.truncate(hive_uploads.MAX_SYNC_IMAGE_BYTES + 1)
            with _allowing():
                client.pushControlDataSegment({"local_id": 3, "bytes": path.stat().st_size}, path)
        self.assertIsNotNone(session.calls[0]["files"])


class _PostRecordingSession:
    def __init__(self, reply: dict | None = None) -> None:
        self.posts: list[dict] = []
        self.headers: dict = {}
        self.reply = reply if reply is not None else {"ok": True}

    def post(self, url: str, **kwargs) -> _FakeResponse:
        self.posts.append({"url": url, **kwargs})
        response = _FakeResponse(self.reply)
        response.ok = True  # type: ignore[attr-defined]
        return response


class HeartbeatBodyTests(unittest.TestCase):
    NETWORK = {"version": 1, "networks": [{"kind": "wifi", "address": "192.168.1.68"}]}
    SPECS = {"schema_version": 3}

    def _beat(self, allowing, **kwargs) -> dict | None:
        client = HiveUploads("https://hive.example", "token", "target-a")
        session = _PostRecordingSession()
        client._session = session  # type: ignore[assignment]
        with allowing:
            reachable, _reply = client.heartbeat(**kwargs)
        self.assertTrue(reachable)
        return session.posts[0]["json"]

    def test_network_rides_a_beat_without_specs(self) -> None:
        self.assertEqual({"network": self.NETWORK}, self._beat(_allowing(), network=self.NETWORK))

    def test_specs_ride_only_when_given(self) -> None:
        body = self._beat(_allowing(), network=self.NETWORK, machine_specs=self.SPECS)
        self.assertEqual({"network": self.NETWORK, "hardware_info": self.SPECS}, body)

    def test_network_stream_off_sends_null(self) -> None:
        # null, not absent: Hive drops the addresses it already has.
        body = self._beat(_allowing(network=False), network=self.NETWORK, machine_specs=self.SPECS)
        self.assertEqual({"network": None, "hardware_info": self.SPECS}, body)

    def test_before_consent_only_the_keep_alive_goes(self) -> None:
        nothing = patch.object(sharing, "streamAllowed", lambda _t, _s: False)
        self.assertEqual({"network": None}, self._beat(nothing, network=self.NETWORK, machine_specs=self.SPECS))
        nothing = patch.object(sharing, "streamAllowed", lambda _t, _s: False)
        self.assertIsNone(self._beat(nothing, machine_specs=self.SPECS))

    def test_reply_is_returned(self) -> None:
        client = HiveUploads("https://hive.example", "token", "target-a")
        client._session = _PostRecordingSession({"ok": True, "limits": {"upload_files_per_minute": 30}})  # type: ignore[assignment]
        with _allowing():
            reachable, reply = client.heartbeat(network=self.NETWORK)
        self.assertTrue(reachable)
        self.assertEqual({"upload_files_per_minute": 30}, reply["limits"])


if __name__ == "__main__":
    unittest.main()
