"""Finding a channel's ring in its camera's pictures.

Every channel is a turning disc with fixed walls around it, seen from above:
its hub, its rim and the walls are circles about one center, and its pieces
ride a narrow band at the rim. So:

- The center is where the most edges point, counted only when they point there
  from many directions (pieces and other clutter point from one side).
- The rim is the first strong circular edge outward from the hub, and, given
  pictures over time, the circle where the change from one picture to the next
  stops: inside it the disc turns and pieces come and go, outside it the walls
  stand still.
- The channel watches everything a piece can be on: from well inside the rim
  out past the wall's outer edge, cut back to the rim at the exit, where the
  opening shows the next channel.

The zones' angles stay where they were on that band (re-anchored to the new
center); with nothing saved, they come from ``defaultZones``.
"""

from __future__ import annotations

import math
import warnings
from dataclasses import dataclass, field, replace
from typing import Sequence

import cv2
import numpy as np

from .model import ChannelZones, Ring, Span

WORK_W = 640
_SECTORS = 8
_ANGLES = 720

# The area a channel watches, as shares of the rim's radius: inward to where no
# piece rests, outward to the wall's outer edge (a little past it), and at
# least this far when the picture shows no such edge.
RING_INNER = 0.4
WALL_MARGIN = 1.05
RING_OUTER_MIN = 1.35
# On C2 and C3 the area starts just outside the hub, the raised cap in the
# middle, fitted as a circle of its own: from the camera it looks shifted
# against the rotor's edge. Looked for between these shares of the rim.
HUB_RANGE = (0.1, 0.45)
HUB_MARGIN = 1.04
# Fitted circles count when at least FIT_POINTS edge points, this share of the
# directions that stay in the picture, lie on them, missing by at most this
# many working pixels.
FIT_POINTS = 30
FIT_SHARE = 0.5
FIT_MISS = 1.5
# The exit is the opening in the wall. Where the wall stands, the rotor's edge
# is a dark line with light on both sides (the disc, and the wall's top);
# where the wall is open the outside is open too, and the line is no valley.
# The opening is a run of the rim this wide where the valley is under this
# share of the wall's, between stretches of wall. Pieces seen to fall pick the
# run (the one they fell in, within FALL_NEAR_DEG); without them, the run
# nearest the old exit's middle (within PRIOR_NEAR_DEG) is taken.
OPENING_VALLEY = 0.4
OPENING_DEG = (15, 100)
WALL_VALLEY_MIN = 8.0
FALL_NEAR_DEG = 20.0
PRIOR_NEAR_DEG = 45.0
# Each end of the opening is the wall's end face: a sharp straight line from
# the rim outward. Found at the rim, an end can be far off: the valley is read
# in whole degrees; where the camera sees an end face at an angle, the face is
# dark where the rim's line would be and reads as opening; and the opening
# runs on to where the rim leaves the picture. A line is where the picture
# changes most across the angle, summed from just past the rim out to the
# area's outer edge over the radii the picture shows (at least EDGE_RADII),
# and sharp where that stands EDGE_SHARPNESS times above its median and
# EDGE_PROMINENCE times above its median on each side within EDGE_LOCAL_DEG
# (a face's shading changes as much over degrees, and is no line). Through
# the opening the next channel shows, with sharp lines of its own (its parts
# stand still while the machine is paused); the end faces bound them. So each
# end is the sharp line furthest from the opening's middle on its side, out
# to EDGE_PAST_DEG past the valley's end (the valley stops a degree or so
# short of a face; further out, a guide bar's far side or the wall's own
# texture can make sharp lines); an end the picture does not show stays
# where it was. On the classification channel, whose exit no valley finds,
# the drawn exit's ends move the same way.
EDGE_PAST_DEG = 2.5
EDGE_STEP_DEG = 0.05
EDGE_SHARPNESS = 6.0
EDGE_RADII = 5
# A line is the sharpest change within EDGE_PEAK_DEG of itself.
EDGE_PEAK_DEG = 0.5
EDGE_PROMINENCE = 3.0
EDGE_LOCAL_DEG = 2.0


@dataclass(frozen=True)
class Found:
    zones: ChannelZones
    center_score: float
    rim_score: float
    frames: int
    notes: list[str] = field(default_factory=list)

    def report(self) -> dict:
        return {
            "center_score": round(self.center_score, 3),
            "rim_score": round(self.rim_score, 3),
            "frames": self.frames,
            "notes": list(self.notes),
        }


