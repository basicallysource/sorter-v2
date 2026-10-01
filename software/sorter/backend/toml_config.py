"""Typed getters and setters for machine.toml's sections.

Declarative machine configuration stays in machine.toml; machine_toml.py reads it
and owns every write. Mutable local state such as polygons, sync state, training
session state, and secrets lives in `local_state.sqlite` via `local_state.py`.
"""

from __future__ import annotations

import time
from typing import Any

import machine_toml


# ---------------------------------------------------------------------------
# Classification channel rev01 tuning config
# ---------------------------------------------------------------------------


def getClassificationChannelRev01Config() -> dict[str, Any]:
    from subsystems.classification_channel.two_piece.rev01_config import (
        Rev01Config, configToDict,
    )
    config = machine_toml.read()
    section = config.get("classification_channel_rev01")
    defaults = configToDict(Rev01Config())
    if isinstance(section, dict):
        merged = {**defaults, **{k: v for k, v in section.items() if k in defaults}}
        return merged
    return defaults


def setClassificationChannelRev01Config(updates: dict[str, Any]) -> dict[str, Any]:
    from subsystems.classification_channel.two_piece.rev01_config import (
        Rev01Config, configToDict, configFromDict,
    )
    defaults = configToDict(Rev01Config())
    valid = {k: v for k, v in updates.items() if k in defaults}

    with machine_toml.edit() as config:
        existing = config.get("classification_channel_rev01")
        base = dict(existing) if isinstance(existing, dict) else {}
        base.update(valid)
        config["classification_channel_rev01"] = base
    return getClassificationChannelRev01Config()


# ---------------------------------------------------------------------------
# Perception object-tracker: active-tracker selection + per-tracker tuning
# ---------------------------------------------------------------------------
# The active tracker type lives in [object_tracker].type; each tracker's params
# live in their own [object_tracker_<type>] section, so switching trackers keeps
# each one's tuning. Helpers are generic over tracker type via TRACKER_SPECS.


def getActiveTrackerType() -> str:
    from perception.tracker_config import DEFAULT_TRACKER_TYPE, TRACKER_SPECS
    config = machine_toml.read()
    section = config.get("object_tracker")
    if isinstance(section, dict):
        t = section.get("type")
        if isinstance(t, str) and t in TRACKER_SPECS:
            return t
    return DEFAULT_TRACKER_TYPE


def setActiveTrackerType(tracker_type: str) -> str:
    from perception.tracker_config import DEFAULT_TRACKER_TYPE, TRACKER_SPECS
    t = tracker_type if tracker_type in TRACKER_SPECS else DEFAULT_TRACKER_TYPE

    with machine_toml.edit() as config:
        existing = config.get("object_tracker")
        base = dict(existing) if isinstance(existing, dict) else {}
        base["type"] = t
        config["object_tracker"] = base
    return getActiveTrackerType()


def getTrackerConfig(tracker_type: str) -> dict[str, Any]:
    from perception.tracker_config import defaultsFor
    config = machine_toml.read()
    section = config.get(f"object_tracker_{tracker_type}")
    defaults = defaultsFor(tracker_type)
    if isinstance(section, dict):
        return {**defaults, **{k: v for k, v in section.items() if k in defaults}}
    return defaults


def setTrackerConfig(tracker_type: str, updates: dict[str, Any]) -> dict[str, Any]:
    from perception.tracker_config import defaultsFor
    defaults = defaultsFor(tracker_type)
    valid = {k: v for k, v in updates.items() if k in defaults}
    key = f"object_tracker_{tracker_type}"

    with machine_toml.edit() as config:
        existing = config.get(key)
        base = dict(existing) if isinstance(existing, dict) else {}
        base.update(valid)
        config[key] = base
    return getTrackerConfig(tracker_type)


# ---------------------------------------------------------------------------
# Classification providers (mold + color)
# ---------------------------------------------------------------------------


