"""Versioned machine-settings backup to Hive.

Snapshots the machine's settings (machine_params.toml + curated local_state)
and pushes them to every enabled Hive target. Hive content-hash-dedups, so a new
version is only stored when the config actually changes. A background thread
re-checks every ``SYNC_INTERVAL_S`` and only POSTs when the local hash moved, so
this doubles as both the change trigger and a drift safety net.

Restore is machine-initiated (matching the "deploy from the machine side" UX):
the sorter pulls a chosen version from Hive, writes the TOML + applies the
local_state, and restarts the backend.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import threading
import time
from typing import Any

import requests

import local_state
from blob_manager import getHiveConfig, getMachineId, getMachineNickname
from server.config_helpers import machine_params_path

log = logging.getLogger(__name__)

SYNC_INTERVAL_S = 30.0
_HTTP_TIMEOUT_S = 15.0

# local_state keys that are pure settings — always safe to restore.
_SETTINGS_KEYS = ("bin_categories", "channel_polygons", "classification_polygons", "classification_training")
# Calibration / live positions — only restored when explicitly opted in, since
# writing stale positions back can desync the hardware until the next homing.
_CALIBRATION_KEYS = ("stepper_positions", "servo_positions")


def _read_local_state() -> dict[str, Any]:
    return {
        "bin_categories": local_state.get_bin_categories(),
        "channel_polygons": local_state.get_channel_polygons(),
        "classification_polygons": local_state.get_classification_polygons(),
        "classification_training": local_state.get_classification_training_state(),
        "stepper_positions": local_state.get_stepper_positions(),
        "servo_positions": local_state.get_servo_positions(),
    }


def _read_toml_text() -> str:
    try:
        with open(machine_params_path(), "r", encoding="utf-8") as fh:
            return fh.read()
    except FileNotFoundError:
        return ""


def build_snapshot() -> tuple[dict[str, Any], str]:
    """Return (payload, content_hash). The hash covers only the restorable
    content (toml + local_state), not the identity envelope."""
    toml_text = _read_toml_text()
    state = _read_local_state()
    core = {"toml_text": toml_text, "local_state": state}
    content_hash = hashlib.sha256(
        json.dumps(core, sort_keys=True, default=str).encode("utf-8")
    ).hexdigest()
    payload = {
        **core,
        "machine_id": getMachineId(),
        "nickname": getMachineNickname(),
    }
    return payload, content_hash


def _enabled_targets() -> list[dict[str, Any]]:
    config = getHiveConfig() or {}
    targets = config.get("targets") if isinstance(config, dict) else None
    if not isinstance(targets, list):
        return []
    out: list[dict[str, Any]] = []
    for target in targets:
        if not isinstance(target, dict) or not target.get("enabled"):
            continue
        url = target.get("url")
        token = target.get("api_token")
        if isinstance(url, str) and url.strip() and isinstance(token, str) and token.strip():
            out.append({"id": target.get("id"), "url": url.rstrip("/"), "token": token})
    return out


def _primary_target() -> dict[str, Any] | None:
    config = getHiveConfig() or {}
    primary_id = config.get("primary_target_id") if isinstance(config, dict) else None
    targets = _enabled_targets()
    if not targets:
        return None
    for target in targets:
        if target.get("id") == primary_id:
            return target
    return targets[0]


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def push_snapshot(trigger: str = "config_change") -> dict[str, Any]:
    """POST the current snapshot to every enabled target. Returns per-target
    results. Hive dedups by hash, so calling this when nothing changed is a
    cheap no-op server-side."""
    payload, content_hash = build_snapshot()
    body = {"content_hash": content_hash, "payload": payload, "trigger": trigger}
    results: list[dict[str, Any]] = []
    for target in _enabled_targets():
        try:
            resp = requests.post(
                f"{target['url']}/api/machine/config-backup",
                json=body,
                headers=_auth(target["token"]),
                timeout=_HTTP_TIMEOUT_S,
            )
            resp.raise_for_status()
            data = resp.json()
            results.append({"target": target.get("id"), "ok": True, "version": data.get("version"), "deduped": data.get("deduped")})
        except Exception as exc:  # noqa: BLE001 — network/HTTP failures are non-fatal
            log.warning("config-backup push to %s failed: %s", target.get("url"), exc)
            results.append({"target": target.get("id"), "ok": False, "error": str(exc)})
    return {"content_hash": content_hash, "results": results}


def list_versions() -> list[dict[str, Any]]:
    target = _primary_target()
    if target is None:
        return []
    resp = requests.get(
        f"{target['url']}/api/machine/config-backups",
        headers=_auth(target["token"]),
        timeout=_HTTP_TIMEOUT_S,
    )
    resp.raise_for_status()
    return resp.json()


def _fetch_version(version: int) -> dict[str, Any]:
    target = _primary_target()
    if target is None:
        raise RuntimeError("No enabled Hive target to restore from.")
    resp = requests.get(
        f"{target['url']}/api/machine/config-backup/{version}",
        headers=_auth(target["token"]),
        timeout=_HTTP_TIMEOUT_S,
    )
    resp.raise_for_status()
    return resp.json()


def _write_toml_text(text: str) -> None:
    path = machine_params_path()
    tmp = f"{path}.restore.tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        fh.write(text)
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp, path)


_LOCAL_STATE_SETTERS = {
    "bin_categories": local_state.set_bin_categories,
    "channel_polygons": local_state.set_channel_polygons,
    "classification_polygons": local_state.set_classification_polygons,
    "classification_training": local_state.set_classification_training_state,
    "stepper_positions": local_state.set_stepper_positions,
    "servo_positions": local_state.set_servo_positions,
}


def restore_version(version: int, *, include_calibration: bool = False) -> dict[str, Any]:
    """Apply a backed-up version to this machine. Writes the TOML and the
    settings local_state keys; calibration/position keys only when opted in.
    Caller should restart the backend afterwards for the TOML to take effect."""
    backup = _fetch_version(version)
    payload = backup.get("payload") or {}
    toml_text = payload.get("toml_text")
    if isinstance(toml_text, str) and toml_text.strip():
        _write_toml_text(toml_text)

    state = payload.get("local_state") or {}
    applied_keys: list[str] = []
    keys = list(_SETTINGS_KEYS) + (list(_CALIBRATION_KEYS) if include_calibration else [])
    for key in keys:
        value = state.get(key)
        setter = _LOCAL_STATE_SETTERS.get(key)
        if value is None or setter is None:
            continue
        try:
            setter(value)
            applied_keys.append(key)
        except Exception as exc:  # noqa: BLE001
            log.warning("restore: failed to apply local_state %s: %s", key, exc)
    return {
        "ok": True,
        "version": version,
        "applied_local_state": applied_keys,
        "wrote_toml": bool(isinstance(toml_text, str) and toml_text.strip()),
    }


class ConfigBackupSync:
    """Background thread: push a snapshot whenever the local hash changes."""

    def __init__(self, interval_s: float = SYNC_INTERVAL_S) -> None:
        self._interval_s = interval_s
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._last_hash: str | None = None

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._thread = threading.Thread(target=self._loop, name="config-backup-sync", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def _loop(self) -> None:
        # Small initial delay so first push doesn't race backend startup.
        if self._stop.wait(5.0):
            return
        while not self._stop.is_set():
            try:
                if _enabled_targets():
                    _, content_hash = build_snapshot()
                    if content_hash != self._last_hash:
                        result = push_snapshot(trigger="heartbeat" if self._last_hash else "config_change")
                        if any(r.get("ok") for r in result.get("results", [])):
                            self._last_hash = content_hash
            except Exception as exc:  # noqa: BLE001
                log.debug("config-backup sync tick failed: %s", exc)
            self._stop.wait(self._interval_s)


_sync: ConfigBackupSync | None = None


def get_config_backup_sync() -> ConfigBackupSync:
    global _sync
    if _sync is None:
        _sync = ConfigBackupSync()
    return _sync
