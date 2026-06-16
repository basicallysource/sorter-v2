"""Tracker selection + per-tracker tunable config.

Two trackers are available (``TrackerType``). The active one is persisted in
``machine_params.toml`` under ``[object_tracker].type``; each tracker's params
live in their OWN ``[object_tracker_<type>]`` section, so switching trackers
preserves each one's tuning. Every tracker has its own config dataclass +
``FIELD_META`` — the params shown in the Settings UI change with the selected
tracker. ``TRACKER_SPECS`` is the single registry the API + factory read, so
adding a tracker is: new enum value, new dataclass + FIELD_META, new spec entry.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any


class TrackerType(str, Enum):
    # supervision ByteTrack: motion (linear Kalman) + box-overlap (IoU). No
    # appearance. Simple/fast but loses ids on fast, curved, or off-frame motion.
    BYTETRACK = "bytetrack"
    # Domain tracker for this machine: associates by ANGLE around the channel
    # center (circular motion + off-screen excursions predict correctly) plus a
    # color gate. Keeps ids through the curve and brief disappearances.
    ANGULAR = "angular"


# --- ByteTrack ------------------------------------------------------------


@dataclass
class ByteTrackConfig:
    track_activation_threshold: float = 0.1
    lost_track_buffer: int = 30
    minimum_matching_threshold: float = 0.9
    frame_rate: int = 30
    minimum_consecutive_frames: int = 1


BYTETRACK_FIELD_META: list[dict] = [
    {
        "section": "Track creation",
        "key": "track_activation_threshold",
        "label": "Activation threshold",
        "type": "float",
        "default": 0.1,
        "description": (
            "Minimum detection confidence to START a new track. ByteTrack derives "
            "its high/low score split from this (only detections above this + 0.1 "
            "start a fresh track; lower ones can still extend an existing track). "
            "Keep it below the detector's conf threshold (≈0.25) or pieces won't "
            "get tracked."
        ),
    },
    {
        "section": "Track creation",
        "key": "minimum_consecutive_frames",
        "label": "Min consecutive frames",
        "type": "int",
        "default": 1,
        "description": (
            "How many frames in a row a detection must be tracked before it gets a "
            "stable id. 1 = labeled immediately; raise to suppress one-frame false "
            "detections."
        ),
    },
    {
        "section": "Matching",
        "key": "minimum_matching_threshold",
        "label": "Matching threshold",
        "type": "float",
        "default": 0.9,
        "description": (
            "Match cost is (1 − IoU) between a track's predicted box and a new "
            "detection; a pair matches below this, so 0.9 accepts IoU ≥ 0.1. Note "
            "this needs the boxes to actually OVERLAP — a piece that leaves the "
            "frame and curves back gets zero overlap and a new id regardless. Use "
            "the Angular tracker for that."
        ),
    },
    {
        "section": "Occlusion / lifetime",
        "key": "lost_track_buffer",
        "label": "Lost-track buffer (frames)",
        "type": "int",
        "default": 30,
        "description": (
            "Frames a track keeps coasting (Kalman prediction) after detections "
            "stop, before losing its id. Frames retained = lost_track_buffer × "
            "(frame_rate ÷ 30). At 30 fps, 30 ≈ 1 second."
        ),
    },
    {
        "section": "Occlusion / lifetime",
        "key": "frame_rate",
        "label": "Frame rate",
        "type": "int",
        "default": 30,
        "description": (
            "The fps ByteTrack assumes — only scales the lost-track buffer into a "
            "real frame count. Set it near the perception loop's actual inference "
            "rate."
        ),
    },
]


# --- Angular + Color ------------------------------------------------------


@dataclass
class AngularTrackerConfig:
    angular_gate_deg: float = 14.0
    radius_gate_frac: float = 0.30
    use_color: bool = True
    color_gate: float = 0.22
    max_coast_s: float = 2.5
    min_hits: int = 1
    activation_score: float = 0.1
    velocity_smoothing: float = 0.5


ANGULAR_FIELD_META: list[dict] = [
    {
        "section": "Track creation",
        "key": "min_hits",
        "label": "Min hits",
        "type": "int",
        "default": 1,
        "description": (
            "How many frames a new detection must be seen before it gets a stable "
            "id. 1 = labeled immediately."
        ),
    },
    {
        "section": "Track creation",
        "key": "activation_score",
        "label": "Activation score",
        "type": "float",
        "default": 0.1,
        "description": (
            "Minimum detection confidence to start a new track. Detections below "
            "the model's own conf threshold never reach the tracker."
        ),
    },
    {
        "section": "Matching",
        "key": "angular_gate_deg",
        "label": "Match gate (°)",
        "type": "float",
        "default": 14.0,
        "description": (
            "Max angle (around the channel center) between a track's PREDICTED "
            "position and a new detection for them to be the same piece. Because "
            "pieces move at a roughly constant angular speed, the prediction "
            "stays accurate around the curve and across brief disappearances — "
            "this is what lets an off-screen piece keep its id. Raise it to "
            "tolerate faster pieces or longer gaps; lower it if nearby pieces get "
            "confused."
        ),
    },
    {
        "section": "Matching",
        "key": "radius_gate_frac",
        "label": "Radius gate (fraction)",
        "type": "float",
        "default": 0.30,
        "description": (
            "Max difference in distance-from-center between a track and a "
            "detection to match, as a fraction of the radius. Pieces stay at a "
            "roughly fixed radius on the channel, so this rejects matches that "
            "jump across the channel width. 0.3 = within 30%."
        ),
    },
    {
        "section": "Color",
        "key": "use_color",
        "label": "Use color gate",
        "type": "bool",
        "default": True,
        "description": (
            "Require a detection's average color to resemble the track's before "
            "matching. Cheap and very effective for LEGO — a gray piece won't be "
            "confused with a yellow one — especially when re-acquiring after a "
            "piece reappears."
        ),
    },
    {
        "section": "Color",
        "key": "color_gate",
        "label": "Color tolerance (0–1)",
        "type": "float",
        "default": 0.22,
        "description": (
            "How different two average colors can be and still match (0 = "
            "identical, 1 = anything). Only used when the color gate is on. Lower "
            "= stricter color match."
        ),
    },
    {
        "section": "Motion",
        "key": "velocity_smoothing",
        "label": "Velocity smoothing (0–1)",
        "type": "float",
        "default": 0.5,
        "description": (
            "Smoothing factor for the estimated angular speed used to predict "
            "where a piece will be after a gap. Higher reacts faster to speed "
            "changes; lower is steadier."
        ),
    },
    {
        "section": "Occlusion / lifetime",
        "key": "max_coast_s",
        "label": "Coast time (s)",
        "type": "float",
        "default": 2.5,
        "description": (
            "How long to keep predicting a piece's position after it stops being "
            "detected (occlusion / off-frame) before giving up its id. The "
            "angular prediction continues around the circle during this window, "
            "so the piece is re-acquired where it actually re-enters."
        ),
    },
]


# --- Registry -------------------------------------------------------------


@dataclass
class TrackerSpec:
    type: str
    label: str
    description: str
    config_cls: type
    field_meta: list[dict]


TRACKER_SPECS: dict[str, "TrackerSpec"] = {
    TrackerType.BYTETRACK.value: TrackerSpec(
        type=TrackerType.BYTETRACK.value,
        label="ByteTrack",
        description=(
            "Motion + box-overlap (supervision). Linear motion model, no "
            "appearance. Fast and simple, but loses ids when a piece moves far, "
            "curves, or briefly leaves the frame."
        ),
        config_cls=ByteTrackConfig,
        field_meta=BYTETRACK_FIELD_META,
    ),
    TrackerType.ANGULAR.value: TrackerSpec(
        type=TrackerType.ANGULAR.value,
        label="Angular + Color",
        description=(
            "Tracks each piece by its angle around the channel center, so "
            "circular motion and off-screen excursions are predicted correctly, "
            "with a color gate. Built for this machine's geometry — best for "
            "keeping ids through the curve and brief disappearances."
        ),
        config_cls=AngularTrackerConfig,
        field_meta=ANGULAR_FIELD_META,
    ),
}

DEFAULT_TRACKER_TYPE = TrackerType.BYTETRACK.value


def specFor(tracker_type: str) -> TrackerSpec:
    return TRACKER_SPECS.get(tracker_type, TRACKER_SPECS[DEFAULT_TRACKER_TYPE])


def _coerce(meta: dict, raw: Any, cfg: Any) -> None:
    k = meta["key"]
    try:
        if meta["type"] == "int":
            setattr(cfg, k, int(raw))
        elif meta["type"] == "bool":
            setattr(cfg, k, bool(raw))
        else:
            setattr(cfg, k, float(raw))
    except (TypeError, ValueError):
        pass


def configFromDict(tracker_type: str, d: dict) -> Any:
    spec = specFor(tracker_type)
    cfg = spec.config_cls()
    for meta in spec.field_meta:
        if meta["key"] in d:
            _coerce(meta, d[meta["key"]], cfg)
    return cfg


def configToDict(tracker_type: str, cfg: Any) -> dict[str, Any]:
    spec = specFor(tracker_type)
    return {meta["key"]: getattr(cfg, meta["key"]) for meta in spec.field_meta}


def defaultsFor(tracker_type: str) -> dict[str, Any]:
    spec = specFor(tracker_type)
    return configToDict(tracker_type, spec.config_cls())
