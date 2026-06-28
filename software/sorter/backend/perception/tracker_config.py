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
    # Strongest domain tracker: exploits the no-crossing order invariant of a
    # rigid one-way platter. Aligns this frame's travel-ordered detections to the
    # live tracks, requiring only that order is preserved and pieces move forward
    # — robust to arbitrarily large between-frame jumps, with no motion model and
    # no motor-timing dependence. Color/size are soft tie-breakers.
    ORDERED = "ordered"


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


# --- Ordered (channel queue) ----------------------------------------------


@dataclass
class OrderedTrackerConfig:
    # Pieces only move toward the exit; a detection whose travel-gap GREW by more
    # than this (deg) moved backward, so it can't be that track. Small — just
    # absorbs COM jitter. Large forward jumps are always allowed.
    back_tol_deg: float = 8.0
    # How long (s) to keep coasting a track with no matching detection before
    # giving up its id. Long enough to ride out a detector blink; a piece that
    # truly left (off the exit) ages out and its disappearance reads as ejected.
    max_coast_s: float = 1.5
    # Soft tie-breaker weights (only used to disambiguate order-compatible
    # candidates, never to bridge a jump). Color dominates; size/radius assist.
    color_weight: float = 1.0
    size_weight: float = 0.4
    radius_weight: float = 0.4
    # Fraction of the bbox (centered) sampled for color — a big box is mostly
    # platter background, so sample the middle where the piece is.
    color_center_frac: float = 0.5
    # A candidate match whose combined tie-breaker cost exceeds this is rejected
    # (treated as exit + new instead) — stops two clearly-different pieces being
    # matched when an exit and an arrival happen in the same frame.
    match_max_cost: float = 0.6
    # Base costs for leaving a track unmatched (exit/blink) vs. spawning a new id.
    # Tuned so re-acquiring a coasting track beats dropping it + making a new one.
    miss_cost: float = 0.7
    new_cost: float = 0.7
    # Min detection confidence to START a new track.
    new_track_min_score: float = 0.1
    # Ghost filter: frames a NEW track must be seen before it is CONFIRMED and its
    # id is emitted. A box that flickers in for a single frame never reaches this,
    # so it never becomes a piece (no false multi-drop, no phantom KnownObject).
    # Real pieces sit at rest in the drop zone for ~1s, so the few-frame delay is
    # invisible. 1 = emit immediately (no filtering).
    min_hits: int = 3
    # Coast leash for a TENTATIVE (not-yet-confirmed) track — much shorter than
    # max_coast_s so a one-frame false detection is dropped almost immediately
    # instead of lingering. Confirmed tracks use max_coast_s to ride real blinks.
    tentative_max_coast_s: float = 0.3
    # EMA factor for the running color estimate.
    smoothing: float = 0.5