def defaultZones(channel: int, frame: tuple[int, int]) -> ChannelZones:
    """A start for a channel with nothing saved: a ring in the middle of the
    picture with zones where a typical build has them, for the person to turn
    into place."""
    w, h = frame
    rim = 0.45 * min(w, h)
    if channel == 4:
        drop, exit_span, precise = Span(282.0, 119.0), Span(233.0, 274.0), 85.0
    else:
        drop, exit_span, precise = Span(288.0, 9.0), Span(169.0, 201.0), 6.0
    return ChannelZones(
        channel=channel,
        frame=(w, h),
        ring=Ring((w / 2.0, h / 2.0), RING_INNER * rim, RING_OUTER_MIN * rim, rim),
        drop=drop,
        exit=exit_span,
        precise_width=precise,
        source={part: "default" for part in ("ring", "drop", "exit", "precise")},
    )


def findZones(
    channel: int,
    frames: Sequence[np.ndarray],
    current: ChannelZones | None = None,
    frame_size: tuple[int, int] | None = None,
    falls: Sequence[tuple[float, float]] = (),
) -> Found:
    """Find the ring in ``frames`` (BGR pictures of the channel as perception
    sees them, at any size of the camera's shape) and fit ``current`` (or the
    defaults) to it, in ``frame_size`` (width, height) pixels, by default the
    first picture's, and on C2 and C3 the exit at the wall's opening.
    ``falls`` are where pieces were last seen before the feeder saw them fall
    off this channel (frame pixels). Locked parts of ``current`` are kept."""
    if not frames:
        raise ValueError("no pictures to find zones in")
    w, h = frame_size if frame_size is not None else (frames[0].shape[1], frames[0].shape[0])
    scale = WORK_W / float(w)
    work_h = int(round(h * scale))
    small = [
        f if f.shape[:2] == (work_h, WORK_W) else cv2.resize(f, (WORK_W, work_h), interpolation=cv2.INTER_AREA)
        for f in frames
        if abs(f.shape[0] / f.shape[1] - h / w) < 0.01
    ]
    if not small:
        raise ValueError("no pictures of the camera's shape to find zones in")
    median = np.median(np.stack(small), axis=0).astype(np.uint8) if len(small) > 1 else small[0]
    notes: list[str] = []

    (cx, cy), center_score = _findCenter(median)
    rim, rim_score, rim_note = _findRim(median, small, cx, cy)
    if rim_note:
        notes.append(rim_note)
    # The rotor's edge, fitted point by point: the zones' rim and the center
    # angles are measured around.
    edge = _fitCircle(median, cx, cy, 0.92 * rim, 1.08 * rim)
    if edge is not None and math.dist(edge[0], (cx, cy)) < 0.1 * rim and abs(edge[1] - rim) < 0.08 * rim:
        (cx, cy), rim = edge
    else:
        notes.append("the rotor's edge was not clear all round, so the rim is the ring's best circle")
    wall = _findWall(median, cx, cy, rim)
    center = (cx / scale, cy / scale)
    rim_px = rim / scale
    outer_px = max(RING_OUTER_MIN * rim, WALL_MARGIN * wall if wall else 0.0) / scale
    inner_px, hub_px = RING_INNER * rim_px, None
    if channel != 4:
        hub = _fitCircle(median, cx, cy, HUB_RANGE[0] * rim, HUB_RANGE[1] * rim)
        if hub is not None and math.dist(hub[0], (cx, cy)) < 0.9 * hub[1]:
            hub_px = (hub[0][0] / scale, hub[0][1] / scale)
            inner_px = HUB_MARGIN * hub[1] / scale
        else:
            notes.append("no hub was found, so the area starts at 0.4 of the rim")

    base = current.scaledTo((w, h)) if current is not None else defaultZones(channel, (w, h))
    if "ring" in base.locked:
        # A locked ring is kept as it is, and an exit that is not locked is
        # still found on it.
        notes.append("the ring is locked, so it was kept")
        zones = base
    else:
        # The zones stay where they were on the band pieces ride, locked or
        # not: only their angles are measured from the new center.
        zones = base.withRing(Ring(center, inner_px, outer_px, rim_px, hub_px), "found")
    ring = zones.ring
    if "exit" not in zones.locked:
        # The wall's edge and the guide are a pixel or two wide: look for the
        # opening at the camera's own size.
        full = _fullMedian(frames, (w, h))
        if channel != 4:
            fell = [_angleAround(ring.center, (x, y)) for x, y in falls]
            opening, note = _findOpening(full, ring.center[0], ring.center[1], ring.exit_radius, fell, zones.exit.middle)
            if opening is not None:
                zones = replace(zones, exit=opening, source={**dict(zones.source), "exit": "found"})
            notes.append(note)
        edged, note = _onTheEdges(full, ring.center[0], ring.center[1], ring.exit_radius, ring.outer_radius, zones.exit)
        if edged is not None:
            zones = replace(zones, exit=edged, source={**dict(zones.source), "exit": "found"})
        notes.append(note)
    return Found(zones=zones, center_score=center_score, rim_score=rim_score, frames=len(small), notes=notes)


