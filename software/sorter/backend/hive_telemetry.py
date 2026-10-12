"""Single choke point for everything this machine uploads to Hive targets.

Every upload request declares which telemetry fields it carries, and a field
that is disabled for the target blocks the request here — at send time, so a
toggle also applies to jobs that were already queued. No other module may talk
to the Hive upload endpoints directly; tests/test_hive_telemetry.py fails if
one does.

The field registry below is the source of truth for what CAN leave the
machine. Settings are per Hive target, stored on the target entry in the hive
config. Adding a new kind of upload means adding a field here and routing the
request through HiveTelemetryClient with that field declared.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

import requests

log = logging.getLogger(__name__)

TELEMETRY_FIELDS: tuple[dict[str, Any], ...] = (
    {
        "key": "detection_images",
        "label": "Detection images",
        "description": "Cropped pictures of individual pieces: the per-piece image history.",
        "default": True,
    },
    {
        "key": "full_frames",
        "label": "Full camera frames",
        "description": "Training samples: whole camera frames taken while sorting, with the camera's settings, the lamp's brightness and the channel outline at the time.",
        "default": True,
    },
    {
        "key": "piece_metadata",
        "label": "Piece metadata",
        "description": "Classification results per piece (part, color, confidence, bin, timestamps), every part and color prediction with its score, your corrections, and set sorting progress.",
        "default": True,
    },
    {
        "key": "upstream_channel_crops",
        "label": "Channel crops (C2/C3)",
        "description": "Unlabeled bbox crops of pieces on the upstream feeder channels, tagged with position for same-piece lookup. High volume.",
        "default": True,
    },
    {
        "key": "feeder_dynamics",
        "label": "Feeder dynamics (control data)",
        "description": "Compressed logs of piece positions (from the vision model) and motor commands while sorting, stamped with the machine's settings at capture time. No images. Used to improve feeder control.",
        "default": True,
    },
    {
        "key": "machine_specs",
        "label": "Machine specs",
        "description": "Basic hardware and software details — camera, controller board, platform, operating system, and per-camera calibration state — shown on the machine's dashboard and used for compatibility and support.",
        "default": True,
    },
    {
        "key": "network",
        "label": "Network addresses",
        "description": "Where to find this Sorter on your networks: its local addresses, Wi-Fi name, hostname and ports. Shown on its Hive page so you can open it from there.",
        "default": True,
    },
)

_TELEMETRY_FIELD_KEYS = tuple(field["key"] for field in TELEMETRY_FIELDS)


def defaultTelemetrySettings() -> dict[str, bool]:
    return {field["key"]: bool(field["default"]) for field in TELEMETRY_FIELDS}


def normalizeTelemetrySettings(raw: Any) -> dict[str, bool]:
    settings = defaultTelemetrySettings()
    if isinstance(raw, dict):
        for key in _TELEMETRY_FIELD_KEYS:
            value = raw.get(key)
            if isinstance(value, bool):
                settings[key] = value
    return settings


def _findTarget(config: dict[str, Any] | None, target_id: str) -> dict[str, Any] | None:
    targets = config.get("targets") if isinstance(config, dict) else None
    if not isinstance(targets, list):
        return None
    for target in targets:
        if isinstance(target, dict) and target.get("id") == target_id:
            return target
    return None


def getTargetTelemetrySettings(target_id: str) -> dict[str, bool]:
    from local_state import get_hive_config

    target = _findTarget(get_hive_config(), target_id)
    return normalizeTelemetrySettings(target.get("telemetry") if target else None)


def setTargetTelemetrySettings(target_id: str, updates: dict[str, Any]) -> dict[str, bool]:
    unknown = sorted(key for key in updates if key not in _TELEMETRY_FIELD_KEYS)
    if unknown:
        raise ValueError(f"Unknown telemetry fields: {', '.join(unknown)}")

    from local_state import get_hive_config, set_hive_config

    config = get_hive_config() or {}
    target = _findTarget(config, target_id)
    if target is None:
        raise ValueError(f"Unknown Hive target: {target_id}")

    settings = normalizeTelemetrySettings(target.get("telemetry"))
    for key, value in updates.items():
        settings[key] = bool(value)
    target["telemetry"] = settings
    set_hive_config(config)
    return settings


def resetTargetTelemetrySettings(target_id: str) -> dict[str, bool]:
    return setTargetTelemetrySettings(target_id, defaultTelemetrySettings())


def telemetryAllows(target_id: str, field: str) -> bool:
    return bool(getTargetTelemetrySettings(target_id).get(field, False))


def telemetryFieldList() -> list[dict[str, Any]]:
    return [
        {
            "key": field["key"],
            "label": field["label"],
            "description": field["description"],
        }
        for field in TELEMETRY_FIELDS
    ]


class TelemetryBlocked(Exception):
    def __init__(self, field: str) -> None:
        super().__init__(f"Telemetry field '{field}' is disabled for this Hive target.")
        self.field = field


# Hive's own limits for a sync row's file (services/storage.py: MAX_FILE_SIZE for
# images, MAX_CONTROL_DATA_FILE_SIZE for control data), under the 100 MB body
# limit of the Cloudflare proxy in front of it. Hive cannot accept anything
# larger, and a file far larger has a corrupted size (seen on a failing SD card:
# 1 KB crops reporting 2 GB to 6 TB) that would pull that much into memory on
# every retry.
MAX_SYNC_IMAGE_BYTES = 10 * 1024 * 1024
MAX_SYNC_SEGMENT_BYTES = 90 * 1024 * 1024

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


class HiveTelemetryClient:
    def __init__(self, url: str, api_token: str, target_id: str) -> None:
        self._url = url.rstrip("/")
        self._target_id = target_id
        self._session = requests.Session()
        self._session.headers["Authorization"] = f"Bearer {api_token}"

    def _request(
        self,
        method: str,
        path: str,
        *,
        fields: tuple[str, ...],
        timeout: float,
        **kwargs: Any,
    ) -> requests.Response:
        settings = getTargetTelemetrySettings(self._target_id)
        for field in fields:
            if not settings.get(field, False):
                raise TelemetryBlocked(field)
        response = self._session.request(method, f"{self._url}{path}", timeout=timeout, **kwargs)
        response.raise_for_status()
        return response

    def _postSyncRow(
        self,
        path: str,
        *,
        fields: tuple[str, ...],
        meta: dict[str, Any],
        files: dict[str, Any] | None,
        timeout: float,
    ) -> requests.Response:
        data = {"metadata": json.dumps(meta)}
        try:
            return self._request("POST", path, fields=fields, data=data, files=files, timeout=timeout)
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
        return self._request("POST", path, fields=fields, data=data, files=None, timeout=timeout)

    def getSyncState(self) -> dict[str, Any]:
        return self._request("GET", "/api/machine/sync/state", fields=(), timeout=15).json()

    def pushPieceRecords(self, records: list[dict[str, Any]]) -> int:
        response = self._request(
            "POST",
            "/api/machine/sync/piece-records",
            fields=("piece_metadata",),
            json={"records": records},
            timeout=60,
        )
        return int(response.json()["max_local_id"])

    def pushPiecePredictions(self, records: list[dict[str, Any]]) -> int:
        response = self._request(
            "POST",
            "/api/machine/sync/piece-predictions",
            fields=("piece_metadata",),
            json={"records": records},
            timeout=60,
        )
        return int(response.json()["max_local_id"])

    def pushPieceImage(self, meta: dict[str, Any], file_path: Path | None) -> int:
        image = _readSyncFile(file_path, meta.get("bytes"), _JPEG_MAGIC, MAX_SYNC_IMAGE_BYTES)
        response = self._postSyncRow(
            "/api/machine/sync/piece-image",
            fields=("detection_images",),
            meta=meta,
            files={"image": (file_path.name, image, "image/jpeg")} if image is not None else None,
            timeout=60,
        )
        return int(response.json()["max_local_id"])

    def pushChannelCrop(self, meta: dict[str, Any], file_path: Path | None) -> int:
        image = _readSyncFile(file_path, meta.get("bytes"), _JPEG_MAGIC, MAX_SYNC_IMAGE_BYTES)
        response = self._postSyncRow(
            "/api/machine/sync/channel-crop",
            fields=("upstream_channel_crops",),
            meta=meta,
            files={"image": (file_path.name, image, "image/jpeg")} if image is not None else None,
            timeout=60,
        )
        return int(response.json()["max_local_id"])

    def pushControlDataSegment(self, meta: dict[str, Any], file_path: Path | None) -> int:
        segment = _readSyncFile(file_path, meta.get("bytes"), _GZIP_MAGIC, MAX_SYNC_SEGMENT_BYTES)
        response = self._postSyncRow(
            "/api/machine/sync/control-data-segment",
            fields=("feeder_dynamics",),
            meta=meta,
            files={"data": (file_path.name, segment, "application/gzip")} if segment is not None else None,
            timeout=120,
        )
        return int(response.json()["max_local_id"])

    def pushSetProgress(self, payload: dict[str, Any]) -> None:
        self._request(
            "POST",
            "/api/machine/set-progress",
            fields=("piece_metadata",),
            json=payload,
            timeout=15,
        )

    def pushSample(self, meta: dict[str, Any], file_path: Path) -> int:
        # A sample is a whole camera frame, so it rides on full_frames. Unlike
        # the other sync rows it is never sent without its image: Hive keeps no
        # sample without one.
        image = _readSyncFile(file_path, meta.get("bytes"), _JPEG_MAGIC, MAX_SYNC_IMAGE_BYTES)
        if image is None:
            raise FileNotFoundError(f"sample image unreadable: {file_path}")
        response = self._request(
            "POST",
            "/api/machine/sync/sample",
            fields=("full_frames",),
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
        # Keep-alive so target reachability shows in the UI. It also carries
        # where to find the Sorter on its networks (every beat; it is small)
        # and, when one is supplied, the machine-specs snapshot, each only
        # while its field is enabled for this target. Reachability never
        # depends on either, so turning them off never makes the machine look
        # offline. Returns (reachable, Hive's reply), the reply carrying the
        # limits Hive sets for this machine (see hive_limits.py).
        settings = getTargetTelemetrySettings(self._target_id)
        body: dict[str, Any] = {}
        if network is not None:
            # With the field off the key is sent as null, which tells Hive to
            # forget the addresses it already has.
            body["network"] = network if settings.get("network", False) else None
        if machine_specs is not None and settings.get("machine_specs", False):
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
