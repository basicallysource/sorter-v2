"""Unified TOML-based config manager.

All settings read/write machine_params.toml as the single source of truth.
Polygons are stored in a separate polygons.json file (same directory as TOML)
because their deeply nested coordinate arrays are unsuitable for TOML.

Runtime state (machine_id, stepper_positions, servo_positions, bin_categories)
stays in data.json via blob_manager.
"""

from __future__ import annotations

import json
import os
import tempfile
import threading
import tomllib
from pathlib import Path
from typing import Any

from server.config_helpers import write_machine_params_config

_TOML_LOCK = threading.Lock()
_POLYGONS_LOCK = threading.Lock()


# ---------------------------------------------------------------------------
# Path helpers
# ---------------------------------------------------------------------------


def _toml_path() -> str:
    """Return the machine params TOML path from env, or a default."""
    path = os.getenv("MACHINE_SPECIFIC_PARAMS_PATH")
    if path:
        return path
    return str(Path(__file__).parent / "machine_params.toml")


def _polygons_path() -> str:
    """Return the polygons.json path (same directory as the TOML file)."""
    toml = _toml_path()
    return str(Path(toml).parent / "polygons.json")


# ---------------------------------------------------------------------------
# TOML read/write primitives
# ---------------------------------------------------------------------------


def _read_toml() -> dict[str, Any]:
    """Read and parse the TOML file. Returns {} if missing or invalid."""
    path = _toml_path()
    if not os.path.exists(path):
        return {}
    try:
        with open(path, "rb") as f:
            return tomllib.load(f)
    except Exception:
        return {}


def _update_toml(updater: Any) -> None:
    """Read TOML, apply updater(config_dict), write back atomically."""
    with _TOML_LOCK:
        config = _read_toml()
        updater(config)
        write_machine_params_config(_toml_path(), config)


# ---------------------------------------------------------------------------
# Polygon JSON read/write primitives
# ---------------------------------------------------------------------------


