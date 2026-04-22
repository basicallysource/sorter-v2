from __future__ import annotations

import time

from rt.contracts.events import Event
from rt.events.bus import InProcessEventBus


def _event(topic: str, payload: dict | None = None) -> Event:
    return Event(
        topic=topic,
        payload=payload or {},
        source="test",
        ts_mono=time.monotonic(),
    )


def test_subscribe_publish_receive_via_drain() -> None:
    bus = InProcessEventBus()
    received: list[Event] = []

    bus.subscribe("piece.registered", received.append)
    bus.publish(_event("piece.registered", {"uuid": "abc"}))

    bus.drain()

    assert len(received) == 1
    assert received[0].topic == "piece.registered"
    assert received[0].payload == {"uuid": "abc"}


def test_glob_subscription_matches_prefix() -> None:
    bus = InProcessEventBus()
    piece_events: list[Event] = []
    all_events: list[Event] = []

    bus.subscribe("piece.*", piece_events.append)
    bus.subscribe("*", all_events.append)

    bus.publish(_event("piece.registered"))
    bus.publish(_event("piece.classified"))
    bus.publish(_event("system.hardware_state"))

    bus.drain()

    assert len(piece_events) == 2
    assert {e.topic for e in piece_events} == {"piece.registered", "piece.classified"}
    assert len(all_events) == 3


def test_unsubscribe_stops_delivery() -> None:
    bus = InProcessEventBus()
    received: list[Event] = []

    sub = bus.subscribe("piece.*", received.append)
    bus.publish(_event("piece.registered"))
    bus.drain()

    assert len(received) == 1

    sub.unsubscribe()
    bus.publish(_event("piece.classified"))
    bus.drain()

    assert len(received) == 1
