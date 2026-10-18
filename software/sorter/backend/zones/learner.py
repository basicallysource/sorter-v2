"""Zones that follow the machine, learned from its pieces while it runs.

A piece seen last on one channel and, moments later, first on the next has
just gone through the first one's exit and landed in the next one's drop zone.
Those hand-offs say where each exit and drop zone really are on this machine,
and how long a piece takes to land; nothing else can tell them as well, since
every machine is built and filmed a little differently.

The learner keeps the last of them per channel and, once there are enough,
moves an unlocked exit or drop zone a few degrees at a time toward what they
show. Where pieces ride says where the ring is: the circle through them, which
the ring follows in small steps too. It also keeps a picture of each channel
every so often while the machine runs, for the zone finder.
"""

from __future__ import annotations

import math
import threading
import time
from collections import deque
from dataclasses import dataclass, replace
from typing import Any, Deque

import cv2
import numpy as np

from .finder import ringAround
from .model import ChannelZones, Span, forwardDeg, normalizeAngle
from .store import loadZones, updateChannel

POLL_S = 0.1
# A track not seen for this long has ended.
TRACK_GONE_S = 0.8
# A piece lands on the next channel within this long of leaving one.
HANDOFF_WINDOW_S = 4.0
HANDOFFS_KEPT = 120
# Zones move once this many hand-offs agree, at most this far at a time.
MIN_HANDOFFS = 25
MAX_STEP_DEG = 4.0
MIN_CHANGE_DEG = 1.5
ADJUST_EVERY_S = 60.0
# Spans keep a margin around what the pieces showed, of the pieces' own angular
# size, and never fall below these widths.
MIN_EXIT_DEG = 20.0
MIN_DROP_DEG = 25.0

# The ring follows the circle pieces ride once this many sightings agree, by at
# most these shares of its radius at a time, and only when it is this far off.
MIN_SIGHTINGS = 400
SIGHTINGS_KEPT = 3000
MAX_RING_STEP = 0.02
MIN_RING_CHANGE = 0.02

FRAME_EVERY_S = 20.0
FRAMES_KEPT = 24
FRAME_WIDTH = 640

_NEXT = {2: 3, 3: 4}


@dataclass(frozen=True)
class Sighting:
    """Where a piece was seen, as shares of the picture's width and height (so
    it holds at any picture size), and its box's longer side as a share of the
    width."""

    ts: float
    u: float
    v: float
    size: float

    def at(self, frame: tuple[int, int]) -> tuple[float, float]:
        return self.u * frame[0], self.v * frame[1]


@dataclass
class _Track:
    first: Sighting
    last: Sighting


@dataclass(frozen=True)
class Handoff:
    from_channel: int
    left: Sighting
    landed: Sighting
    delay_s: float


