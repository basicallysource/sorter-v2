"""Hive Python client for machine API."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any, Callable

import requests


class HiveError(Exception):
    """Error returned by the Hive API."""

    def __init__(self, status_code: int, message: str, code: str | None = None):
        self.status_code = status_code
        self.code = code
        super().__init__(message)


class HiveClient:
    """Python client for Hive machine API."""

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
            raise HiveError(resp.status_code, message, code)
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

    def list_models(
        self,
        scope: str | None = None,
        runtime: str | None = None,
        family: str | None = None,
        q: str | None = None,
        page: int = 1,
        page_size: int = 30,
    ) -> dict:
        """GET /api/machine/models -- paginated catalog."""
        params: dict[str, Any] = {"page": page, "page_size": page_size}
        if scope:
            params["scope"] = scope
        if runtime:
            params["runtime"] = runtime
        if family:
            params["family"] = family
        if q:
            params["q"] = q
        return self._request("GET", "/api/machine/models", params=params)

    def get_model(self, model_id: str) -> dict:
        """GET /api/machine/models/{id}."""
        return self._request("GET", f"/api/machine/models/{model_id}")

    def download_model_variant(
        self,
        model_id: str,
        variant_id: str,
        dest_path: Path,
        on_progress: Callable[[int, int], None] | None = None,
        expected_sha256: str | None = None,
    ) -> str:
        """GET /api/machine/models/{id}/variants/{vid}/download -- stream to disk, verify sha256."""
        dest_path = Path(dest_path)
        dest_path.parent.mkdir(parents=True, exist_ok=True)
        partial = dest_path.with_suffix(dest_path.suffix + ".partial")
        url = f"{self.api_url}/api/machine/models/{model_id}/variants/{variant_id}/download"
        with self._session.get(url, stream=True) as resp:
            if not resp.ok:
                try:
                    body = resp.json()
                    message = body.get("error", resp.text)
                    code = body.get("code")
                except (ValueError, KeyError):
                    message = resp.text
                    code = None
                raise HiveError(resp.status_code, message, code)
            header_sha = resp.headers.get("X-Model-SHA256")
            total = int(resp.headers.get("Content-Length") or 0)
            hasher = hashlib.sha256()
            written = 0
            with open(partial, "wb") as out:
                for chunk in resp.iter_content(chunk_size=1024 * 1024):
                    if not chunk:
                        continue
                    hasher.update(chunk)
                    out.write(chunk)
                    written += len(chunk)
                    if on_progress is not None:
                        on_progress(written, total)
                out.flush()
                os.fsync(out.fileno())
        digest = hasher.hexdigest()
        expected = expected_sha256 or header_sha
        if expected and digest != expected:
            partial.unlink(missing_ok=True)
            raise HiveError(
                500,
                f"SHA256 mismatch on download (expected {expected}, got {digest})",
                "SHA256_MISMATCH",
            )
        os.replace(partial, dest_path)
        return digest


class HiveAdminClient:
    """Admin client for publishing models.

    Two auth modes:
      - API key (recommended): pass ``api_key=`` at construction. All requests
        attach ``Authorization: Bearer <key>``. No login call needed.
      - Legacy cookie login: construct without ``api_key`` then call ``login()``.
    """

    def __init__(self, api_url: str, api_key: str | None = None):
        self.api_url = api_url.rstrip("/")
        self._session = requests.Session()
        self._csrf_token: str | None = None
        self._api_key = api_key
        if api_key:
            self._session.headers["Authorization"] = f"Bearer {api_key}"

    def login(self, email: str, password: str) -> None:
        if self._api_key:
            return  # API key auth active — login call is a no-op
        resp = self._session.post(
            f"{self.api_url}/api/auth/login",
            json={"email": email, "password": password},
        )
        if not resp.ok:
            raise HiveError(resp.status_code, f"Login failed: {resp.text}", None)
        self._csrf_token = self._session.cookies.get("csrf_token")
        if not self._csrf_token:
            raise HiveError(500, "No CSRF token in login response", None)

    def _headers(self) -> dict[str, str]:
        if self._api_key:
            return {}
        if not self._csrf_token:
            raise HiveError(401, "Not logged in; call login() first", None)
        return {"X-CSRF-Token": self._csrf_token}

    def _request(self, method: str, path: str, **kwargs: Any) -> Any:
        headers = kwargs.pop("headers", {})
        headers.update(self._headers())
        resp = self._session.request(method, f"{self.api_url}{path}", headers=headers, **kwargs)
        if not resp.ok:
            try:
                body = resp.json()
                message = body.get("error", resp.text)
                code = body.get("code")
            except (ValueError, KeyError):
                message = resp.text
                code = None
            raise HiveError(resp.status_code, message, code)
        if resp.status_code == 204:
            return None
        return resp.json()

    def create_model(self, payload: dict) -> dict:
        """POST /api/models."""
        return self._request("POST", "/api/models", json=payload)

    def upload_variant(
        self,
        model_id: str,
        runtime: str,
        file_path: Path,
        format_meta: dict | None = None,
        on_progress: Callable[[int, int], None] | None = None,
    ) -> dict:
        """POST /api/models/{id}/variants -- multipart streamed."""
        file_path = Path(file_path)
        total = file_path.stat().st_size
        data: dict[str, Any] = {"runtime": runtime}
        if format_meta is not None:
            data["format_meta"] = json.dumps(format_meta)
        with open(file_path, "rb") as fh:
            files = {
                "file": (file_path.name, _ProgressReader(fh, total, on_progress), "application/octet-stream")
            }
            return self._request(
                "POST",
                f"/api/models/{model_id}/variants",
                data=data,
                files=files,
            )


class _ProgressReader:
    """Wraps a file object to emit progress callbacks while requests reads from it."""

    def __init__(self, fh, total: int, on_progress: Callable[[int, int], None] | None):
        self._fh = fh
        self._total = total
        self._read = 0
        self._cb = on_progress

    def read(self, size: int = -1) -> bytes:
        chunk = self._fh.read(size)
        if chunk:
            self._read += len(chunk)
            if self._cb is not None:
                self._cb(self._read, self._total)
        return chunk

    def __len__(self) -> int:
        return self._total
