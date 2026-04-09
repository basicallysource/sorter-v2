"""SortHive Python client for machine API."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import requests


class SortHiveError(Exception):
    """Error returned by the SortHive API."""

    def __init__(self, status_code: int, message: str, code: str | None = None):
        self.status_code = status_code
        self.code = code
        super().__init__(message)


class SortHiveClient:
    """Python client for SortHive machine API."""

    def __init__(self, api_url: str, api_token: str):
        self.api_url = api_url.rstrip("/")
        self.api_token = api_token
        self._session = requests.Session()
        self._session.headers["Authorization"] = f"Bearer {api_token}"

    def _request(self, method: str, path: str, **kwargs: Any) -> Any:
        url = f"{self.api_url}{path}"
        resp = self._session.request(method, url, **kwargs)
        if not resp.ok:
            try:
                body = resp.json()
                message = body.get("error", resp.text)
                code = body.get("code")
            except (ValueError, KeyError):
                message = resp.text
                code = None
            raise SortHiveError(resp.status_code, message, code)
        if resp.status_code == 204:
            return None
        return resp.json()

    def heartbeat(
        self,
        hardware_info: dict | None = None,
        local_ui_port: str | int | None = None,
    ) -> dict:
        """POST /api/machine/heartbeat"""
        payload: dict[str, Any] = {}
        if hardware_info is not None:
            payload["hardware_info"] = hardware_info
        if local_ui_port is not None:
            payload["local_ui_port"] = str(local_ui_port)
        return self._request("POST", "/api/machine/heartbeat", json=payload)

    def upload_sample(
        self,
        source_session_id: str,
        local_sample_id: str,
        image_path: Path,
        full_frame_path: Path | None = None,
        overlay_path: Path | None = None,
        source_role: str | None = None,
        capture_reason: str | None = None,
        captured_at: str | None = None,
        session_name: str | None = None,
        detection_algorithm: str | None = None,
        detection_bboxes: list | None = None,
        detection_count: int | None = None,
        detection_score: float | None = None,
    ) -> dict:
        """POST /api/machine/upload -- multipart with metadata JSON + image files."""
        metadata: dict[str, Any] = {
            "source_session_id": source_session_id,
            "local_sample_id": local_sample_id,
        }
        for key in (
            "source_role",
            "capture_reason",
            "captured_at",
            "session_name",
            "detection_algorithm",
            "detection_bboxes",
            "detection_count",
            "detection_score",
        ):
            value = locals()[key]
            if value is not None:
                metadata[key] = value

        image_path = Path(image_path)
        files: dict[str, Any] = {
            "image": (image_path.name, open(image_path, "rb"), "image/png"),
        }
        if full_frame_path is not None:
            full_frame_path = Path(full_frame_path)
            files["full_frame"] = (
                full_frame_path.name,
                open(full_frame_path, "rb"),
                "image/png",
            )
        if overlay_path is not None:
            overlay_path = Path(overlay_path)
            files["overlay"] = (
                overlay_path.name,
                open(overlay_path, "rb"),
                "image/png",
            )

        data = {"metadata": json.dumps(metadata)}

        try:
            return self._request("POST", "/api/machine/upload", data=data, files=files)
        finally:
            for _name, file_tuple in files.items():
                file_tuple[1].close()

    def get_models(self) -> list[dict]:
        """GET /api/machine/models (placeholder for future)."""
        return self._request("GET", "/api/machine/models")
