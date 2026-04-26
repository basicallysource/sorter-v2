"""CarouselC4Handler — Main-style sequential carousel applied to a polar C4.

Built as the analogue of ``SectionFeederHandler`` for the classification
chamber. Where Main's carousel is *physically* discrete (4 platforms,
90° lockstep rotation), our C4 is a continuous polar tray — but we
*can* treat it as a virtual carousel by walking the front piece through
a fixed sequence of angular checkpoints:

    arriving (intake) → advancing → classify (settle + snap) → await
    distributor → advancing → drop (eject) → idle

This handler only owns the **scheduling decisions**: when to pulse C4
transport, when to request a distributor handoff, when to fire the
exit eject. It deliberately does *not* own perception, classifier
submission, or piece UUID generation — those stay on the existing
RuntimeC4 path so BoxMot tracking and image collection keep working
unchanged. Operationally: ``c4_mode = "carousel"`` skips the
RuntimeC4 transport / handoff / eject decisions and lets this handler
drive instead. Default mode (``"runtime"``) keeps the legacy stack.

This is the C4 counterpart to the section feeder's "swap the decision
layer, keep BoxMot for piece UUIDs and image crops" architecture.

State machine (per cycle, single piece):

* ``IDLE`` — no piece in cycle. Wait for one.
* ``ADVANCING_TO_CLASSIFY`` — pulse transport until front piece's
  angle is within ``classify_tolerance_deg`` of ``classify_deg``.
* ``SETTLING_AT_CLASSIFY`` — hold position for ``settle_s`` so the
  classifier sees a stable frame.
* ``AWAIT_CLASSIFICATION`` — RuntimeC4's classifier finished its
  submission while we were settling; we just wait for the dossier
  to carry a result.
* ``REQUESTING_DISTRIBUTOR`` — got a result. Ask the distributor to
  position to the chosen bin.
* ``AWAIT_DISTRIBUTOR_READY`` — distributor still moving the chute.
* ``ADVANCING_TO_DROP`` — pulse transport until the piece is at
  ``drop_deg``.
* ``DROPPING`` — fire eject + commit the handoff.

The handler is intentionally small (~250 lines). It's a starting
point: live throughput tuning and multi-piece pipelining are follow-up
work, mirrored on the SectionFeederHandler progression.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Protocol


class CarouselState(str, Enum):
    IDLE = "idle"
    ADVANCING_TO_CLASSIFY = "advancing_to_classify"
    SETTLING_AT_CLASSIFY = "settling_at_classify"
    AWAIT_CLASSIFICATION = "await_classification"
    REQUESTING_DISTRIBUTOR = "requesting_distributor"
    AWAIT_DISTRIBUTOR_READY = "await_distributor_ready"
    ADVANCING_TO_DROP = "advancing_to_drop"
    DROPPING = "dropping"


@dataclass(slots=True)
class _CycleSnapshot:
    """Per-piece visibility into the handler's pipeline."""

    piece_uuid: str
    started_at_mono: float
    state: CarouselState = CarouselState.IDLE
    state_entered_at_mono: float = 0.0
    classification_present: bool = False
    distributor_ready: bool = False
    eject_attempted: bool = False
    completed: bool = False
    completion_reason: str | None = None


@dataclass(slots=True)
class _Counters:
    cycles_started: int = 0
    cycles_completed: int = 0
    cycles_aborted: int = 0
    transport_pulses_classify: int = 0
    transport_pulses_drop: int = 0
    distributor_requests: int = 0
    distributor_request_rejects: int = 0
    ejects_fired: int = 0
    state_transitions: dict[str, int] = field(default_factory=dict)


# Pulled at tick time. The orchestrator builds this from the C4 runtime's
# perception + dossier state so we don't reach back into runtime internals.
@dataclass(frozen=True, slots=True)
class CarouselTickInput:
    front_piece_uuid: str | None
    front_track_angle_deg: float | None
    front_classification_present: bool
    front_classification: Any  # ClassifierResult, kept opaque to avoid import cycles
    front_dossier: dict[str, Any]
    front_track_count: int
    distributor_pending_piece_uuid: str | None
    distributor_pending_ready: bool


class _DistributorPort(Protocol):
    def handoff_request(
        self,
        *,
        piece_uuid: str,
        classification: Any,
        dossier: dict[str, Any] | None = None,
        now_mono: float | None = None,
    ) -> bool: ...

    def pending_ready(self, piece_uuid: str | None = None) -> bool: ...

    def handoff_commit(
        self, piece_uuid: str, now_mono: float | None = None
    ) -> bool: ...


