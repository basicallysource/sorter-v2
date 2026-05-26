"""Machine config helpers.

Declarative machine configuration stays in `machine_params.toml`.
Mutable local state such as polygons, sync state, training session state,
and secrets lives in `local_state.sqlite` via `local_state.py`.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import threading
import tomllib
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from server.config_helpers import write_machine_params_config


def loadTomlFile(path: str | Path) -> dict[str, Any]:
    path_str = str(path)
    try:
        with open(path_str, "rb") as f:
            return tomllib.load(f)
    except tomllib.TOMLDecodeError as e:
        print(f"[config] malformed TOML at {path_str}: {e}", file=sys.stderr)
        sys.exit(1)

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
    """Read and parse the TOML file. Returns {} if missing. Malformed TOML exits the program."""
    path = _toml_path()
    if not os.path.exists(path):
        return {}
    return loadTomlFile(path)


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
# Classification channel rev01 tuning config
# ---------------------------------------------------------------------------


def getClassificationChannelRev01Config() -> dict[str, Any]:
    from subsystems.classification_channel.simple_state_machine_rev01.rev01_config import (
        Rev01Config, configToDict,
    )
    config = _read_toml()
    section = config.get("classification_channel_rev01")
    defaults = configToDict(Rev01Config())
    if isinstance(section, dict):
        merged = {**defaults, **{k: v for k, v in section.items() if k in defaults}}
        return merged
    return defaults


def setClassificationChannelRev01Config(updates: dict[str, Any]) -> dict[str, Any]:
    from subsystems.classification_channel.simple_state_machine_rev01.rev01_config import (
        Rev01Config, configToDict, configFromDict,
    )
    defaults = configToDict(Rev01Config())
    valid = {k: v for k, v in updates.items() if k in defaults}

    def updater(config: dict[str, Any]) -> None:
        existing = config.get("classification_channel_rev01")
        base = dict(existing) if isinstance(existing, dict) else {}
        base.update(valid)
        config["classification_channel_rev01"] = base

    _update_toml(updater)
    return getClassificationChannelRev01Config()


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
    # Flatten role-specific sub-tables into the dict.
    result = dict(section)
    algorithm_by_role = result.pop("algorithm_by_role", None)
    if isinstance(algorithm_by_role, dict):
        result["algorithm_by_role"] = algorithm_by_role
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
        # Separate role-specific keys into sub-tables.
        algorithm_by_role = section.pop("algorithm_by_role", None)
        by_role = section.pop("sample_collection_enabled_by_role", None)
        config["detection"][scope] = section
        if isinstance(algorithm_by_role, dict):
            config["detection"][scope]["algorithm_by_role"] = algorithm_by_role
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
# Dashboard preferences
# ---------------------------------------------------------------------------


_INCIDENT_MODE_OFF = "off"
_INCIDENT_MODE_MANUAL = "manual"
_INCIDENT_MODE_AUTOMATIC = "automatic"
_INCIDENT_EXIT_STUCK = "exit_stuck"
_INCIDENT_KIND_ALIASES: dict[str, str] = {
    "classification_exit_release": _INCIDENT_EXIT_STUCK,
    "channel_exit_stuck": _INCIDENT_EXIT_STUCK,
}
_INCIDENT_HANDLING_DEFAULTS: dict[str, str] = {
    _INCIDENT_EXIT_STUCK: _INCIDENT_MODE_MANUAL,
    "channel_dropzone_stuck": _INCIDENT_MODE_MANUAL,
    "c2_separation_needed": _INCIDENT_MODE_MANUAL,
    "bulk_feeder_stalled": _INCIDENT_MODE_MANUAL,
    "feeder_detection_unavailable": _INCIDENT_MODE_MANUAL,
    "distribution_chute_jam": _INCIDENT_MODE_MANUAL,
    "distribution_servo_bus_offline": _INCIDENT_MODE_MANUAL,
    "distribution_no_bin_available": _INCIDENT_MODE_MANUAL,
    "classification_unresolved": _INCIDENT_MODE_MANUAL,
    "classification_multi_drop_collision": _INCIDENT_MODE_MANUAL,
    "classification_intake_request_timeout": _INCIDENT_MODE_MANUAL,
    "classification_track_lost": _INCIDENT_MODE_MANUAL,
}
_INCIDENT_DEFINITIONS: tuple[dict[str, Any], ...] = (
    {
        "kind": _INCIDENT_EXIT_STUCK,
        "label": "Exit Stuck",
        "scope": "C2/C3/C4",
        "description": "A piece is not falling off the channel.",
        "off_label": "Do not raise exit-stuck incidents",
        "manual_label": "Operator tunes release wiggle",
        "automatic_label": "Run release wiggle automatically",
        "automatic_supported": True,
    },
    {
        "kind": "channel_dropzone_stuck",
        "label": "Dropzone Stuck",
        "scope": "C2/C3/C4",
        "description": "A piece is not moving as expected.",
        "off_label": "Leave normal backpressure unchanged",
        "manual_label": "Operator acknowledges ignore",
        "automatic_label": "Ignore stuck track automatically",
        "automatic_supported": True,
    },
    {
        "kind": "c2_separation_needed",
        "label": "Slip-Stick Separation",
        "scope": "C2",
        "description": "Pieces are not spreading out as expected.",
        "off_label": "Do not raise separation incident",
        "manual_label": "Operator reviews separation",
        "automatic_label": "Automatic slip-stick separation",
        "automatic_supported": False,
    },
    {
        "kind": "bulk_feeder_stalled",
        "label": "Bulk Feed Stalled",
        "scope": "C1",
        "description": "No pieces are reaching the next channel.",
        "off_label": "Keep legacy bulk-feeder recovery hidden",
        "manual_label": "Operator checks the bulk feeder",
        "automatic_label": "Automatic bulk-feeder recovery",
        "automatic_supported": False,
    },
    {
        "kind": "feeder_detection_unavailable",
        "label": "Detection Unavailable",
        "scope": "C2/C3/C4",
        "description": "Feeder camera detection is not reliable.",
        "off_label": "Use hardware alert only",
        "manual_label": "Operator restores detection",
        "automatic_label": "Automatic camera recovery",
        "automatic_supported": False,
    },
    {
        "kind": "distribution_chute_jam",
        "label": "Chute Jam",
        "scope": "Distribution",
        "description": "The distribution chute did not finish moving.",
        "off_label": "Use hardware alert only",
        "manual_label": "Operator clears the chute",
        "automatic_label": "Automatic chute recovery",
        "automatic_supported": False,
    },
    {
        "kind": "distribution_servo_bus_offline",
        "label": "Servo Bus Offline",
        "scope": "Distribution",
        "description": "The distribution servo bus is not responding.",
        "off_label": "Use hardware alert only",
        "manual_label": "Operator restores the servo bus",
        "automatic_label": "Automatic servo bus recovery",
        "automatic_supported": False,
    },
    {
        "kind": "distribution_no_bin_available",
        "label": "No Bin Available",
        "scope": "Distribution",
        "description": "No matching bin is available for the piece.",
        "off_label": "Allow bottom-tray passthrough",
        "manual_label": "Operator assigns capacity or approves passthrough",
        "automatic_label": "Automatic no-bin passthrough",
        "automatic_supported": False,
    },
    {
        "kind": "classification_unresolved",
        "label": "Classification Unresolved",
        "scope": "C4",
        "description": "A piece reached the drop point without a resolved classification.",
        "off_label": "Keep unknown fallback hidden",
        "manual_label": "Operator reviews unresolved classifications",
        "automatic_label": "Automatic unresolved-classification handling",
        "automatic_supported": False,
    },
    {
        "kind": "classification_multi_drop_collision",
        "label": "Multi-Drop Collision",
        "scope": "C4",
        "description": "Multiple pieces reached the drop point together.",
        "off_label": "Keep multi-drop fallback hidden",
        "manual_label": "Operator reviews multi-drop collisions",
        "automatic_label": "Automatic multi-drop handling",
        "automatic_supported": False,
    },
    {
        "kind": "classification_intake_request_timeout",
        "label": "Intake Request Timeout",
        "scope": "C4",
        "description": "C4 requested a piece, but no handoff arrived.",
        "off_label": "Retry C4 intake requests silently",
        "manual_label": "Operator checks C3 to C4 handoff",
        "automatic_label": "Automatic C4 handoff recovery",
        "automatic_supported": False,
    },
    {
        "kind": "classification_track_lost",
        "label": "Track Lost",
        "scope": "C4",
        "description": "A tracked piece disappeared before the expected drop flow completed.",
        "off_label": "Treat stale C4 tracks as diagnostics",
        "manual_label": "Operator reviews lost C4 tracks",
        "automatic_label": "Automatic track-loss handling",
        "automatic_supported": False,
    },
)

_DASHBOARD_DEFAULTS: dict[str, Any] = {
    "show_sample_capture": False,
    "incident_handling": dict(_INCIDENT_HANDLING_DEFAULTS),
}


def _canonicalIncidentKind(kind: Any) -> str | None:
    if not isinstance(kind, str):
        return None
    normalized = kind.strip()
    if not normalized:
        return None
    return _INCIDENT_KIND_ALIASES.get(normalized, normalized)


def _sanitizeIncidentHandling(value: Any) -> dict[str, str]:
    if not isinstance(value, dict):
        return {}
    sanitized: dict[str, str] = {}
    supported_kinds = set(_INCIDENT_HANDLING_DEFAULTS.keys())
    for kind, mode in value.items():
        canonical_kind = _canonicalIncidentKind(kind)
        if canonical_kind not in supported_kinds:
            continue
        if mode in {_INCIDENT_MODE_OFF, _INCIDENT_MODE_MANUAL, _INCIDENT_MODE_AUTOMATIC}:
            sanitized[canonical_kind] = str(mode)
    return sanitized


def incidentDefinitions() -> list[dict[str, Any]]:
    return [dict(entry) for entry in _INCIDENT_DEFINITIONS]


def incidentHandlingMode(kind: str) -> str:
    canonical_kind = _canonicalIncidentKind(kind) or kind
    handling = getDashboardConfig().get("incident_handling")
    if isinstance(handling, dict):
        mode = handling.get(canonical_kind)
        if mode in {_INCIDENT_MODE_OFF, _INCIDENT_MODE_MANUAL, _INCIDENT_MODE_AUTOMATIC}:
            return str(mode)
    return _INCIDENT_HANDLING_DEFAULTS.get(canonical_kind, _INCIDENT_MODE_MANUAL)


def incidentHandlingAutomatic(kind: str) -> bool:
    return incidentHandlingMode(kind) == _INCIDENT_MODE_AUTOMATIC


def incidentHandlingOff(kind: str) -> bool:
    return incidentHandlingMode(kind) == _INCIDENT_MODE_OFF


def getDashboardConfig() -> dict[str, Any]:
    """Return dashboard preferences merged on top of defaults."""
    config = _read_toml()
    section = config.get("dashboard")
    merged = {
        "show_sample_capture": bool(_DASHBOARD_DEFAULTS["show_sample_capture"]),
        "incident_handling": dict(_INCIDENT_HANDLING_DEFAULTS),
        "incident_definitions": incidentDefinitions(),
    }
    if isinstance(section, dict):
        value = section.get("show_sample_capture")
        if isinstance(value, bool):
            merged["show_sample_capture"] = value
        handling = dict(_INCIDENT_HANDLING_DEFAULTS)
        handling.update(_sanitizeIncidentHandling(section.get("incident_handling")))
        merged["incident_handling"] = handling
    return merged


def setDashboardConfig(updates: dict[str, Any]) -> dict[str, Any]:
    """Persist dashboard preferences; unknown keys are ignored. Returns merged state."""
    sanitized: dict[str, Any] = {}
    if "show_sample_capture" in updates and isinstance(updates["show_sample_capture"], bool):
        sanitized["show_sample_capture"] = updates["show_sample_capture"]
    if "incident_handling" in updates:
        handling = _sanitizeIncidentHandling(updates["incident_handling"])
        if handling:
            existing_config = getDashboardConfig()
            existing = (
                existing_config.get("incident_handling")
                if isinstance(existing_config.get("incident_handling"), dict)
                else {}
            )
            merged_handling = dict(_INCIDENT_HANDLING_DEFAULTS)
            merged_handling.update(_sanitizeIncidentHandling(existing))
            merged_handling.update(handling)
            sanitized["incident_handling"] = merged_handling

    def updater(config: dict[str, Any]) -> None:
        existing = config.get("dashboard") if isinstance(config.get("dashboard"), dict) else {}
        config["dashboard"] = {**existing, **sanitized}

    _update_toml(updater)
    return getDashboardConfig()


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
