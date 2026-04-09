"""Machine config helpers.

Declarative machine configuration stays in `machine_params.toml`.
Mutable local state such as polygons, sync state, training session state,
and secrets lives in `local_state.sqlite` via `local_state.py`.
"""

from __future__ import annotations

import json
import os
import tempfile
import threading
import tomllib
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

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
    """Legacy helper for the old polygons.json location."""
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
    """Read the legacy polygons.json file. Returns {} if missing."""
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
    """Read classification training state from local SQLite storage."""
    from local_state import get_classification_training_state

    return get_classification_training_state()


def setClassificationTrainingConfig(cfg: dict[str, Any]) -> None:
    """Write classification training state to local SQLite storage."""
    from local_state import set_classification_training_state

    set_classification_training_state(cfg)


# ---------------------------------------------------------------------------
# Hive config
# ---------------------------------------------------------------------------


def _default_hive_target_name(url: str, index: int) -> str:
    hostname = urlparse(url).hostname
    if isinstance(hostname, str) and hostname.strip():
        return hostname.strip()
    return f"Hive {index + 1}"


def _normalize_hive_target(raw: Any, index: int) -> dict[str, Any] | None:
    if not isinstance(raw, dict):
        return None

    url = raw.get("url")
    api_token = raw.get("api_token")
    if not isinstance(url, str) or not url.strip():
        return None
    if not isinstance(api_token, str) or not api_token.strip():
        return None

    target_id = raw.get("id")
    name = raw.get("name")
    machine_id = raw.get("machine_id")

    target = {
        "id": target_id.strip() if isinstance(target_id, str) and target_id.strip() else f"target-{index + 1}",
        "name": name.strip() if isinstance(name, str) and name.strip() else _default_hive_target_name(url, index),
        "url": url.strip().rstrip("/"),
        "api_token": api_token.strip(),
        "enabled": bool(raw.get("enabled", True)),
    }
    if isinstance(machine_id, str) and machine_id.strip():
        target["machine_id"] = machine_id.strip()
    return target


def getHiveConfig() -> dict[str, Any] | None:
    """Read Hive connection state from local SQLite storage."""
    from local_state import get_hive_config

    return get_hive_config()


def setHiveConfig(cfg: dict[str, Any]) -> None:
    """Write Hive connection state to local SQLite storage."""
    from local_state import set_hive_config

    set_hive_config(cfg)


def getSortingProfileSyncState() -> dict[str, Any] | None:
    """Read persisted sorting-profile sync metadata from local SQLite storage."""
    from local_state import get_sorting_profile_sync_state

    return get_sorting_profile_sync_state()


def setSortingProfileSyncState(state: dict[str, Any]) -> None:
    """Write persisted sorting-profile sync metadata to local SQLite storage."""
    from local_state import set_sorting_profile_sync_state

    set_sorting_profile_sync_state(state)


# ---------------------------------------------------------------------------
# API keys
# ---------------------------------------------------------------------------


def getApiKeys() -> dict[str, str]:
    """Read API keys from local SQLite storage."""
    from local_state import get_api_keys

    return get_api_keys()


def setApiKeys(keys: dict[str, str]) -> None:
    """Write API keys to local SQLite storage."""
    from local_state import set_api_keys

    set_api_keys(keys)


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
# Polygons (stored in local SQLite state, not TOML)
# ---------------------------------------------------------------------------


def getChannelPolygons() -> dict[str, Any] | None:
    """Read channel polygons from local SQLite storage."""
    from local_state import get_channel_polygons

    return get_channel_polygons()


def setChannelPolygons(polygons: dict[str, Any]) -> None:
    """Write channel polygons to local SQLite storage."""
    from local_state import set_channel_polygons

    set_channel_polygons(polygons)


def getClassificationPolygons() -> dict[str, Any] | None:
    """Read classification polygons from local SQLite storage."""
    from local_state import get_classification_polygons

    return get_classification_polygons()


def setClassificationPolygons(polygons: dict[str, Any]) -> None:
    """Write classification polygons to local SQLite storage."""
    from local_state import set_classification_polygons

    set_classification_polygons(polygons)


# ---------------------------------------------------------------------------
# Legacy migration entry point
# ---------------------------------------------------------------------------


def migrateFromDataJson() -> None:
    """Compatibility wrapper for the legacy startup migration entry point."""
    from local_state import initialize_local_state

    initialize_local_state()
