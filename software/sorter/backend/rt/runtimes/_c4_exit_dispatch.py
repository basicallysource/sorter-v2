from __future__ import annotations

import time
from typing import Any

from rt.contracts.runtime import RuntimeInbox
from rt.contracts.tracking import Track


class C4ExitDispatcher:
    """Own C4 handoff, exit, shimmy, and eject dispatch decisions."""

    def __init__(self, runtime: Any) -> None:
        self._rt = runtime

    def request_pending_handoffs(self, now_mono: float) -> None:
        rt = self._rt
        if rt._handoff is None:
            rt._mark_handoff("request_not_wired")
            return
        dossier = self.next_handoff_candidate()
        if dossier is None:
            return
        self.request_distributor_handoff(dossier, now_mono)

    def next_handoff_candidate(self) -> Any | None:
        rt = self._rt
        for dossier in rt._dossiers_by_exit_distance():
            if dossier.handoff_requested:
                rt._mark_handoff("front_already_requested")
                return None
            if dossier.result is None:
                rt._mark_handoff("front_not_classified")
                return None
            distance = rt._dossier_exit_distance(dossier)
            if (
                rt._handoff_request_horizon_deg > 0.0
                and distance > rt._handoff_request_horizon_deg
            ):
                rt._mark_handoff("front_outside_handoff_horizon")
                return None
            return dossier
        return None

    def request_distributor_handoff(
        self,
        dossier: Any,
        now_mono: float,
    ) -> bool:
        rt = self._rt
        port = rt._handoff
        result = dossier.result
        if port is None or result is None:
            rt._mark_handoff("request_not_ready")
            return False
        if rt._sync_handoff_from_port(dossier):
            rt._mark_handoff("synced_pending")
            return True
        if dossier.handoff_requested:
            rt._mark_handoff("already_requested")
            return True
        # Backoff: after a distributor_busy rejection, wait before hitting
        # the port again so the distributor has time to complete its
        # chute-move -> ready -> eject cycle. Without this, C4 spams
        # handoff_request at tick rate and the busy counter explodes.
        if (
            dossier.last_handoff_attempt_at > 0.0
            and now_mono - dossier.last_handoff_attempt_at
            < rt._handoff_retry_cooldown_s
        ):
            rt._mark_handoff("retry_cooldown")
            return False
        # Cheap, non-blocking probe: if the distributor has no free slot
        # there's no point reserving the c4_to_distributor slot either.
        try:
            port_slots = int(port.available_slots())
        except Exception:
            port_slots = 1  # assume capacity; the full request path will reject if busy
        if port_slots <= 0:
            dossier.last_handoff_attempt_at = now_mono
            rt._mark_handoff("distributor_busy")
            return False
        if not rt._downstream_slot.try_claim(now_mono=now_mono, hold_time_s=15.0):
            rt._set_state("drop_commit", blocked_reason="downstream_full")
            rt._mark_handoff("downstream_full")
            return False
        try:
            accepted = bool(
                port.handoff_request(
                    piece_uuid=dossier.piece_uuid,
                    classification=result,
                    dossier=rt._payloads.handoff_dossier_payload(dossier),
                    now_mono=now_mono,
                )
            )
        except Exception:
            rt._downstream_slot.release()
            rt._logger.exception(
                "RuntimeC4: distributor handoff_request raised for piece=%s",
                dossier.piece_uuid,
            )
            rt._mark_handoff("callback_raised")
            return False
        if not accepted:
            rt._downstream_slot.release()
            rt._set_state("drop_commit", blocked_reason="distributor_busy")
            rt._mark_handoff("distributor_busy")
            dossier.last_handoff_attempt_at = now_mono
            bank_track = rt._bank.track(dossier.piece_uuid)
            if bank_track is not None:
                bank_track.last_handoff_attempt_at = now_mono
            return False
        dossier.handoff_requested = True
        bank_track = rt._bank.track(dossier.piece_uuid)
        if bank_track is not None:
            bank_track.handoff_requested = True
            bank_track.last_handoff_attempt_at = now_mono
        rt._handoff_debug.record_handoff_move(
            now_mono=now_mono,
            source="c4_distributor_handoff_request",
            step_deg=None,
            use_exit_approach=None,
            track_count=len(rt._pieces),
            dossier=dossier,
        )
        rt._mark_handoff("accepted")
        return True

    def abort_non_front_handoffs(
        self,
        front_piece_uuid: str,
        now_mono: float,
    ) -> None:
        rt = self._rt
        for dossier in list(rt._pieces.values()):
            if dossier.piece_uuid == front_piece_uuid:
                continue
            if not dossier.handoff_requested:
                continue
            self.abort_handoff_only(
                dossier,
                now_mono=now_mono,
                reason="out_of_order_exit",
                front_piece_uuid=front_piece_uuid,
            )

    def abort_handoff_only(
        self,
        dossier: Any,
        *,
        now_mono: float,
        reason: str,
        front_piece_uuid: str | None = None,
    ) -> bool:
        rt = self._rt
        if not dossier.handoff_requested:
            return False
        port = rt._handoff
        if port is not None:
            try:
                port.handoff_abort(
                    dossier.piece_uuid,
                    reason=reason,
                    now_mono=now_mono,
                )
            except Exception:
                rt._logger.exception(
                    "RuntimeC4: distributor handoff_abort raised for piece=%s",
                    dossier.piece_uuid,
                )
        rt._downstream_slot.release()
        dossier.handoff_requested = False
        dossier.distributor_ready = False
        dossier.eject_enqueued = False
        dossier.eject_committed = False
        dossier.last_handoff_attempt_at = now_mono
        rt._mark_handoff(f"aborted_{reason}")
        rt._handoff_debug.record_handoff_move(
            now_mono=now_mono,
            source=f"c4_handoff_abort_{reason}",
            step_deg=None,
            use_exit_approach=None,
            track_count=len(rt._pieces),
            dossier=dossier,
            extra={"front_piece_uuid": front_piece_uuid},
        )
        rt._logger.warning(
            "RuntimeC4: aborted distributor handoff for piece=%s reason=%s front=%s",
            dossier.piece_uuid,
            reason,
            front_piece_uuid,
        )
        return True

    def handle_exit(
        self,
        tracks: list[Track],
        inbox: RuntimeInbox,
        now_mono: float,
    ) -> None:
        rt = self._rt
        state = type(rt._fsm)
        exit_track = rt._exit_geometry.pick_exit_track(tracks)
        if exit_track is None:
            rt._exit_stall_since = None
            if rt._fsm is state.EXIT_SHIMMY:
                rt._fsm = state.RUNNING
            return

        piece_uuid = rt._piece_uuid_for_track(exit_track)
        if piece_uuid is None:
            return
        dossier = rt._pieces.get(piece_uuid)
        if dossier is not None:
            rt._sync_handoff_from_port(dossier)
        self.abort_non_front_handoffs(piece_uuid, now_mono)
        if dossier is None or dossier.result is None:
            if inbox.capacity_downstream <= 0:
                self.maybe_shimmy(now_mono)
            return
        if dossier.eject_enqueued:
            rt._set_state("drop_commit", blocked_reason="eject_in_flight")
            return

        if rt._handoff is not None:
            if not dossier.handoff_requested:
                self.request_distributor_handoff(dossier, now_mono)
                return
            if not dossier.distributor_ready:
                rt._set_state("drop_commit", blocked_reason="waiting_distributor")
                return
            if rt._hw.busy():
                rt._set_state("drop_commit", blocked_reason="hw_busy")
                return
            # Dispatch gate: posterior-singleton check via the
            # PieceTrackBank. The bank knows every chute-blocking
            # PieceTrack's 2-sigma angular interval and refuses the
            # eject unless this piece is the only one whose interval
            # overlaps the chute window. Falls back to the deterministic
            # trailing-safety guard if the bank does not know the piece.
            bank_track = rt._bank.track(piece_uuid)
            if bank_track is not None:
                if not rt._bank_mirror.singleton_for_eject(piece_uuid):
                    rt._set_state(
                        "drop_commit", blocked_reason="trailing_piece_in_chute"
                    )
                    return
            elif rt._exit_geometry.has_trailing_piece_within_safety(
                exit_track,
                tracks,
            ):
                rt._set_state(
                    "drop_commit", blocked_reason="trailing_piece_in_chute"
                )
                return
            self.enqueue_eject(piece_uuid, claim_downstream=False)
            return

        if inbox.capacity_downstream <= 0:
            self.maybe_shimmy(now_mono)
            return
        if rt._hw.busy():
            rt._set_state("drop_commit", blocked_reason="hw_busy")
            return
        if not rt._downstream_slot.try_claim(
            now_mono=now_mono, hold_time_s=5.0
        ):
            rt._set_state("drop_commit", blocked_reason="downstream_full")
            return

        self.enqueue_eject(piece_uuid, claim_downstream=True)

    def enqueue_eject(self, piece_uuid: str, *, claim_downstream: bool) -> bool:
        rt = self._rt
        state = type(rt._fsm)
        dossier = rt._pieces.get(piece_uuid)
        if dossier is not None:
            if dossier.eject_enqueued:
                rt._set_state("drop_commit", blocked_reason="eject_in_flight")
                return False
            dossier.eject_enqueued = True
        bank_track = rt._bank.track(piece_uuid)
        if bank_track is not None:
            bank_track.eject_enqueued = True

        def _do_eject() -> None:
            try:
                ok = bool(rt._eject())
            except Exception:
                rt._logger.exception("RuntimeC4: eject_command raised")
                ok = False
            if not ok:
                live_dossier = rt._pieces.get(piece_uuid)
                if live_dossier is not None:
                    live_dossier.eject_enqueued = False
                live_bank = rt._bank.track(piece_uuid)
                if live_bank is not None:
                    live_bank.eject_enqueued = False
                rt._downstream_slot.release()
                return
            port = rt._handoff
            if port is not None:
                try:
                    committed = bool(
                        port.handoff_commit(piece_uuid, now_mono=time.monotonic())
                    )
                except Exception:
                    rt._logger.exception(
                        "RuntimeC4: distributor handoff_commit raised for piece=%s",
                        piece_uuid,
                    )
                    committed = False
                live_dossier = rt._pieces.get(piece_uuid)
                if live_dossier is not None:
                    live_dossier.eject_committed = committed
                live_bank = rt._bank.track(piece_uuid)
                if live_bank is not None:
                    live_bank.eject_committed = bool(committed)
                if not committed:
                    rt._logger.warning(
                        "RuntimeC4: distributor handoff_commit rejected for piece=%s",
                        piece_uuid,
                    )

        if not rt._hw.enqueue(_do_eject, label="c4_eject"):
            if dossier is not None:
                dossier.eject_enqueued = False
            if claim_downstream:
                rt._downstream_slot.release()
            rt._set_state("drop_commit", blocked_reason="hw_queue_full")
            return False
        rt._handoff_debug.record_handoff_move(
            now_mono=time.monotonic(),
            source="c4_eject",
            step_deg=None,
            use_exit_approach=None,
            track_count=len(rt._pieces),
            dossier=dossier,
            extra={"claim_downstream": bool(claim_downstream)},
        )
        rt._fsm = state.DROP_COMMIT
        rt._set_state(rt._fsm.value)
        rt._exit_stall_since = None
        return True

    def maybe_shimmy(self, now_mono: float) -> bool:
        rt = self._rt
        state = type(rt._fsm)
        if rt._exit_stall_since is None:
            rt._exit_stall_since = now_mono
            return False
        stall = now_mono - rt._exit_stall_since
        if stall < rt._shimmy_stall_s:
            return False
        if now_mono < rt._next_shimmy_at:
            return False
        if rt._hw_busy_or_backlogged():
            return False
        step = rt._shimmy_step_deg

        def _do_shimmy() -> None:
            try:
                rt._wiggle_move(step)
                rt._wiggle_move(-step)
            except Exception:
                rt._logger.exception("RuntimeC4: shimmy move raised")

        if rt._hw.enqueue(_do_shimmy, label="c4_exit_shimmy"):
            rt._next_shimmy_at = now_mono + rt._shimmy_cooldown_s
            rt._fsm = state.EXIT_SHIMMY
            rt._set_state(rt._fsm.value)
            return True
        return False


__all__ = ["C4ExitDispatcher"]
