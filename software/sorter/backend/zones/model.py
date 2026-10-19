"""A channel's zones: the ring its pieces ride on and the arcs along it.

Pieces travel the ring forward, which is increasing image angle (clockwise on
screen, y pointing down). A ``Span`` is an arc in that order: a piece meets its
``start`` first. Angles are image angles in degrees around the ring's center.

Every channel has the same three zones:

- ``drop``: where pieces from the channel before land.
- ``exit``: where they leave, through the opening in the wall. Past
  ``exit_radius`` the camera sees the next channel, so the exit, and the
  channel itself, end there over the exit's angles.
- ``precise``: a sliver just before the exit, ``precise_width`` degrees wide,
  where pieces are metered out one at a time.

The channel is the ring from the drop's start forward to the exit's end; the
stretch from the exit's end back round to the drop's start is where nothing
rides (the guide that turns pieces out of the exit).
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field, replace
from typing import Any, Iterable, Mapping

CHANNELS: tuple[int, ...] = (2, 3, 4)
ZONE_NAMES: tuple[str, ...] = ("drop", "precise", "exit")
PARTS: tuple[str, ...] = ("ring", "drop", "precise", "exit")
SOURCES: tuple[str, ...] = ("default", "drawn", "found", "learned")

CAMERA_ROLE: dict[int, str] = {2: "c_channel_2", 3: "c_channel_3", 4: "carousel"}

MIN_SPAN_DEG = 1.0
MIN_RING_PX = 4.0


def normalizeAngle(angle: float) -> float:
    return float(angle) % 360.0


def forwardDeg(from_angle: float, to_angle: float) -> float:
    return (float(to_angle) - float(from_angle)) % 360.0


@dataclass(frozen=True)
class Span:
    start: float
    end: float

    def __post_init__(self) -> None:
        object.__setattr__(self, "start", normalizeAngle(self.start))
        object.__setattr__(self, "end", normalizeAngle(self.end))

    @property
    def width(self) -> float:
        width = forwardDeg(self.start, self.end)
        return width if width > 0 else 360.0

    @property
    def middle(self) -> float:
        return normalizeAngle(self.start + self.width / 2.0)

    def contains(self, angle: float) -> bool:
        return forwardDeg(self.start, angle) < self.width

    def moved(self, deg: float) -> "Span":
        return Span(self.start + deg, self.end + deg)

    def widened(self, deg: float) -> "Span":
        width = max(MIN_SPAN_DEG, self.width + deg)
        return Span(self.middle - width / 2.0, self.middle + width / 2.0)


# The inner circle's center stays within this share of its radius of the ring's
# center, so every ray from the ring's center leaves the inner circle once.
MAX_INNER_OFFSET = 0.9


@dataclass(frozen=True)
class Ring:
    """The rotor's edge (``exit_radius`` around ``center``, which angles are
    measured around), the area watched out to ``outer_radius`` around the same
    center, and an inner circle the area starts at. The inner circle has a
    center of its own, ``inner_center``: the hub stands above the rotor, so
    from the camera it looks shifted against the rotor's edge. None: the
    ring's center."""

    center: tuple[float, float]
    inner_radius: float
    outer_radius: float
    exit_radius: float
    inner_center: tuple[float, float] | None = None

    def __post_init__(self) -> None:
        center = (float(self.center[0]), float(self.center[1]))
        inner = max(0.0, float(self.inner_radius))
        inner_center: tuple[float, float] | None = None
        if self.inner_center is not None and inner > 0:
            dx, dy = float(self.inner_center[0]) - center[0], float(self.inner_center[1]) - center[1]
            off = math.hypot(dx, dy)
            most = MAX_INNER_OFFSET * inner
            if off > most:
                dx, dy = dx * most / off, dy * most / off
            inner_center = (center[0] + dx, center[1] + dy)
        reach = inner + (math.dist(inner_center, center) if inner_center is not None else 0.0)
        outer = max(reach + MIN_RING_PX, float(self.outer_radius))
        exit_radius = min(outer, max(reach + MIN_RING_PX, float(self.exit_radius)))
        object.__setattr__(self, "center", center)
        object.__setattr__(self, "inner_radius", inner)
        object.__setattr__(self, "outer_radius", outer)
        object.__setattr__(self, "exit_radius", exit_radius)
        object.__setattr__(self, "inner_center", inner_center)

    def scaled(self, sx: float, sy: float) -> "Ring":
        s = (sx + sy) / 2.0
        hub = None if self.inner_center is None else (self.inner_center[0] * sx, self.inner_center[1] * sy)
        return Ring(
            center=(self.center[0] * sx, self.center[1] * sy),
            inner_radius=self.inner_radius * s,
            outer_radius=self.outer_radius * s,
            exit_radius=self.exit_radius * s,
            inner_center=hub,
        )

    def movedTo(self, center: tuple[float, float], scale: float = 1.0) -> "Ring":
        """This ring at another center and size, the inner circle moving with it."""
        hub = None
        if self.inner_center is not None:
            hub = (
                center[0] + (self.inner_center[0] - self.center[0]) * scale,
                center[1] + (self.inner_center[1] - self.center[1]) * scale,
            )
        return Ring(center, self.inner_radius * scale, self.outer_radius * scale, self.exit_radius * scale, hub)


