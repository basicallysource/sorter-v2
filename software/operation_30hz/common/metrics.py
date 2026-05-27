from __future__ import annotations

import json
import threading
import time
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Dict, List


@dataclass
class _Series:
    values: List[float] = field(default_factory=list)
    counts: int = 0

    def add(self, v: float) -> None:
        self.values.append(v)
        self.counts += 1


class Metrics:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._series: Dict[str, _Series] = defaultdict(_Series)
        self._counters: Dict[str, int] = defaultdict(int)
        self._thread_counters: Dict[str, Dict[str, int]] = defaultdict(lambda: defaultdict(int))
        self._started_at = time.perf_counter()

    def observe(self, name: str, value_ms: float) -> None:
        with self._lock:
            self._series[name].add(value_ms)

    def hit(self, name: str) -> None:
        with self._lock:
            self._counters[name] += 1

    def hit_by_thread(self, name: str) -> None:
        tname = threading.current_thread().name
        with self._lock:
            self._thread_counters[name][tname] += 1

    def snapshot(self) -> dict:
        with self._lock:
            elapsed = time.perf_counter() - self._started_at
            out_series = {}
            for n, s in self._series.items():
                v = sorted(s.values)
                if not v:
                    continue
                out_series[n] = {
                    "count": len(v),
                    "avg_ms": sum(v) / len(v),
                    "p50_ms": v[len(v) // 2],
                    "p90_ms": v[int(len(v) * 0.9)],
                    "max_ms": v[-1],
                    "min_ms": v[0],
                }
            out_counters = dict(self._counters)
            out_thread = {k: dict(v) for k, v in self._thread_counters.items()}
            return {
                "elapsed_s": elapsed,
                "series": out_series,
                "counters": out_counters,
                "thread_counters": out_thread,
            }

    def dump(self, path: str) -> None:
        with open(path, "w") as f:
            json.dump(self.snapshot(), f, indent=2, default=str)


class Timer:
    __slots__ = ("metrics", "name", "started")

    def __init__(self, metrics: Metrics, name: str) -> None:
        self.metrics = metrics
        self.name = name
        self.started = 0.0

    def __enter__(self) -> "Timer":
        self.started = time.perf_counter()
        return self

    def __exit__(self, *exc) -> None:
        self.metrics.observe(self.name, (time.perf_counter() - self.started) * 1000.0)
