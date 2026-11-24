"""The live linker: one thread that follows the control data as it is recorded
and, asked about a piece on the classification channel, answers with the stored
C2 and C3 crops that show it.

control_data_store hands every record it writes to `offer` (a queue put, under
its write lock). The thread turns them into tracklets as they come, keeps the
model's answers warm between pieces, and serves requests in the order they were
posted among the records, so an answer reflects exactly what had been recorded
when it was asked. Nothing here touches hardware or the control loop; a caller
that gets no answer in time carries on without one.
"""

from __future__ import annotations

import queue
import threading
import time
from pathlib import Path
from typing import Any, Callable, Optional

import numpy as np

from .journey import MULTI_P, Journey, Kept
from .model import LinkModel, isJourneyModel
from .record import Channel, Stream

# Tracklets seen within this long become nodes: a piece's whole ride through C2 and C3.
NODE_WINDOW_S = 480.0
# Between pieces the answers are brought up to date this often, and at once when a piece lands.
WARM_EVERY_S = 10.0
LINK_TIMEOUT_S = 1.5
MAX_QUEUE = 20000
# What one piece is handed: up to this many crops, C3's first.
C3_PICKS = 8
MAX_PICKS = 12
# A crop is cut from the detection of the same frame (to 20 ms) with the same box or the same track id.
CROP_FRAME_S = 0.02
CROP_BOX_PX = 60.0


class _Request:
    def __init__(self, piece_uuid: str, arrival_ts: float, min_p: float) -> None:
        self.piece_uuid = piece_uuid
        self.arrival_ts = arrival_ts
        self.min_p = min_p
        self.done = threading.Event()
        self.result: Optional[list[dict[str, Any]]] = None


def cropDetection(c: Channel, ts: float, tid: int, box: tuple[float, ...]) -> int:
    lo, hi = np.searchsorted(c.t, [ts - CROP_FRAME_S, ts + CROP_FRAME_S])
    best, best_d = -1, 1e9
    wanted = np.array(box, dtype=float)
    for d in range(int(lo), int(hi)):
        dist = float(np.abs(c.box[d] - wanted).sum())
        if c.tid[d] == tid:
            dist -= 1e6
        if dist < best_d:
            best, best_d = d, dist
    return best if best >= 0 and best_d < CROP_BOX_PX else -1


def spread(rows: list[dict[str, Any]], k: int) -> list[dict[str, Any]]:
    if len(rows) <= k:
        return list(rows)
    if k <= 0:
        return []
    picks = sorted(set(np.linspace(0, len(rows) - 1, k).round().astype(int).tolist()))
    return [rows[i] for i in picks]


