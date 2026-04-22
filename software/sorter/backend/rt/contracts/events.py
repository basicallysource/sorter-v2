from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Protocol


@dataclass(frozen=True, slots=True)
class Event:
    """Typed envelope on the EventBus. `payload` is topic-specific."""

    topic: str
    payload: dict[str, Any]
    source: str
    ts_mono: float


class Subscription(Protocol):
    """Handle returned by EventBus.subscribe; call unsubscribe to detach."""

    def unsubscribe(self) -> None: ...


class EventBus(Protocol):
    """In-process, topic-glob pub/sub with dedicated dispatcher thread."""

    def publish(self, event: Event) -> None: ...

    def subscribe(
        self, topic_glob: str, handler: Callable[[Event], None]
    ) -> Subscription: ...

    def drain(self) -> None: ...

    def start(self) -> None: ...

    def stop(self) -> None: ...