def _write_json_atomic(path: str, data: dict[str, Any]) -> None:
    """Write JSON atomically via tempfile + rename."""
    parent = Path(path).parent
    parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(dir=parent, suffix=".json.tmp")
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(data, f, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.rename(tmp_path, path)
    except BaseException:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def _read_polygons_json() -> dict[str, Any]:
    """Read the polygons.json file. Returns {} if missing."""
    path = _polygons_path()
    if not os.path.exists(path):
        return {}
    try:
        with open(path, "r") as f:
            return json.load(f)
    except Exception:
        return {}


# ---------------------------------------------------------------------------
# Detection configs
# ---------------------------------------------------------------------------


def getDetectionConfig(scope: str) -> dict[str, Any] | None:
    """Read detection config for a scope (classification/feeder/carousel)."""
    config = _read_toml()
    detection = config.get("detection")
    if not isinstance(detection, dict):
        return None
    section = detection.get(scope)
    if not isinstance(section, dict):
        return None
    # Flatten sample_collection_enabled_by_role sub-table into the dict
    result = dict(section)
    by_role = result.pop("sample_collection_enabled_by_role", None)
    if isinstance(by_role, dict):
        result["sample_collection_enabled_by_role"] = by_role
    return result


def setDetectionConfig(scope: str, cfg: dict[str, Any]) -> None:
    """Write detection config for a scope."""
    def updater(config: dict[str, Any]) -> None:
        if "detection" not in config:
            config["detection"] = {}
        section = dict(cfg)
        # Separate sample_collection_enabled_by_role into a sub-table
        by_role = section.pop("sample_collection_enabled_by_role", None)
        config["detection"][scope] = section
        if isinstance(by_role, dict):
            config["detection"][scope]["sample_collection_enabled_by_role"] = by_role

    _update_toml(updater)


# ---------------------------------------------------------------------------
# Machine nickname
# ---------------------------------------------------------------------------


def getMachineNickname() -> str | None:
    """Read machine nickname from TOML [machine] section."""
    config = _read_toml()
    machine = config.get("machine")
    if not isinstance(machine, dict):
        return None
    nickname = machine.get("nickname")
    if not isinstance(nickname, str):
        return None
    nickname = nickname.strip()
    return nickname or None


def setMachineNickname(nickname: str | None) -> None:
    """Write machine nickname to TOML [machine] section."""
    def updater(config: dict[str, Any]) -> None:
        if "machine" not in config:
            config["machine"] = {}
        normalized = nickname.strip() if isinstance(nickname, str) else ""
        if normalized:
            config["machine"]["nickname"] = normalized
        else:
            config["machine"].pop("nickname", None)

    _update_toml(updater)


# ---------------------------------------------------------------------------
# Classification training config
# ---------------------------------------------------------------------------


def getClassificationTrainingConfig() -> dict[str, Any] | None:
    """Read classification training config from TOML."""
    config = _read_toml()
    section = config.get("classification_training")
    if not isinstance(section, dict):
        return None
    return dict(section)


def setClassificationTrainingConfig(cfg: dict[str, Any]) -> None:
    """Write classification training config to TOML."""
    def updater(config: dict[str, Any]) -> None:
        config["classification_training"] = dict(cfg)

    _update_toml(updater)


# ---------------------------------------------------------------------------
# API keys
# ---------------------------------------------------------------------------


def getApiKeys() -> dict[str, str]:
    """Read API keys from TOML [api_keys] section."""
    config = _read_toml()
    section = config.get("api_keys")
    if not isinstance(section, dict):
        return {}
    return {k: str(v) for k, v in section.items()}


def setApiKeys(keys: dict[str, str]) -> None:
    """Write API keys to TOML [api_keys] section."""
    def updater(config: dict[str, Any]) -> None:
        config["api_keys"] = dict(keys)

    _update_toml(updater)


# ---------------------------------------------------------------------------
# Chute calibration
# ---------------------------------------------------------------------------


def getChuteCalibration() -> dict[str, float] | None:
    """Read chute calibration from TOML [chute] section."""
    config = _read_toml()
    chute = config.get("chute")
    if not isinstance(chute, dict):
        return None
    return dict(chute)


def setChuteCalibration(calibration: dict[str, float]) -> None:
    """Write chute calibration to TOML [chute] section (merge, not replace)."""
    def updater(config: dict[str, Any]) -> None:
        if "chute" not in config:
            config["chute"] = {}
        config["chute"].update(calibration)

    _update_toml(updater)


# ---------------------------------------------------------------------------
# Camera setup (for default layout compatibility)
# ---------------------------------------------------------------------------


def getCameraSetup() -> dict[str, Any] | None:
    """Read camera setup from TOML [cameras] section."""
    config = _read_toml()
    cameras = config.get("cameras")
    if not isinstance(cameras, dict):
        return None
    # Return the roles that have device indices assigned
    result: dict[str, Any] = {}
    for role in ("feeder", "classification_top", "classification_bottom",
                 "c_channel_2", "c_channel_3", "carousel"):
        val = cameras.get(role)
        if val is not None:
            result[role] = val
    return result if result else None


def setCameraSetup(setup: dict[str, Any]) -> None:
    """Write camera setup to TOML [cameras] section."""
    def updater(config: dict[str, Any]) -> None:
        if "cameras" not in config:
            config["cameras"] = {}
        for role, val in setup.items():
            config["cameras"][role] = val

    _update_toml(updater)


# ---------------------------------------------------------------------------
# Polygons (stored in polygons.json, not TOML)
# ---------------------------------------------------------------------------


def getChannelPolygons() -> dict[str, Any] | None:
    """Read channel polygons from polygons.json."""
    data = _read_polygons_json()
    result = data.get("channel_polygons")
    return result if isinstance(result, dict) else None


def setChannelPolygons(polygons: dict[str, Any]) -> None:
    """Write channel polygons to polygons.json."""
    with _POLYGONS_LOCK:
        data = _read_polygons_json()
        data["channel_polygons"] = polygons
        _write_json_atomic(_polygons_path(), data)


def getClassificationPolygons() -> dict[str, Any] | None:
    """Read classification polygons from polygons.json."""
    data = _read_polygons_json()
    result = data.get("classification_polygons")
    return result if isinstance(result, dict) else None


def setClassificationPolygons(polygons: dict[str, Any]) -> None:
    """Write classification polygons to polygons.json."""
    with _POLYGONS_LOCK:
        data = _read_polygons_json()
        data["classification_polygons"] = polygons
        _write_json_atomic(_polygons_path(), data)


# ---------------------------------------------------------------------------
# Migration: data.json → TOML + polygons.json
# ---------------------------------------------------------------------------


def migrateFromDataJson() -> None:
    """One-time migration of settings from data.json to TOML + polygons.json.

    Only copies values that don't already exist in the target store.
    Does NOT delete from data.json (preserves as fallback).
    """
    from blob_manager import loadData

    data = loadData()
    if not data:
        return

    toml_path = _toml_path()
    config = _read_toml()
    changed = False

    # Detection configs
    for json_key, toml_scope in [
        ("classification_detection", "classification"),
        ("feeder_detection", "feeder"),
        ("carousel_detection", "carousel"),
    ]:
        val = data.get(json_key)
        if isinstance(val, dict):
            detection = config.setdefault("detection", {})
            if toml_scope not in detection:
                section = dict(val)
                by_role = section.pop("sample_collection_enabled_by_role", None)
                detection[toml_scope] = section
                if isinstance(by_role, dict):
                    detection[toml_scope]["sample_collection_enabled_by_role"] = by_role
                changed = True

    # Machine nickname
    nickname = data.get("machine_nickname")
    if isinstance(nickname, str) and nickname.strip():
        machine = config.setdefault("machine", {})
        if "nickname" not in machine:
            machine["nickname"] = nickname.strip()
            changed = True

    # Classification training config
    training = data.get("classification_training")
    if isinstance(training, dict) and "classification_training" not in config:
        config["classification_training"] = dict(training)
        changed = True

    # API keys
    api_keys = data.get("api_keys")
    if isinstance(api_keys, dict) and "api_keys" not in config:
        config["api_keys"] = dict(api_keys)
        changed = True

    # Camera setup → [cameras] section (for default layout)
    camera_setup = data.get("camera_setup")
    if isinstance(camera_setup, dict):
        cameras = config.setdefault("cameras", {})
        for role in ("feeder", "classification_top", "classification_bottom"):
            val = camera_setup.get(role)
            if val is not None and role not in cameras:
                # Legacy format may be "opencv:N|name" string — extract index
                if isinstance(val, str):
                    if val == "none":
                        cameras[role] = -1
                    elif val.startswith("opencv:"):
                        try:
                            cameras[role] = int(val.split(":")[1].split("|")[0])
                        except (ValueError, IndexError):
                            pass
                    else:
                        try:
                            cameras[role] = int(val)
                        except ValueError:
                            pass
                elif isinstance(val, int):
                    cameras[role] = val
                changed = True

    # Chute calibration
    chute_cal = data.get("chute_calibration")
    if isinstance(chute_cal, dict):
        chute = config.setdefault("chute", {})
        for k, v in chute_cal.items():
            if k not in chute:
                chute[k] = v
                changed = True

    if changed:
        with _TOML_LOCK:
            write_machine_params_config(toml_path, config)

    # Polygons → polygons.json
    polygons_data = _read_polygons_json()
    polygons_changed = False

    channel_polys = data.get("channel_polygons")
    if isinstance(channel_polys, dict) and "channel_polygons" not in polygons_data:
        polygons_data["channel_polygons"] = channel_polys
        polygons_changed = True

    class_polys = data.get("classification_polygons")
    if isinstance(class_polys, dict) and "classification_polygons" not in polygons_data:
        polygons_data["classification_polygons"] = class_polys
        polygons_changed = True

    if polygons_changed:
        with _POLYGONS_LOCK:
            _write_json_atomic(_polygons_path(), polygons_data)
