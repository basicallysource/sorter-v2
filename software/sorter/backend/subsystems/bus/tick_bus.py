from __future__ import annotations

import time
from collections import deque
from dataclasses import asdict, is_dataclass
from enum import Enum
from typing import Any, TypeVar

from subsystems.bus.messages import ChuteMotion, Message, StationGate, StationId


TMessage = TypeVar("TMessage", bound=Message)


class TickBus:
    def __init__(self, recent_limit: int = 30) -> None:
        self._recent_limit = max(1, int(recent_limit))
        self._tick_events: list[Message] = []
        self._recent: deque[dict[str, Any]] = deque(maxlen=self._recent_limit)
        self._publish_counts: dict[str, int] = {}
        self._station_gates: dict[StationId, StationGate] = {}
        self._chute_motion: ChuteMotion | None = None
        self._tick_started_at_mono: float = 0.0

    def begin_tick(self, now_mono: float | None = None) -> None:
        self._tick_started_at_mono = (
            time.monotonic() if now_mono is None else float(now_mono)
        )
        self._tick_events = []

    def publish(self, msg: Message) -> None:
        self._tick_events.append(msg)
        message_name = type(msg).__name__
        self._publish_counts[message_name] = self._publish_counts.get(message_name, 0) + 1
        if isinstance(msg, StationGate):
            self._station_gates[msg.station] = msg
        elif isinstance(msg, ChuteMotion):
            self._chute_motion = msg
        self._recent.append(self._serialize_message(msg))

    def events(self, message_type: type[TMessage] | None = None) -> tuple[TMessage, ...] | tuple[Message, ...]:
        if message_type is None:
            return tuple(self._tick_events)
        return tuple(
            msg for msg in self._tick_events if isinstance(msg, message_type)
        )

    def station_gate(self, station: StationId) -> StationGate | None:
        return self._station_gates.get(station)

    def is_station_open(self, station: StationId, default: bool = False) -> bool:
        gate = self.station_gate(station)
        if gate is None:
            return default
        return bool(gate.open)

    def chute_motion(self) -> ChuteMotion | None:
        return self._chute_motion

    def recent(self) -> list[dict[str, Any]]:
        return list(self._recent)

    def publish_counts(self) -> dict[str, int]:
        return dict(sorted(self._publish_counts.items()))

    def _serialize_message(self, msg: Message) -> dict[str, Any]:
        payload = _serialize_value(asdict(msg) if is_dataclass(msg) else msg)
        assert isinstance(payload, dict)
        payload["type"] = type(msg).__name__
        payload["tick_started_at_mono"] = self._tick_started_at_mono
        payload["recorded_at_wall"] = time.time()
        return payload


def _serialize_value(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, dict):
        return {str(key): _serialize_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_serialize_value(item) for item in value]
    return value


__all__ = ["TickBus"]
