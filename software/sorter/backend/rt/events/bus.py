from __future__ import annotations

import fnmatch
import logging
import queue
import threading
from dataclasses import dataclass
from typing import Callable

from rt.contracts.events import Event


_LOG = logging.getLogger(__name__)

_QUEUE_MAX = 2048
_POISON: object = object()


@dataclass
class _SubscriptionRecord:
    topic_glob: str
    handler: Callable[[Event], None]
    active: bool = True


class _SubscriptionHandle:
    """Opaque Subscription handle; calling unsubscribe detaches the handler."""

    def __init__(self, bus: "InProcessEventBus", record: _SubscriptionRecord) -> None:
        self._bus = bus
        self._record = record

    def unsubscribe(self) -> None:
        self._bus._detach(self._record)


class InProcessEventBus:
    """Dedicated-thread pub/sub over a bounded queue with drop-oldest policy.

    - `publish` is non-blocking; if the queue is full, the oldest event is dropped
      and the drop counter is incremented (logged periodically).
    - `subscribe` uses `fnmatch`-style topic globs (`piece.*`, `system.*`, `*`).
    - Handlers run on a single dispatcher thread (sequential ordering).
    - `drain` is for tests: processes queued events synchronously without the
      dispatcher thread running.
    """

    def __init__(self, queue_max: int = _QUEUE_MAX) -> None:
        self._queue: queue.Queue[Event | object] = queue.Queue(maxsize=queue_max)
        self._subs: list[_SubscriptionRecord] = []
        self._subs_lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self._running = False
        self._dropped = 0

    def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(
            target=self._run, name="EventBusDispatcher", daemon=True
        )
        self._thread.start()

    def stop(self) -> None:
        if not self._running:
            return
        self._running = False
        try:
            self._queue.put_nowait(_POISON)
        except queue.Full:
            try:
                self._queue.get_nowait()
            except queue.Empty:
                pass
            self._queue.put_nowait(_POISON)
        thread = self._thread
        if thread is not None:
            thread.join(timeout=2.0)
        self._thread = None

    def publish(self, event: Event) -> None:
        try:
            self._queue.put_nowait(event)
        except queue.Full:
            try:
                self._queue.get_nowait()
                self._dropped += 1
                if self._dropped % 100 == 1:
                    _LOG.warning(
                        "EventBus queue full; dropped %d events so far",
                        self._dropped,
                    )
            except queue.Empty:
                pass
            try:
                self._queue.put_nowait(event)
            except queue.Full:
                self._dropped += 1

    def subscribe(
        self, topic_glob: str, handler: Callable[[Event], None]
    ) -> _SubscriptionHandle:
        record = _SubscriptionRecord(topic_glob=topic_glob, handler=handler)
        with self._subs_lock:
            self._subs.append(record)
        return _SubscriptionHandle(self, record)

    def drain(self) -> None:
        """Test helper: synchronously dispatch all queued events."""
        while True:
            try:
                item = self._queue.get_nowait()
            except queue.Empty:
                return
            if item is _POISON:
                continue
            assert isinstance(item, Event)
            self._dispatch(item)

    def dropped_count(self) -> int:
        return self._dropped

    def _detach(self, record: _SubscriptionRecord) -> None:
        with self._subs_lock:
            record.active = False
            try:
                self._subs.remove(record)
            except ValueError:
                pass

    def _snapshot_subs(self) -> list[_SubscriptionRecord]:
        with self._subs_lock:
            return [s for s in self._subs if s.active]

    def _dispatch(self, event: Event) -> None:
        for sub in self._snapshot_subs():
            if not fnmatch.fnmatchcase(event.topic, sub.topic_glob):
                continue
            try:
                sub.handler(event)
            except Exception:
                _LOG.exception(
                    "EventBus handler for %r raised on topic %r",
                    sub.topic_glob,
                    event.topic,
                )

    def _run(self) -> None:
        while self._running:
            try:
                item = self._queue.get(timeout=0.25)
            except queue.Empty:
                continue
            if item is _POISON:
                break
            assert isinstance(item, Event)
            self._dispatch(item)


__all__ = ["InProcessEventBus"]
