"""Tracklets: runs of detections that are surely one piece.

Built from a channel's raw detections, one frame at a time. Consecutive
detections are joined only where nothing else could be meant (one candidate near
where the ring carried the piece, no second candidate close), so a tracklet is
short but pure, and every doubtful join is left for the model, which sees both
sides and their neighbours. The tracker's own track ids are not used: they are
cut and reused where pieces crowd, which is where the link is hardest.
"""

from __future__ import annotations

from collections import deque
from typing import Optional

import numpy as np

MAX_GAP_S = 0.6
SIGMA_RHO = 0.07
GATE = 1.0
MARGIN = 0.9
GAP_EVERY_FRAMES = 64


def fmed(x: np.ndarray) -> float:
    # np.median spends most of its time on bookkeeping at these sizes.
    n = len(x)
    if n == 0:
        return 0.0
    v = np.sort(x)
    return float(v[n // 2]) if n % 2 else 0.5 * float(v[n // 2 - 1] + v[n // 2])


def colorDist(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    d = a - b
    d = np.sqrt(d[..., 0] ** 2 + d[..., 1] ** 2 + (0.6 * d[..., 2]) ** 2)
    return np.where(np.isnan(d), 0.0, np.minimum(d, 1.0))


class ChannelTracker:
    def __init__(self) -> None:
        self.next_id = 0
        # Running total of the pieces' common flow, degrees toward the exit.
        self.phi = 0.0
        # Pieces' flow over the rotor's commanded turn, a running estimate.
        self.carry = 0.85
        self.max_gap = MAX_GAP_S
        self._prev_odo: Optional[float] = None
        self._prev_t: Optional[float] = None
        self._gaps: deque[float] = deque(maxlen=600)
        self._frames = 0
        self._id: list[int] = []
        self._t: list[float] = []
        self._deg: list[float] = []
        self._rho: list[float] = []
        self._col: list[np.ndarray] = []
        self._size: list[float] = []
        self._drop: list[bool] = []
        self._phi: list[float] = []

    def _keep(self, keep: list[int]) -> None:
        for name in ("_id", "_t", "_deg", "_rho", "_col", "_size", "_drop", "_phi"):
            values = getattr(self, name)
            setattr(self, name, [values[k] for k in keep])

    def _open(self, t: float, deg: float, rho: float, col: np.ndarray, size: float, drop: bool, phi: float) -> int:
        tracklet = self.next_id
        self.next_id += 1
        self._id.append(tracklet)
        self._t.append(t)
        self._deg.append(deg)
        self._rho.append(rho)
        self._col.append(col)
        self._size.append(size)
        self._drop.append(drop)
        self._phi.append(phi)
        return tracklet

    def _noteGap(self, t: float) -> None:
        if self._prev_t is not None and 0.0 < t - self._prev_t < 5.0:
            self._gaps.append(t - self._prev_t)
        self._prev_t = t
        self._frames += 1
        # A slow camera's tracklets may skip more time: 2.5 of its frames, up to 3 s.
        if self._frames % GAP_EVERY_FRAMES == 0 and self._gaps:
            self.max_gap = min(3.0, max(MAX_GAP_S, 2.5 * float(np.median(self._gaps))))

    def step(
        self,
        t: float,
        odo: float,
        deg: np.ndarray,
        rho: np.ndarray,
        color: np.ndarray,
        logsize: np.ndarray,
        in_drop: np.ndarray,
    ) -> tuple[np.ndarray, float]:
        self._noteGap(t)
        n = len(deg)
        cmd = 0.0 if self._prev_odo is None else odo - self._prev_odo
        if self._id:
            keep = [k for k in range(len(self._id)) if t - self._t[k] <= self.max_gap]
            if len(keep) != len(self._id):
                self._keep(keep)
        guess = self.carry * cmd
        step = guess
        ids = np.empty(n, dtype=np.int64)
        if n and self._id:
            rows = np.arange(len(self._id))
            a_deg = np.array(self._deg)
            a_rho = np.array(self._rho)
            a_col = np.array(self._col).reshape(-1, 3)
            a_size = np.array(self._size)
            a_drop = np.array(self._drop, dtype=bool)
            # How far each open tracklet's piece seems to have moved toward the exit to reach each detection.
            delta = a_deg[:, None] - deg[None, :]
            drho = a_rho[:, None] - rho[None, :]
            cd = colorDist(a_col[:, None, :], color[None, :, :])
            ds = np.abs(a_size[:, None] - logsize[None, :])
            alike = (np.abs(drho) < 0.2) & (cd < 0.25) & (ds < 0.6)
            # This frame's common flow: among look-alike pairs, each tracklet's displacement nearest the
            # guess, counted from when that tracklet was last seen.
            since = self.phi - np.array(self._phi)
            cand = np.where(alike, np.abs(delta - since[:, None] - guess), np.inf)
            best = cand.argmin(axis=1)
            ok = np.isfinite(cand[rows, best])
            if ok.any():
                moved = (delta - since[:, None])[rows, best][ok]
                lo, hi = min(-6.0, 1.6 * cmd - 6.0), max(6.0, 1.6 * cmd + 6.0)
                moved = moved[(moved > lo) & (moved < hi)]
                if len(moved):
                    step = fmed(moved)
            pred = since[:, None] + step
            sigma = 2.0 + 0.25 * np.abs(pred) + 10.0 * (a_drop[:, None] | in_drop[None, :])
            cost = np.hypot((delta - pred) / sigma, drho / SIGMA_RHO) + 2.0 * cd + 0.5 * ds
            # Join where each is the other's best, the cost is small, and no other pairing of either comes close.
            row_best = cost.argmin(axis=1)
            col_best = cost.argmin(axis=0)
            row_min = cost[rows, row_best]
            row_2nd = np.sort(cost, axis=1)[:, 1] if cost.shape[1] > 1 else np.full(len(rows), np.inf)
            col_2nd = np.sort(cost, axis=0)[1] if cost.shape[0] > 1 else np.full(n, np.inf)
            joined = [False] * len(rows)
            taken: set[int] = set()
            for i in np.flatnonzero((row_min < GATE) & (col_best[row_best] == rows)):
                j = int(row_best[i])
                cij = row_min[i]
                if min(row_2nd[i], col_2nd[j]) < max(2.0 * cij, cij + MARGIN):
                    continue
                ids[j] = self._id[i]
                self._t[i] = t
                self._deg[i] = float(deg[j])
                self._rho[i] = float(rho[j])
                self._col[i] = color[j].copy()
                self._size[i] = float(logsize[j])
                self._drop[i] = bool(in_drop[j])
                self._phi[i] = self.phi + step
                joined[i] = True
                taken.add(j)
            # Tracklets whose piece is in doubt this frame (a second candidate close by) end here: whatever
            # comes after is the model's to decide.
            under = cost < GATE
            doubt = (under.sum(axis=1) > 1) | ((row_min < GATE) & (under.sum(axis=0)[row_best] > 1))
            if doubt.any():
                gone = {int(i) for i in np.flatnonzero(doubt) if not joined[i]}
                self._keep([k for k in range(len(self._id)) if k not in gone])
            for j in range(n):
                if j not in taken:
                    ids[j] = self._open(t, float(deg[j]), float(rho[j]), color[j].copy(), float(logsize[j]), bool(in_drop[j]), self.phi + step)
        elif n:
            for j in range(n):
                ids[j] = self._open(t, float(deg[j]), float(rho[j]), color[j].copy(), float(logsize[j]), bool(in_drop[j]), self.phi + step)
        if abs(cmd) > 1.0 and step != guess:
            self.carry = float(np.clip(0.95 * self.carry + 0.05 * np.clip(step / cmd, 0.0, 1.5), 0.3, 1.2))
        self.phi += step
        self._prev_odo = odo
        return ids, step