ORDERED_FIELD_META: list[dict] = [
    {
        "section": "Matching",
        "key": "back_tol_deg",
        "label": "Backward tolerance (°)",
        "type": "float",
        "default": OrderedTrackerConfig().back_tol_deg,
        "description": (
            "Pieces only travel toward the exit. A detection whose travel position "
            "moved backward by more than this many degrees can't be the same piece "
            "(just absorbs detection jitter). Forward jumps of any size are always "
            "allowed — that's what makes this robust to the platter's fast moves."
        ),
    },
    {
        "section": "Matching",
        "key": "match_max_cost",
        "label": "Max match cost",
        "type": "float",
        "default": OrderedTrackerConfig().match_max_cost,
        "description": (
            "Upper bound on the color+size+radius tie-breaker cost for a match. Above "
            "it the pair is treated as 'one piece exited and a different one arrived' "
            "rather than the same piece. Lower = stricter about appearance changes."
        ),
    },
    {
        "section": "Appearance",
        "key": "color_weight",
        "label": "Color weight",
        "type": "float",
        "default": OrderedTrackerConfig().color_weight,
        "description": (
            "How strongly color disambiguates two order-ambiguous candidates. Color "
            "is sampled from the center of the box (saturation-weighted hue + "
            "brightness), so it separates e.g. a gray piece from a yellow one."
        ),
    },
    {
        "section": "Appearance",
        "key": "size_weight",
        "label": "Size weight",
        "type": "float",
        "default": OrderedTrackerConfig().size_weight,
        "description": "Tie-breaker weight on relative bbox-area difference between a track and a detection.",
    },
    {
        "section": "Appearance",
        "key": "radius_weight",
        "label": "Radius weight",
        "type": "float",
        "default": OrderedTrackerConfig().radius_weight,
        "description": "Tie-breaker weight on how far the two sit from the channel center (pieces stay at a roughly fixed radius).",
    },
    {
        "section": "Appearance",
        "key": "color_center_frac",
        "label": "Color sample (center fraction)",
        "type": "float",
        "default": OrderedTrackerConfig().color_center_frac,
        "description": (
            "Fraction of the bbox, centered, used to sample color. 0.5 = the middle "
            "50%. Smaller focuses on the piece and ignores surrounding platter; too "
            "small gets noisy."
        ),
    },
    {
        "section": "Lifetime",
        "key": "max_coast_s",
        "label": "Coast time (s)",
        "type": "float",
        "default": OrderedTrackerConfig().max_coast_s,
        "description": (
            "How long to keep a track alive with no matching detection (a blink / "
            "brief occlusion) before dropping its id. A piece that actually left the "
            "exit ages out here, and its disappearance is what marks it ejected."
        ),
    },
    {
        "section": "Lifetime",
        "key": "miss_cost",
        "label": "Unmatched-track cost",
        "type": "float",
        "default": OrderedTrackerConfig().miss_cost,
        "description": (
            "Cost of leaving a live track with no detection this frame (it exited or "
            "blinked). Raise to hold ids harder through dropouts; lower to give them "
            "up sooner."
        ),
    },
    {
        "section": "Lifetime",
        "key": "new_cost",
        "label": "New-track cost",
        "type": "float",
        "default": OrderedTrackerConfig().new_cost,
        "description": (
            "Cost of spawning a new id for a detection that matched no track. A box "
            "in the drop zone is discounted (legitimate arrival); raise this to "
            "suppress spurious new ids elsewhere."
        ),
    },
    {
        "section": "Track creation",
        "key": "new_track_min_score",
        "label": "Activation score",
        "type": "float",
        "default": OrderedTrackerConfig().new_track_min_score,
        "description": "Minimum detection confidence to start a new track.",
    },
    {
        "section": "Track creation",
        "key": "min_hits",
        "label": "Confirm frames (ghost filter)",
        "type": "int",
        "default": OrderedTrackerConfig().min_hits,
        "description": (
            "Frames a new detection must persist before it gets an id and counts "
            "as a real piece. This is the filter for spurious one-frame detections "
            "— raise it if false boxes still slip through, lower toward 1 if real "
            "pieces are slow to be picked up. 3 ≈ a quarter second."
        ),
    },
    {
        "section": "Track creation",
        "key": "tentative_max_coast_s",
        "label": "Tentative coast (s)",
        "type": "float",
        "default": OrderedTrackerConfig().tentative_max_coast_s,
        "description": (
            "How long an unconfirmed track is kept when it stops being detected, "
            "before it's discarded. Short, so a one-frame ghost vanishes fast. "
            "Confirmed pieces instead use the (longer) coast time so they survive "
            "real detector blinks."
        ),
    },
    {
        "section": "Motion",
        "key": "smoothing",
        "label": "Color smoothing (0–1)",
        "type": "float",
        "default": OrderedTrackerConfig().smoothing,
        "description": "EMA factor for the running color estimate. Higher reacts faster; lower is steadier.",
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
    TrackerType.ORDERED.value: TrackerSpec(
        type=TrackerType.ORDERED.value,
        label="Ordered + Color (channel)",
        description=(
            "Strongest tracker for this machine. On a rigid one-way platter pieces "
            "never pass each other, so it aligns each frame's travel-ordered "
            "detections to the live tracks, requiring only that order is preserved "
            "and pieces move forward. Robust to the platter's large between-frame "
            "jumps with no motion model and no motor-timing dependence; color/size "
            "only break ties. Best for 0–4 pieces."
        ),
        config_cls=OrderedTrackerConfig,
        field_meta=ORDERED_FIELD_META,
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
