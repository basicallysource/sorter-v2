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
from pathlib import Path
from typing import Any

import requests

TELEMETRY_FIELDS: tuple[dict[str, Any], ...] = (
    {
        "key": "detection_images",
        "label": "Detection images",
        "description": "Cropped pictures of individual pieces: live training samples and the per-piece image history.",
        "default": True,
    },
    {
        "key": "full_frames",
        "label": "Full camera frames",
        "description": "Uncropped camera captures and detection overlay images attached to training samples.",
        "default": True,
    },
    {
        "key": "piece_metadata",
        "label": "Piece metadata",
        "description": "Classification results per piece (part, color, confidence, bin, timestamps) and set sorting progress.",
        "default": True,
    },
    {
        "key": "channel_crops",
        "label": "Channel crops (C2/C3)",
        "description": "Unlabeled bbox crops of pieces on the upstream feeder channels, tagged with position for same-piece lookup. Off by default — experimental, high volume.",
        "default": False,
    },
    {
        "key": "machine_specs",
        "label": "Machine specs",
        "description": "Basic hardware and software details — camera, controller board, platform and operating system — shown on the machine's dashboard and used for compatibility and support.",
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

    def pushPieceCorrections(self, records: list[dict[str, Any]]) -> int:
        response = self._request(
            "POST",
            "/api/machine/sync/piece-corrections",
            fields=("piece_metadata",),
            json={"records": records},
            timeout=60,
        )
        return int(response.json()["max_local_id"])

    def pushPieceImage(self, meta: dict[str, Any], file_path: Path | None) -> int:
        files = None
        if file_path is not None and file_path.is_file():
            with open(file_path, "rb") as handle:
                files = {"image": (file_path.name, handle.read(), "image/jpeg")}
        response = self._request(
            "POST",
            "/api/machine/sync/piece-image",
            fields=("detection_images",),
            data={"metadata": json.dumps(meta)},
            files=files,
            timeout=60,
        )
        return int(response.json()["max_local_id"])

    def pushChannelCrop(self, meta: dict[str, Any], file_path: Path | None) -> int:
        files = None
        if file_path is not None and file_path.is_file():
            with open(file_path, "rb") as handle:
                files = {"image": (file_path.name, handle.read(), "image/jpeg")}
        response = self._request(
            "POST",
            "/api/machine/sync/channel-crop",
            fields=("channel_crops",),
            data={"metadata": json.dumps(meta)},
            files=files,
            timeout=60,
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

    def _sendSample(
        self,
        *,
        method: str,
        path: str,
        source_session_id: str,
        local_sample_id: str,
        image_path: Path | None = None,
        full_frame_path: Path | None = None,
        overlay_path: Path | None = None,
        source_role: str | None = None,
        capture_reason: str | None = None,
        captured_at: str | None = None,
        session_name: str | None = None,
        detection_algorithm: str | None = None,
        detection_bboxes: Any = None,
        detection_count: int | None = None,
        detection_score: float | None = None,
        sample_payload: dict[str, Any] | None = None,
        extra_metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        # A sample IS a detection image plus its detection metadata, so the
        # whole request rides on detection_images; full-frame attachments are
        # stripped (not blocked) when full_frames is off.
        settings = getTargetTelemetrySettings(self._target_id)
        if not settings.get("detection_images", False):
            raise TelemetryBlocked("detection_images")
        if not settings.get("full_frames", False):
            full_frame_path = None
            overlay_path = None

        metadata: dict[str, Any] = {
            "source_session_id": source_session_id,
            "local_sample_id": local_sample_id,
        }
        for key, value in [
            ("source_role", source_role),
            ("capture_reason", capture_reason),
            ("captured_at", captured_at),
            ("session_name", session_name),
            ("detection_algorithm", detection_algorithm),
            ("detection_bboxes", detection_bboxes),
            ("detection_count", detection_count),
            ("detection_score", detection_score),
            ("sample_payload", sample_payload),
        ]:
            if value is not None:
                metadata[key] = value
        if extra_metadata:
            metadata["extra_metadata"] = extra_metadata

        handles: list[Any] = []
        try:
            files: dict[str, Any] = {}
            if image_path is not None:
                image_fh = open(image_path, "rb")
                handles.append(image_fh)
                files["image"] = (image_path.name, image_fh, "image/jpeg")
            if full_frame_path and full_frame_path.exists():
                full_frame_fh = open(full_frame_path, "rb")
                handles.append(full_frame_fh)
                files["full_frame"] = (full_frame_path.name, full_frame_fh, "image/jpeg")
            if overlay_path and overlay_path.exists():
                overlay_fh = open(overlay_path, "rb")
                handles.append(overlay_fh)
                files["overlay"] = (overlay_path.name, overlay_fh, "image/jpeg")

            response = self._request(
                method,
                path,
                fields=("detection_images",),
                data={"metadata": json.dumps(metadata)},
                files=files or None,
                timeout=30,
            )
            return response.json()
        finally:
            for handle in handles:
                handle.close()

    def uploadSample(self, *, source_session_id: str, local_sample_id: str, image_path: Path, **kwargs: Any) -> dict[str, Any]:
        return self._sendSample(
            method="POST",
            path="/api/machine/upload",
            source_session_id=source_session_id,
            local_sample_id=local_sample_id,
            image_path=image_path,
            **kwargs,
        )

    def updateSample(self, *, source_session_id: str, local_sample_id: str, image_path: Path | None = None, **kwargs: Any) -> dict[str, Any]:
        return self._sendSample(
            method="PATCH",
            path=f"/api/machine/upload/{source_session_id}/{local_sample_id}",
            source_session_id=source_session_id,
            local_sample_id=local_sample_id,
            image_path=image_path,
            **kwargs,
        )

    def heartbeat(self, machine_specs: dict[str, Any] | None = None) -> bool:
        # Keep-alive so target reachability shows in the UI. It also carries the
        # machine-specs snapshot when one is supplied and the "machine_specs"
        # field is enabled for this target; reachability still works when the
        # field is off (the body is simply omitted), so toggling specs off never
        # makes the machine look offline.
        body: dict[str, Any] | None = None
        if machine_specs is not None and getTargetTelemetrySettings(self._target_id).get("machine_specs", False):
            body = {"hardware_info": machine_specs}
        try:
            response = self._session.post(f"{self._url}/api/machine/heartbeat", json=body, timeout=10)
            return response.status_code < 500
        except requests.RequestException:
            return False