def getClassificationProviders() -> dict[str, str]:
    from classification.providers import normalizeColorProvider, normalizeMoldProvider
    config = machine_toml.read()
    section = config.get("classification_providers")
    section = section if isinstance(section, dict) else {}
    return {
        "color_provider": normalizeColorProvider(section.get("color_provider")),
        "mold_provider": normalizeMoldProvider(section.get("mold_provider")),
    }


def setClassificationProviders(updates: dict[str, Any]) -> dict[str, str]:
    from classification.providers import normalizeColorProvider, normalizeMoldProvider
    valid: dict[str, str] = {}
    if "color_provider" in updates:
        valid["color_provider"] = normalizeColorProvider(updates.get("color_provider"))
    if "mold_provider" in updates:
        valid["mold_provider"] = normalizeMoldProvider(updates.get("mold_provider"))

    with machine_toml.edit() as config:
        existing = config.get("classification_providers")
        base = dict(existing) if isinstance(existing, dict) else {}
        base.update(valid)
        config["classification_providers"] = base
    return getClassificationProviders()


# ---------------------------------------------------------------------------
# Feeder pulse-perception tuning config
# ---------------------------------------------------------------------------


def getPulsePerceptionConfig() -> dict[str, Any]:
    from subsystems.feeder.pulse_perception.config import (
        PulsePerceptionConfig, configToDict, migrateLegacyKeys,
    )
    config = machine_toml.read()
    section = config.get("feeder_pulse_perception")
    defaults = configToDict(PulsePerceptionConfig())
    if isinstance(section, dict):
        # Migrate before filtering: retired keys are not in ``defaults``, so an
        # unmigrated section would have its old tuned value dropped on the floor.
        section = migrateLegacyKeys(section)
        return {**defaults, **{k: v for k, v in section.items() if k in defaults}}
    return defaults


def setPulsePerceptionConfig(updates: dict[str, Any]) -> dict[str, Any]:
    from subsystems.feeder.pulse_perception.config import (
        PulsePerceptionConfig, configToDict,
    )
    defaults = configToDict(PulsePerceptionConfig())
    valid = {k: v for k, v in updates.items() if k in defaults}

    with machine_toml.edit() as config:
        existing = config.get("feeder_pulse_perception")
        base = dict(existing) if isinstance(existing, dict) else {}
        base.update(valid)
        config["feeder_pulse_perception"] = base
    return getPulsePerceptionConfig()


# ---------------------------------------------------------------------------
# Detection configs
# ---------------------------------------------------------------------------


def getDetectionConfig(scope: str) -> dict[str, Any] | None:
    """Read detection config for a scope (classification/feeder/carousel)."""
    config = machine_toml.read()
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
    with machine_toml.edit() as config:
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


# ---------------------------------------------------------------------------
# Machine nickname
# ---------------------------------------------------------------------------


def getMachineNickname() -> str | None:
    """Read machine nickname from TOML [machine] section."""
    config = machine_toml.read()
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
    with machine_toml.edit() as config:
        if "machine" not in config:
            config["machine"] = {}
        normalized = nickname.strip() if isinstance(nickname, str) else ""
        if normalized:
            config["machine"]["nickname"] = normalized
        else:
            config["machine"].pop("nickname", None)


# ---------------------------------------------------------------------------
# Dashboard preferences
# ---------------------------------------------------------------------------


_INCIDENT_MODE_OFF = "off"
_INCIDENT_MODE_MANUAL = "manual"
_INCIDENT_MODE_AUTOMATIC = "automatic"
# Every incident kind is defined once, in incidents/kinds.py; the ones with a
# default handling are the ones this settings section offers.
def _incidentRegistry():
    from incidents import ALIASES, KINDS

    return KINDS, ALIASES


def _incidentHandlingDefaults() -> dict[str, str]:
    kinds, _aliases = _incidentRegistry()
    return {k: v.default_handling for k, v in kinds.items() if v.default_handling}


_DASHBOARD_DEFAULTS: dict[str, Any] = {
    "show_sample_capture": False,
}


