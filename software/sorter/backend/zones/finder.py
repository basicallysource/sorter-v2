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
from dataclasses import dataclass, field
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
) -> Found:
    """Find the ring in ``frames`` (BGR pictures of the channel as perception
    sees them, at any size of the camera's shape) and fit ``current`` (or the
    defaults) to it, in ``frame_size`` (width, height) pixels, by default the
    first picture's. Locked parts of ``current`` are kept."""
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
    wall = _findWall(median, cx, cy, rim)
    center = (cx / scale, cy / scale)
    rim_px = rim / scale
    outer_px = max(RING_OUTER_MIN * rim, WALL_MARGIN * wall if wall else 0.0) / scale

    base = current.scaledTo((w, h)) if current is not None else defaultZones(channel, (w, h))
    if "ring" in base.locked:
        notes.append("the ring is locked, so it was kept")
        return Found(zones=base, center_score=center_score, rim_score=rim_score, frames=len(small), notes=notes)
    # The zones stay where they were on the band pieces ride, locked or not:
    # only their angles are measured from the new center.
    zones = base.withRing(Ring(center, RING_INNER * rim_px, outer_px, rim_px), "found")
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
        input=pickle.dumps((channel, list(frames), current, frame_size)),
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

    channel_, frames_, current_, frame_size_ = pickle.load(sys.stdin.buffer)
    sys.stdout.buffer.write(pickle.dumps(find(channel_, frames_, current_, frame_size_)))