@dataclass(frozen=True)
class ChannelZones:
    channel: int
    frame: tuple[int, int]
    ring: Ring
    drop: Span
    exit: Span
    precise_width: float = 0.0
    reference_angle: float = 0.0
    locked: frozenset[str] = frozenset()
    source: Mapping[str, str] = field(default_factory=dict)
    updated_at: float | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "frame", (int(self.frame[0]), int(self.frame[1])))
        object.__setattr__(self, "precise_width", max(0.0, min(float(self.precise_width), 120.0)))
        object.__setattr__(self, "reference_angle", normalizeAngle(self.reference_angle))
        object.__setattr__(self, "locked", frozenset(p for p in self.locked if p in PARTS))
        object.__setattr__(
            self,
            "source",
            {p: str(s) for p, s in dict(self.source).items() if p in PARTS and s in SOURCES},
        )

    @property
    def precise(self) -> Span | None:
        if self.precise_width <= 0:
            return None
        return Span(self.exit.start - self.precise_width, self.exit.start)

    @property
    def travel(self) -> Span:
        """The arc pieces ride: from the drop's start to the exit's end."""
        return Span(self.drop.start, self.exit.end)

    def zone(self, name: str) -> Span | None:
        return {"drop": self.drop, "exit": self.exit, "precise": self.precise}[name]

    def scaledTo(self, frame: tuple[int, int]) -> "ChannelZones":
        w, h = int(frame[0]), int(frame[1])
        if (w, h) == self.frame or self.frame[0] <= 0 or self.frame[1] <= 0:
            return self
        return replace(
            self,
            frame=(w, h),
            ring=self.ring.scaled(w / self.frame[0], h / self.frame[1]),
        )

    def withRing(self, ring: Ring, source: str) -> "ChannelZones":
        """These zones on another ring, each zone kept where it was on the band
        pieces ride: its edges are measured again from the new center."""
        return replace(
            self,
            ring=ring,
            drop=_reanchored(self.drop, self.ring, ring),
            exit=_reanchored(self.exit, self.ring, ring),
            source={**dict(self.source), "ring": source},
        )

    def withParts(self, other: "ChannelZones", parts: Iterable[str], source: str) -> "ChannelZones":
        """These zones with ``parts`` taken from ``other`` (rescaled to this frame),
        except the locked ones."""
        other = other.scaledTo(self.frame)
        take = [p for p in parts if p in PARTS and p not in self.locked]
        if not take:
            return self
        values: dict[str, Any] = {}
        if "ring" in take:
            values["ring"] = other.ring
        if "drop" in take:
            values["drop"] = other.drop
        if "exit" in take:
            values["exit"] = other.exit
        if "precise" in take:
            values["precise_width"] = other.precise_width
        sources = dict(self.source)
        for part in take:
            sources[part] = source
        return replace(self, source=sources, **values)


