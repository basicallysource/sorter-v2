"""Watching the pieces while the machine runs.

When the feeder sees the piece it pushed off a channel's exit fall, the piece
that appears on the next channel moments later is that piece landing. How long
that takes, channel by channel, sets how long the feeder holds an exit after a
fall (subsystems/feeder/pulse_perception/adapt.py): a long drop or a ramp holds
longer. The watch also keeps a picture of each channel every so often while the
machine runs, for the zone finder.

It never changes the zones. They are found in the picture or set by hand, and
someone looks at them before they are kept.
"""

from __future__ import annotations

import threading
import time
from collections import deque
from dataclasses import dataclass
from typing import Any, Deque

import cv2
import numpy as np

POLL_S = 0.1
# A track not seen for this long has ended.
TRACK_GONE_S = 0.8
# Kept this long after a track is last seen, for a fall reported late.
GONE_KEPT_S = 30.0
# A piece lands on the next channel within this long of falling off one.
HANDOFF_WINDOW_S = 4.0
HANDOFFS_KEPT = 120

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


class PieceWatch:
    def __init__(self, perception_service: Any, logger: Any = None) -> None:
        self._perception = perception_service
        self._logger = logger
        self._tracks: dict[int, dict[int, _Track]] = {2: {}, 3: {}, 4: {}}
        # Tracks no longer seen, by id, for a while: a fall reported for one.
        self._gone: dict[int, dict[int, _Track]] = {2: {}, 3: {}, 4: {}}
        # Falls the feeder saw, (channel, track id), and where each fell piece
        # was last seen once looked up.
        self._fall_reports: Deque[tuple[int, int]] = deque(maxlen=200)
        self._falls: dict[int, Deque[Sighting]] = {2: deque(maxlen=50), 3: deque(maxlen=50)}
        self._fall_count: dict[int, int] = {2: 0, 3: 0}
        self._started: dict[int, Deque[tuple[int, _Track]]] = {3: deque(maxlen=50), 4: deque(maxlen=50)}
        self._handoffs: dict[int, Deque[Handoff]] = {2: deque(maxlen=HANDOFFS_KEPT), 3: deque(maxlen=HANDOFFS_KEPT)}
        self._frames: dict[int, Deque[np.ndarray]] = {ch: deque(maxlen=FRAMES_KEPT) for ch in (2, 3, 4)}
        self._frame_at: dict[int, float] = {}
        self._last_frame_ts: dict[int, float] = {}
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._loop, daemon=True, name="piece-watch")

    def start(self) -> None:
        self._thread.start()

    def fell(self, channel: int, track_id: int) -> None:
        """The feeder saw the piece with ``track_id`` fall off ``channel``'s exit."""
        self._fall_reports.append((int(channel), int(track_id)))

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

    def report(self) -> dict[str, Any]:
        out: dict[str, Any] = {"channels": {}}
        for channel in _NEXT:
            hand = self.handoffs(channel)
            entry: dict[str, Any] = {
                "falls": self._fall_count[channel],
                "handoffs": len(hand),
                "frames": len(self.frames(channel)),
            }
            if hand:
                delays = sorted(h.delay_s for h in hand)
                entry["landing_delay_s"] = {
                    "p50": round(delays[len(delays) // 2], 3),
                    "p90": round(delays[min(len(delays) - 1, int(len(delays) * 0.9))], 3),
                }
            out["channels"][str(channel)] = entry
        out["channels"]["4"] = {"frames": len(self.frames(4))}
        return out

    # --- the loop ---------------------------------------------------------

    def _loop(self) -> None:
        while not self._stop.wait(POLL_S):
            try:
                self._tick(time.monotonic(), time.time())
            except Exception as exc:
                self._log("warning", f"[zones] piece watch tick failed: {exc}")

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
        self._resolveFalls()
        self._matchHandoffs()

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
            gone = self._gone[channel]
            for track_id in [t for t, tr in tracks.items() if now - tr.last.ts > TRACK_GONE_S]:
                gone[track_id] = tracks.pop(track_id)
            for track_id in [t for t, tr in gone.items() if now - tr.last.ts > GONE_KEPT_S]:
                del gone[track_id]

    def _resolveFalls(self) -> None:
        while self._fall_reports:
            channel, track_id = self._fall_reports.popleft()
            if channel not in self._falls:
                continue
            track = self._tracks[channel].get(track_id) or self._gone[channel].get(track_id)
            if track is not None:
                self._falls[channel].append(track.last)
                self._fall_count[channel] += 1

    def _matchHandoffs(self) -> None:
        """Pair each piece that appears on a channel with the latest piece seen
        to fall off the channel before it, within the time a piece takes to
        land. A landing waits a moment, since its fall can be confirmed after
        the next camera already sees it."""
        now = time.time()
        for channel, nxt in _NEXT.items():
            falls = self._falls[channel]
            started = self._started[nxt]
            while started:
                track = started[0][1]
                landed_at = track.first.ts
                if now - landed_at < 1.0:
                    break
                started.popleft()
                candidates = [f for f in falls if -0.5 <= landed_at - f.ts <= HANDOFF_WINDOW_S]
                if not candidates:
                    continue
                left = max(candidates, key=lambda f: f.ts)
                falls.remove(left)
                with self._lock:
                    self._handoffs[channel].append(
                        Handoff(from_channel=channel, left=left, landed=track.first, delay_s=landed_at - left.ts)
                    )
            while falls and now - falls[0].ts > HANDOFF_WINDOW_S + 5.0:
                falls.popleft()

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

    def _log(self, level: str, message: str) -> None:
        if self._logger is None:
            return
        fn = getattr(self._logger, level, None)
        if fn is not None:
            fn(message)


_watch: PieceWatch | None = None


def start(perception_service: Any, logger: Any = None) -> PieceWatch:
    global _watch
    if _watch is None:
        _watch = PieceWatch(perception_service, logger)
        _watch.start()
    return _watch


def current() -> PieceWatch | None:
    return _watch


def recentFrames(channel: int) -> list[np.ndarray]:
    return _watch.frames(channel) if _watch is not None else []


def noteFall(channel: int, track_id: int) -> None:
    if _watch is not None:
        _watch.fell(channel, track_id)