def chooseCrops(c3: list[dict[str, Any]], c2: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Up to MAX_PICKS of a piece's crops, spread over its ride so they show
    it from different sides: C3's first (up to C3_PICKS), then C2's, then more
    of C3's when C2 has few. Within a channel the sharpest come first."""
    from_c3 = spread(c3, C3_PICKS)
    from_c2 = spread(c2, MAX_PICKS - len(from_c3))
    if len(from_c3) + len(from_c2) < MAX_PICKS:
        from_c3 = spread(c3, MAX_PICKS - len(from_c2))

    def sharpest(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return sorted(rows, key=lambda r: r.get("sharpness") or 0.0, reverse=True)

    return sharpest(from_c3) + sharpest(from_c2)


def journeyCrops(journey: Journey, walk: list[tuple[int, float]], min_p: float, rows_of: Any) -> dict[int, list[dict[str, Any]]]:
    """The stored crops cut from the walk's tracklets, by channel, oldest
    first. `rows_of(channel, t0, t1)` lists a channel's crop rows in a time
    range. A tracklet the model takes for two pieces boxed as one is walked
    through, but its crops show both, so they are left out."""
    nd = journey.nd
    chain: dict[int, float] = {}
    for node, p in walk[1:]:
        if p < min_p:
            break
        if journey.multi[node] < MULTI_P:
            chain[node] = p
    out: dict[int, list[dict[str, Any]]] = {2: [], 3: []}
    for ch in (2, 3):
        nodes = [k for k in chain if nd.ch[k] == ch]
        if not nodes:
            continue
        t0 = float(min(nd.t0[k] for k in nodes)) - CROP_FRAME_S
        t1 = float(max(nd.t1[k] for k in nodes)) + CROP_FRAME_S
        c = journey.win.ch[ch]
        for row in rows_of(ch, t0, t1):
            box = row.get("bbox")
            if row.get("ts") is None or not box or any(v is None for v in box):
                continue
            tid = row.get("track_id")
            det = cropDetection(c, float(row["ts"]), -1 if tid is None else int(tid), tuple(float(v) for v in box))
            node = journey.nodeOf(ch, det) if det >= 0 else -1
            if node in chain:
                out[ch].append({**row, "p": chain[node]})
        out[ch].sort(key=lambda r: r["ts"])
    return out


class LiveLinker:
    def __init__(self, gc: Any, model: LinkModel, local_id: str) -> None:
        self._gc = gc
        self._model = model
        self.local_id = local_id
        self._queue: "queue.SimpleQueue[Any]" = queue.SimpleQueue()
        self._stream = Stream()
        self._kept = Kept()
        # Where a channel's stored crops in a time range come from: the machine's crop store, unless set.
        self.rows_of: Optional[Callable[[int, float, float], list[dict[str, Any]]]] = None
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._loop, daemon=True, name="piece-link")
        self._last_warm = 0.0
        self._warm_wanted = False
        self._frames_at_warm = 0
        self._stats_lock = threading.Lock()
        self._stats: dict[str, Any] = {
            "records": 0, "dropped": 0, "pieces": 0, "linked": 0, "timeouts": 0, "errors": 0,
            "last_ms": None, "max_ms": 0.0, "last_asked": None, "last": None,
        }

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._queue.put(None)

    def offer(self, record: dict[str, Any]) -> None:
        if self._queue.qsize() > MAX_QUEUE:
            with self._stats_lock:
                self._stats["dropped"] += 1
            return
        self._queue.put(record)

    def link(self, piece_uuid: str, arrival_ts: float, min_p: float, timeout_s: float = LINK_TIMEOUT_S) -> Optional[list[dict[str, Any]]]:
        if not self._thread.is_alive():
            return None
        request = _Request(piece_uuid, arrival_ts, min_p)
        self._queue.put(request)
        if not request.done.wait(timeout_s):
            with self._stats_lock:
                self._stats["timeouts"] += 1
            return None
        return request.result

    def stats(self) -> dict[str, Any]:
        with self._stats_lock:
            out = dict(self._stats)
        out["model"] = self._model.name
        out["running"] = self._thread.is_alive()
        out["queue"] = self._queue.qsize()
        out["kept_answers"] = len(self._kept.answers)
        return out

    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                item = self._queue.get(timeout=1.0)
            except queue.Empty:
                item = None
            try:
                if isinstance(item, _Request):
                    self._answer(item)
                elif item is not None:
                    self._stream.ingest(item)
                    if item.get("type") == "event" and item.get("kind") == "c4_piece":
                        self._warm_wanted = True
                if self._queue.empty():
                    self._maybeWarm()
            except Exception as exc:
                with self._stats_lock:
                    self._stats["errors"] += 1
                if isinstance(item, _Request):
                    item.done.set()
                try:
                    self._gc.logger.warning(f"[link] live linker: {type(exc).__name__}: {exc}")
                except Exception:
                    pass

    def _frames(self) -> int:
        return sum(log.frame_count for log in self._stream.logs.values())

    def _journey(self) -> Journey:
        win = self._stream.window()
        return Journey(win, self._model, self._kept, since=win.now - NODE_WINDOW_S)

    def _maybeWarm(self) -> None:
        now = time.monotonic()
        frames = self._frames()
        if frames == self._frames_at_warm:
            return
        if not self._warm_wanted and now - self._last_warm < WARM_EVERY_S:
            return
        self._warm_wanted = False
        self._last_warm = now
        self._frames_at_warm = frames
        self._journey()
        with self._stats_lock:
            self._stats["records"] = self._stream.records

    def _rowsOf(self, channel: int, t0: float, t1: float) -> list[dict[str, Any]]:
        if self.rows_of is None:
            import channel_crop_store

            self.rows_of = channel_crop_store.listCropsOfChannel
        return self.rows_of(channel, t0, t1)

    def _answer(self, request: _Request) -> None:
        started = time.perf_counter()
        try:
            tracks = self._stream.piece_tracks.get(request.piece_uuid) or []
            picks: Optional[list[dict[str, Any]]] = None
            summary: dict[str, Any] = {"piece": request.piece_uuid, "tracks": tracks}
            asked = 0
            if tracks:
                journey = self._journey()
                asked = journey.asked_fresh
                walk = journey.pieceWalk(tracks)
                crops = journeyCrops(journey, walk, request.min_p, self._rowsOf)
                picks = []
                for row in chooseCrops(crops[3], crops[2]):
                    picks.append(
                        {
                            "id": row["id"],
                            "channel": row["channel"],
                            "ts": row["ts"],
                            "dt": round(request.arrival_ts - float(row["ts"]), 2),
                            "zone_code": row["zone_code"],
                            "com_forward_to_exit_deg": row["com_forward_to_exit_deg"],
                            "track_id": row["track_id"],
                            "sharpness": row["sharpness"],
                            "model_score": round(float(row["p"]), 4),
                            "model_same": True,
                        }
                    )
                nd = journey.nd
                sure = [k for k, p in walk if p >= 0.5]
                summary.update(
                    # Where the walk ends: a piece followed back to the first frame on record has no earlier ride to find.
                    from_ch=int(nd.ch[sure[-1]]) if sure else None,
                    from_t=float(nd.t0[sure[-1]]) if sure else None,
                    steps=len(walk) - 1 if walk else 0,
                    c3_tracklets=sum(1 for k, p in walk[1:] if p >= request.min_p and nd.ch[k] == 3),
                    c2_tracklets=sum(1 for k, p in walk[1:] if p >= request.min_p and nd.ch[k] == 2),
                    c3_crops=len(crops[3]),
                    c2_crops=len(crops[2]),
                    handed=len(picks),
                )
            request.result = picks
        finally:
            request.done.set()
        ms = (time.perf_counter() - started) * 1000.0
        with self._stats_lock:
            self._stats["pieces"] += 1
            self._stats["linked"] += 1 if request.result else 0
            self._stats["last_ms"] = round(ms, 1)
            self._stats["max_ms"] = round(max(self._stats["max_ms"], ms), 1)
            self._stats["last_asked"] = asked
            self._stats["last"] = summary
            self._stats["records"] = self._stream.records


_lock = threading.Lock()
_linker: Optional[LiveLinker] = None


def _stopLocked() -> None:
    global _linker
    import control_data_store

    if _linker is not None:
        control_data_store.setTap(None)
        _linker.stop()
        _linker = None


def sync(gc: Any, entry: Optional[dict[str, Any]]) -> None:
    """Run the live linker for `entry` (the installed link model the machine
    is set to use, or None), and only for a model of this kind."""
    global _linker
    import control_data_store

    wanted = entry if entry is not None and entry.get("path") and isJourneyModel(Path(str(entry["path"]))) else None
    with _lock:
        if _linker is not None and (wanted is None or wanted.get("local_id") != _linker.local_id):
            _stopLocked()
        if wanted is None or _linker is not None:
            return
        try:
            model = LinkModel(Path(str(wanted["path"])))
        except Exception as exc:
            gc.logger.error(f"[link] {wanted.get('local_id')}: cannot load: {exc}")
            return
        linker = LiveLinker(gc, model, str(wanted["local_id"]))
        linker.start()
        control_data_store.setTap(linker.offer)
        _linker = linker
        gc.logger.info(f"[link] live linker started with {model.name}")


def linkPiece(
    piece_uuid: str, arrival_ts: float, min_p: float, timeout_s: float = LINK_TIMEOUT_S
) -> Optional[list[dict[str, Any]]]:
    linker = _linker
    if linker is None:
        return None
    return linker.link(piece_uuid, arrival_ts, min_p, timeout_s)


def status() -> Optional[dict[str, Any]]:
    linker = _linker
    return linker.stats() if linker is not None else None
