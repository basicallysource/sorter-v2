"""RuntimeDistributor — chute positioning + handoff commit.

Blind runtime (no camera, no perception feed). Reacts to:

* Synchronous :meth:`handoff_request` from RuntimeC4 carrying a piece
  dossier + ``ClassifierResult``.
* Orchestrator ``tick`` calls that drive the internal FSM forward based on
  the chute motor state.

FSM: ``IDLE -> POSITIONING -> READY -> SENDING -> COMMIT_WAIT -> IDLE``
with a sideband ``REJECT_DISPATCH`` state for unknown-part rejects and
hardware errors (chute timeout, rules-engine no-match-no-default).

Callable-injection for hardware: the concrete wiring to ``Chute.moveToBin``
and the C4 eject callback is assembled in ``main.py``. No bridge imports.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable

from rt.contracts.classification import ClassifierResult
from rt.contracts.ejection import EjectionTimingStrategy
from rt.contracts.events import Event, EventBus
from rt.contracts.rules import BinDecision, RulesEngine
from rt.contracts.runtime import RuntimeInbox
from rt.coupling.slots import CapacitySlot
from rt.events.topics import PIECE_DISTRIBUTED

from .base import BaseRuntime, HwWorker


DEFAULT_CHUTE_SETTLE_S = 0.4
DEFAULT_FALL_TIME_S = 1.5
DEFAULT_SIMULATED_CHUTE_MOVE_S = 0.8
DEFAULT_REJECT_BIN_ID = "reject"
DEFAULT_RUNTIME_ID = "distributor"


class _DistState(str, Enum):
    IDLE = "idle"
    POSITIONING = "positioning"
    READY = "ready"
    SENDING = "sending"
    COMMIT_WAIT = "commit_wait"
    REJECT_DISPATCH = "reject_dispatch"


@dataclass(slots=True)
class _PendingPiece:
    piece_uuid: str
    classification: ClassifierResult
    dossier: dict[str, Any] = field(default_factory=dict)
    requested_at: float = 0.0
    decision: BinDecision | None = None
    target_bin_id: str | None = None
    positioned_at: float | None = None
    ready_at: float | None = None
    eject_requested_at: float | None = None
    commit_deadline: float | None = None
    accepted: bool = True
    reject_reason: str | None = None


class RuntimeDistributor(BaseRuntime):
    """Bin-mapping + chute runtime. Blind; C4 feeds via handoff_request."""

    def __init__(
        self,
        *,
        upstream_slot: CapacitySlot,
        rules_engine: RulesEngine,
        ejection_timing: EjectionTimingStrategy,
        chute_move_command: Callable[[str], bool],
        chute_position_query: Callable[[], str | None],
        on_ready_callback: Callable[[str], None],
        on_piece_delivered_callback: Callable[[str], None],
        on_ack_callback: Callable[[str, bool, str], None],
        logger: logging.Logger | None = None,
        hw_worker: HwWorker | None = None,
        event_bus: EventBus | None = None,
        runtime_id: str = DEFAULT_RUNTIME_ID,
        reject_bin_id: str = DEFAULT_REJECT_BIN_ID,
        position_timeout_s: float = 6.0,
        ready_timeout_s: float = 60.0,
        chute_settle_s: float = DEFAULT_CHUTE_SETTLE_S,
        fall_time_s: float = DEFAULT_FALL_TIME_S,
        simulate_chute: bool = False,
        simulated_chute_move_s: float = DEFAULT_SIMULATED_CHUTE_MOVE_S,
        run_recorder: Any | None = None,
        state_observer: Callable[[str, str, str], None] | None = None,
    ) -> None:
        super().__init__(
            runtime_id, feed_id=None, logger=logger, hw_worker=hw_worker,
            state_observer=state_observer,
        )
        self._upstream_slot = upstream_slot
        self._rules_engine = rules_engine
        self._ejection = ejection_timing
        self._chute_move = chute_move_command
        self._chute_position_query = chute_position_query
        self._on_ready = on_ready_callback
        self._on_delivered = on_piece_delivered_callback
        self._on_ack = on_ack_callback
        self._bus = event_bus
        self._reject_bin_id = str(reject_bin_id)
        self._position_timeout_s = float(position_timeout_s)
        self._ready_timeout_s = max(0.0, float(ready_timeout_s))
        self._chute_settle_s = float(chute_settle_s)
        self._fall_time_s = float(fall_time_s)
        self._simulate_chute = bool(simulate_chute)
        self._simulated_chute_move_s = max(0.0, float(simulated_chute_move_s))
        self._run_recorder = run_recorder
        self._fsm: _DistState = _DistState.IDLE
        self._pending: _PendingPiece | None = None
        self._simulated_position_ready_at: float | None = None
        self._last_chute_move_bin: str | None = None
        self._last_chute_move_ok: bool | None = None
        self._last_chute_move_error: str | None = None
        self._last_chute_move_at: float | None = None
        self._last_chute_position: str | None = None
        self._last_chute_position_error: str | None = None
        self._last_chute_position_at: float | None = None
        self._set_state(self._fsm.value)

    # ------------------------------------------------------------------
    # External API called by C4

    def handoff_request(
        self,
        *,
        piece_uuid: str,
        classification: ClassifierResult,
        dossier: dict[str, Any] | None = None,
        now_mono: float | None = None,
    ) -> bool:
        """C4 asks the distributor to take a classified piece.

        Returns ``True`` if the distributor accepted the request and
        started positioning. ``False`` iff the distributor is already
        busy with another piece (caller must back off).
        """
        if self._pending is not None:
            self._logger.warning(
                "RuntimeDistributor: handoff_request rejected — busy with %s (fsm=%s)",
                self._pending.piece_uuid,
                self._fsm.value,
            )
            return False

        ts = float(now_mono) if now_mono is not None else time.monotonic()
        self._pending = _PendingPiece(
            piece_uuid=str(piece_uuid),
            classification=classification,
            dossier=dict(dossier or {}),
            requested_at=ts,
        )
        try:
            decision = self._rules_engine.decide_bin(
                classification=classification,
                context={"piece_uuid": piece_uuid, "dossier": self._pending.dossier},
            )
        except Exception:
            self._logger.exception(
                "RuntimeDistributor: rules_engine.decide_bin raised for %s",
                piece_uuid,
            )
            decision = BinDecision(
                bin_id=None,
                category=None,
                reason="rules_engine_error",
            )
        self._pending.decision = decision

        if decision.bin_id is None:
            # No bin => reject. Route to reject bin, ack negatively.
            self._pending.accepted = False
            self._pending.reject_reason = decision.reason
            self._pending.target_bin_id = self._reject_bin_id
        else:
            self._pending.target_bin_id = decision.bin_id

        ok = self._start_positioning(self._pending.target_bin_id, ts)
        if not ok:
            self._logger.error(
                "RuntimeDistributor: chute move rejected for bin=%s (piece=%s)",
                self._pending.target_bin_id,
                piece_uuid,
            )
            self._ack_and_release(
                accepted=False,
                reason="chute_move_rejected",
                now_mono=ts,
            )
            return False

        if self._pending is not None and not self._pending.accepted:
            self._fsm = _DistState.REJECT_DISPATCH
        else:
            self._fsm = _DistState.POSITIONING
        self._set_state(self._fsm.value)
        return True

    # ------------------------------------------------------------------
    # Runtime ABC

    def available_slots(self) -> int:
        return 1 if self._pending is None else 0

    def tick(self, inbox: RuntimeInbox, now_mono: float) -> None:
        start = self._tick_begin()
        try:
            self._tick_inner(now_mono)
        except Exception:
            self._logger.exception("RuntimeDistributor: tick raised")
        finally:
            self._tick_end(start)

    def on_piece_delivered(self, piece_uuid: str, now_mono: float) -> None:
        """Not used upstream-side; Distributor is the terminal runtime."""
        return None

    # ------------------------------------------------------------------
    # Introspection (tests + telemetry)

    def fsm_state(self) -> str:
        return self._fsm.value

    def pending_piece_uuid(self) -> str | None:
        return self._pending.piece_uuid if self._pending else None

    def pending_target_bin(self) -> str | None:
        return self._pending.target_bin_id if self._pending else None

    def debug_snapshot(self) -> dict[str, Any]:
        snap = super().debug_snapshot()
        now = time.monotonic()
        pending = self._pending
        pending_payload: dict[str, Any] | None = None
        if pending is not None:
            decision = pending.decision
            pending_payload = {
                "piece_uuid": pending.piece_uuid,
                "target_bin_id": pending.target_bin_id,
                "accepted": bool(pending.accepted),
                "reject_reason": pending.reject_reason,
                "decision_reason": decision.reason if decision is not None else None,
                "decision_category": decision.category if decision is not None else None,
                "requested_age_s": max(0.0, now - float(pending.requested_at)),
                "positioned_age_s": (
                    max(0.0, now - float(pending.positioned_at))
                    if pending.positioned_at is not None
                    else None
                ),
                "ready_age_s": (
                    max(0.0, now - float(pending.ready_at))
                    if pending.ready_at is not None
                    else None
                ),
                "eject_age_s": (
                    max(0.0, now - float(pending.eject_requested_at))
                    if pending.eject_requested_at is not None
                    else None
                ),
                "commit_due_in_s": (
                    float(pending.commit_deadline) - now
                    if pending.commit_deadline is not None
                    else None
                ),
            }
        snap.update(
            {
                "fsm_state": self._fsm.value,
                "available_slots": int(self.available_slots()),
                "pending": pending_payload,
                "position_timeout_s": self._position_timeout_s,
                "ready_timeout_s": self._ready_timeout_s,
                "chute": {
                    "simulated": bool(self._simulate_chute),
                    "simulated_move_s": float(self._simulated_chute_move_s),
                    "simulated_ready_in_s": (
                        max(0.0, float(self._simulated_position_ready_at) - now)
                        if self._simulated_position_ready_at is not None
                        else None
                    ),
                    "last_move_bin": self._last_chute_move_bin,
                    "last_move_ok": self._last_chute_move_ok,
                    "last_move_error": self._last_chute_move_error,
                    "last_move_age_s": (
                        max(0.0, now - float(self._last_chute_move_at))
                        if self._last_chute_move_at is not None
                        else None
                    ),
                    "last_position": self._last_chute_position,
                    "last_position_error": self._last_chute_position_error,
                    "last_position_age_s": (
                        max(0.0, now - float(self._last_chute_position_at))
                        if self._last_chute_position_at is not None
                        else None
                    ),
                },
            }
        )
        return snap

    def inspect_snapshot(self, *, now_mono: float | None = None) -> dict[str, Any]:
        ts = time.monotonic() if now_mono is None else float(now_mono)
        snap = self.debug_snapshot()
        snap["upstream_slot_taken"] = int(self._upstream_slot.taken(now_mono=ts))
        return snap

    # ------------------------------------------------------------------
    # Internals

    def _tick_inner(self, now_mono: float) -> None:
        pending = self._pending
        if pending is None:
            self._fsm = _DistState.IDLE
            self._set_state(self._fsm.value)
            return

        if self._fsm is _DistState.POSITIONING or self._fsm is _DistState.REJECT_DISPATCH:
            self._advance_positioning(pending, now_mono)
            return

        if self._fsm is _DistState.READY:
            # Waiting for C4 to eject; nothing to do.
            if (
                self._ready_timeout_s > 0.0
                and pending.ready_at is not None
                and (now_mono - pending.ready_at) > self._ready_timeout_s
            ):
                self._logger.error(
                    "RuntimeDistributor: ready timeout for piece=%s bin=%s",
                    pending.piece_uuid,
                    pending.target_bin_id,
                )
                self._ack_and_release(
                    accepted=False,
                    reason="handoff_ready_timeout",
                    now_mono=now_mono,
                )
            return

        if self._fsm is _DistState.SENDING:
            # Fall-time has been armed by _on_eject_commit; wait out the deadline.
            deadline = pending.commit_deadline or 0.0
            if now_mono >= deadline:
                self._complete_delivery(pending, now_mono)
            return

        if self._fsm is _DistState.COMMIT_WAIT:
            # Guard band — handshake finished on previous tick.
            self._pending = None
            self._fsm = _DistState.IDLE
            self._set_state(self._fsm.value)
            return

    def _start_positioning(self, bin_id: str | None, now_mono: float) -> bool:
        if bin_id is None:
            return False
        target = bin_id
        if self._simulate_chute:
            self._simulated_position_ready_at = (
                float(now_mono) + self._simulated_chute_move_s
            )
            self._last_chute_move_bin = target
            self._last_chute_move_ok = True
            self._last_chute_move_error = None
            self._last_chute_move_at = now_mono
            self._last_chute_position = None
            self._last_chute_position_error = None
            self._last_chute_position_at = now_mono
            return True
        self._simulated_position_ready_at = None

        def _do_move() -> None:
            try:
                ok = bool(self._chute_move(target))
            except Exception:
                self._last_chute_move_bin = target
                self._last_chute_move_ok = False
                self._last_chute_move_error = "exception"
                self._last_chute_move_at = time.monotonic()
                self._logger.exception(
                    "RuntimeDistributor: chute_move_command raised for bin=%s",
                    target,
                )
                ok = False
            else:
                self._last_chute_move_bin = target
                self._last_chute_move_ok = ok
                self._last_chute_move_error = None if ok else "returned_false"
                self._last_chute_move_at = time.monotonic()
            if not ok:
                self._logger.error(
                    "RuntimeDistributor: chute move returned False for bin=%s",
                    target,
                )

        enqueued = self._hw.enqueue(_do_move, label="dist_chute_move")
        if not enqueued:
            return False
        return True

    def _advance_positioning(self, pending: _PendingPiece, now_mono: float) -> None:
        if (now_mono - pending.requested_at) > self._position_timeout_s:
            self._logger.error(
                "RuntimeDistributor: chute positioning timeout for piece=%s bin=%s",
                pending.piece_uuid,
                pending.target_bin_id,
            )
            self._ack_and_release(
                accepted=False,
                reason="position_timeout",
                now_mono=now_mono,
            )
            return

        if self._simulate_chute:
            if (
                self._simulated_position_ready_at is not None
                and now_mono < self._simulated_position_ready_at
            ):
                self._last_chute_position = None
                self._last_chute_position_error = None
                self._last_chute_position_at = now_mono
                return
            current = pending.target_bin_id
            self._last_chute_position = current
            self._last_chute_position_error = None
            self._last_chute_position_at = now_mono
        else:
            try:
                current = self._chute_position_query()
            except Exception:
                self._last_chute_position = None
                self._last_chute_position_error = "exception"
                self._last_chute_position_at = now_mono
                self._logger.exception(
                    "RuntimeDistributor: chute_position_query raised"
                )
                current = None
            else:
                self._last_chute_position = current
                self._last_chute_position_error = None
                self._last_chute_position_at = now_mono
        if current is None:
            # Still in motion.
            return
        if current != pending.target_bin_id:
            return

        if pending.positioned_at is None:
            pending.positioned_at = now_mono
        settled_for = now_mono - pending.positioned_at
        if settled_for < self._chute_settle_s:
            return

        if not pending.accepted:
            # Reject path: no C4-eject handshake; we still walk through the
            # drop side effect so the piece physically falls into the reject
            # bin, then ack negatively.
            self._arm_sending(pending, now_mono)
            return

        # Normal path: signal C4 that the chute is ready to receive the piece.
        self._fsm = _DistState.READY
        pending.ready_at = now_mono
        self._set_state(self._fsm.value)
        try:
            self._on_ready(pending.piece_uuid)
        except Exception:
            self._logger.exception(
                "RuntimeDistributor: on_ready callback raised for piece=%s",
                pending.piece_uuid,
            )
            self._ack_and_release(
                accepted=False,
                reason="ready_callback_error",
                now_mono=now_mono,
            )

    def handoff_commit(self, piece_uuid: str, now_mono: float | None = None) -> bool:
        """C4 signals the eject pulse fired — start the fall-time countdown."""
        pending = self._pending
        if pending is None or pending.piece_uuid != piece_uuid:
            self._logger.warning(
                "RuntimeDistributor: handoff_commit for unknown piece=%s",
                piece_uuid,
            )
            return False
        if self._fsm is not _DistState.READY:
            self._logger.warning(
                "RuntimeDistributor: handoff_commit in wrong state=%s (piece=%s)",
                self._fsm.value,
                piece_uuid,
            )
            return False
        ts = float(now_mono) if now_mono is not None else time.monotonic()
        self._arm_sending(pending, ts)
        return True

    def handoff_abort(
        self,
        piece_uuid: str,
        reason: str = "handoff_aborted",
        now_mono: float | None = None,
    ) -> bool:
        """C4 lost or rejected a piece after the distributor accepted it."""
        pending = self._pending
        if pending is None or pending.piece_uuid != piece_uuid:
            self._logger.warning(
                "RuntimeDistributor: handoff_abort for unknown piece=%s",
                piece_uuid,
            )
            return False
        ts = float(now_mono) if now_mono is not None else time.monotonic()
        self._ack_and_release(accepted=False, reason=str(reason), now_mono=ts)
        return True

    def _arm_sending(self, pending: _PendingPiece, now_mono: float) -> None:
        try:
            timing = self._ejection.timing_for(
                {
                    "piece_uuid": pending.piece_uuid,
                    "bin_id": pending.target_bin_id,
                    "accepted": pending.accepted,
                }
            )
            fall_ms = float(timing.fall_time_ms)
        except Exception:
            self._logger.exception(
                "RuntimeDistributor: ejection.timing_for raised; using default fall time"
            )
            fall_ms = self._fall_time_s * 1000.0
        pending.eject_requested_at = now_mono
        pending.commit_deadline = now_mono + max(0.0, fall_ms / 1000.0)
        self._fsm = _DistState.SENDING
        self._set_state(self._fsm.value)

    def _complete_delivery(self, pending: _PendingPiece, now_mono: float) -> None:
        topic_payload: dict[str, Any] = {
            "piece_uuid": pending.piece_uuid,
            "bin_id": pending.target_bin_id,
            "category": pending.decision.category if pending.decision else None,
            "category_id": pending.decision.category if pending.decision else None,
            "accepted": pending.accepted,
            "reason": (
                pending.decision.reason if pending.decision else "unknown"
            ),
            "distribution_reason": (
                pending.decision.reason if pending.decision else "unknown"
            ),
        }
        if self._bus is not None:
            try:
                self._bus.publish(
                    Event(
                        topic=PIECE_DISTRIBUTED,
                        payload=topic_payload,
                        source=self.runtime_id,
                        ts_mono=now_mono,
                    )
                )
            except Exception:
                self._logger.exception(
                    "RuntimeDistributor: event publish failed for piece=%s",
                    pending.piece_uuid,
                )
        if self._run_recorder is not None:
            try:
                self._run_recorder.record_distributed(topic_payload)
            except AttributeError:
                # Optional hook; not every recorder implements it yet.
                pass
            except Exception:
                self._logger.exception(
                    "RuntimeDistributor: run_recorder hook raised for piece=%s",
                    pending.piece_uuid,
                )

        self._ack_and_release(
            accepted=pending.accepted,
            reason=pending.reject_reason or (
                pending.decision.reason if pending.decision else "ok"
            ),
            now_mono=now_mono,
        )

    def _ack_and_release(
        self,
        *,
        accepted: bool,
        reason: str,
        now_mono: float,
    ) -> None:
        pending = self._pending
        if pending is None:
            return
        piece_uuid = pending.piece_uuid
        try:
            if accepted:
                self._on_delivered(piece_uuid)
            self._on_ack(piece_uuid, accepted, reason)
        except Exception:
            self._logger.exception(
                "RuntimeDistributor: ack callback raised for piece=%s (accepted=%s)",
                piece_uuid,
                accepted,
            )
        self._upstream_slot.release()
        self._pending = None
        self._fsm = _DistState.COMMIT_WAIT
        self._set_state(self._fsm.value)


__all__ = ["RuntimeDistributor", "DEFAULT_REJECT_BIN_ID"]