def _reanchored(span: Span, old: Ring, new: Ring) -> Span:
    """The same stretch of the band, measured around the new center: each edge's
    ray from the old center, met at the new ring's exit radius."""
    radius = new.exit_radius

    def moved(angle: float) -> float:
        ox, oy = old.center
        dx, dy = math.cos(math.radians(angle)), math.sin(math.radians(angle))
        fx, fy = ox - new.center[0], oy - new.center[1]
        b = fx * dx + fy * dy
        c = fx * fx + fy * fy - radius * radius
        disc = b * b - c
        if disc < 0:
            return angle
        t = -b + math.sqrt(disc)
        px, py = ox + t * dx, oy + t * dy
        return normalizeAngle(math.degrees(math.atan2(py - new.center[1], px - new.center[0])))

    return Span(moved(span.start), moved(span.end))


# ---------------------------------------------------------------------------
# Geometry
# ---------------------------------------------------------------------------


def polarPoint(center: tuple[float, float], radius: float, angle: float) -> tuple[float, float]:
    rad = math.radians(angle)
    return center[0] + radius * math.cos(rad), center[1] + radius * math.sin(rad)


def innerPoint(ring: Ring, angle: float) -> tuple[float, float]:
    """Where the ray from the ring's center at ``angle`` leaves the inner circle."""
    if ring.inner_center is None:
        return polarPoint(ring.center, ring.inner_radius, angle)
    dx, dy = math.cos(math.radians(angle)), math.sin(math.radians(angle))
    fx, fy = ring.center[0] - ring.inner_center[0], ring.center[1] - ring.inner_center[1]
    b = fx * dx + fy * dy
    t = -b + math.sqrt(max(0.0, b * b - (fx * fx + fy * fy - ring.inner_radius**2)))
    return ring.center[0] + t * dx, ring.center[1] + t * dy


def _arcAngles(span: Span, step_deg: float) -> list[float]:
    steps = max(2, int(math.ceil(span.width / step_deg)))
    return [span.start + span.width * i / steps for i in range(steps + 1)]


def channelPolygon(zones: ChannelZones, step_deg: float = 3.0) -> list[tuple[float, float]]:
    """The channel's area: the ring over the travel arc, its outer edge drawn
    in to ``exit_radius`` across the exit (which runs to the travel's end)."""
    ring = zones.ring
    travel = zones.travel
    cut = ring.exit_radius < ring.outer_radius - 1e-6
    exit_from = forwardDeg(travel.start, zones.exit.start)
    if exit_from > travel.width:
        exit_from = 0.0
    steps = max(2, int(math.ceil(travel.width / step_deg)))
    rels = sorted({travel.width * i / steps for i in range(steps + 1)} | ({exit_from} if cut else set()))
    outer: list[tuple[float, float]] = []
    for rel in rels:
        angle = travel.start + rel
        if cut and rel >= exit_from - 1e-6:
            if abs(rel - exit_from) < 1e-6:
                outer.append(polarPoint(ring.center, ring.outer_radius, angle))
            outer.append(polarPoint(ring.center, ring.exit_radius, angle))
        else:
            outer.append(polarPoint(ring.center, ring.outer_radius, angle))
    inner = [innerPoint(ring, a) for a in reversed(_arcAngles(travel, step_deg))]
    return outer + inner


def zonePolygon(zones: ChannelZones, name: str, step_deg: float = 3.0) -> list[tuple[float, float]] | None:
    span = zones.zone(name)
    if span is None:
        return None
    ring = zones.ring
    outer_radius = ring.exit_radius if name == "exit" else ring.outer_radius
    angles = _arcAngles(span, step_deg)
    return [polarPoint(ring.center, outer_radius, a) for a in angles] + [innerPoint(ring, a) for a in reversed(angles)]


def sectionsFor(span: Span | None, reference_angle: float) -> frozenset[int]:
    """The 1-degree sections, counted from ``reference_angle``, from the one
    the span starts in up to (not including) the one it ends in."""
    if span is None:
        return frozenset()
    start = forwardDeg(reference_angle, span.start)
    first = int(math.floor(start))
    stop = int(math.floor(start + span.width))
    return frozenset(s % 360 for s in range(first, stop))


