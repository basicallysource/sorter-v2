"""Mock USB-serial bus. Single lock — same shape as live `TickBus`.

NO fake sleeps. The live bus takes ~5ms per call because it actually round-
trips to a Pico over USB serial; this bench has no Pico, so the call returns
immediately after the lock is acquired. The lock contention from multiple
writers is the only faithful concurrency property and that's what we keep.

Bus time is NOT the bottleneck in live code anyway (~5ms × ~5 calls per
coordinator tick = 25ms out of 590ms total = 4%). Modelling it as zero-cost
doesn't change the bottleneck story; modelling it as 5ms would falsify the
GIL/contention measurement by mixing wall-clock sleep into the comparison.
"""
from __future__ import annotations

import threading
import time

from .metrics import Metrics


class MockBus:
    def __init__(self, command_ms: float, metrics: Metrics) -> None:
        self._lock = threading.Lock()
        self._command_ms = command_ms  # retained for config logging only
        self._metrics = metrics
        self._count = 0

    def send(self, name: str) -> None:
        t0 = time.perf_counter()
        with self._lock:
            self._count += 1
        self._metrics.observe(f"bus.{name}_ms", (time.perf_counter() - t0) * 1000.0)
        self._metrics.hit(f"bus.{name}.calls")

    @property
    def count(self) -> int:
        return self._count
