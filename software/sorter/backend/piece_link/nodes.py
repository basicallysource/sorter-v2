"""The model's question, as arrays: for one tracklet (the anchor), which earlier
tracklet was the same piece?

Tracklets of two or more detections become nodes. An anchor's candidates are
every earlier tracklet that could physically be it: on its own channel, one that
ended upstream of where the anchor starts (a lost box, the stretch the camera
cannot see); on the channel above, one that ended near that channel's exit
shortly before (a drop). It also gets its rivals (other tracklets starting
around the same time, which compete for the same candidates) and a summary of
each channel as this machine's record shows it, so the answer can depend on the
machine without anything being set per machine. Features are in units that mean
the same on any machine: degrees to the exit, degrees the rotors were told to
turn in between, seconds, a channel's own colour and size scales.

The layout of a token (F_DIM columns) and of a channel's summary (CTX_DIM) is
the model's contract: FORMAT names it, and a model made for another is refused.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

import numpy as np

from .record import CHANNELS, Window
from .tracklets import fmed

K_SAME, K_UP, K_RIVAL = 24, 16, 10
N_CAND = K_SAME + K_UP
N_TOKENS = 1 + N_CAND + K_RIVAL
# A piece may sit hidden this long while its channel holds, but not while its channel turns more than this.
SAME_WINDOW_S = 150.0
SAME_TURN_DEG = 600.0
UP_WINDOW_S = 10.0
# A tracklet that ended within this of its channel's exit may have dropped.
UP_EXIT_DEG = 50.0
# A piece is found at most this far behind where it was lost: where pieces land (they bounce), and anywhere else.
BACK_DEG = 30.0
BACK_RIDE_DEG = 10.0
# ... and at most this many times the rotor's turn ahead of it, plus REACH_DEG.
REACH = 1.6
REACH_DEG = 35.0
MIN_NODE = 2
HIST_LO, HIST_HI, HIST_BIN = -60.0, 300.0, 10.0
N_HIST = int((HIST_HI - HIST_LO) / HIST_BIN)
CTX_DIM = 7 * N_HIST + 8
F_DIM = 82
FORMAT = {
    "features": "sim-v7",
    "f_dim": F_DIM,
    "ctx_dim": CTX_DIM,
    "k_same": K_SAME,
    "k_up": K_UP,
    "k_rival": K_RIVAL,
}


@dataclass
class Query:
    """How the piece being followed looked later (in the tracklet the walk came
    from), when the anchor itself may not show it alone: two pieces boxed as
    one, or a sliver at the edge of view."""

    col: np.ndarray
    size: float
    has_col: bool
    below: bool
    n: int


@dataclass
class Nodes:
    ch: np.ndarray
    tl: np.ndarray
    gid: np.ndarray
    n: np.ndarray
    t0: np.ndarray
    t1: np.ndarray
    deg0: np.ndarray
    deg1: np.ndarray
    degmin: np.ndarray
    rho0: np.ndarray
    rho1: np.ndarray
    zone0: np.ndarray
    zone1: np.ndarray
    size: np.ndarray
    size0: np.ndarray
    size1: np.ndarray
    aspect: np.ndarray
    col: np.ndarray
    col0: np.ndarray
    col1: np.ndarray
    has_col: np.ndarray
    odo0: np.ndarray
    odo1: np.ndarray
    rhoc0: np.ndarray
    rhoc1: np.ndarray
    sizec0: np.ndarray
    sizec1: np.ndarray
    ctx: np.ndarray
    fps: dict[int, float]

    def __len__(self) -> int:
        return len(self.ch)


# A node's own numbers, in the order makeNodes keeps them (a row of ROW_WIDTH floats).
_ROW = (
    "n t0 t1 deg0 deg1 degmin rho0 rho1 zone0 zone1 size size0 size1 aspect has_col rhoc0 rhoc1 sizec0 sizec1"
).split()
ROW_WIDTH = len(_ROW) + 9
_INT_COLUMNS = ("n", "zone0", "zone1")
# A tracklet out of sight this long cannot grow: longer than any tracklet may skip.
CLOSED_AFTER_S = 3.5

Key = tuple[int, int]
# A channel's scales (colour mean and spread, usual size, usual place and size by place) move while a run is young.
# Kept rows were worked out against one reading of them; once the scales have moved this far, they are worked out again.
SCALE_DRIFT = {"color": 0.05, "size": 0.03, "rho": 0.02}


@dataclass
class KeptRows:
    rows: dict[Key, list[float]] = field(default_factory=dict)
    scales: dict[int, tuple[np.ndarray, np.ndarray, float, np.ndarray, np.ndarray]] = field(default_factory=dict)

    def dropChannel(self, ch: int) -> None:
        self.rows = {k: v for k, v in self.rows.items() if k[0] != ch}


def scalesMoved(held: tuple, now: tuple) -> bool:
    mu0, sd0, med0, rho0, size0 = held
    mu1, sd1, med1, rho1, size1 = now
    return bool(
        np.abs((mu1 - mu0) / sd0).max() > SCALE_DRIFT["color"]
        or np.abs(sd1 / sd0 - 1.0).max() > SCALE_DRIFT["color"]
        or abs(med1 - med0) > SCALE_DRIFT["size"]
        or np.abs(size1 - size0).max() > SCALE_DRIFT["size"]
        or np.abs(rho1 - rho0).max() > SCALE_DRIFT["rho"]
    )


def med3(x: np.ndarray) -> np.ndarray:
    # np.median(x, axis=0) for a short (n, 3) array, without its bookkeeping.
    n = len(x)
    v = np.sort(x, axis=0)
    return v[n // 2] if n % 2 else 0.5 * (v[n // 2 - 1] + v[n // 2])


def makeNodes(win: Window, since: Optional[float] = None, kept: Optional[KeptRows] = None) -> Nodes:
    """`since`: only tracklets seen at or after this time become nodes (the
    channels' summaries still take the whole window). `kept`: the rows of
    tracklets that have ended, by (channel, tracklet id), read and added to:
    such a tracklet's numbers are worked out once, not at every look."""
    rows: list[list[float]] = []
    heads: list[tuple[int, int, int]] = []
    odo0: list[float] = []
    odo1: list[float] = []
    ctx = np.zeros((3, CTX_DIM), dtype=np.float32)
    fps: dict[int, float] = {}
    for ci, ch in enumerate(CHANNELS):
        c, tl = win.ch[ch], win.tls[ch]
        gaps = np.diff(c.frame_t)
        gaps = gaps[(gaps > 0) & (gaps < 2.0)]
        fps[ch] = float(1.0 / np.median(gaps)) if len(gaps) else 15.0
        if not len(c):
            continue
        deg = np.where(np.isnan(c.deg), 0.0, c.deg)
        rho = np.where(np.isnan(c.rho), 0.5, c.rho)
        known = ~np.isnan(c.color[:, 0])
        mu = np.nanmean(c.color, axis=0) if known.any() else np.zeros(3)
        sd = np.nanstd(c.color, axis=0) + 1e-3 if known.any() else np.ones(3)
        logsize_raw = np.log(np.maximum(c.size, 1e-4))
        usual_size = float(np.median(logsize_raw))
        logsize = logsize_raw - usual_size
        logaspect = np.log(np.maximum(c.aspect, 1e-3))
        # What is usual at each place on this channel: the median place across the ring and median size of
        # the detections there (10-degree bins; a bin too thin takes its nearest neighbour's). A camera reads
        # both differently around its ring, so a piece is compared with itself against these, not raw.
        place = np.clip(((deg - HIST_LO) / HIST_BIN).astype(int), 0, N_HIST - 1)
        prof_rho, prof_size, thick = np.zeros(N_HIST), np.zeros(N_HIST), np.zeros(N_HIST, dtype=bool)
        order_p = np.argsort(place, kind="stable")
        bounds_p = np.searchsorted(place[order_p], np.arange(N_HIST + 1))
        for b in range(N_HIST):
            m = order_p[bounds_p[b] : bounds_p[b + 1]]
            if len(m) >= 40:
                prof_rho[b], prof_size[b], thick[b] = np.median(rho[m]), np.median(logsize[m]), True
        if thick.any():
            near = np.flatnonzero(thick)
            fill = near[np.abs(np.arange(N_HIST)[:, None] - near[None, :]).argmin(axis=1)]
            prof_rho, prof_size = prof_rho[fill], prof_size[fill]
        scales = (mu, sd, usual_size, prof_rho, prof_size)
        if kept is not None:
            held = kept.scales.get(ch)
            if held is None or scalesMoved(held, scales):
                kept.scales[ch] = scales
                kept.dropChannel(ch)
            else:
                scales = held
        # Rows are worked out against `scales`; the channel's summary below takes the window as it is now.
        z = np.where(known[:, None], (c.color - scales[0]) / scales[1], 0.0)
        logsize = logsize_raw - scales[2]
        rho_c = rho - scales[3][place]
        size_c = logsize - scales[4][place]
        every = np.flatnonzero(tl.count >= MIN_NODE)
        keep = every if since is None else every[c.t[tl.last[every]] >= since]
        for k in keep:
            key = (ch, int(tl.ids[k]))
            heads.append((ch, int(k), key[1]))
            row = kept.rows.get(key) if kept is not None else None
            if row is None:
                m = tl.members[k]
                a, b = m[:3], m[-3:]
                row = [
                    len(m), c.t[m[0]], c.t[m[-1]], fmed(deg[a]), fmed(deg[b]), float(deg[m].min()),
                    fmed(rho[a]), fmed(rho[b]), int(c.zone[m[0]]), int(c.zone[m[-1]]),
                    fmed(logsize[m]), fmed(logsize[a]), fmed(logsize[b]), fmed(logaspect[m]),
                    float(known[m].any()), fmed(rho_c[a]), fmed(rho_c[b]), fmed(size_c[a]), fmed(size_c[b]),
                    *med3(z[m]), *med3(z[a]), *med3(z[b]),
                ]
                if kept is not None and win.now - row[2] > CLOSED_AFTER_S:
                    kept.rows[key] = row
            rows.append(row)
        # A kept row's times are the tracklet's own, whole: the window may since have cut its first detections.
        firsts = np.array([r[1] for r in rows[len(rows) - len(keep):]])
        lasts = np.array([r[2] for r in rows[len(rows) - len(keep):]])
        odo0 += np.atleast_1d(win.odometer(ch, firsts)).tolist()
        odo1 += np.atleast_1d(win.odometer(ch, lasts)).tolist()
        # The channel as this record shows it.
        big = every[tl.count[every] >= 3]

        def hist(values: np.ndarray) -> np.ndarray:
            h, _ = np.histogram(values, bins=N_HIST, range=(HIST_LO, HIST_HI))
            return h / max(h.sum(), 1)

        ctx[ci, :N_HIST] = hist(deg)
        ctx[ci, N_HIST : 2 * N_HIST] = hist(deg[tl.first[big]]) if len(big) else 0
        ctx[ci, 2 * N_HIST : 3 * N_HIST] = hist(deg[tl.last[big]]) if len(big) else 0
        # Carry by place: over consecutive detections of one tracklet, degrees moved toward the exit over
        # degrees the rotor was told to turn, where on the ring it happened. The camera's angle scale shows here.
        order = np.lexsort((c.t, tl.of))
        same = tl.of[order[1:]] == tl.of[order[:-1]]
        a, b = order[:-1][same], order[1:][same]
        if len(a):
            turn = win.odometer(ch, c.t[b]) - win.odometer(ch, c.t[a])
            use = turn > 0.5
            bins = np.clip(((deg[a[use]] - HIST_LO) / HIST_BIN).astype(int), 0, N_HIST - 1)
            num = np.bincount(bins, weights=(deg[a[use]] - deg[b[use]]), minlength=N_HIST)
            den = np.bincount(bins, weights=turn[use], minlength=N_HIST)
            seen = den > 20.0
            ctx[ci, 3 * N_HIST : 4 * N_HIST] = np.where(seen, np.clip(num / np.maximum(den, 1e-6), 0.0, 2.5), 0.0)
            ctx[ci, 4 * N_HIST : 5 * N_HIST] = seen
        ctx[ci, 5 * N_HIST : 6 * N_HIST] = np.where(thick, prof_rho - np.median(rho), 0.0)
        ctx[ci, 6 * N_HIST : 7 * N_HIST] = np.where(thick, np.clip(prof_size, -2, 2), 0.0)
        span = max(c.frame_t[-1] - c.frame_t[0], 1.0)
        moves = win.moves.get(ch)
        turned = float(win.odometer(ch, c.frame_t[-1]) - win.odometer(ch, c.frame_t[0]))
        ctx[ci, 7 * N_HIST :] = [
            np.log(fps[ch]) / 3.0,
            float(c.frame_n.mean()) / 10.0,
            len(big) / span,
            float(known.mean()),
            np.log1p(fmed(np.abs(moves[:, 1])) if moves is not None and len(moves) else 0.0) / 5.0,
            (len(moves) / span) if moves is not None else 0.0,
            float(tl.flow.sum()) / max(turned, 1.0),
            np.log1p(fmed(c.t[tl.last[big]] - c.t[tl.first[big]]) if len(big) else 0.0) / 3.0,
        ]
    table = np.array(rows, dtype=float).reshape(-1, ROW_WIDTH)
    head = np.array(heads, dtype=np.int64).reshape(-1, 3)
    arr: dict[str, np.ndarray] = {"ch": head[:, 0], "tl": head[:, 1], "gid": head[:, 2]}
    for i, name in enumerate(_ROW):
        arr[name] = table[:, i].astype(np.int64) if name in _INT_COLUMNS else table[:, i]
    arr["has_col"] = arr["has_col"] > 0.5
    at = len(_ROW)
    for i, name in enumerate(("col", "col0", "col1")):
        arr[name] = table[:, at + 3 * i : at + 3 * i + 3].astype(np.float32)
    arr["odo0"] = np.array(odo0, dtype=float)
    arr["odo1"] = np.array(odo1, dtype=float)
    return Nodes(ctx=ctx, fps=fps, **arr)


def features(nd: Nodes, win: Window, j: int, idx: np.ndarray, kind: np.ndarray, query: Optional[Query] = None) -> np.ndarray:
    """One row a token. `kind`: 0 the anchor, 1 a candidate on the anchor's
    channel, 2 a candidate on the channel above, 3 a rival. Candidates are
    described by how they ended, the anchor and rivals by how they start."""
    n = len(idx)
    f = np.zeros((n, F_DIM), dtype=np.float32)
    ch_j, t_j = nd.ch[j], nd.t0[j]
    cand = (kind == 1) | (kind == 2)
    f[np.arange(n), kind] = 1.0
    f[np.arange(n), 4 + (nd.ch[idx] - 2)] = 1.0
    t_ref = np.where(cand, nd.t1[idx], nd.t0[idx])
    dt = t_j - t_ref
    f[:, 7] = np.clip(dt / 10.0, -2, 15)
    f[:, 8] = np.sign(dt) * np.log1p(np.abs(dt))
    f[:, 9] = dt < 0
    own = np.zeros(n)
    below = np.zeros(n)
    for c in np.unique(nd.ch[idx]):
        m = nd.ch[idx] == c
        own[m] = win.odometer(int(c), t_j) - win.odometer(int(c), t_ref[m])
    below[:] = win.odometer(int(ch_j), t_j) - win.odometer(int(ch_j), t_ref)
    f[:, 10] = np.clip(own / 100.0, -1, 8)
    f[:, 11] = np.sign(own) * np.log1p(np.abs(own)) / 3.0
    f[:, 12] = np.clip(below / 100.0, -1, 8)
    f[:, 13] = np.sign(below) * np.log1p(np.abs(below)) / 3.0
    deg = np.where(cand, nd.deg1[idx], nd.deg0[idx])
    rho = np.where(cand, nd.rho1[idx], nd.rho0[idx])
    f[:, 14] = deg / 180.0
    f[:, 15] = rho
    gap = deg - nd.deg0[j]
    same = kind == 1
    f[:, 16] = np.where(same, gap / 180.0, 0.0)
    f[:, 17] = np.where(same, np.clip(gap / np.maximum(np.abs(own), 1.0), -3, 3), 0.0)
    f[:, 18] = np.where(same, np.clip((gap - own) / 60.0, -4, 4), 0.0)
    f[:, 19] = np.where(same | (kind == 3), rho - nd.rho0[j], 0.0)
    zone = np.where(cand, nd.zone1[idx], nd.zone0[idx])
    f[np.arange(n), 20 + np.clip(zone, 0, 3)] = 1.0
    f[:, 24] = nd.degmin[idx] / 180.0
    f[:, 25] = nd.deg0[idx] / 180.0
    f[:, 26] = nd.deg1[idx] / 180.0
    life = nd.t1[idx] - nd.t0[idx]
    travel = nd.deg0[idx] - nd.deg1[idx]
    turned = nd.odo1[idx] - nd.odo0[idx]
    f[:, 27] = np.log1p(nd.n[idx]) / 5.0
    f[:, 28] = np.log1p(life) / 4.0
    f[:, 29] = np.clip(travel / 100.0, -1, 4)
    f[:, 30] = np.clip(travel / np.maximum(np.abs(turned), 2.0), -2, 3)
    f[:, 31] = np.clip(turned / 100.0, -1, 6)
    size = np.where(cand, nd.size1[idx], nd.size0[idx])
    f[:, 32] = nd.size[idx]
    f[:, 33] = size
    f[:, 34] = nd.aspect[idx]
    f[:, 35] = nd.size[idx] - nd.size[j]
    f[:, 36] = size - nd.size0[j]
    f[:, 37] = np.abs(nd.aspect[idx]) - abs(nd.aspect[j])
    col = np.where(cand[:, None], nd.col1[idx], nd.col0[idx])
    both = (nd.has_col[idx] & nd.has_col[j]).astype(np.float32)
    f[:, 38:41] = np.clip(nd.col[idx], -4, 4)
    f[:, 41:44] = np.clip(col, -4, 4)
    f[:, 44:47] = np.clip(nd.col[idx] - nd.col[j], -6, 6) * both[:, None]
    f[:, 47:50] = np.clip(col - nd.col0[j], -6, 6) * both[:, None]
    f[:, 50] = np.sqrt(np.sum((nd.col[idx] - nd.col[j]) ** 2, axis=1)) * both / 3.0
    f[:, 51] = both
    f[:, 52] = nd.has_col[idx]
    # Columns 53, 54 and 63 are part of the layout and stay empty.
    f[:, 55] = np.where(cand, np.clip((UP_EXIT_DEG - nd.deg1[idx]) / 50.0, -4, 2), 0.0)
    f[:, 56] = nd.deg0[j] / 180.0
    f[:, 57] = nd.rho0[j]
    f[:, 58] = nd.zone0[j] == 1
    f[:, 59] = np.log1p(nd.n[j]) / 5.0
    f[:, 60] = nd.ch[idx] == ch_j
    f[:, 61] = np.clip((nd.t1[idx] - t_j) / 10.0, -15, 15)
    f[:, 62] = np.clip((nd.t0[idx] - t_j) / 10.0, -15, 15)
    rho_c = np.where(cand, nd.rhoc1[idx], nd.rhoc0[idx])
    size_c = np.where(cand, nd.sizec1[idx], nd.sizec0[idx])
    f[:, 76] = np.clip(rho_c, -1, 1)
    f[:, 77] = np.where(nd.ch[idx] == ch_j, np.clip(rho_c - nd.rhoc0[j], -1, 1), 0.0)
    f[:, 78] = np.clip(size_c, -3, 3)
    f[:, 79] = np.clip(size_c - nd.sizec0[j], -3, 3)
    if query is not None:
        qboth = (nd.has_col[idx] & query.has_col).astype(np.float32)
        f[:, 64:67] = np.clip(col - query.col, -6, 6) * qboth[:, None]
        f[:, 67:70] = np.clip(nd.col[idx] - query.col, -6, 6) * qboth[:, None]
        f[:, 70] = size_c - query.size
        f[:, 71] = 0.5 * (nd.sizec0[idx] + nd.sizec1[idx]) - query.size
        f[:, 72] = 1.0
        f[:, 73] = query.below
        f[:, 74] = qboth
        f[:, 75] = np.log1p(query.n) / 5.0
    return f


def timeOrders(nd: Nodes) -> dict[int, np.ndarray]:
    """Node indices of each channel sorted by end time (key ch) and by start time (key -ch)."""
    out = {}
    for ch in CHANNELS:
        m = np.flatnonzero(nd.ch == ch)
        out[ch] = m[np.argsort(nd.t1[m], kind="stable")]
        out[-ch] = m[np.argsort(nd.t0[m], kind="stable")]
    return out


def candidates(nd: Nodes, win: Window, j: int, order: dict[int, np.ndarray]) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    ch, t0, deg0 = int(nd.ch[j]), nd.t0[j], nd.deg0[j]
    own = order[ch]
    # Same channel: ended before the anchor started (a frame's slack), not long ago, upstream of it.
    lo = np.searchsorted(nd.t1[own], t0 - SAME_WINDOW_S, side="left")
    hi = np.searchsorted(nd.t1[own], t0 + 0.12, side="right")
    back = BACK_DEG if (nd.zone0[j] == 1 or deg0 > 150.0) else BACK_RIDE_DEG
    c = own[lo:hi]
    c = c[(c != j) & (nd.deg1[c] >= deg0 - back)]
    turned = np.zeros(0)
    if len(c):
        # The ring must have turned enough since to carry it from where it ended to where the anchor starts.
        turned = win.odometer(ch, t0) - win.odometer(ch, nd.t1[c])
        ok = (turned <= SAME_TURN_DEG) & (nd.deg1[c] - deg0 <= REACH * np.maximum(turned, 0.0) + REACH_DEG)
        c, turned = c[ok], turned[ok]
    if len(c) > K_SAME:
        # More than fit (a crowded channel sheds fragments by the second): first those whose distance to the
        # anchor's start fits what the ring turned since, the latest first; then the rest.
        gap = nd.deg1[c] - deg0
        fits = gap >= 0.25 * np.maximum(turned, 0.0) - 25.0
        age = t0 - nd.t1[c]
        same = c[np.lexsort((age, ~fits))][:K_SAME]
    else:
        same = c[::-1]
    up = np.array([], dtype=np.int64)
    if ch > 2:
        above = order[ch - 1]
        lo = np.searchsorted(nd.t1[above], t0 - UP_WINDOW_S, side="left")
        hi = np.searchsorted(nd.t1[above], t0 + 0.3, side="right")
        u = above[lo:hi]
        u = u[nd.deg1[u] <= UP_EXIT_DEG]
        if len(u) > K_UP:
            # A crowded exit sheds fragments too: tracklets of 4 or more detections first, the latest first.
            age = t0 - nd.t1[u]
            up = u[np.lexsort((age, nd.n[u] < 4))][:K_UP]
        else:
            up = u[::-1]
    starts = order[-ch]
    lo = np.searchsorted(nd.t0[starts], t0 - 8.0, side="left")
    hi = np.searchsorted(nd.t0[starts], t0 + 8.0, side="right")
    r = starts[lo:hi]
    r = r[(r != j) & (nd.n[r] >= 3)]
    r = r[np.argsort(np.abs(nd.t0[r] - t0))][:K_RIVAL]
    return same, up, r


def queryOf(nd: Nodes, node: int, below: bool) -> Query:
    return Query(nd.col[node], float(0.5 * (nd.sizec0[node] + nd.sizec1[node])), bool(nd.has_col[node]), below, int(nd.n[node]))


@dataclass
class Questions:
    anchor: np.ndarray
    tokens: np.ndarray
    mask: np.ndarray
    # Each candidate slot's node, -1 when empty.
    cand: np.ndarray


def questions(
    nd: Nodes,
    win: Window,
    anchors: np.ndarray,
    order: dict[int, np.ndarray],
    queries: Optional[list[Optional[Query]]] = None,
) -> Questions:
    n = len(anchors)
    # Half precision on the way to the model, as its training data was stored.
    tokens = np.zeros((n, N_TOKENS, F_DIM), dtype=np.float16)
    mask = np.zeros((n, N_TOKENS), dtype=bool)
    cand = np.full((n, N_CAND), -1, dtype=np.int64)
    for e, j in enumerate(anchors):
        j = int(j)
        same, up, riv = candidates(nd, win, j, order)
        idx = np.concatenate([[j], same, up, riv]).astype(np.int64)
        kind = np.concatenate([[0], np.full(len(same), 1), np.full(len(up), 2), np.full(len(riv), 3)]).astype(np.int64)
        f = features(nd, win, j, idx, kind, queries[e] if queries is not None else None)
        # Slots: the anchor, then same-channel candidates, then the channel above, then rivals.
        pos = np.concatenate(
            [[0], 1 + np.arange(len(same)), 1 + K_SAME + np.arange(len(up)), 1 + N_CAND + np.arange(len(riv))]
        )
        tokens[e, pos] = f
        mask[e, pos] = True
        cand[e, : len(same)] = same
        cand[e, K_SAME : K_SAME + len(up)] = up
    return Questions(np.asarray(anchors, dtype=np.int64), tokens, mask, cand)