class CarouselC4Handler:
    """Sequential single-piece scheduler for C4.

    All hardware moves go through *callables* injected at construction —
    same pattern as ``SectionFeederHandler``. The handler enforces its
    own per-state cooldowns so it never stacks pending hardware commands.
    """

    DEFAULT_CLASSIFY_DEG = 18.0
    DEFAULT_DROP_DEG = 30.0
    DEFAULT_CLASSIFY_TOLERANCE_DEG = 6.0
    DEFAULT_DROP_TOLERANCE_DEG = 3.0
    DEFAULT_SETTLE_S = 0.6
    DEFAULT_ADVANCE_STEP_DEG = 4.0
    DEFAULT_ADVANCE_COOLDOWN_S = 0.18
    DEFAULT_DISTRIBUTOR_TIMEOUT_S = 8.0

    def __init__(
        self,
        *,
        c4_transport: Callable[[float], bool],
        c4_eject: Callable[[], bool],
        distributor_port: _DistributorPort,
        c4_hw_busy: Callable[[], bool] | None = None,
        classify_deg: float = DEFAULT_CLASSIFY_DEG,
        drop_deg: float = DEFAULT_DROP_DEG,
        classify_tolerance_deg: float = DEFAULT_CLASSIFY_TOLERANCE_DEG,
        drop_tolerance_deg: float = DEFAULT_DROP_TOLERANCE_DEG,
        settle_s: float = DEFAULT_SETTLE_S,
        advance_step_deg: float = DEFAULT_ADVANCE_STEP_DEG,
        advance_cooldown_s: float = DEFAULT_ADVANCE_COOLDOWN_S,
        distributor_timeout_s: float = DEFAULT_DISTRIBUTOR_TIMEOUT_S,
        logger: logging.Logger | None = None,
    ) -> None:
        self._c4_transport = c4_transport
        self._c4_eject = c4_eject
        self._distributor = distributor_port
        self._c4_hw_busy = c4_hw_busy or (lambda: False)
        self._classify_deg = float(classify_deg)
        self._drop_deg = float(drop_deg)
        self._classify_tolerance_deg = max(0.5, float(classify_tolerance_deg))
        self._drop_tolerance_deg = max(0.5, float(drop_tolerance_deg))
        self._settle_s = max(0.0, float(settle_s))
        self._advance_step_deg = max(0.5, float(advance_step_deg))
        self._advance_cooldown_s = max(0.0, float(advance_cooldown_s))
        self._distributor_timeout_s = max(0.5, float(distributor_timeout_s))
        self._logger = logger or logging.getLogger("rt.carousel_c4")
        self._enabled = False
        self._state: CarouselState = CarouselState.IDLE
        self._state_entered_at_mono: float = -float("inf")
        self._last_advance_at_mono: float = -float("inf")
        self._cycle: _CycleSnapshot | None = None
        self._counters = _Counters()

    # ------------------------------------------------------------------
    # Lifecycle

    def enable(self) -> None:
        self._enabled = True

    def disable(self) -> None:
        self._enabled = False
        self._abort_cycle("handler_disabled")

    def is_enabled(self) -> bool:
        return self._enabled

    def update_geometry(
        self,
        *,
        classify_deg: float | None = None,
        drop_deg: float | None = None,
        classify_tolerance_deg: float | None = None,
        drop_tolerance_deg: float | None = None,
    ) -> None:
        if classify_deg is not None:
            self._classify_deg = float(classify_deg)
        if drop_deg is not None:
            self._drop_deg = float(drop_deg)
        if classify_tolerance_deg is not None:
            self._classify_tolerance_deg = max(0.5, float(classify_tolerance_deg))
        if drop_tolerance_deg is not None:
            self._drop_tolerance_deg = max(0.5, float(drop_tolerance_deg))

    def update_timing(
        self,
        *,
        settle_s: float | None = None,
        advance_step_deg: float | None = None,
        advance_cooldown_s: float | None = None,
        distributor_timeout_s: float | None = None,
    ) -> None:
        if settle_s is not None:
            self._settle_s = max(0.0, float(settle_s))
        if advance_step_deg is not None:
            self._advance_step_deg = max(0.5, float(advance_step_deg))
        if advance_cooldown_s is not None:
            self._advance_cooldown_s = max(0.0, float(advance_cooldown_s))
        if distributor_timeout_s is not None:
            self._distributor_timeout_s = max(0.5, float(distributor_timeout_s))

    # ------------------------------------------------------------------
    # Tick

    def tick(self, payload: CarouselTickInput, *, now_mono: float | None = None) -> CarouselState:
        ts = time.monotonic() if now_mono is None else float(now_mono)
        if not self._enabled:
            return self._state

        # Pick up the cycle's piece on first appearance, or when the
        # current cycle's piece has rotated away.
        if self._cycle is None and payload.front_piece_uuid is not None:
            self._begin_cycle(payload.front_piece_uuid, ts)

        if self._cycle is None:
            self._set_state(CarouselState.IDLE, ts)
            return self._state

        # If the runtime lost track of our piece (different uuid at the
        # front), abort the cycle so we don't wait forever.
        if (
            payload.front_piece_uuid is not None
            and payload.front_piece_uuid != self._cycle.piece_uuid
        ):
            self._abort_cycle("front_piece_changed")
            return self._state

        if payload.front_piece_uuid is None and self._state in {
            CarouselState.IDLE,
            CarouselState.ADVANCING_TO_CLASSIFY,
        }:
            # Piece disappeared before we even started classifying.
            self._abort_cycle("front_piece_lost")
            return self._state

        # Dispatch on the current state. Each branch is small and
        # idempotent — tick is called every orchestrator cycle (50 Hz)
        # so any guard that returns without a transition just retries
        # next tick.
        if self._state in (CarouselState.IDLE, CarouselState.ADVANCING_TO_CLASSIFY):
            self._handle_advance_to_classify(payload, ts)
        elif self._state == CarouselState.SETTLING_AT_CLASSIFY:
            self._handle_settle(payload, ts)
        elif self._state == CarouselState.AWAIT_CLASSIFICATION:
            self._handle_await_classification(payload, ts)
        elif self._state == CarouselState.REQUESTING_DISTRIBUTOR:
            self._handle_request_distributor(payload, ts)
        elif self._state == CarouselState.AWAIT_DISTRIBUTOR_READY:
            self._handle_await_distributor(payload, ts)
        elif self._state == CarouselState.ADVANCING_TO_DROP:
            self._handle_advance_to_drop(payload, ts)
        elif self._state == CarouselState.DROPPING:
            self._handle_drop(payload, ts)
        return self._state

    # ------------------------------------------------------------------
    # Snapshot

    def snapshot(self) -> dict[str, Any]:
        cycle = self._cycle
        return {
            "enabled": self._enabled,
            "state": self._state.value,
            "state_entered_at_mono": self._state_entered_at_mono,
            "geometry": {
                "classify_deg": self._classify_deg,
                "drop_deg": self._drop_deg,
                "classify_tolerance_deg": self._classify_tolerance_deg,
                "drop_tolerance_deg": self._drop_tolerance_deg,
            },
            "timing": {
                "settle_s": self._settle_s,
                "advance_step_deg": self._advance_step_deg,
                "advance_cooldown_s": self._advance_cooldown_s,
                "distributor_timeout_s": self._distributor_timeout_s,
            },
            "current_cycle": (
                {
                    "piece_uuid": cycle.piece_uuid,
                    "state": cycle.state.value,
                    "started_at_mono": cycle.started_at_mono,
                    "classification_present": cycle.classification_present,
                    "distributor_ready": cycle.distributor_ready,
                    "eject_attempted": cycle.eject_attempted,
                }
                if cycle is not None
                else None
            ),
            "counters": {
                "cycles_started": self._counters.cycles_started,
                "cycles_completed": self._counters.cycles_completed,
                "cycles_aborted": self._counters.cycles_aborted,
                "transport_pulses_classify": self._counters.transport_pulses_classify,
                "transport_pulses_drop": self._counters.transport_pulses_drop,
                "distributor_requests": self._counters.distributor_requests,
                "distributor_request_rejects": self._counters.distributor_request_rejects,
                "ejects_fired": self._counters.ejects_fired,
                "state_transitions": dict(self._counters.state_transitions),
            },
        }

    # ------------------------------------------------------------------
    # Internals

    def _begin_cycle(self, piece_uuid: str, ts: float) -> None:
        self._cycle = _CycleSnapshot(
            piece_uuid=piece_uuid,
            started_at_mono=ts,
            state=CarouselState.ADVANCING_TO_CLASSIFY,
            state_entered_at_mono=ts,
        )
        self._counters.cycles_started += 1
        self._set_state(CarouselState.ADVANCING_TO_CLASSIFY, ts)

    def _abort_cycle(self, reason: str) -> None:
        if self._cycle is not None:
            self._cycle.completed = True
            self._cycle.completion_reason = reason
            self._counters.cycles_aborted += 1
        self._cycle = None
        self._set_state(CarouselState.IDLE, time.monotonic())

    def _complete_cycle(self) -> None:
        if self._cycle is not None:
            self._cycle.completed = True
            self._cycle.completion_reason = "delivered"
            self._counters.cycles_completed += 1
        self._cycle = None
        self._set_state(CarouselState.IDLE, time.monotonic())

    def _set_state(self, new_state: CarouselState, ts: float) -> None:
        if new_state == self._state:
            return
        key = f"{self._state.value}->{new_state.value}"
        self._counters.state_transitions[key] = (
            self._counters.state_transitions.get(key, 0) + 1
        )
        self._state = new_state
        self._state_entered_at_mono = ts
        if self._cycle is not None:
            self._cycle.state = new_state
            self._cycle.state_entered_at_mono = ts

    def _handle_advance_to_classify(self, payload: CarouselTickInput, ts: float) -> None:
        if payload.front_track_angle_deg is None:
            return
        if abs(_wrap_deg(payload.front_track_angle_deg - self._classify_deg)) <= self._classify_tolerance_deg:
            self._set_state(CarouselState.SETTLING_AT_CLASSIFY, ts)
            return
        if self._maybe_advance(ts):
            self._counters.transport_pulses_classify += 1

    def _handle_settle(self, payload: CarouselTickInput, ts: float) -> None:
        if payload.front_classification_present:
            self._cycle.classification_present = True  # type: ignore[union-attr]
            self._set_state(CarouselState.REQUESTING_DISTRIBUTOR, ts)
            return
        if (ts - self._state_entered_at_mono) < self._settle_s:
            return
        # Settle period elapsed. The classifier (still owned by RuntimeC4)
        # had time to capture the piece at rest; wait for the result.
        self._set_state(CarouselState.AWAIT_CLASSIFICATION, ts)

    def _handle_await_classification(
        self, payload: CarouselTickInput, ts: float
    ) -> None:
        if payload.front_classification_present:
            self._cycle.classification_present = True  # type: ignore[union-attr]
            self._set_state(CarouselState.REQUESTING_DISTRIBUTOR, ts)

    def _handle_request_distributor(
        self, payload: CarouselTickInput, ts: float
    ) -> None:
        if self._cycle is None:
            return
        if payload.distributor_pending_piece_uuid == self._cycle.piece_uuid:
            self._set_state(CarouselState.AWAIT_DISTRIBUTOR_READY, ts)
            return
        if payload.distributor_pending_piece_uuid is not None:
            # Distributor is busy with someone else — wait, don't spam.
            return
        try:
            ok = bool(
                self._distributor.handoff_request(
                    piece_uuid=self._cycle.piece_uuid,
                    classification=payload.front_classification,
                    dossier=payload.front_dossier,
                    now_mono=ts,
                )
            )
        except Exception:
            self._logger.exception(
                "CarouselC4Handler: distributor.handoff_request raised"
            )
            ok = False
        self._counters.distributor_requests += 1
        if not ok:
            self._counters.distributor_request_rejects += 1
            return
        self._set_state(CarouselState.AWAIT_DISTRIBUTOR_READY, ts)

    def _handle_await_distributor(
        self, payload: CarouselTickInput, ts: float
    ) -> None:
        if self._cycle is None:
            return
        if (ts - self._state_entered_at_mono) > self._distributor_timeout_s:
            self._abort_cycle("distributor_timeout")
            return
        ready = (
            payload.distributor_pending_piece_uuid == self._cycle.piece_uuid
            and payload.distributor_pending_ready
        )
        if ready:
            self._cycle.distributor_ready = True
            self._set_state(CarouselState.ADVANCING_TO_DROP, ts)

    def _handle_advance_to_drop(
        self, payload: CarouselTickInput, ts: float
    ) -> None:
        if payload.front_track_angle_deg is None:
            return
        if abs(_wrap_deg(payload.front_track_angle_deg - self._drop_deg)) <= self._drop_tolerance_deg:
            self._set_state(CarouselState.DROPPING, ts)
            return
        if self._maybe_advance(ts):
            self._counters.transport_pulses_drop += 1

    def _handle_drop(self, payload: CarouselTickInput, ts: float) -> None:
        if self._cycle is None:
            return
        if self._cycle.eject_attempted:
            return
        try:
            ejected = bool(self._c4_eject())
        except Exception:
            self._logger.exception("CarouselC4Handler: c4_eject raised")
            ejected = False
        self._cycle.eject_attempted = True
        self._counters.ejects_fired += 1
        if not ejected:
            self._abort_cycle("eject_failed")
            return
        try:
            self._distributor.handoff_commit(self._cycle.piece_uuid, now_mono=ts)
        except Exception:
            self._logger.exception(
                "CarouselC4Handler: distributor.handoff_commit raised"
            )
        self._complete_cycle()

    def _maybe_advance(self, ts: float) -> bool:
        if (ts - self._last_advance_at_mono) < self._advance_cooldown_s:
            return False
        if self._c4_hw_busy():
            return False
        try:
            ok = bool(self._c4_transport(self._advance_step_deg))
        except Exception:
            self._logger.exception("CarouselC4Handler: c4_transport raised")
            ok = False
        if ok:
            self._last_advance_at_mono = ts
        return ok


def _wrap_deg(angle: float) -> float:
    a = float(angle) % 360.0
    if a > 180.0:
        a -= 360.0
    elif a <= -180.0:
        a += 360.0
    return a


__all__ = [
    "CarouselC4Handler",
    "CarouselState",
    "CarouselTickInput",
]
