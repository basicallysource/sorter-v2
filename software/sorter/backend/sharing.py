"""What this sorter shares with Hive, and with which Hive.

STREAMS declares, once, every kind of data that can leave the machine for a
Hive: its label and the sentence the UI shows behind its info icon, its kind
(telemetry about the machine, records about pieces and runs, or pictures), its
size (small rows, or large files that draw on the upload budget), whether it is
required, and its default. hive_uploads is the only code that talks to a Hive's
upload endpoints and it asks streamAllowed before every request, so a choice
applies at send time, to uploads already queued too.

Choices are made for every Hive at once, and a Hive can override any of them.
A stream's value for a Hive: on if the stream is required; else that Hive's
override; else the machine-wide choice; else the default, which the primary
Hive can set for every sorter (hive_defaults) over the one declared here. An override is kept
only while it differs from the machine-wide value, so "follows every Hive" is
the absence of one.

Nothing but the keep-alive leaves for a Hive until the person has agreed to
what is shared (the consent, kept with the version of the notice they saw). A
machine that already shared with a Hive before there was a notice is
grandfathered: it keeps syncing, and the Data page asks once for a review.

The state is one local_state entry, cached in memory: every upload asks
streamAllowed, and this process is the only writer.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

KIND_TELEMETRY = "telemetry"
KIND_RECORDS = "records"
KIND_PICTURES = "pictures"
SIZE_SMALL = "small"
SIZE_LARGE = "large"

# The version of the notice the person agrees to. Raise it when what is
# shared changes enough that they should see the notice again.
CONSENT_VERSION = 1
# A machine that shared with a Hive before there was a notice.
CONSENT_GRANDFATHERED = 0


@dataclass(frozen=True)
class Stream:
    key: str
    label: str
    info: str
    kind: str
    size: str
    required: bool
    default: bool
    # Its key among the per-target fields that came before this module.
    legacy_key: str | None = None


STREAMS: tuple[Stream, ...] = (
    Stream(
        "machine_telemetry",
        "Machine telemetry",
        "How this sorter is set up and how it runs: its hardware and software, each motor's driver "
        "settings and load, each camera's exposure, and stalls. Summarised an hour at a time, so it "
        "stays small. No pictures and nothing about what you sort.",
        KIND_TELEMETRY, SIZE_SMALL, required=True, default=True, legacy_key="machine_specs",
    ),
    Stream(
        "piece_records",
        "Piece records",
        "What the sorter decided for each piece (part, color, confidence, bin and when), every "
        "prediction with its score, your corrections, sorting runs and set progress.",
        KIND_RECORDS, SIZE_SMALL, required=False, default=True, legacy_key="piece_metadata",
    ),
    Stream(
        "piece_images",
        "Piece pictures",
        "The cropped pictures each piece was classified from.",
        KIND_PICTURES, SIZE_LARGE, required=False, default=True, legacy_key="detection_images",
    ),
    Stream(
        "camera_frames",
        "Full camera frames",
        "Training samples: whole frames from each camera while sorting, with the camera's "
        "settings, the lamp's brightness and the channel outline at the time.",
        KIND_PICTURES, SIZE_LARGE, required=False, default=True, legacy_key="full_frames",
    ),
    Stream(
        "channel_crops",
        "Channel crops",
        "Small crops of pieces on C2 and C3 with where they were, used to follow a piece from "
        "channel to channel. Many a minute.",
        KIND_PICTURES, SIZE_LARGE, required=False, default=True, legacy_key="upstream_channel_crops",
    ),
    Stream(
        "feeder_logs",
        "Feeder logs",
        "Compressed logs of where the vision model saw pieces and every motor command while "
        "sorting, with the settings at the time. No pictures. Used to improve feeding.",
        KIND_TELEMETRY, SIZE_LARGE, required=False, default=True, legacy_key="feeder_dynamics",
    ),
    Stream(
        "network",
        "Network addresses",
        "Where to find this sorter on your networks (its addresses, Wi-Fi name, hostname and "
        "ports), so its Hive page can open it. Turned off, Hive forgets them.",
        KIND_TELEMETRY, SIZE_SMALL, required=False, default=True, legacy_key="network",
    ),
)

STREAM_KEYS = tuple(stream.key for stream in STREAMS)
_BY_KEY = {stream.key: stream for stream in STREAMS}
_BY_LEGACY_KEY = {stream.legacy_key: stream for stream in STREAMS if stream.legacy_key}
OPTIONAL_KEYS = tuple(stream.key for stream in STREAMS if not stream.required)

_lock = threading.Lock()
_cached: dict[str, Any] | None = None


def streamNamed(key: str) -> Stream | None:
    return _BY_KEY.get(key)


def defaults() -> dict[str, bool]:
    """Each optional stream's default: the primary Hive's, else the code's."""
    import hive_defaults

    return {
        stream.key: hive_defaults.value(f"sharing.{stream.key}", stream.default, lambda v: isinstance(v, bool))
        for stream in STREAMS
        if not stream.required
    }


