"""The control data stream as arrays, kept current one record at a time.

Takes the records perception.transition_capture and the hardware layer write
(`meta`, `frame_info`, `state`, `cmd`, `event`) in the order they are written
and keeps, for the last WINDOW_S seconds: every detection on C2, C3 and C4 in
ring coordinates with the tracklet it belongs to, every recorded frame, each
rotor's commanded turn as an odometer, and which C4 track is which piece.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional

import numpy as np

from .tracklets import ChannelTracker

CHANNELS = (2, 3, 4)
STEPPER_CHANNEL = {"c_channel_1_rotor": 1, "c_channel_2_rotor": 2, "c_channel_3_rotor": 3, "carousel": 4}
ARC_NAME = {2: "second", 3: "third", 4: "classification_channel"}
MOTOR_DEG_PER_USTEP = 0.225
ZONE_DROP = 1
WINDOW_S = 900.0
# The channels' frames reach the record a little apart.
CLOCK_SLACK_S = 0.25
# Trimming moves nothing, but there is no point doing it for a handful of frames.
TRIM_EVERY_FRAMES = 512

T, FRAME, DEG, SEC, ZONE, X1, Y1, X2, Y2, TID, C0, C1, C2, RHO, SIZE, ASPECT, OF = range(17)
FRAME_T, FRAME_N, FRAME_FLOW = range(3)


class Rows:
    def __init__(self, width: int, capacity: int = 4096) -> None:
        self._width = width
        self._buf = np.empty((capacity, width))
        self._lo = 0
        self._hi = 0

    def __len__(self) -> int:
        return self._hi - self._lo

    def append(self, rows: np.ndarray) -> None:
        n = len(rows)
        if self._hi + n > len(self._buf):
            live = self._buf[self._lo : self._hi]
            capacity = len(self._buf)
            while len(live) + n > capacity // 2:
                capacity *= 2
            fresh = np.empty((capacity, self._width))
            fresh[: len(live)] = live
            self._buf = fresh
            self._lo, self._hi = 0, len(live)
        self._buf[self._hi : self._hi + n] = rows
        self._hi += n

    def view(self) -> np.ndarray:
        return self._buf[self._lo : self._hi]

    def dropFirst(self, n: int) -> None:
        self._lo += min(max(n, 0), len(self))


class Odometer:
    """Output degrees a rotor has been told to turn forward by a time, each
    move spread over the time it takes."""

    def __init__(self) -> None:
        self._knots = Rows(2, 1024)
        self._moves = Rows(3, 512)
        self.total = 0.0
        self._last_end = -np.inf

    def add(self, t: float, out_deg: float, seconds: float) -> None:
        # A move sent before the one before has ended starts where that one ends.
        start = max(t, self._last_end)
        end = start + max(seconds, 1e-3)
        self._knots.append(np.array([[start, self.total], [end, self.total + out_deg]]))
        self._moves.append(np.array([[t, out_deg, seconds]]))
        self.total += out_deg
        self._last_end = end

    def at(self, t: Any) -> Any:
        knots = self._knots.view()
        if not len(knots):
            return np.zeros_like(np.asarray(t, dtype=float))
        return np.interp(t, knots[:, 0], knots[:, 1], left=knots[0, 1], right=knots[-1, 1])

    def moves(self) -> np.ndarray:
        return self._moves.view()

    def trim(self, before: float) -> None:
        knots = self._knots.view()
        # Keep one knot before the cut, so the turn at the window's start stays known.
        self._knots.dropFirst(int(np.searchsorted(knots[:, 0], before)) - 1)
        moves = self._moves.view()
        self._moves.dropFirst(int(np.searchsorted(moves[:, 0], before)))


@dataclass
class Channel:
    ch: int
    t: np.ndarray
    frame: np.ndarray
    deg: np.ndarray
    sec: np.ndarray
    zone: np.ndarray
    box: np.ndarray
    tid: np.ndarray
    color: np.ndarray
    rho: np.ndarray
    size: np.ndarray
    aspect: np.ndarray
    frame_t: np.ndarray
    frame_n: np.ndarray

    def __len__(self) -> int:
        return len(self.t)


@dataclass
class Tracklets:
    ch: int
    of: np.ndarray
    n: int
    first: np.ndarray
    last: np.ndarray
    count: np.ndarray
    members: list[np.ndarray]
    flow: np.ndarray
    # Each tracklet's id in the stream: it stays the same from one window to the next.
    ids: np.ndarray


@dataclass
class Window:
    meta: dict[str, Any]
    ch: dict[int, Channel]
    tls: dict[int, Tracklets]
    moves: dict[int, np.ndarray]
    now: float
    # Per channel: a tracklet whose last detection is before this time has ended (nothing can join it any more).
    ended_before: dict[int, float]
    _stream: "Stream"

    def odometer(self, ch: int, t: Any) -> Any:
        return self._stream.odometer(ch, t)

    def tracksOf(self, piece_uuid: str) -> list[int]:
        return list(self._stream.piece_tracks.get(piece_uuid, ()))


def moveSeconds(out_deg: float, speed: float, accel: float) -> float:
    d = abs(out_deg)
    if d <= 0 or speed <= 0:
        return 0.0
    if accel <= 0:
        return d / speed
    if d >= speed * speed / accel:
        return d / speed + speed / accel
    return 2.0 * (d / accel) ** 0.5


def gearRatios(meta: dict[str, Any]) -> dict[int, float]:
    base = float(meta.get("channel_output_gear_ratio") or 1.0)
    per = meta.get("channel_output_gear_ratios") or {}
    return {ch: float(per.get(str(ch), base)) for ch in (1, 2, 3, 4)}


def moveSpeeds(meta: dict[str, Any], ratio: dict[int, float]) -> dict[int, float]:
    cfg = meta.get("pulse_perception_config") or {}
    c4 = meta.get("classification_channel_config") or {}
    usteps = {
        1: cfg.get("ch1_move_speed_usteps_per_s"),
        2: cfg.get("ch2_move_speed_usteps_per_s"),
        3: cfg.get("ch3_move_speed_usteps_per_s"),
        4: c4.get("rotate_speed_usteps_per_s"),
    }
    return {ch: (float(u) * MOTOR_DEG_PER_USTEP / ratio[ch] if u else 45.0) for ch, u in usteps.items()}


def ringGeometry(meta: dict[str, Any], ch: int) -> Optional[tuple[tuple[float, float], float, float, Any]]:
    # Newer code writes `zones`, older `channel_polygons.arc_params`.
    zone = (meta.get("zones") or {}).get(str(ch))
    if zone and zone.get("center") and zone.get("outer_radius"):
        return tuple(zone["center"]), float(zone.get("inner_radius") or 0.0), float(zone["outer_radius"]), zone.get("frame")
    arc = (((meta.get("channel_polygons") or {}).get("arc_params")) or {}).get(ARC_NAME[ch]) or {}
    if arc.get("center") and arc.get("outer_radius"):
        return tuple(arc["center"]), float(arc.get("inner_radius") or 0.0), float(arc["outer_radius"]), arc.get("resolution")
    return None


class _ChannelLog:
    def __init__(self, ch: int) -> None:
        self.ch = ch
        self.dets = Rows(17, 8192)
        self.frames = Rows(3, 4096)
        self.frame_count = 0
        self.first_frame = 0
        self.last_t = -np.inf
        self.tracker = ChannelTracker()


class Stream:
    def __init__(self, window_s: float = WINDOW_S) -> None:
        self.window_s = window_s
        self.meta: dict[str, Any] = {}
        self.frame_size: dict[int, tuple[int, int]] = {}
        self.logs = {ch: _ChannelLog(ch) for ch in CHANNELS}
        self.odo = {ch: Odometer() for ch in (1, 2, 3, 4)}
        self.piece_tracks: dict[str, list[int]] = {}
        self._piece_t: dict[str, float] = {}
        self.now = 0.0
        self.records = 0
        self._ratio = gearRatios({})
        self._speeds = moveSpeeds({}, self._ratio)
        self._sign = 1.0
        self._since_trim = 0

    def setMeta(self, meta: dict[str, Any]) -> None:
        self.meta = meta
        self._ratio = gearRatios(meta)
        self._speeds = moveSpeeds(meta, self._ratio)
        cfg = meta.get("pulse_perception_config") or {}
        self._sign = 1.0 if float(cfg.get("forward_direction_sign", 1) or 1) >= 0 else -1.0

    def odometer(self, ch: int, t: Any) -> Any:
        turned = self.odo[ch].at(t)
        # The carousel's forward is the way it carries pieces to its exit,
        # which is most of what it turns: read its sign from what it has done.
        return -turned if ch == 4 and self.odo[4].total < 0 else turned

    def ingest(self, r: dict[str, Any]) -> None:
        kind = r.get("type")
        self.records += 1
        if kind == "state":
            self._state(r)
        elif kind == "cmd":
            if r.get("cmd") == "move_steps" and r.get("success", True) and r.get("stepper") in STEPPER_CHANNEL:
                ch = STEPPER_CHANNEL[r["stepper"]]
                out = float(r.get("deg") or 0.0) / self._ratio[ch]
                if ch != 4:
                    out *= self._sign
                accel = float(r.get("accel") or 0.0) * MOTOR_DEG_PER_USTEP / self._ratio[ch]
                self.odo[ch].add(float(r["t"]), out, moveSeconds(out, self._speeds[ch], accel))
        elif kind == "event":
            if r.get("kind") == "c4_piece" and "track" in r and r.get("piece"):
                tracks = self.piece_tracks.setdefault(str(r["piece"]), [])
                if int(r["track"]) not in tracks:
                    tracks.append(int(r["track"]))
                self._piece_t[str(r["piece"])] = float(r.get("t") or self.now)
        elif kind == "frame_info":
            self.frame_size[int(r["ch"])] = (int(r["w"]), int(r["h"]))
        elif kind == "meta":
            self.setMeta(r)

    def _state(self, r: dict[str, Any]) -> None:
        log = self.logs.get(r.get("ch"))
        if log is None:
            return
        ts = float(r["ts"])
        if ts <= log.last_t:
            return
        log.last_t = ts
        self.now = max(self.now, ts)
        pieces = r.get("pieces") or ()
        n = len(pieces)
        rows = np.empty((n, 17))
        for k, p in enumerate(pieces):
            deg, sec, zone, x1, y1, x2, y2, tid = p[:8]
            col = p[8] if len(p) > 8 and p[8] else (np.nan, np.nan, np.nan)
            rows[k, :13] = (
                ts, log.frame_count, np.nan if deg is None else deg, -1 if sec is None else sec, zone or 0,
                x1, y1, x2, y2, -1 if tid is None else tid, col[0], col[1], col[2],
            )
        if n:
            w = np.maximum(rows[:, X2] - rows[:, X1], 1.0)
            h = np.maximum(rows[:, Y2] - rows[:, Y1], 1.0)
            ring = ringGeometry(self.meta, log.ch)
            fs = self.frame_size.get(log.ch)
            outer = None
            if ring is not None:
                (cx, cy), inner, outer, res = ring
                # The ring is drawn at one resolution; frames may come at another.
                sx = fs[0] / res[0] if res and fs and res[0] else 1.0
                sy = fs[1] / res[1] if res and fs and res[1] else 1.0
                mx = (rows[:, X1] + rows[:, X2]) / 2.0 / sx
                my = (rows[:, Y1] + rows[:, Y2]) / 2.0 / sy
                rows[:, RHO] = (np.hypot(mx - cx, my - cy) - inner) / max(outer - inner, 1.0)
                w, h = w / sx, h / sy
            else:
                rows[:, RHO] = np.nan
            scale = outer if outer else ((fs or (1280, 720))[1] * 0.9)
            rows[:, SIZE] = np.sqrt(w * h) / scale
            rows[:, ASPECT] = w / h
        ids, flow = log.tracker.step(
            ts,
            float(self.odometer(log.ch, ts)),
            np.where(np.isnan(rows[:, DEG]), 0.0, rows[:, DEG]),
            np.where(np.isnan(rows[:, RHO]), 0.5, rows[:, RHO]),
            rows[:, C0 : C2 + 1],
            np.log(np.maximum(rows[:, SIZE], 1e-4)),
            rows[:, ZONE] == ZONE_DROP,
        )
        rows[:, OF] = ids
        if n:
            log.dets.append(rows)
        log.frames.append(np.array([[ts, n, flow]]))
        log.frame_count += 1
        self._since_trim += 1
        if self._since_trim >= TRIM_EVERY_FRAMES:
            self._since_trim = 0
            self.trim()

    def trim(self) -> None:
        cut = self.now - self.window_s
        for log in self.logs.values():
            frames = log.frames.view()
            k = int(np.searchsorted(frames[:, FRAME_T], cut))
            if k <= 0:
                continue
            log.frames.dropFirst(k)
            log.first_frame += k
            dets = log.dets.view()
            log.dets.dropFirst(int(np.searchsorted(dets[:, FRAME], log.first_frame)))
        for odo in self.odo.values():
            odo.trim(cut)
        for piece in [p for p, t in self._piece_t.items() if t < cut]:
            self._piece_t.pop(piece, None)
            self.piece_tracks.pop(piece, None)

    def window(self) -> Window:
        channels: dict[int, Channel] = {}
        tracklets: dict[int, Tracklets] = {}
        for ch, log in self.logs.items():
            d = log.dets.view()
            f = log.frames.view()
            channels[ch] = Channel(
                ch=ch,
                t=d[:, T],
                frame=d[:, FRAME].astype(np.int64) - log.first_frame,
                deg=d[:, DEG],
                sec=d[:, SEC].astype(np.int64),
                zone=d[:, ZONE].astype(np.int64),
                box=d[:, X1 : Y2 + 1],
                tid=d[:, TID].astype(np.int64),
                color=d[:, C0 : C2 + 1],
                rho=d[:, RHO],
                size=d[:, SIZE],
                aspect=d[:, ASPECT],
                frame_t=f[:, FRAME_T],
                frame_n=f[:, FRAME_N].astype(np.int64),
            )
            ids, of = np.unique(d[:, OF].astype(np.int64), return_inverse=True)
            order = np.argsort(of, kind="stable")
            bounds = np.searchsorted(of[order], np.arange(len(ids) + 1))
            members = [order[bounds[k] : bounds[k + 1]] for k in range(len(ids))]
            tracklets[ch] = Tracklets(
                ch=ch,
                of=of,
                n=len(ids),
                first=np.array([m[0] for m in members], dtype=np.int64),
                last=np.array([m[-1] for m in members], dtype=np.int64),
                count=np.array([len(m) for m in members], dtype=np.int64),
                members=members,
                flow=f[:, FRAME_FLOW],
                ids=ids,
            )
        moves = {ch: odo.moves() for ch, odo in self.odo.items()}
        if self.odo[4].total < 0:
            flipped = moves[4].copy()
            flipped[:, 1] *= -1.0
            moves[4] = flipped
        # By the stream's clock, not the channel's own: an emptied channel records no more frames.
        ended_before = {ch: self.now - log.tracker.max_gap - CLOCK_SLACK_S for ch, log in self.logs.items()}
        return Window(
            meta=self.meta, ch=channels, tls=tracklets, moves=moves, now=self.now, ended_before=ended_before, _stream=self
        )
