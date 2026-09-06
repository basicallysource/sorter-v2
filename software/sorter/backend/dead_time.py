"""Station timeline and dead-time analysis.

Every stage of the machine (belt, C3, C4, distribution) reports what it is
doing right now as a short activity slug plus a free-text detail. The timeline
keeps run-length segments (a new one only when the activity changes) so a
window of the run can be replayed station by station.

The analysis lays the stations side by side and measures the moments where one
stage waits although another stage was idle or holding: the gaps where a part
of the process could have kept running. Each pattern names the pair of
conditions, the time it cost in the window and what the breakdown station was
doing meanwhile.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Iterable

MAX_STATION_EVENTS = 20000
SNAPSHOT_EVENTS = 400
TOP_EPISODES = 5

# C3 activities that mean "a piece is on its way to C4 but has not landed".
C3_DELIVERING = frozenset({"arm", "armed_hold", "hold", "approach", "tip", "release", "crowded_tip"})
# C3 activities where the channel holds a piece back because C4 is not ready.
C3_BLOCKED = frozenset({"armed_hold", "hold", "waiting_c4"})
# C4 activities other than "gate open, nothing on the platter".
C4_BUSY = frozenset(
    {
        "capturing", "classifying", "aiming", "waiting_successor", "ready",
        "ejecting", "staging", "settling", "aligning", "drop_blocked",
    }
)
C3_EMPTY = frozenset({"empty", "idle"})


@dataclass(frozen=True)
class Segment:
    start: float
    end: float
    activity: str
    detail: str = ""

    @property
    def seconds(self) -> float:
        return max(0.0, self.end - self.start)


@dataclass(frozen=True)
class Pattern:
    key: str
    title: str
    hint: str
    where: dict[str, frozenset[str]]
    breakdown: str | None = None

    def matches(self, activities: dict[str, str]) -> bool:
        return all(activities.get(station) in allowed for station, allowed in self.where.items())


PATTERNS: tuple[Pattern, ...] = (
    Pattern(
        "c4_starved_c3_holding",
        "C4 empty while C3 holds a piece",
        "Gate open to landing. Arming and release on C3 decide how long this takes.",
        {"c4": frozenset({"waiting_drop"}), "c3": C3_DELIVERING},
        breakdown="c3",
    ),
    Pattern(
        "c4_starved_c3_empty",
        "C4 empty while C3 is empty",
        "The feed ran dry. The belt reason tells whether the pile is empty or the belt was held.",
        {"c4": frozenset({"waiting_drop"}), "c3": C3_EMPTY},
        breakdown="belt",
    ),
    Pattern(
        "c3_waits_for_c4",
        "C3 waits for C4",
        "Serial coupling: C3 could deliver while C4 still works on the previous piece. A buffer pocket on the platter takes exactly this time out.",
        {"c3": C3_BLOCKED, "c4": C4_BUSY},
        breakdown="c4",
    ),
    Pattern(
        "c4_waits_for_chute",
        "C4 waits for the chute",
        "The head is classified but the chute is not there yet. Distribution latency sits on the critical path.",
        {"c4": frozenset({"aiming"})},
        breakdown="distribution",
    ),
    Pattern(
        "c4_lone_head_grace",
        "C4 waits for a successor that cannot come",
        "Head ready, C3 empty: the successor grace period buys nothing here, the head could leave at once.",
        {"c4": frozenset({"waiting_successor"}), "c3": C3_EMPTY},
        breakdown="belt",
    ),
    Pattern(
        "belt_gated_c4_idle",
        "Belt held back while C4 is empty",
        "C3 is the bottleneck, not the feed: the belt stops for a full C3 while C4 has nothing.",
        {"belt": frozenset({"stopped_c3_full", "throttled"}), "c4": frozenset({"waiting_drop"})},
        breakdown="c3",
    ),
    Pattern(
        "c4_classifying",
        "C4 waits for the classification",
        "Recognition latency on the critical path. Only a buffer or a faster model shortens it.",
        {"c4": frozenset({"classifying"})},
        breakdown="c3",
    ),
)


class StationTimeline:
    """Run-length recorder for station activities."""

    def __init__(self) -> None:
        self._current: dict[str, dict[str, Any]] = {}
        self._totals_s: dict[str, dict[str, float]] = {}
        self._events: list[dict[str, Any]] = []

    def observe(
        self,
        station: str,
        activity: str,
        detail: str = "",
        counting: bool = True,
        now_wall: float | None = None,
        now_monotonic: float | None = None,
    ) -> None:
        now_wall = time.time() if now_wall is None else now_wall
        now_monotonic = time.monotonic() if now_monotonic is None else now_monotonic
        current = self._current.get(station)
        if current is not None and current["activity"] == activity:
            current["detail"] = detail
            return
        if current is not None:
            self._fold(station, current, now_monotonic, counting)
        self._current[station] = {
            "activity": activity,
            "detail": detail,
            "since_wall": now_wall,
            "since_monotonic": now_monotonic,
        }
        self._events.append({"ts": now_wall, "station": station, "activity": activity, "detail": detail})
        if len(self._events) > MAX_STATION_EVENTS:
            del self._events[: len(self._events) - MAX_STATION_EVENTS]

    def foldOpen(self, counting: bool, now_monotonic: float | None = None) -> None:
        """Book the open segments up to now (call when the run pauses or resumes
        so paused time never counts as station time)."""
        now_monotonic = time.monotonic() if now_monotonic is None else now_monotonic
        for station, current in self._current.items():
            self._fold(station, current, now_monotonic, counting)

    def _fold(self, station: str, current: dict[str, Any], now_monotonic: float, counting: bool) -> None:
        if counting:
            totals = self._totals_s.setdefault(station, {})
            elapsed = max(0.0, now_monotonic - float(current["since_monotonic"]))
            totals[current["activity"]] = totals.get(current["activity"], 0.0) + elapsed
        current["since_monotonic"] = now_monotonic

    def snapshot(self, counting: bool, now_monotonic: float | None = None) -> dict[str, Any]:
        now_monotonic = time.monotonic() if now_monotonic is None else now_monotonic
        time_s: dict[str, dict[str, float]] = {}
        share_pct: dict[str, dict[str, float]] = {}
        current: dict[str, dict[str, Any]] = {}
        for station, cur in self._current.items():
            totals = dict(self._totals_s.get(station, {}))
            if counting:
                open_s = max(0.0, now_monotonic - float(cur["since_monotonic"]))
                totals[cur["activity"]] = totals.get(cur["activity"], 0.0) + open_s
            total = sum(totals.values())
            time_s[station] = totals
            share_pct[station] = {k: (v / total) * 100.0 for k, v in totals.items()} if total > 0 else {}
            current[station] = {"activity": cur["activity"], "detail": cur["detail"], "since": cur["since_wall"]}
        return {
            "current": current,
            "time_s": time_s,
            "share_pct": share_pct,
            "timeline_recent": list(self._events[-SNAPSHOT_EVENTS:]),
        }

    def segments(self, window_s: float, now_wall: float | None = None) -> dict[str, list[Segment]]:
        """Per-station segments clipped to the last ``window_s`` seconds."""
        now_wall = time.time() if now_wall is None else now_wall
        start = now_wall - float(window_s)
        per_station: dict[str, list[dict[str, Any]]] = {}
        for event in self._events:
            per_station.setdefault(str(event["station"]), []).append(event)
        out: dict[str, list[Segment]] = {}
        for station, events in per_station.items():
            segs: list[Segment] = []
            for i, event in enumerate(events):
                seg_start = float(event["ts"])
                seg_end = float(events[i + 1]["ts"]) if i + 1 < len(events) else now_wall
                if seg_end <= start or seg_start >= now_wall:
                    continue
                segs.append(
                    Segment(max(seg_start, start), min(seg_end, now_wall), str(event["activity"]), str(event.get("detail", "")))
                )
            out[station] = segs
        return out


@dataclass
class _Tally:
    seconds: float = 0.0
    episodes: int = 0
    longest_s: float = 0.0
    breakdown: dict[str, float] = field(default_factory=dict)
    top_episodes: list[dict[str, float]] = field(default_factory=list)
    _open_start: float | None = None
    _open_end: float | None = None

    def add(self, start: float, end: float, breakdown_key: str) -> None:
        self.seconds += end - start
        self.breakdown[breakdown_key] = self.breakdown.get(breakdown_key, 0.0) + (end - start)
        if self._open_end is not None and abs(self._open_end - start) < 1e-6:
            self._open_end = end
        else:
            self._closeEpisode()
            self._open_start, self._open_end = start, end

    def _closeEpisode(self) -> None:
        if self._open_start is None or self._open_end is None:
            return
        duration = self._open_end - self._open_start
        self.episodes += 1
        self.longest_s = max(self.longest_s, duration)
        self.top_episodes.append({"start": self._open_start, "end": self._open_end, "seconds": duration})
        self.top_episodes.sort(key=lambda e: -e["seconds"])
        del self.top_episodes[TOP_EPISODES:]
        self._open_start = self._open_end = None

    def finish(self) -> None:
        self._closeEpisode()


def analyze(
    segments: dict[str, list[Segment]],
    window_s: float,
    now_wall: float,
    patterns: Iterable[Pattern] = PATTERNS,
) -> dict[str, Any]:
    """Overlay the station segments and measure every pattern's share of the window."""
    window_start = now_wall - float(window_s)
    cuts = {window_start, now_wall}
    for segs in segments.values():
        for seg in segs:
            cuts.add(seg.start)
            cuts.add(seg.end)
    points = sorted(cuts)
    cursors = {station: 0 for station in segments}
    tallies = {pattern.key: _Tally() for pattern in patterns}
    station_time: dict[str, dict[str, float]] = {station: {} for station in segments}
    for a, b in zip(points, points[1:]):
        if b - a <= 0:
            continue
        mid = (a + b) / 2.0
        activities: dict[str, str] = {}
        for station, segs in segments.items():
            i = cursors[station]
            while i < len(segs) and segs[i].end <= mid:
                i += 1
            cursors[station] = i
            if i < len(segs) and segs[i].start <= mid:
                activities[station] = segs[i].activity
        for station, activity in activities.items():
            station_time[station][activity] = station_time[station].get(activity, 0.0) + (b - a)
        for pattern in patterns:
            if pattern.matches(activities):
                key = activities.get(pattern.breakdown, "n/a") if pattern.breakdown else "all"
                tallies[pattern.key].add(a, b, key)
    opportunities = []
    for pattern in patterns:
        tally = tallies[pattern.key]
        tally.finish()
        if tally.seconds <= 0:
            continue
        opportunities.append(
            {
                "key": pattern.key,
                "title": pattern.title,
                "hint": pattern.hint,
                "seconds": round(tally.seconds, 1),
                "share_pct": round(tally.seconds / float(window_s) * 100.0, 1) if window_s > 0 else 0.0,
                "episodes": tally.episodes,
                "longest_s": round(tally.longest_s, 1),
                "breakdown": {k: round(v, 1) for k, v in sorted(tally.breakdown.items(), key=lambda kv: -kv[1])},
                "top_episodes": tally.top_episodes,
            }
        )
    opportunities.sort(key=lambda o: -o["seconds"])
    stations = {
        station: {
            "time_s": {k: round(v, 1) for k, v in sorted(times.items(), key=lambda kv: -kv[1])},
            "coverage_s": round(sum(times.values()), 1),
        }
        for station, times in station_time.items()
    }
    return {
        "window_s": float(window_s),
        "now": now_wall,
        "stations": stations,
        "opportunities": opportunities,
    }