def _bools(raw: Any) -> dict[str, bool]:
    if not isinstance(raw, dict):
        return {}
    return {key: value for key, value in raw.items() if key in OPTIONAL_KEYS and isinstance(value, bool)}


def _normalized(raw: Any) -> dict[str, Any]:
    raw = raw if isinstance(raw, dict) else {}
    targets = raw.get("targets") if isinstance(raw.get("targets"), dict) else {}
    consent = raw.get("consent")
    return {
        "every_hive": _bools(raw.get("every_hive")),
        "targets": {
            target_id: overrides
            for target_id, overrides in ((str(k), _bools(v)) for k, v in targets.items())
            if overrides
        },
        "consent": consent if isinstance(consent, dict) and isinstance(consent.get("version"), int) else None,
    }


def _migrated() -> dict[str, Any]:
    """The first state: per-target choices made before this module, moved
    into machine-wide choices where every Hive agrees and overrides where they
    differ. A machine that already had a Hive is grandfathered."""
    from local_state import get_hive_config, get_legacy_hive_telemetry, set_hive_config

    legacy = get_legacy_hive_telemetry()
    target_ids = [
        target["id"] for target in (get_hive_config() or {}).get("targets", []) if isinstance(target.get("id"), str)
    ]
    chosen: dict[str, dict[str, bool]] = {target_id: {} for target_id in target_ids}
    for target_id, fields in legacy.items():
        if target_id not in chosen:
            continue
        for legacy_key, value in fields.items():
            stream = _BY_LEGACY_KEY.get(legacy_key)
            if stream is not None and not stream.required and isinstance(value, bool):
                chosen[target_id][stream.key] = value
    every_hive: dict[str, bool] = {}
    overrides: dict[str, dict[str, bool]] = {}
    base = defaults()
    for key in OPTIONAL_KEYS:
        default = base[key]
        values = [chosen[target_id].get(key, default) for target_id in target_ids]
        if values and all(value == values[0] for value in values):
            if values[0] != default:
                every_hive[key] = values[0]
            continue
        for target_id, value in zip(target_ids, values):
            if value != default:
                overrides.setdefault(target_id, {})[key] = value
    state = {
        "every_hive": every_hive,
        "targets": overrides,
        "consent": {"version": CONSENT_GRANDFATHERED, "accepted_at": time.time()} if target_ids else None,
    }
    if legacy:
        # Rewritten without the per-target fields this replaces.
        set_hive_config(get_hive_config() or {"targets": []})
    return state


def _state() -> dict[str, Any]:
    global _cached
    with _lock:
        if _cached is None:
            from local_state import get_sharing_state, set_sharing_state

            raw = get_sharing_state()
            if raw is None:
                raw = _migrated()
                set_sharing_state(_normalized(raw))
            _cached = _normalized(raw)
        return _cached


def _save(state: dict[str, Any]) -> None:
    global _cached
    from local_state import set_sharing_state

    normalized = _normalized(state)
    with _lock:
        set_sharing_state(normalized)
        _cached = normalized


def invalidate() -> None:
    """Read the state again on next use (tests, and a restore of local state)."""
    global _cached
    with _lock:
        _cached = None


def everyHive() -> dict[str, bool]:
    return {**defaults(), **_state()["every_hive"]}


def everyHiveSet() -> list[str]:
    chosen = _state()["every_hive"]
    return [key for key in OPTIONAL_KEYS if key in chosen]


def targetOverrides(target_id: str) -> dict[str, bool]:
    return dict(_state()["targets"].get(target_id, {}))


def effective(target_id: str) -> dict[str, bool]:
    values = {**everyHive(), **targetOverrides(target_id)}
    return {stream.key: True if stream.required else values[stream.key] for stream in STREAMS}


def consentGiven() -> bool:
    return _state()["consent"] is not None


