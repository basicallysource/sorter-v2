from __future__ import annotations

import hashlib
import shutil
import subprocess
import threading
import time
from typing import Any, Dict, List

import requests
from zeroconf import IPVersion, ServiceBrowser, ServiceListener, Zeroconf

SERVICE_TYPE = "_legosorter-camera._tcp.local."


def _decode_properties(properties: Dict[bytes, bytes]) -> Dict[str, str]:
    decoded: Dict[str, str] = {}
    for raw_key, raw_value in properties.items():
        key = raw_key.decode("utf-8", errors="ignore")
        value = raw_value.decode("utf-8", errors="ignore")
        decoded[key] = value
    return decoded


def _normalized_path(path: str, fallback: str) -> str:
    value = (path or fallback).strip() or fallback
    return value if value.startswith("/") else f"/{value}"


def _adb_forward_port(serial: str) -> int:
    digest = hashlib.sha1(serial.encode("utf-8")).hexdigest()
    return 18080 + (int(digest[:6], 16) % 1000)


def _parse_adb_field(line: str, field: str) -> str | None:
    prefix = f"{field}:"
    for part in line.split():
        if part.startswith(prefix):
            value = part[len(prefix) :].strip()
            return value or None
    return None


class _CameraDiscoveryListener(ServiceListener):
    def __init__(self, registry: "CameraDiscoveryRegistry") -> None:
        self._registry = registry

    def add_service(self, zc: Zeroconf, type_: str, name: str) -> None:
        self._registry.upsert_service(zc, type_, name)

    def update_service(self, zc: Zeroconf, type_: str, name: str) -> None:
        self._registry.upsert_service(zc, type_, name)

    def remove_service(self, zc: Zeroconf, type_: str, name: str) -> None:
        self._registry.remove_service(name)


class CameraDiscoveryRegistry:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._zeroconf: Zeroconf | None = None
        self._browser: ServiceBrowser | None = None
        self._services: Dict[str, Dict[str, Any]] = {}
        self._started_at = 0.0

    def start(self) -> None:
        with self._lock:
            if self._zeroconf is not None:
                return
            self._zeroconf = Zeroconf(ip_version=IPVersion.V4Only)
            self._browser = ServiceBrowser(
                self._zeroconf,
                SERVICE_TYPE,
                listener=_CameraDiscoveryListener(self),
            )
            self._started_at = time.time()

    def stop(self) -> None:
        with self._lock:
            browser = self._browser
            zeroconf = self._zeroconf
            self._browser = None
            self._zeroconf = None
            self._services = {}

        if browser is not None:
            browser.cancel()
        if zeroconf is not None:
            zeroconf.close()

    def remove_service(self, name: str) -> None:
        with self._lock:
            self._services.pop(name, None)

    def upsert_service(self, zc: Zeroconf, type_: str, name: str) -> None:
        info = zc.get_service_info(type_, name, timeout=1_500)
        if info is None:
            return

        props = _decode_properties(info.properties)
        addresses = info.parsed_addresses(version=IPVersion.V4Only)
        host = addresses[0] if addresses else ""
        if not host:
            return

        path = _normalized_path(props.get("path", "/video"), "/video")
        snapshot_path = _normalized_path(props.get("snapshot", "/snapshot.jpg"), "/snapshot.jpg")
        health_path = _normalized_path(props.get("health", "/health"), "/health")
        label = props.get("name") or info.server.rstrip(".") or name.split(".")[0]

        service = {
            "kind": "network",
            "id": props.get("id") or name,
            "name": label,
            "source": f"http://{host}:{info.port}{path}",
            "preview_url": f"http://{host}:{info.port}{snapshot_path}",
            "health_url": f"http://{host}:{info.port}{health_path}",
            "host": host,
            "port": info.port,
            "model": props.get("model") or None,
            "lens_facing": props.get("lens") or None,
            "transport": props.get("transport") or "network",
            "last_seen_ms": int(time.time() * 1000),
        }

        with self._lock:
            self._services[name] = service

    def list_cameras(self) -> List[Dict[str, Any]]:
        self.start()
        for _ in range(10):
            with self._lock:
                cameras = list(self._services.values())
                started_at = self._started_at
            if cameras or time.time() - started_at >= 1.0:
                break
            time.sleep(0.1)

        return sorted(
            cameras,
            key=lambda camera: (
                str(camera.get("name") or "").lower(),
                str(camera.get("host") or ""),
                int(camera.get("port") or 0),
            ),
        )


_registry = CameraDiscoveryRegistry()


def _discover_adb_camera_streams() -> List[Dict[str, Any]]:
    adb = shutil.which("adb")
    if adb is None:
        return []

    try:
        result = subprocess.run(
            [adb, "devices", "-l"],
            check=False,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except Exception:
        return []

    cameras: List[Dict[str, Any]] = []
    for line in result.stdout.splitlines():
        parts = line.split()
        if len(parts) < 2 or parts[1] != "device":
            continue

        serial = parts[0]
        model = _parse_adb_field(line, "model") or serial
        port = _adb_forward_port(serial)

        try:
            subprocess.run(
                [adb, "-s", serial, "forward", f"tcp:{port}", "tcp:8080"],
                check=False,
                capture_output=True,
                text=True,
                timeout=5,
            )
            health = requests.get(f"http://127.0.0.1:{port}/health", timeout=0.75)
            health.raise_for_status()
            payload = health.json()
        except Exception:
            continue

        if not payload.get("ok"):
            continue

        cameras.append(
            {
                "kind": "network",
                "id": f"adb:{serial}",
                "name": f"{model.replace('_', ' ')} (USB)",
                "source": f"http://127.0.0.1:{port}/video",
                "preview_url": f"http://127.0.0.1:{port}/snapshot.jpg",
                "health_url": f"http://127.0.0.1:{port}/health",
                "host": "127.0.0.1",
                "port": port,
                "model": model.replace("_", " "),
                "lens_facing": None,
                "transport": "adb",
                "last_seen_ms": int(time.time() * 1000),
            }
        )

    return cameras


def getDiscoveredCameraStreams() -> List[Dict[str, Any]]:
    discovered: List[Dict[str, Any]] = []
    seen_sources: set[str] = set()

    try:
        for camera in _registry.list_cameras():
            source = str(camera.get("source") or "")
            if not source or source in seen_sources:
                continue
            discovered.append(camera)
            seen_sources.add(source)
    except Exception:
        pass

    for camera in _discover_adb_camera_streams():
        source = str(camera.get("source") or "")
        if not source or source in seen_sources:
            continue
        discovered.append(camera)
        seen_sources.add(source)

    return sorted(
        discovered,
        key=lambda camera: (
            str(camera.get("transport") or ""),
            str(camera.get("name") or "").lower(),
        ),
    )


def shutdownCameraDiscovery() -> None:
    _registry.stop()
