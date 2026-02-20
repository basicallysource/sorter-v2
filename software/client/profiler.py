import time
import threading
import atexit
from dataclasses import dataclass
from typing import Optional

DEFAULT_REPORT_INTERVAL_S = 5.0
DEFAULT_TOP_N = 12


@dataclass
class DurationStat:
    count: int = 0
    total_ms: float = 0.0
    max_ms: float = 0.0
    last_ms: float = 0.0


@dataclass
class CounterStat:
    count: int = 0


@dataclass
class ValueStat:
    count: int = 0
    total: float = 0.0
    max_value: float = 0.0
    last_value: float = 0.0


@dataclass
class IntervalStat:
    count: int = 0
    total_ms: float = 0.0
    max_ms: float = 0.0
    last_ms: float = 0.0


class _TimerContext:
    def __init__(self, profiler: "Profiler", name: str):
        self.profiler = profiler
        self.name = name
        self.start: Optional[float] = None

    def __enter__(self):
        self.start = time.perf_counter()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self.start is None:
            return
        elapsed_ms = (time.perf_counter() - self.start) * 1000
        self.profiler.observeDuration(self.name, elapsed_ms)


class Profiler:
    def __init__(
        self,
        enabled: bool,
        report_interval_s: float = DEFAULT_REPORT_INTERVAL_S,
        top_n: int = DEFAULT_TOP_N,
    ):
        self.enabled = enabled
        self.report_interval_s = report_interval_s
        self.top_n = top_n

        self._lock = threading.Lock()
        self._durations: dict[str, DurationStat] = {}
        self._counters: dict[str, CounterStat] = {}
        self._values: dict[str, ValueStat] = {}
        self._intervals: dict[str, IntervalStat] = {}
        self._last_mark_s: dict[str, float] = {}
        self._state_start_s: dict[str, float] = {}
        self._state_name: dict[str, str] = {}
        self._active_timers: dict[tuple[str, str], float] = {}

        self._running = False
        self._report_thread: Optional[threading.Thread] = None

        if self.enabled:
            self._running = True
            self._report_thread = threading.Thread(
                target=self._reportLoop,
                daemon=True,
            )
            self._report_thread.start()
            atexit.register(self.stop)

    def timer(self, name: str) -> _TimerContext:
        return _TimerContext(self, name)

    def startTimer(self, name: str, key: str = "") -> None:
        if not self.enabled:
            return
        thread_id = threading.get_ident()
        timer_key = (f"{thread_id}:{name}", key)
        with self._lock:
            self._active_timers[timer_key] = time.perf_counter()

    def endTimer(self, name: str, key: str = "") -> None:
        if not self.enabled:
            return
        thread_id = threading.get_ident()
        timer_key = (f"{thread_id}:{name}", key)
        with self._lock:
            start = self._active_timers.pop(timer_key, None)
        if start is None:
            return
        elapsed_ms = (time.perf_counter() - start) * 1000
        self.observeDuration(name, elapsed_ms)

    def observeDuration(self, name: str, elapsed_ms: float) -> None:
        if not self.enabled:
            return
        with self._lock:
            stat = self._durations.get(name)
            if stat is None:
                stat = DurationStat()
                self._durations[name] = stat
            stat.count += 1
            stat.total_ms += elapsed_ms
            stat.last_ms = elapsed_ms
            if elapsed_ms > stat.max_ms:
                stat.max_ms = elapsed_ms

    def hit(self, name: str, count: int = 1) -> None:
        if not self.enabled:
            return
        with self._lock:
            stat = self._counters.get(name)
            if stat is None:
                stat = CounterStat()
                self._counters[name] = stat
            stat.count += count

    def observeValue(self, name: str, value: float) -> None:
        if not self.enabled:
            return
        with self._lock:
            stat = self._values.get(name)
            if stat is None:
                stat = ValueStat()
                self._values[name] = stat
            stat.count += 1
            stat.total += value
            stat.last_value = value
            if value > stat.max_value:
                stat.max_value = value

    def mark(self, name: str) -> None:
        if not self.enabled:
            return
        now_s = time.perf_counter()
        with self._lock:
            prev_s = self._last_mark_s.get(name)
            self._last_mark_s[name] = now_s
            if prev_s is None:
                return
            interval_ms = (now_s - prev_s) * 1000
            stat = self._intervals.get(name)
            if stat is None:
                stat = IntervalStat()
                self._intervals[name] = stat
            stat.count += 1
            stat.total_ms += interval_ms
            stat.last_ms = interval_ms
            if interval_ms > stat.max_ms:
                stat.max_ms = interval_ms

    def enterState(self, group: str, state: str) -> None:
        if not self.enabled:
            return
        now_s = time.perf_counter()
        with self._lock:
            prev_state = self._state_name.get(group)
            prev_start = self._state_start_s.get(group)
            if prev_state is not None and prev_start is not None:
                elapsed_ms = (now_s - prev_start) * 1000
                self._addDurationUnlocked(
                    f"state_duration_ms.{group}.{prev_state}", elapsed_ms
                )
            self._state_name[group] = state
            self._state_start_s[group] = now_s
            self._addCounterUnlocked(f"state_entry_count.{group}.{state}", 1)
            if prev_state is not None and prev_state != state:
                self._addCounterUnlocked(
                    f"state_transition_count.{group}.{prev_state}->{state}", 1
                )

    def exitState(self, group: str) -> None:
        if not self.enabled:
            return
        now_s = time.perf_counter()
        with self._lock:
            prev_state = self._state_name.get(group)
            prev_start = self._state_start_s.get(group)
            if prev_state is None or prev_start is None:
                return
            elapsed_ms = (now_s - prev_start) * 1000
            self._addDurationUnlocked(
                f"state_duration_ms.{group}.{prev_state}", elapsed_ms
            )
            del self._state_name[group]
            del self._state_start_s[group]

    def _addDurationUnlocked(self, name: str, elapsed_ms: float) -> None:
        stat = self._durations.get(name)
        if stat is None:
            stat = DurationStat()
            self._durations[name] = stat
        stat.count += 1
        stat.total_ms += elapsed_ms
        stat.last_ms = elapsed_ms
        if elapsed_ms > stat.max_ms:
            stat.max_ms = elapsed_ms

    def _addCounterUnlocked(self, name: str, count: int) -> None:
        stat = self._counters.get(name)
        if stat is None:
            stat = CounterStat()
            self._counters[name] = stat
        stat.count += count

    def _reportLoop(self) -> None:
        while self._running:
            time.sleep(self.report_interval_s)
            if not self._running:
                break
            report = self.getReport()
            if report:
                print(report)

    def getReport(self) -> str:
        if not self.enabled:
            return ""

        with self._lock:
            durations = list(self._durations.items())
            counters = list(self._counters.items())
            values = list(self._values.items())
            intervals = list(self._intervals.items())

        durations.sort(key=lambda kv: kv[1].total_ms, reverse=True)
        counters.sort(key=lambda kv: kv[1].count, reverse=True)
        values.sort(key=lambda kv: kv[1].total, reverse=True)
        intervals.sort(key=lambda kv: kv[1].total_ms, reverse=True)

        lines: list[str] = []
        lines.append("\n" + "=" * 80)
        lines.append("PROFILER REPORT")
        lines.append("=" * 80)

        lines.append("Top durations (by total ms):")
        for name, stat in durations[: self.top_n]:
            avg_ms = stat.total_ms / stat.count if stat.count > 0 else 0.0
            lines.append(
                f"  {name}: count={stat.count} total={stat.total_ms:.1f}ms avg={avg_ms:.1f}ms max={stat.max_ms:.1f}ms last={stat.last_ms:.1f}ms"
            )

        lines.append("Top counters:")
        for name, stat in counters[: self.top_n]:
            lines.append(f"  {name}: count={stat.count}")

        lines.append("Top observed values:")
        for name, stat in values[: self.top_n]:
            avg_value = stat.total / stat.count if stat.count > 0 else 0.0
            lines.append(
                f"  {name}: count={stat.count} avg={avg_value:.2f} max={stat.max_value:.2f} last={stat.last_value:.2f}"
            )

        lines.append("Top intervals:")
        for name, stat in intervals[: self.top_n]:
            avg_ms = stat.total_ms / stat.count if stat.count > 0 else 0.0
            lines.append(
                f"  {name}: count={stat.count} avg={avg_ms:.1f}ms max={stat.max_ms:.1f}ms last={stat.last_ms:.1f}ms"
            )

        lines.append("=" * 80 + "\n")
        return "\n".join(lines)

    def stop(self) -> None:
        if not self.enabled:
            return
        self._running = False