def _canonicalIncidentKind(kind: Any) -> str | None:
    if not isinstance(kind, str):
        return None
    normalized = kind.strip()
    if not normalized:
        return None
    return _incidentRegistry()[1].get(normalized, normalized)


def _sanitizeIncidentHandling(value: Any) -> dict[str, str]:
    if not isinstance(value, dict):
        return {}
    sanitized: dict[str, str] = {}
    supported_kinds = set(_incidentHandlingDefaults().keys())
    for kind, mode in value.items():
        canonical_kind = _canonicalIncidentKind(kind)
        if canonical_kind not in supported_kinds:
            continue
        if mode in {_INCIDENT_MODE_OFF, _INCIDENT_MODE_MANUAL, _INCIDENT_MODE_AUTOMATIC}:
            sanitized[canonical_kind] = str(mode)
    return sanitized


def incidentDefinitions() -> list[dict[str, Any]]:
    kinds, _aliases = _incidentRegistry()
    return [
        {
            "kind": k.kind,
            "label": k.title,
            "scope": k.scope,
            "description": k.description,
            "off_label": k.off_label,
            "manual_label": k.manual_label,
            "automatic_label": k.automatic_label or "",
            "automatic_supported": k.automatic_label is not None,
        }
        for k in kinds.values()
        if k.default_handling
    ]


# The control loop asks how each incident is handled on every tick, so the map
# is read from machine.toml at most once a second (and at once after
# setDashboardConfig): (file, read at, handling).
_INCIDENT_HANDLING_TTL_S = 1.0
_incident_handling: tuple[Any, float, dict[str, Any]] | None = None


def incidentHandlingMode(kind: str) -> str:
    global _incident_handling
    canonical_kind = _canonicalIncidentKind(kind) or kind
    path, now = machine_toml.machine_toml_path(), time.monotonic()
    cached = _incident_handling
    if cached is None or cached[0] != path or now - cached[1] >= _INCIDENT_HANDLING_TTL_S:
        handling = getDashboardConfig().get("incident_handling")
        cached = (path, now, handling if isinstance(handling, dict) else {})
        _incident_handling = cached
    mode = cached[2].get(canonical_kind)
    if mode in {_INCIDENT_MODE_OFF, _INCIDENT_MODE_MANUAL, _INCIDENT_MODE_AUTOMATIC}:
        return str(mode)
    return _incidentHandlingDefaults().get(canonical_kind, _INCIDENT_MODE_MANUAL)


def incidentHandlingAutomatic(kind: str) -> bool:
    return incidentHandlingMode(kind) == _INCIDENT_MODE_AUTOMATIC


def incidentHandlingOff(kind: str) -> bool:
    return incidentHandlingMode(kind) == _INCIDENT_MODE_OFF


def getDashboardConfig() -> dict[str, Any]:
    """Return dashboard preferences merged on top of defaults."""
    config = machine_toml.read()
    section = config.get("dashboard")
    merged = {
        "show_sample_capture": bool(_DASHBOARD_DEFAULTS["show_sample_capture"]),
        "incident_handling": _incidentHandlingDefaults(),
        "incident_definitions": incidentDefinitions(),
    }
    if isinstance(section, dict):
        value = section.get("show_sample_capture")
        if isinstance(value, bool):
            merged["show_sample_capture"] = value
        handling = _incidentHandlingDefaults()
        handling.update(_sanitizeIncidentHandling(section.get("incident_handling")))
        merged["incident_handling"] = handling
    return merged


def setDashboardConfig(updates: dict[str, Any]) -> dict[str, Any]:
    """Persist dashboard preferences; unknown keys are ignored. Returns merged state."""
    global _incident_handling
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
            merged_handling = _incidentHandlingDefaults()
            merged_handling.update(_sanitizeIncidentHandling(existing))
            merged_handling.update(handling)
            sanitized["incident_handling"] = merged_handling

    with machine_toml.edit() as config:
        existing = config.get("dashboard") if isinstance(config.get("dashboard"), dict) else {}
        config["dashboard"] = {**existing, **sanitized}
    _incident_handling = None
    return getDashboardConfig()


