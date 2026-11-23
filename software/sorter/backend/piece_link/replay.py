"""Run the live linker over recorded control data, as if it were happening now.

    python -m piece_link.replay MODEL_DIR SEGMENT.jsonl.gz [...] [--after 1.0] [--min-p 0.9] [--store] [--hindsight]

Feeds a segment's records in the order they were written and, `--after`
seconds after each piece is first seen on the classification channel (about
when it is classified), asks for its C2 and C3 tracklets exactly as the running
machine would: only what was recorded by then is known. Prints one line a
piece and a summary with the time each answer took on this computer.

`--store` looks the tracklets' crops up in this machine's own crop store
(recent segments only: the store is capped). `--hindsight` also links each
piece once more with the whole segment known, and counts how often the answer
given at the time already held every tracklet of that one.
"""

from __future__ import annotations

import argparse
import gzip
import json
import time
from pathlib import Path
from typing import Any, Callable, Iterator, Optional

import numpy as np

from .journey import MULTI_P, Journey
from .live import NODE_WINDOW_S, LiveLinker, _Request
from .model import LinkModel
from .record import Stream


def readRecords(path: Path) -> Iterator[dict[str, Any]]:
    opener = gzip.open if path.name.endswith(".gz") else open
    with opener(path, "rt") as handle:
        for line in handle:
            try:
                record = json.loads(line)
            except ValueError:
                continue
            if isinstance(record, dict):
                yield record


class _Log:
    def warning(self, message: str) -> None:
        print(message)

    info = error = debug = warning


class _Gc:
    logger = _Log()


def sureTracklets(journey: Journey, walk: list[tuple[int, float]], min_p: float) -> set[tuple[int, int]]:
    nd = journey.nd
    out = set()
    for node, p in walk[1:]:
        if p < min_p:
            break
        if journey.multi[node] < MULTI_P:
            out.add((int(nd.ch[node]), int(nd.gid[node])))
    return out


RowsOf = Callable[[int, float, float], list[dict[str, Any]]]


def noRows(channel: int, t0: float, t1: float) -> list[dict[str, Any]]:
    return []


def replaySegment(
    model: LinkModel,
    path: Path,
    after_s: float,
    min_p: float,
    rows_of: Optional[RowsOf] = noRows,
    hindsight: bool = False,
) -> list[dict[str, Any]]:
    """`rows_of` lists a channel's stored crop rows in a time range; None
    reads this machine's crop store."""
    linker = LiveLinker(_Gc(), model, "replay")
    linker.rows_of = rows_of
    whole = Stream(window_s=float("inf")) if hindsight else None
    due: list[tuple[float, str]] = []
    seen: set[str] = set()
    pieces: list[dict[str, Any]] = []
    at_the_time: dict[str, set[tuple[int, int]]] = {}

    def ask(piece: str) -> None:
        request = _Request(piece, linker._stream.now, min_p)
        linker._answer(request)
        stats = linker.stats()
        row = dict(stats["last"] or {})
        row["ms"] = stats["last_ms"]
        row["asked"] = stats["last_asked"]
        pieces.append(row)
        if whole is not None:
            win = linker._stream.window()
            journey = Journey(win, model, linker._kept, since=win.now - NODE_WINDOW_S)
            at_the_time[piece] = sureTracklets(journey, journey.pieceWalk(win.tracksOf(piece)), min_p)

    for record in readRecords(path):
        t = float(record.get("t") or 0.0)
        while due and due[0][0] <= t:
            ask(due.pop(0)[1])
        linker._stream.ingest(record)
        if whole is not None:
            whole.ingest(record)
        if record.get("type") == "event" and record.get("kind") == "c4_piece" and record.get("piece"):
            piece = str(record["piece"])
            if piece not in seen:
                seen.add(piece)
                due.append((t + after_s, piece))
            # The running linker brings its answers up to date when a piece lands.
            linker._warm_wanted = True
            linker._maybeWarm()
    for _, piece in due:
        ask(piece)
    if whole is not None:
        win = whole.window()
        journey = Journey(win, model)
        for row in pieces:
            later = sureTracklets(journey, journey.pieceWalk(win.tracksOf(row["piece"])), min_p)
            now = at_the_time.get(row["piece"], set())
            row["later"] = len(later)
            row["same"] = now == later
            row["missed"] = len(later - now)
            row["extra"] = len(now - later)
    return pieces


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("model")
    ap.add_argument("segments", nargs="+")
    ap.add_argument("--after", type=float, default=1.0)
    ap.add_argument("--min-p", type=float, default=0.9)
    ap.add_argument("--store", action="store_true")
    ap.add_argument("--hindsight", action="store_true")
    ap.add_argument("--quiet", action="store_true")
    ap.add_argument("--save")
    args = ap.parse_args()
    model = LinkModel(Path(args.model))
    every: list[dict[str, Any]] = []
    for name in args.segments:
        started = time.perf_counter()
        pieces = replaySegment(model, Path(name), args.after, args.min_p, None if args.store else noRows, args.hindsight)
        took = time.perf_counter() - started
        every += pieces
        if not args.quiet:
            for row in pieces:
                line = (
                    f"  {str(row.get('piece'))[:8]} tracks {row.get('tracks')} steps {row.get('steps', 0):2} "
                    f"tracklets C3 {row.get('c3_tracklets', 0):2} C2 {row.get('c2_tracklets', 0):2} "
                    f"crops C3 {row.get('c3_crops', 0):2} C2 {row.get('c2_crops', 0):2} handed {row.get('handed', 0):2} "
                    f"{row['ms']:6.0f} ms ({row['asked']} asked)"
                )
                if "same" in row:
                    line += f" | later {row['later']}, missed {row['missed']}, extra {row['extra']}"
                print(line)
        print(f"{Path(name).name}: {len(pieces)} pieces in {took:.1f} s")
    if not every:
        return
    ms = np.array([row["ms"] for row in every])
    c3 = np.array([row.get("c3_tracklets", 0) for row in every])
    c2 = np.array([row.get("c2_tracklets", 0) for row in every])
    print(
        f"{len(every)} pieces: followed into C3 {np.mean(c3 > 0):.0%}, into C2 {np.mean(c2 > 0):.0%} at {args.min_p}; "
        f"an answer takes {np.median(ms):.0f} ms (median), {np.quantile(ms, 0.95):.0f} ms (95%), {ms.max():.0f} ms (longest)"
    )
    if args.store:
        k3 = np.array([row.get("c3_crops", 0) for row in every])
        k2 = np.array([row.get("c2_crops", 0) for row in every])
        print(
            f"stored crops a piece: C3 median {np.median(k3):.0f}, C2 median {np.median(k2):.0f}; 8 or more from C3 "
            f"{np.mean(k3 >= 8):.0%}, 4 or more from C2 {np.mean(k2 >= 4):.0%}, both {np.mean((k3 >= 8) & (k2 >= 4)):.0%}"
        )
    if args.hindsight:
        with_later = [row for row in every if row.get("later")]
        if with_later:
            print(
                f"of {len(with_later)} pieces linked with the whole segment known: the answer at the time was the same "
                f"for {np.mean([row['same'] for row in with_later]):.0%}, missed tracklets for "
                f"{np.mean([row['missed'] > 0 for row in with_later]):.0%}, held other tracklets for "
                f"{np.mean([row['extra'] > 0 for row in with_later]):.0%}"
            )
    if args.save:
        Path(args.save).write_text(json.dumps(every))


if __name__ == "__main__":
    main()