# ---------------------------------------------------------------------------
# The center
# ---------------------------------------------------------------------------


def _edgeField(img: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Per pixel, the gradient of whichever Lab channel changes most there, so
    a coloured rim on a coloured wall counts as much as grey on white."""
    lab = cv2.cvtColor(img, cv2.COLOR_BGR2LAB).astype(np.float32)
    gx = np.zeros(img.shape[:2], np.float32)
    gy = np.zeros(img.shape[:2], np.float32)
    best = np.zeros(img.shape[:2], np.float32)
    for c in range(3):
        channel = cv2.GaussianBlur(lab[:, :, c], (0, 0), 1.5)
        dx = cv2.Sobel(channel, cv2.CV_32F, 1, 0, ksize=3)
        dy = cv2.Sobel(channel, cv2.CV_32F, 0, 1, ksize=3)
        mag = dx * dx + dy * dy
        take = mag > best
        best = np.where(take, mag, best)
        gx = np.where(take, dx, gx)
        gy = np.where(take, dy, gy)
    return gx, gy, np.sqrt(best)


def _findCenter(img: np.ndarray) -> tuple[tuple[float, float], float]:
    h, w = img.shape[:2]
    gx, gy, mag = _edgeField(img)
    threshold = float(np.percentile(mag, 88))
    ys, xs = np.nonzero(mag > threshold)
    if len(xs) > 50000:
        pick = np.random.default_rng(0).choice(len(xs), 50000, replace=False)
        ys, xs = ys[pick], xs[pick]
    ux = gx[ys, xs] / (mag[ys, xs] + 1e-6)
    uy = gy[ys, xs] / (mag[ys, xs] + 1e-6)
    weight = np.minimum(mag[ys, xs] / max(threshold, 1e-6), 3.0)
    # Short votes come from the small circles of studs and pieces.
    dists = np.arange(0.08 * w, math.hypot(w, h) * 0.8, 2, dtype=np.float32)
    acc = np.zeros((_SECTORS, h, w), np.float32)
    for sign in (1.0, -1.0):
        dx, dy = sign * ux, sign * uy
        sector = ((np.arctan2(dy, dx) + math.pi) / (2 * math.pi) * _SECTORS).astype(np.int32) % _SECTORS
        px = xs[:, None] + dx[:, None] * dists[None, :]
        py = ys[:, None] + dy[:, None] * dists[None, :]
        ok = (px >= 0) & (px < w) & (py >= 0) & (py < h)
        np.add.at(
            acc,
            (np.broadcast_to(sector[:, None], px.shape)[ok], py[ok].astype(np.int32), px[ok].astype(np.int32)),
            np.broadcast_to(weight[:, None], px.shape)[ok],
        )
    for s in range(_SECTORS):
        acc[s] = cv2.GaussianBlur(acc[s], (0, 0), 4)
        top = float(acc[s].max())
        if top > 0:
            acc[s] /= top
    # A center is seen from many directions: score it by its better half of
    # the directions, so clutter on one side cannot win.
    score = np.sort(acc, axis=0)[_SECTORS // 2 :].mean(axis=0)
    y, x = np.unravel_index(int(np.argmax(score)), score.shape)
    return (float(x), float(y)), float(score[y, x])


# ---------------------------------------------------------------------------
# The rim
# ---------------------------------------------------------------------------


def _polar(img: np.ndarray, cx: float, cy: float, rmax: int) -> tuple[np.ndarray, np.ndarray]:
    theta = np.radians(np.arange(_ANGLES) * 360.0 / _ANGLES)
    rr = np.arange(rmax, dtype=np.float32)
    xs = (cx + rr[None, :] * np.cos(theta)[:, None]).astype(np.float32)
    ys = (cy + rr[None, :] * np.sin(theta)[:, None]).astype(np.float32)
    valid = (xs >= 1) & (xs < img.shape[1] - 2) & (ys >= 1) & (ys < img.shape[0] - 2)
    return cv2.remap(img, xs, ys, cv2.INTER_LINEAR), valid


def _edgeProfile(img: np.ndarray, cx: float, cy: float, rmax: int) -> np.ndarray:
    """How strongly each radius is a circular edge: the radial step, taken at
    the angle-median so only edges present all round count."""
    lab = cv2.cvtColor(img, cv2.COLOR_BGR2LAB).astype(np.float32)
    pol, valid = _polar(lab, cx, cy, rmax)
    pol = cv2.GaussianBlur(pol, (0, 0), sigmaX=1.2, sigmaY=2.0)
    step = np.linalg.norm(np.diff(pol, axis=1), axis=2)
    ok = valid[:, 1:] & valid[:, :-1]
    step[~ok] = np.nan
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        profile = np.nanmedian(step, axis=0)
    profile[ok.mean(axis=0) < 0.15] = np.nan
    return np.nan_to_num(np.concatenate([profile, [np.nan]]), nan=0.0)


def _motionProfile(frames: Sequence[np.ndarray], cx: float, cy: float, rmax: int) -> np.ndarray | None:
    """How much each radius changes from picture to picture (median absolute
    change, brightness-normalised)."""
    if len(frames) < 4:
        return None
    grays = []
    for f in frames:
        g = cv2.GaussianBlur(cv2.cvtColor(f, cv2.COLOR_BGR2GRAY).astype(np.float32), (0, 0), 1.5)
        grays.append(g / max(float(np.median(g)), 1.0))
    stack = np.stack(grays)
    change = np.median(np.abs(stack - np.median(stack, axis=0)[None]), axis=0)
    pol, valid = _polar(change, cx, cy, rmax)
    pol[~valid] = np.nan
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        profile = np.nanmean(pol, axis=0)
    profile[valid.mean(axis=0) < 0.15] = np.nan
    return np.nan_to_num(profile, nan=0.0)


def _peaks(profile: np.ndarray, half: int = 3) -> list[int]:
    return [
        r
        for r in range(half, len(profile) - half)
        if profile[r] > 0 and profile[r] == profile[r - half : r + half + 1].max()
    ]


# Across machines the rim sits between these shares of the picture's shorter
# side: hubs are well inside it, and the stator's outer edge is the other
# strong circle in it, always further out than the rim.
RIM_RANGE = (0.3, 0.75)


def _findRim(
    median: np.ndarray, frames: Sequence[np.ndarray], cx: float, cy: float
) -> tuple[float, float, str | None]:
    h, w = median.shape[:2]
    rmax = int(math.hypot(w, h))
    edges = _edgeProfile(median, cx, cy, rmax)
    low, high = RIM_RANGE[0] * min(w, h), RIM_RANGE[1] * min(w, h)
    peaks = [r for r in _peaks(edges) if low <= r <= high]
    if not peaks:
        return 0.45 * min(w, h), 0.0, "no circular edge found; the ring is a guess"
    strongest = float(max(edges[r] for r in peaks))
    strong = [r for r in peaks if edges[r] >= 0.35 * strongest]
    motion = _motionProfile(frames, cx, cy, rmax)
    if motion is not None:
        # Over time the pieces riding against the wall change the picture most
        # in a band at the rim: the rim is the circular edge nearest that band.
        band = np.convolve(motion, np.ones(9) / 9.0, mode="same")
        lo, hi = int(low), min(int(high), len(band) - 1)
        if hi > lo:
            ridden = lo + int(np.argmax(band[lo:hi]))
            if band[ridden] > 1.5 * float(np.median(band[lo:hi])):
                near = [r for r in peaks if edges[r] >= 0.15 * strongest and abs(r - ridden) <= 0.12 * ridden]
                rim = min(near, key=lambda r: abs(r - ridden)) if near else ridden
                return float(rim), float(edges[rim] / strongest) if near else 0.0, None
    rim = strong[0]
    return float(rim), float(edges[rim] / strongest), "from one picture" if len(frames) < 4 else None


def _fitCircle(
    img: np.ndarray, cx: float, cy: float, lo: float, hi: float
) -> tuple[tuple[float, float], float] | None:
    """The circle through the sharpest light-to-dark step (or dark-to-light,
    whichever fits better) between radii ``lo`` and ``hi`` around (cx, cy),
    one point every 2 degrees; None when too few of the directions that stay
    in the picture find it or the points do not lie on one circle."""
    gray = cv2.GaussianBlur(cv2.cvtColor(img, cv2.COLOR_BGR2GRAY) if img.ndim == 3 else img, (3, 3), 0)
    gray = gray.astype(np.float32)
    h, w = gray.shape
    radii = np.arange(lo, hi, 0.5, dtype=np.float32)
    if radii.size < 16:
        return None
    angles = np.radians(np.arange(0, 360, 2, dtype=np.float32))
    xs = (cx + np.outer(np.cos(angles), radii)).astype(np.float32)
    ys = (cy + np.outer(np.sin(angles), radii)).astype(np.float32)
    inside = (xs >= 1) & (xs < w - 2) & (ys >= 1) & (ys < h - 2)
    samples = cv2.remap(gray, xs, ys, cv2.INTER_LINEAR)
    rays = int((inside.mean(axis=1) >= 0.9).sum())
    best = None
    for sign in (1.0, -1.0):
        points = []
        for i in range(len(angles)):
            if inside[i].mean() < 0.9:
                continue
            v = np.convolve(samples[i], np.ones(5) / 5.0, mode="valid")
            step = sign * (v[:-6] - v[6:])
            if step.size < 3:
                continue
            k = int(np.argmax(step[1:-1])) + 1
            if step[k] > 8.0:
                j = k + 5
                points.append((float(xs[i, j]), float(ys[i, j])))
        if len(points) < 20:
            continue
        fit = _trimmedCircle(np.asarray(points))
        if fit is None:
            continue
        (fx, fy), fr, kept, miss = fit
        share = kept / float(max(rays, 1))
        if kept >= FIT_POINTS and share >= FIT_SHARE and miss <= FIT_MISS and (best is None or kept > best[2]):
            best = ((fx, fy), fr, kept)
    return (best[0], best[1]) if best is not None else None


def _trimmedCircle(points: np.ndarray) -> tuple[tuple[float, float], float, int, float] | None:
    """Least-squares circle, refitted without the points it misses most."""
    keep = np.ones(len(points), bool)
    fit = None
    for _ in range(4):
        x, y = points[keep, 0], points[keep, 1]
        if len(x) < 10:
            return None
        a = np.column_stack([2 * x, 2 * y, np.ones(len(x))])
        sol, *_ = np.linalg.lstsq(a, x * x + y * y, rcond=None)
        fx, fy = float(sol[0]), float(sol[1])
        fr = math.sqrt(max(float(sol[2]) + fx * fx + fy * fy, 1.0))
        miss = np.abs(np.hypot(points[:, 0] - fx, points[:, 1] - fy) - fr)
        keep = miss <= max(1.0, float(np.percentile(miss, 80)))
        fit = ((fx, fy), fr, int(keep.sum()), float(np.median(miss[keep])))
    return fit


def _fullMedian(frames: Sequence[np.ndarray], size: tuple[int, int], most: int = 16) -> np.ndarray:
    """The median of up to ``most`` of the pictures, evenly spread, at ``size``."""
    w, h = size
    picked = [frames[int(i)] for i in np.linspace(0, len(frames) - 1, min(most, len(frames)))]
    same = [f if f.shape[:2] == (h, w) else cv2.resize(f, (w, h), interpolation=cv2.INTER_AREA) for f in picked]
    return np.median(np.stack(same), axis=0).astype(np.uint8) if len(same) > 1 else same[0]


def _angleAround(center: tuple[float, float], point: tuple[float, float]) -> float:
    return math.degrees(math.atan2(point[1] - center[1], point[0] - center[0])) % 360.0


def _findOpening(
    img: np.ndarray, cx: float, cy: float, rim: float, falls: Sequence[float], prior: float
) -> tuple[Span | None, str]:
    """The wall's opening at the rim (see OPENING_VALLEY), and a sentence on
    how it was found or why not."""
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY) if img.ndim == 3 else img
    gray = gray.astype(np.float32)
    h, w = gray.shape
    rad = np.radians(np.arange(360, dtype=np.float32))

    def band(f0: float, f1: float, n: int) -> tuple[np.ndarray, np.ndarray]:
        rs = (rim * np.linspace(f0, f1, n)).astype(np.float32)
        xs = (cx + np.outer(np.cos(rad), rs)).astype(np.float32)
        ys = (cy + np.outer(np.sin(rad), rs)).astype(np.float32)
        ok = ((xs >= 0) & (xs < w - 1) & (ys >= 0) & (ys < h - 1)).all(axis=1)
        return cv2.remap(gray, xs, ys, cv2.INTER_LINEAR), ok

    inner, ok_in = band(0.90, 0.96, 6)
    outer, ok_out = band(1.04, 1.10, 6)
    edge, ok_edge = band(0.97, 1.03, 13)
    valid = ok_in & ok_out & ok_edge
    if valid.sum() < 90:
        return None, "too little of the rim is in the picture to find the exit, so it was kept"
    valley = np.minimum(inner.mean(axis=1), outer.mean(axis=1)) - edge.min(axis=1)
    valley = np.convolve(np.r_[valley[-2:], valley, valley[:2]], np.ones(5) / 5.0, mode="valid")
    wall = float(np.median(valley[valid]))
    if wall < WALL_VALLEY_MIN:
        return None, "the wall's edge is not clear enough to find the exit, so it was kept"
    wall_here = valid & (valley >= OPENING_VALLEY * wall)
    open_here = valid & ~wall_here
    # Runs of opening that start at the wall and end at the wall, or where the
    # rim leaves the picture (the visible part is the exit then).
    runs: list[tuple[int, int]] = []
    start = None
    for i in range(720):
        a = i % 360
        if open_here[a] and start is None and wall_here[(a - 1) % 360]:
            start = i
        elif start is not None and not open_here[a]:
            if OPENING_DEG[0] <= i - start <= OPENING_DEG[1]:
                runs.append((start % 360, i - start))
            start = None
    runs = sorted(set(runs))
    if not runs:
        return None, "no opening was found in the wall, so the exit was kept"

    def gap(angle: float, run: tuple[int, int]) -> float:
        into = (angle - run[0]) % 360.0
        if into <= run[1]:
            return 0.0
        return min(into - run[1], 360.0 - into)

    if falls:
        r = np.radians(np.asarray(falls, dtype=np.float64))
        fell = math.degrees(math.atan2(float(np.sin(r).mean()), float(np.cos(r).mean()))) % 360.0
        best = min(runs, key=lambda r: gap(fell, r))
        if gap(fell, best) <= FALL_NEAR_DEG:
            return Span(best[0], best[0] + best[1]), "the exit is the wall's opening where pieces fell"
        return None, "pieces fell away from every opening in the wall, so the exit was kept"
    best = min(runs, key=lambda r: gap(prior, r))
    if gap(prior, best) <= PRIOR_NEAR_DEG:
        return Span(best[0], best[0] + best[1]), "the exit is the wall's opening nearest the old exit; run pieces and find again to place it by where they fall"
    return None, "no opening near the old exit, so it was kept"


def _onTheEdges(
    img: np.ndarray, cx: float, cy: float, rim: float, outer: float, exit_span: Span
) -> tuple[Span | None, str]:
    """``exit_span`` with each end moved onto the wall's end face on its side
    (see EDGE_PAST_DEG), or None when neither end shows one; and a sentence
    on what was done."""
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY) if img.ndim == 3 else img
    gray = cv2.GaussianBlur(gray.astype(np.float32), (0, 0), max(1.0, gray.shape[1] / 1280.0))
    into = np.arange(-EDGE_PAST_DEG, exit_span.width + EDGE_PAST_DEG + 1e-9, EDGE_STEP_DEG)
    change = _radialChange(gray, cx, cy, rim, outer, exit_span.start + into)
    seen = ~np.isnan(change)
    if not seen.any():
        return None, "the opening's ends are out of the picture, so they were kept"
    filled = np.where(seen, change, 0.0)
    peak = int(round(EDGE_PEAK_DEG / EDGE_STEP_DEG))
    highest = np.lib.stride_tricks.sliding_window_view(np.pad(filled, peak), 2 * peak + 1).max(axis=1)
    # The usual change on each side of each angle, the larger of the two.
    local = int(round(EDGE_LOCAL_DEG / EDGE_STEP_DEG))
    windows = np.lib.stride_tricks.sliding_window_view(np.pad(change, local, constant_values=np.nan), local)
    beside = np.full(len(change), 1e-6)
    for side in (windows[: len(change)], windows[local + 1 : local + 1 + len(change)]):
        shown = ~np.isnan(side).all(axis=1)
        beside[shown] = np.maximum(beside[shown], np.nanmedian(side[shown], axis=1))
    lines = (
        seen
        & (filled >= highest)
        & (filled >= EDGE_SHARPNESS * max(float(np.median(change[seen])), 1e-6))
        & (filled >= EDGE_PROMINENCE * beside)
    )
    starts = np.flatnonzero(lines & (into < exit_span.width / 2.0))
    ends = np.flatnonzero(lines & (into > exit_span.width / 2.0))
    start = float(exit_span.start + into[starts[0]]) % 360.0 if len(starts) else None
    end = float(exit_span.start + into[ends[-1]]) % 360.0 if len(ends) else None
    if start is None and end is None:
        return None, "the opening's ends show no sharp edge past the rim, so they were kept"
    moved = Span(exit_span.start if start is None else start, exit_span.end if end is None else end)
    if not OPENING_DEG[0] <= moved.width <= OPENING_DEG[1]:
        return None, "the edges past the rim do not make an opening, so the exit was kept"
    which = "both ends sit" if start is not None and end is not None else ("start sits" if start is not None else "end sits")
    return moved, f"the exit's {which} on the wall's end face past the rim"


def _radialChange(gray: np.ndarray, cx: float, cy: float, rim: float, outer: float, angles: np.ndarray) -> np.ndarray:
    """How much the picture changes across each of ``angles``, summed over the
    radii from just past the rim to ``outer`` that the picture shows there;
    NaN where it shows fewer than EDGE_RADII."""
    h, w = gray.shape
    rad = np.radians(angles)
    total = np.zeros(len(angles))
    radii = np.zeros(len(angles), dtype=int)
    for r in np.arange(rim * 1.02, outer, 2.0):
        xs = (cx + r * np.cos(rad)).astype(np.float32)
        ys = (cy + r * np.sin(rad)).astype(np.float32)
        shown = (xs >= 1) & (xs < w - 2) & (ys >= 1) & (ys < h - 2)
        if not shown.any():
            continue
        values = cv2.remap(gray, xs.reshape(1, -1), ys.reshape(1, -1), cv2.INTER_LINEAR).ravel()
        # Both neighbours in the picture, or the frame's border reads as an edge.
        shown = shown & np.r_[shown[1:], False] & np.r_[False, shown[:-1]]
        total[shown] += np.abs(np.gradient(values))[shown]
        radii += shown
    return np.where(radii >= EDGE_RADII, total, np.nan)


def _findWall(median: np.ndarray, cx: float, cy: float, rim: float) -> float | None:
    """The wall's outer edge: the strongest circular edge between 1.1 and 1.8
    times the rim, if the picture shows one."""
    h, w = median.shape[:2]
    edges = _edgeProfile(median, cx, cy, int(math.hypot(w, h)))
    beyond = [r for r in _peaks(edges) if 1.1 * rim <= r <= 1.8 * rim]
    if not beyond:
        return None
    return float(max(beyond, key=lambda r: edges[r]))


def findInChild(
    channel: int,
    frames: Sequence[np.ndarray],
    current: ChannelZones | None,
    frame_size: tuple[int, int],
    falls: Sequence[tuple[float, float]] = (),
    timeout_s: float = 60.0,
) -> Found:
    """``findZones`` in a process of its own: a second of image work there
    never holds up the machine's own loop (one interpreter lock per process)."""
    import pickle
    import subprocess
    import sys
    from pathlib import Path

    backend = Path(__file__).resolve().parent.parent
    result = subprocess.run(
        [sys.executable, "-m", "zones.finder"],
        input=pickle.dumps((channel, list(frames), current, frame_size, list(falls))),
        capture_output=True,
        cwd=str(backend),
        timeout=timeout_s,
        check=False,
    )
    if result.returncode != 0:
        lines = result.stderr.decode(errors="replace").strip().splitlines()
        raise RuntimeError(lines[-1] if lines else "the finder failed")
    return pickle.loads(result.stdout)


if __name__ == "__main__":
    import pickle
    import sys

    # Found by its module's own name, so the result unpickles in the caller.
    from zones.finder import findZones as find

    channel_, frames_, current_, frame_size_, falls_ = pickle.load(sys.stdin.buffer)
    sys.stdout.buffer.write(pickle.dumps(find(channel_, frames_, current_, frame_size_, falls_)))
