"""The only code that talks to a Hive's machine endpoints: the sync uploads,
set progress and the heartbeat.

Every request names the sharing stream it carries (sharing.py), and a stream
that is off for the target, or anything before the person agreed to what is
shared, blocks the request here: at send time, so a choice also applies to
uploads already queued. tests/test_hive_uploads.py fails if another module
calls these endpoints itself.

Adding a kind of upload means adding (or choosing) its stream in sharing.py and
a method here that names it.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

import requests

import sharing

log = logging.getLogger(__name__)


class StreamBlocked(Exception):
    def __init__(self, stream: str) -> None:
        super().__init__(f"'{stream}' is not shared with this Hive.")
        self.stream = stream


# Hive's own limits for a sync row's file (services/storage.py: MAX_FILE_SIZE for
# images, MAX_CONTROL_DATA_FILE_SIZE for control data), under the 100 MB body
# limit of the Cloudflare proxy in front of it. Hive cannot accept anything
# larger, and a file far larger has a corrupted size (seen on a failing SD card:
# 1 KB crops reporting 2 GB to 6 TB) that would pull that much into memory on
# every retry.
MAX_SYNC_IMAGE_BYTES = 10 * 1024 * 1024
MAX_SYNC_SEGMENT_BYTES = 90 * 1024 * 1024

# A batch of channel crops is one upload and one stored file on Hive, each
# crop a byte range in it. Hive refuses a batch over this size.
MAX_CROP_BATCH_BYTES = 4 * 1024 * 1024

# The leading bytes Hive checks before it accepts a file.
_JPEG_MAGIC = b"\xff\xd8\xff"
_GZIP_MAGIC = b"\x1f\x8b"


def _readSyncFile(file_path: Path | None, expected_bytes: Any, magic: bytes, max_bytes: int) -> bytes | None:
    """Return the file to upload with a sync row, or None to send the row
    metadata-only: the file is missing, unreadable, not the size the row
    recorded, over max_bytes, or not the format Hive accepts. Hive would refuse
    it (413/400) and the sync would retry that row forever."""
    if file_path is None:
        return None
    try:
        if not file_path.is_file():
            return None
        size = file_path.stat().st_size
        if size > max_bytes:
            problem = f"is {size} bytes, over the {max_bytes} limit"
        elif isinstance(expected_bytes, int) and not isinstance(expected_bytes, bool) and expected_bytes > 0 and size != expected_bytes:
            problem = f"is {size} bytes, {expected_bytes} recorded"
        else:
            with open(file_path, "rb") as handle:
                data = handle.read()
            if data.startswith(magic):
                return data
            problem = "is not the expected format"
    except OSError as exc:
        problem = f"is unreadable ({exc.strerror or exc})"
    log.warning("hive_sync: sending %s metadata-only: file %s", file_path, problem)
    return None


class HiveUploads:
    def __init__(self, url: str, api_token: str, target_id: str) -> None:
        self._url = url.rstrip("/")
        self._target_id = target_id
        self._session = requests.Session()
        self._session.headers["Authorization"] = f"Bearer {api_token}"
        # The size of the last batch of rows sent, for upload_stats.
        self.last_body_bytes = 0

    def _request(
        self,
        method: str,
        path: str,
        *,
        stream: str | None,
        timeout: float,
        **kwargs: Any,
    ) -> requests.Response:
        if stream is not None and not sharing.streamAllowed(self._target_id, stream):
            raise StreamBlocked(stream)
        response = self._session.request(method, f"{self._url}{path}", timeout=timeout, **kwargs)
        response.raise_for_status()
        return response

    def _postSyncRow(
        self,
        path: str,
        *,
        stream: str,
        meta: dict[str, Any],
        files: dict[str, Any] | None,
        timeout: float,
    ) -> requests.Response:
        data = {"metadata": json.dumps(meta)}
        try:
            return self._request("POST", path, stream=stream, data=data, files=files, timeout=timeout)
        except requests.HTTPError as exc:
            status = exc.response.status_code if exc.response is not None else None
            if files is None or status not in (400, 413):
                raise
        # Hive refused the file itself (too large, or not a valid image). Send the
        # row without it so one bad file cannot stall the sync. A metadata problem
        # fails again here and backs off as before.
        log.warning(
            "hive_sync: %s refused the file for local_id %s (HTTP %s); sending the row metadata-only",
            path, meta.get("local_id"), status,
        )
        return self._request("POST", path, stream=stream, data=data, files=None, timeout=timeout)

    def _pushRows(self, path: str, stream: str, body: dict[str, Any]) -> int:
        # Encoded here, as requests would (no NaN), so its size is known.
        encoded = json.dumps(body, separators=(",", ":"), allow_nan=False).encode()
        self.last_body_bytes = len(encoded)
        response = self._request(
            "POST", path, stream=stream, data=encoded,
            headers={"Content-Type": "application/json"}, timeout=60,
        )
        return int(response.json()["max_local_id"])

    def getSyncState(self) -> dict[str, Any]:
        return self._request("GET", "/api/machine/sync/state", stream=None, timeout=15).json()

    def getDefaults(self, etag: str | None = None) -> dict[str, Any] | None:
        """The Hive's block of defaults (hive_defaults.py), or None when it
        answers that the block with `etag` is still current. A download, so
        no stream gates it."""
        headers = {"If-None-Match": etag} if etag else None
        response = self._session.get(f"{self._url}/api/machine/defaults", headers=headers, timeout=15)
        if response.status_code == 304:
            return None
        response.raise_for_status()
        return response.json()

    def pushTelemetry(self, records: list[dict[str, Any]]) -> int:
        return self._pushRows("/api/machine/sync/telemetry", "machine_telemetry", {"records": records})

    def pushPieceRecords(self, records: list[dict[str, Any]]) -> int:
        return self._pushRows("/api/machine/sync/piece-records", "piece_records", {"records": records})

    def pushTrainingRuns(self, runs: list[dict[str, Any]]) -> int:
        return self._pushRows("/api/machine/sync/training-runs", "piece_records", {"records": runs})

    def pushSortingRuns(self, sorting_set: dict[str, Any]) -> int:
        """Every lot and sorting run, as one set; Hive answers with the
        version it now keeps."""
        return self._pushRows("/api/machine/sync/sorting-runs", "piece_records", sorting_set)

    def pushPiecePredictions(self, records: list[dict[str, Any]]) -> int:
        return self._pushRows("/api/machine/sync/piece-predictions", "piece_records", {"records": records})

    def pushPieceImage(self, meta: dict[str, Any], file_path: Path | None) -> int:
        image = _readSyncFile(file_path, meta.get("bytes"), _JPEG_MAGIC, MAX_SYNC_IMAGE_BYTES)
        response = self._postSyncRow(
            "/api/machine/sync/piece-image",
            stream="piece_images",
            meta=meta,
            files={"image": (file_path.name, image, "image/jpeg")} if image is not None else None,
            timeout=60,
        )
        return int(response.json()["max_local_id"])

    def pushChannelCrop(self, meta: dict[str, Any], file_path: Path | None) -> int:
        image = _readSyncFile(file_path, meta.get("bytes"), _JPEG_MAGIC, MAX_SYNC_IMAGE_BYTES)
        response = self._postSyncRow(
            "/api/machine/sync/channel-crop",
            stream="channel_crops",
            meta=meta,
            files={"image": (file_path.name, image, "image/jpeg")} if image is not None else None,
            timeout=60,
        )
        return int(response.json()["max_local_id"])

    def pushChannelCropBatch(self, crops: list[tuple[dict[str, Any], Path | None]]) -> int:
        """Send several crops in one request: their JPEGs back to back in one
        file, each crop's metadata naming its range in it (offset, length). A
        crop whose file is missing or unreadable goes metadata-only, as with
        pushChannelCrop."""
        blob = bytearray()
        metas = []
        for meta, file_path in crops:
            image = _readSyncFile(file_path, meta.get("bytes"), _JPEG_MAGIC, MAX_SYNC_IMAGE_BYTES)
            entry = dict(meta)
            if image is not None and len(blob) + len(image) <= MAX_CROP_BATCH_BYTES:
                entry["offset"], entry["length"] = len(blob), len(image)
                blob += image
            metas.append(entry)
        response = self._request(
            "POST",
            "/api/machine/sync/channel-crop-batch",
            stream="channel_crops",
            data={"metadata": json.dumps({"crops": metas})},
            files={"crops": ("crops.bin", bytes(blob), "application/octet-stream")} if blob else None,
            timeout=120,
        )
        return int(response.json()["max_local_id"])

    def pushControlDataSegment(self, meta: dict[str, Any], file_path: Path | None) -> int:
        segment = _readSyncFile(file_path, meta.get("bytes"), _GZIP_MAGIC, MAX_SYNC_SEGMENT_BYTES)
        response = self._postSyncRow(
            "/api/machine/sync/control-data-segment",
            stream="feeder_logs",
            meta=meta,
            files={"data": (file_path.name, segment, "application/gzip")} if segment is not None else None,
            timeout=120,
        )
        return int(response.json()["max_local_id"])

    def pushSetProgress(self, payload: dict[str, Any]) -> None:
        self._request(
            "POST",
            "/api/machine/set-progress",
            stream="piece_records",
            json=payload,
            timeout=15,
        )

    def pushSample(self, meta: dict[str, Any], file_path: Path) -> int:
        # A sample is a whole camera frame. Unlike the other sync rows it is
        # never sent without its image: Hive keeps no sample without one.
        image = _readSyncFile(file_path, meta.get("bytes"), _JPEG_MAGIC, MAX_SYNC_IMAGE_BYTES)
        if image is None:
            raise FileNotFoundError(f"sample image unreadable: {file_path}")
        response = self._request(
            "POST",
            "/api/machine/sync/sample",
            stream="camera_frames",
            data={"metadata": json.dumps(meta)},
            files={"image": (file_path.name, image, "image/jpeg")},
            timeout=60,
        )
        return int(response.json()["max_local_id"])

    def heartbeat(
        self,
        *,
        network: dict[str, Any] | None = None,
        machine_specs: dict[str, Any] | None = None,
    ) -> tuple[bool, dict[str, Any] | None]:
        # Keep-alive so target reachability shows in the UI, sent whatever is
        # shared. It carries where to find the Sorter on its networks (every
        # beat; it is small) while that stream is on, and a machine-specs
        # snapshot when one is supplied (only to a Hive that does not take
        # telemetry records yet, see hive_heartbeat). Returns (reachable,
        # Hive's reply), the reply carrying the limits Hive sets for this
        # machine (see hive_limits.py).
        body: dict[str, Any] = {}
        if network is not None:
            # With the stream off the key is sent as null, which tells Hive to
            # forget the addresses it already has.
            body["network"] = network if sharing.streamAllowed(self._target_id, "network") else None
        if machine_specs is not None and sharing.streamAllowed(self._target_id, "machine_telemetry"):
            body["hardware_info"] = machine_specs
        try:
            response = self._session.post(f"{self._url}/api/machine/heartbeat", json=body or None, timeout=10)
        except requests.RequestException:
            return False, None
        reply: dict[str, Any] | None = None
        if response.ok:
            try:
                parsed = response.json()
                reply = parsed if isinstance(parsed, dict) else None
            except ValueError:
                reply = None
        return response.status_code < 500, reply