class ZoneLearner:
    def __init__(self, perception_service: Any, logger: Any = None, apply_changes: bool = True) -> None:
        self._perception = perception_service
        self._logger = logger
        self.apply_changes = apply_changes
        self._tracks: dict[int, dict[int, _Track]] = {2: {}, 3: {}, 4: {}}
        self._ended: dict[int, Deque[_Track]] = {2: deque(maxlen=50), 3: deque(maxlen=50)}
        self._started: dict[int, Deque[tuple[int, _Track]]] = {3: deque(maxlen=50), 4: deque(maxlen=50)}
        self._handoffs: dict[int, Deque[Handoff]] = {2: deque(maxlen=HANDOFFS_KEPT), 3: deque(maxlen=HANDOFFS_KEPT)}
        self._sightings: dict[int, Deque[Sighting]] = {ch: deque(maxlen=SIGHTINGS_KEPT) for ch in (2, 3, 4)}
        self._frames: dict[int, Deque[np.ndarray]] = {ch: deque(maxlen=FRAMES_KEPT) for ch in (2, 3, 4)}
        self._frame_at: dict[int, float] = {}
        self._last_frame_ts: dict[int, float] = {}
        self._adjusted_at = time.monotonic()
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._loop, daemon=True, name="zone-learner")

    def start(self) -> None:
        self._thread.start()

    def stop(self, timeout: float = 2.0) -> None:
        self._stop.set()
        self._thread.join(timeout=timeout)

    # --- what it knows -----------------------------------------------------

    def frames(self, channel: int) -> list[np.ndarray]:
        with self._lock:
            return list(self._frames.get(channel, ()))

    def handoffs(self, from_channel: int) -> list[Handoff]:
        with self._lock:
            return list(self._handoffs.get(from_channel, ()))

    def sightings(self, channel: int) -> list[Sighting]:
        with self._lock:
            return list(self._sightings.get(channel, ()))

    def report(self) -> dict[str, Any]:
        zones = loadZones()
        out: dict[str, Any] = {"apply_changes": self.apply_changes, "channels": {}}
        for channel, nxt in _NEXT.items():
            hand = self.handoffs(channel)
            entry: dict[str, Any] = {"handoffs": len(hand), "frames": len(self.frames(channel))}
            if hand:
                delays = sorted(h.delay_s for h in hand)
                entry["landing_delay_s"] = {
                    "p50": round(delays[len(delays) // 2], 3),
                    "p90": round(delays[min(len(delays) - 1, int(len(delays) * 0.9))], 3),
                }
            own, down = zones.get(channel), zones.get(nxt)
            if own is not None and len(hand) >= 5:
                exit_span = learnedExit(own, hand)
                if exit_span is not None:
                    entry["learned_exit"] = {"start": round(exit_span.start, 1), "end": round(exit_span.end, 1)}
            if down is not None and len(hand) >= 5:
                drop = learnedDrop(down, hand)
                if drop is not None:
                    entry[f"learned_drop_on_{nxt}"] = {"start": round(drop.start, 1), "end": round(drop.end, 1)}
            out["channels"][str(channel)] = entry
        out["channels"]["4"] = {"frames": len(self.frames(4))}
        return out

    # --- the loop ---------------------------------------------------------

    def _loop(self) -> None:
        while not self._stop.wait(POLL_S):
            try:
                self._tick(time.monotonic(), time.time())
            except Exception as exc:
                self._log("warning", f"[zones] learner tick failed: {exc}")

    def _tick(self, now_mono: float, now: float) -> None:
        for channel in (2, 3, 4):
            res = self._perception.read_pieces_and_frame(channel)
            if res is None:
                continue
            pieces, frame = res
            ts = float(getattr(frame, "timestamp", now))
            bgr = getattr(frame, "bgr", None)
            if self._last_frame_ts.get(channel) == ts or bgr is None:
                continue
            self._last_frame_ts[channel] = ts
            self._observe(channel, pieces, ts, (bgr.shape[1], bgr.shape[0]))
            self._keepFrame(channel, frame, now_mono)
        self._closeTracks(now)
        self._matchHandoffs()
        if self.apply_changes and now_mono - self._adjusted_at >= ADJUST_EVERY_S:
            self._adjusted_at = now_mono
            self._adjust()

    def _observe(self, channel: int, pieces: Any, ts: float, size: tuple[int, int]) -> None:
        tracks = self._tracks[channel]
        w, h = size
        for piece in pieces or ():
            track_id = getattr(piece, "sv_bt_track_id", None)
            bbox = getattr(piece, "bbox", None)
            if track_id is None or not bbox:
                continue
            x1, y1, x2, y2 = bbox
            seen = Sighting(ts, (x1 + x2) / 2.0 / w, (y1 + y2) / 2.0 / h, float(max(x2 - x1, y2 - y1)) / w)
            with self._lock:
                self._sightings[channel].append(seen)
            track = tracks.get(int(track_id))
            if track is None:
                track = _Track(first=seen, last=seen)
                tracks[int(track_id)] = track
                if channel in self._started:
                    self._started[channel].append((int(track_id), track))
            else:
                track.last = seen

    def _closeTracks(self, now: float) -> None:
        for channel, tracks in self._tracks.items():
            for track_id in [t for t, tr in tracks.items() if now - tr.last.ts > TRACK_GONE_S]:
                track = tracks.pop(track_id)
                if channel in self._ended and track.last.ts > track.first.ts:
                    self._ended[channel].append(track)

    def _matchHandoffs(self) -> None:
        """Pair each piece that appears on a channel with the piece seen leave
        the channel before it most recently before it landed: the one that fell,
        not one that went out of the camera's sight a moment earlier. A landing
        waits until any piece that left just before it is known to have gone."""
        now = time.time()
        for channel, nxt in _NEXT.items():
            ended = self._ended[channel]
            started = self._started[nxt]
            while started:
                track = started[0][1]
                landed_at = track.first.ts
                if now - landed_at < TRACK_GONE_S + 1.0:
                    break
                started.popleft()
                candidates = [t for t in ended if -0.3 <= landed_at - t.last.ts <= HANDOFF_WINDOW_S]
                if not candidates:
                    continue
                left = max(candidates, key=lambda t: t.last.ts)
                ended.remove(left)
                with self._lock:
                    self._handoffs[channel].append(
                        Handoff(
                            from_channel=channel,
                            left=left.last,
                            landed=track.first,
                            delay_s=landed_at - left.last.ts,
                        )
                    )
            while ended and now - ended[0].last.ts > HANDOFF_WINDOW_S + TRACK_GONE_S + 2.0:
                ended.popleft()

    def _keepFrame(self, channel: int, frame: Any, now_mono: float) -> None:
        if now_mono - self._frame_at.get(channel, -1e9) < FRAME_EVERY_S:
            return
        bgr = getattr(frame, "bgr", None)
        if bgr is None:
            return
        small = cv2.resize(
            bgr, (FRAME_WIDTH, int(round(bgr.shape[0] * FRAME_WIDTH / bgr.shape[1]))), interpolation=cv2.INTER_AREA
        )
        with self._lock:
            kept = self._frames[channel]
            # A paused machine shows the same picture: keep one of it.
            if kept and float(np.mean(cv2.absdiff(kept[-1], small))) < 1.5:
                return
            kept.append(small)
        self._frame_at[channel] = now_mono

    # --- moving zones ----------------------------------------------------

    def _adjust(self) -> None:
        for channel in (2, 3, 4):
            seen = self.sightings(channel)
            if len(seen) >= MIN_SIGHTINGS:
                updateChannel(channel, lambda z, s=seen: _ringStepped(z, s))
        for channel, nxt in _NEXT.items():
            hand = self.handoffs(channel)
            if len(hand) < MIN_HANDOFFS:
                continue
            updateChannel(channel, lambda z, h=hand: _stepped(z, "exit", learnedExit(z, h)))
            updateChannel(nxt, lambda z, h=hand: _stepped(z, "drop", learnedDrop(z, h)))

    def _log(self, level: str, message: str) -> None:
        if self._logger is None:
            return
        fn = getattr(self._logger, level, None)
        if fn is not None:
            fn(message)


# ---------------------------------------------------------------------------
# What the hand-offs show
# ---------------------------------------------------------------------------


def _angle(zones: ChannelZones, s: Sighting) -> float:
    cx, cy = zones.ring.center
    x, y = s.at(zones.frame)
    return normalizeAngle(math.degrees(math.atan2(y - cy, x - cx)))


def _sizeDeg(zones: ChannelZones, sightings: list[Sighting]) -> float:
    radius = max(zones.ring.exit_radius, 1.0)
    sizes = sorted(s.size * zones.frame[0] for s in sightings)
    return math.degrees(sizes[len(sizes) // 2] / radius)


def _spread(angles: list[float], around: float, share: float) -> tuple[float, float]:
    """The ``share`` and ``1 - share`` percentiles of ``angles``, as signed
    degrees from ``around``."""
    rel = sorted(((a - around + 180.0) % 360.0) - 180.0 for a in angles)
    return rel[int(len(rel) * share)], rel[min(len(rel) - 1, int(len(rel) * (1.0 - share)))]


def learnedExit(zones: ChannelZones, handoffs: list[Handoff]) -> Span | None:
    """Where pieces were last seen before they landed downstream, with half a
    piece of margin each side: the stretch pieces fall from."""
    if not handoffs:
        return None
    angles = [_angle(zones, h.left) for h in handoffs]
    low, high = _spread(angles, zones.exit.middle, 0.1)
    margin = _sizeDeg(zones, [h.left for h in handoffs]) / 2.0
    start = zones.exit.middle + low - margin
    width = max(MIN_EXIT_DEG, high - low + 2 * margin)
    return Span(start, start + width)


def learnedDrop(zones: ChannelZones, handoffs: list[Handoff]) -> Span | None:
    """Where pieces were first seen after leaving the channel before, with a
    piece of margin each side: nearly everywhere one lands, since a piece that
    lands outside the drop zone lets the channel before send the next."""
    if not handoffs:
        return None
    angles = [_angle(zones, h.landed) for h in handoffs]
    low, high = _spread(angles, zones.drop.middle, 0.03)
    margin = _sizeDeg(zones, [h.landed for h in handoffs])
    start = zones.drop.middle + low - margin
    width = max(MIN_DROP_DEG, high - low + 2 * margin)
    return Span(start, start + width)


def _stepped(zones: ChannelZones, name: str, target: Span | None) -> ChannelZones | None:
    """``zones`` with zone ``name`` moved toward ``target`` by at most
    ``MAX_STEP_DEG`` at each edge, unless it is locked or barely differs."""
    if target is None or name in zones.locked:
        return None
    current = zones.drop if name == "drop" else zones.exit

    def toward(a: float, b: float) -> float:
        delta = ((b - a + 180.0) % 360.0) - 180.0
        return a + max(-MAX_STEP_DEG, min(MAX_STEP_DEG, delta))

    def far(a: float, b: float) -> bool:
        return abs(((b - a + 180.0) % 360.0) - 180.0) >= MIN_CHANGE_DEG

    if not (far(current.start, target.start) or far(current.end, target.end)):
        return None
    moved = Span(toward(current.start, target.start), toward(current.end, target.end))
    if forwardDeg(moved.start, moved.end) <= 0:
        return None
    sources = {**dict(zones.source), name: "learned"}
    return replace(zones, source=sources, **{name: moved})


def ridingCircle(points: list[tuple[float, float]]) -> tuple[tuple[float, float], float] | None:
    """The circle pieces ride: a least-squares circle through where they were
    seen, refit without the farthest fifth (pieces falling off, odd boxes)."""
    if len(points) < 20:
        return None
    pts = np.asarray(points, dtype=np.float64)
    keep = np.ones(len(pts), bool)
    cx = cy = r = 0.0
    for _ in range(5):
        x, y = pts[keep, 0], pts[keep, 1]
        a = np.column_stack([2 * x, 2 * y, np.ones(len(x))])
        sol, *_ = np.linalg.lstsq(a, x * x + y * y, rcond=None)
        cx, cy = float(sol[0]), float(sol[1])
        r = math.sqrt(max(float(sol[2]) + cx * cx + cy * cy, 1.0))
        off = np.abs(np.hypot(pts[:, 0] - cx, pts[:, 1] - cy) - r)
        keep = off <= max(float(np.percentile(off, 80)), 1.0)
    return (cx, cy), r


def _ringStepped(zones: ChannelZones, seen: list[Sighting]) -> ChannelZones | None:
    """``zones`` with the ring moved toward the circle pieces ride, a small step
    at a time, unless it is locked or already close."""
    if "ring" in zones.locked:
        return None
    circle = ridingCircle([s.at(zones.frame) for s in seen])
    if circle is None:
        return None
    (cx, cy), r = circle
    ring = zones.ring
    rim = ring.exit_radius
    off_center = math.dist((cx, cy), ring.center) / rim
    off_radius = (r - rim) / rim
    if off_center < MIN_RING_CHANGE and abs(off_radius) < MIN_RING_CHANGE:
        return None
    step = min(1.0, MAX_RING_STEP / max(off_center, 1e-9))
    center = (ring.center[0] + (cx - ring.center[0]) * step, ring.center[1] + (cy - ring.center[1]) * step)
    new_rim = rim * (1.0 + max(-MAX_RING_STEP, min(MAX_RING_STEP, off_radius)))
    return zones.withRing(ringAround(center, new_rim), "learned")


_learner: ZoneLearner | None = None


def start(perception_service: Any, logger: Any = None) -> ZoneLearner:
    global _learner
    _learner = ZoneLearner(perception_service, logger)
    _learner.start()
    return _learner


def current() -> ZoneLearner | None:
    return _learner


def recentFrames(channel: int) -> list[np.ndarray]:
    return _learner.frames(channel) if _learner is not None else []