# ---------------------------------------------------------------------------
# Bin assignment preferences
# ---------------------------------------------------------------------------


def getBinAssignmentConfig() -> dict[str, Any]:
    """Bin-assignment behavior. When allow_multiple_categories_per_bin is True,
    once every bin already has an assignment the distributor keeps sorting new
    categories by combining them into existing bins (picking the least-loaded
    one) instead of falling through to the misc/discard passthrough."""
    config = machine_toml.read()
    section = config.get("bins")
    allow_multiple = False
    if isinstance(section, dict) and isinstance(
        section.get("allow_multiple_categories_per_bin"), bool
    ):
        allow_multiple = section["allow_multiple_categories_per_bin"]
    return {"allow_multiple_categories_per_bin": allow_multiple}


def setBinAssignmentConfig(updates: dict[str, Any]) -> dict[str, Any]:
    with machine_toml.edit() as config:
        existing = config.get("bins")
        base = dict(existing) if isinstance(existing, dict) else {}
        if "allow_multiple_categories_per_bin" in updates:
            base["allow_multiple_categories_per_bin"] = bool(
                updates["allow_multiple_categories_per_bin"]
            )
        config["bins"] = base
    return getBinAssignmentConfig()


# ---------------------------------------------------------------------------
# Camera setup
# ---------------------------------------------------------------------------


def getCameraSetup() -> dict[str, Any] | None:
    """Read camera setup from TOML [cameras] section."""
    config = machine_toml.read()
    cameras = config.get("cameras")
    if not isinstance(cameras, dict):
        return None
    # Return the roles that have device indices assigned
    result: dict[str, Any] = {}
    for role in ("c_channel_2", "c_channel_3", "carousel", "classification_channel"):
        val = cameras.get(role)
        if val is not None:
            result[role] = val
    return result if result else None


# ---------------------------------------------------------------------------
# Piece-link matching (experimental)
# ---------------------------------------------------------------------------


DEFAULT_LINK_MIN_CONFIDENCE = 0.95


def getLinkMatchingConfig() -> dict[str, Any]:
    # Off by default: the matcher is experimental and costs an ONNX pass per
    # classified piece. ``algorithm`` is an installed piece_link model's
    # local_id; empty means "use whichever one is installed".
    # ``min_confidence`` overrides the threshold baked into the model at
    # publish time (0.5 for link-v3) — fused/preselected picks must score at
    # or above it.
    config = machine_toml.read()
    section = config.get("link_matching")
    section = section if isinstance(section, dict) else {}
    raw = section.get("min_confidence")
    min_confidence = (
        float(raw) if isinstance(raw, (int, float)) else DEFAULT_LINK_MIN_CONFIDENCE
    )
    return {
        "enabled": bool(section.get("enabled", False)),
        "algorithm": str(section.get("algorithm") or ""),
        "min_confidence": min(max(min_confidence, 0.0), 1.0),
    }


def setLinkMatchingConfig(updates: dict[str, Any]) -> dict[str, Any]:
    valid: dict[str, Any] = {}
    if "enabled" in updates:
        valid["enabled"] = bool(updates.get("enabled"))
    if "algorithm" in updates:
        valid["algorithm"] = str(updates.get("algorithm") or "")
    if "min_confidence" in updates:
        value = float(updates.get("min_confidence"))  # type: ignore[arg-type]
        if not (0.0 <= value <= 1.0):
            raise ValueError("min_confidence must be between 0 and 1")
        valid["min_confidence"] = value

    with machine_toml.edit() as config:
        existing = config.get("link_matching")
        base = dict(existing) if isinstance(existing, dict) else {}
        base.update(valid)
        config["link_matching"] = base
    return getLinkMatchingConfig()