# ---------------------------------------------------------------------------
# The saved document
# ---------------------------------------------------------------------------


def _num(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    value = float(value)
    return value if math.isfinite(value) else None


def _pair(value: Any) -> tuple[float, float] | None:
    if not isinstance(value, (list, tuple)) or len(value) < 2:
        return None
    a, b = _num(value[0]), _num(value[1])
    return (a, b) if a is not None and b is not None else None


def toDict(zones: ChannelZones) -> dict[str, Any]:
    out: dict[str, Any] = {
        "channel": zones.channel,
        "frame": list(zones.frame),
        "center": [round(zones.ring.center[0], 2), round(zones.ring.center[1], 2)],
        "inner_radius": round(zones.ring.inner_radius, 2),
        "outer_radius": round(zones.ring.outer_radius, 2),
        "exit_radius": round(zones.ring.exit_radius, 2),
        "inner_center": (
            None
            if zones.ring.inner_center is None
            else [round(zones.ring.inner_center[0], 2), round(zones.ring.inner_center[1], 2)]
        ),
        "drop": {"start": round(zones.drop.start, 3), "end": round(zones.drop.end, 3)},
        "exit": {"start": round(zones.exit.start, 3), "end": round(zones.exit.end, 3)},
        "precise_width": round(zones.precise_width, 3),
        "reference_angle": round(zones.reference_angle, 3),
        "locked": sorted(zones.locked),
        "source": dict(zones.source),
    }
    if zones.updated_at is not None:
        out["updated_at"] = zones.updated_at
    return out


def fromDict(raw: Mapping[str, Any], channel: int | None = None) -> ChannelZones | None:
    if not isinstance(raw, Mapping):
        return None
    channel_id = channel if channel is not None else raw.get("channel")
    if not isinstance(channel_id, int) or channel_id not in CHANNELS:
        return None
    frame = _pair(raw.get("frame"))
    center = _pair(raw.get("center"))
    inner = _num(raw.get("inner_radius"))
    outer = _num(raw.get("outer_radius"))
    if frame is None or center is None or inner is None or outer is None:
        return None
    spans: dict[str, Span] = {}
    for name in ("drop", "exit"):
        span = raw.get(name)
        if not isinstance(span, Mapping):
            return None
        start, end = _num(span.get("start")), _num(span.get("end"))
        if start is None or end is None:
            return None
        spans[name] = Span(start, end)
    exit_radius = _num(raw.get("exit_radius"))
    updated_at = _num(raw.get("updated_at"))
    return ChannelZones(
        channel=int(channel_id),
        frame=(int(frame[0]), int(frame[1])),
        ring=Ring(center, inner, outer, exit_radius if exit_radius is not None else outer, _pair(raw.get("inner_center"))),
        drop=spans["drop"],
        exit=spans["exit"],
        precise_width=_num(raw.get("precise_width")) or 0.0,
        reference_angle=_num(raw.get("reference_angle")) or 0.0,
        locked=frozenset(str(p) for p in (raw.get("locked") or ()) if isinstance(p, str)),
        source={str(k): str(v) for k, v in dict(raw.get("source") or {}).items()},
        updated_at=updated_at,
    )


# ---------------------------------------------------------------------------
# The blob versions before this module wrote (the editor's ``arc_params``)
# ---------------------------------------------------------------------------

LEGACY_ARC_KEY: dict[int, str] = {2: "second", 3: "third", 4: "classification_channel"}
LEGACY_POLYGON_KEY: dict[int, str] = {2: "second_channel", 3: "third_channel", 4: "classification_channel"}


def _legacyEdges(raw: Any) -> tuple[float, float] | None:
    if not isinstance(raw, Mapping):
        return None
    start = _num(raw.get("start_outer_angle", raw.get("start_angle")))
    end = _num(raw.get("end_outer_angle", raw.get("end_angle")))
    if start is None or end is None:
        return None
    return start, end


def fromLegacyBlob(blob: Mapping[str, Any] | None) -> dict[int, ChannelZones]:
    """Zones from the blob the old editor saved: per channel an ``arc_params``
    entry (center, radii, outer/inner angles of each zone, the editor's
    resolution) and the section-zero angle in ``channel_angles``. Inner angles
    (slanted zone edges) are dropped: zones are arcs with radial edges."""
    out: dict[int, ChannelZones] = {}
    if not isinstance(blob, Mapping):
        return out
    arc_params = blob.get("arc_params") or {}
    channel_angles = blob.get("channel_angles") or {}
    for channel in CHANNELS:
        raw = arc_params.get(LEGACY_ARC_KEY[channel]) or arc_params.get(LEGACY_POLYGON_KEY[channel])
        if not isinstance(raw, Mapping):
            continue
        center = _pair(raw.get("center"))
        inner = _num(raw.get("inner_radius"))
        outer = _num(raw.get("outer_radius"))
        frame = _pair(raw.get("resolution")) or _pair(blob.get("resolution"))
        drop = _legacyEdges(raw.get("drop_zone"))
        exit_edges = _legacyEdges(raw.get("exit_zone"))
        if center is None or inner is None or outer is None or frame is None or drop is None or exit_edges is None:
            continue
        exit_radius = _num(raw.get("exit_outer_radius"))
        if exit_radius is None and isinstance(raw.get("exit_zone"), Mapping):
            exit_radius = _num(raw["exit_zone"].get("outer_radius"))
        precise_width = 0.0
        precise = _legacyEdges(raw.get("precise_zone"))
        if precise is not None:
            precise_width = forwardDeg(precise[0], precise[1])
        out[channel] = ChannelZones(
            channel=channel,
            frame=(int(frame[0]), int(frame[1])),
            ring=Ring(center, inner, outer, exit_radius if exit_radius is not None else outer),
            drop=Span(*drop),
            exit=Span(*exit_edges),
            precise_width=precise_width,
            reference_angle=_num(channel_angles.get(LEGACY_ARC_KEY[channel])) or 0.0,
            source={part: "drawn" for part in PARTS},
        )
    return out


def _legacyZone(span: Span, outer_radius: float | None = None) -> dict[str, Any]:
    zone: dict[str, Any] = {
        "start_angle": round(span.start, 3),
        "end_angle": round(span.end, 3),
        "start_outer_angle": round(span.start, 3),
        "end_outer_angle": round(span.end, 3),
        "start_inner_angle": round(span.start, 3),
        "end_inner_angle": round(span.end, 3),
    }
    if outer_radius is not None:
        zone["outer_radius"] = round(outer_radius, 2)
    return zone


def toLegacyBlob(zones_by_channel: Mapping[int, ChannelZones]) -> dict[str, Any]:
    """The same zones in the old blob's shape, so a machine switched back to an
    older version keeps its zones."""
    polygons: dict[str, Any] = {}
    arc_params: dict[str, Any] = {}
    channel_angles: dict[str, float] = {}
    resolution: list[int] | None = None
    for channel, zones in sorted(zones_by_channel.items()):
        ring = zones.ring
        entry: dict[str, Any] = {
            "center": [round(ring.center[0], 2), round(ring.center[1], 2)],
            "inner_radius": round(ring.inner_radius, 2),
            "outer_radius": round(ring.outer_radius, 2),
            "exit_outer_radius": round(ring.exit_radius, 2),
            "resolution": list(zones.frame),
            "drop_zone": _legacyZone(zones.drop),
            "exit_zone": _legacyZone(zones.exit, ring.exit_radius),
        }
        precise = zones.precise
        entry["precise_zone"] = _legacyZone(precise if precise is not None else Span(zones.exit.start, zones.exit.start))
        arc_params[LEGACY_ARC_KEY[channel]] = entry
        polygons[LEGACY_POLYGON_KEY[channel]] = [
            [int(round(x)), int(round(y))] for x, y in channelPolygon(zones)
        ]
        channel_angles[LEGACY_ARC_KEY[channel]] = round(zones.reference_angle, 3)
        resolution = resolution or list(zones.frame)
    return {
        "polygons": polygons,
        "arc_params": arc_params,
        "channel_angles": channel_angles,
        "resolution": resolution or [1280, 720],
    }