def streamAllowed(target_id: str, key: str) -> bool:
    stream = _BY_KEY.get(key)
    if stream is None or not consentGiven():
        return False
    return effective(target_id)[key]


def _checked(values: dict[str, Any]) -> dict[str, bool]:
    unknown = sorted(key for key in values if key not in _BY_KEY)
    if unknown:
        raise ValueError(f"Unknown streams: {', '.join(unknown)}")
    required = sorted(key for key in values if _BY_KEY[key].required)
    if required:
        raise ValueError(f"Always shared, so it cannot be turned off: {', '.join(required)}")
    wrong = sorted(key for key, value in values.items() if not isinstance(value, bool))
    if wrong:
        raise ValueError(f"Expected true or false for: {', '.join(wrong)}")
    return dict(values)


def setEveryHive(values: dict[str, Any]) -> None:
    """Choose for every Hive. A choice equal to the default is no choice (the
    stream follows its default, should that change), and a Hive's override
    that now matches every Hive is dropped."""
    values = _checked(values)
    state = _state()
    base = defaults()
    every_hive = {key: value for key, value in {**state["every_hive"], **values}.items() if value != base[key]}
    merged = {**base, **every_hive}
    targets = {
        target_id: {key: value for key, value in overrides.items() if value != merged[key]}
        for target_id, overrides in state["targets"].items()
    }
    _save({**state, "every_hive": every_hive, "targets": targets})


def setForTarget(target_id: str, values: dict[str, Any]) -> None:
    """Override some streams for one Hive; a value equal to every Hive's
    removes that override."""
    values = _checked(values)
    state = _state()
    base = everyHive()
    overrides = {**state["targets"].get(target_id, {}), **values}
    overrides = {key: value for key, value in overrides.items() if value != base[key]}
    _save({**state, "targets": {**state["targets"], target_id: overrides}})


def resetEveryHive() -> None:
    state = _state()
    base = defaults()
    targets = {
        target_id: {key: value for key, value in overrides.items() if value != base[key]}
        for target_id, overrides in state["targets"].items()
    }
    _save({**state, "every_hive": {}, "targets": targets})


def resetTarget(target_id: str) -> None:
    state = _state()
    targets = {key: value for key, value in state["targets"].items() if key != target_id}
    _save({**state, "targets": targets})


def forgetTarget(target_id: str) -> None:
    """A Hive was removed: its overrides go with it."""
    if target_id in _state()["targets"]:
        resetTarget(target_id)


def recordConsent(version: int, values: dict[str, Any] | None = None) -> None:
    """The person agreed to the notice of `version`, choosing `values` for
    every Hive (the optional streams they left on or turned off)."""
    if version != CONSENT_VERSION:
        raise ValueError(f"The notice is version {CONSENT_VERSION}, not {version}.")
    if values:
        setEveryHive(values)
    state = _state()
    _save({**state, "consent": {"version": version, "accepted_at": time.time()}})


def consentView() -> dict[str, Any]:
    consent = _state()["consent"]
    version: int | None = consent["version"] if consent else None
    accepted_at = consent.get("accepted_at") if consent else None
    return {
        "current_version": CONSENT_VERSION,
        "version": version,
        "accepted_at": (
            datetime.fromtimestamp(float(accepted_at), timezone.utc).isoformat()
            if isinstance(accepted_at, (int, float)) else None
        ),
        "needs_consent": version is None,
        "needs_review": version is not None and version < CONSENT_VERSION,
    }


def streamList() -> list[dict[str, Any]]:
    base = defaults()
    return [
        {
            "key": stream.key,
            "label": stream.label,
            "info": stream.info,
            "kind": stream.kind,
            "size": stream.size,
            "required": stream.required,
            "default": base.get(stream.key, stream.default),
        }
        for stream in STREAMS
    ]


def view(targets: list[dict[str, Any]], primary_target_id: str | None) -> dict[str, Any]:
    """Everything the Data page shows about sharing, for these Hive targets."""
    return {
        "streams": streamList(),
        "defaults": defaults(),
        "every_hive": everyHive(),
        "every_hive_set": everyHiveSet(),
        "targets": [
            {
                "id": target["id"],
                "name": target.get("name") or target.get("url"),
                "url": target.get("url", ""),
                "enabled": bool(target.get("enabled", False)),
                "is_primary": target["id"] == primary_target_id,
                "effective": effective(target["id"]),
                "overrides": targetOverrides(target["id"]),
            }
            for target in targets
        ],
        "consent": consentView(),
    }
