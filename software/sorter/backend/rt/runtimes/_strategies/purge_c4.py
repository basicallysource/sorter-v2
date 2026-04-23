"""C4 startup purge strategy.

Owns the one-shot clearout policy that runs when the runtime first starts:
prime the tray so tracking can latch onto visible parts, then keep purging
until the tray actually looks clear. Visible-but-unowned parts are treated as
work still left to do; the purge keeps sweeping the tray instead of silently
finishing once an initial prime budget is exhausted.
"""

from __future__ import annotations

from typing import Any, Callable, Protocol

from rt.contracts.tracking import Track


class _PurgeHost(Protocol):
    _startup_purge_armed: bool
    _startup_purge_prime_moves: int
    _startup_purge_next_prime_at: float
    _startup_purge_clear_since: float | None
    _startup_purge_commit_piece_uuid: str | None
    _startup_purge_commit_deadline: float | None
    _startup_purge_eject_ok: bool | None
    _pieces: dict[str, Any]
    _track_to_piece: dict[int, str]
    _hw: Any
    _ejection: Any
    _logger: Any
    _carousel_move: Callable[[float], bool]
    _startup_purge_move: Callable[[float], bool]
    _eject: Callable[[], bool]

    def _owned_tracks(self, tracks: list[Track]) -> list[Track]: ...
    def _reconcile_visible_tracks(self, tracks: list[Track], now_mono: float) -> None: ...
    def _pick_exit_track(self, tracks: list[Track]) -> Track | None: ...
    def _finalize_piece(
        self,
        piece_uuid: str,
        *,
        now_mono: float | None,
        arm_cooldown: bool,
    ) -> None: ...
    def _maybe_advance_transport(
        self,
        tracks: list[Track],
        now_mono: float,
        *,
        move_command: Callable[[float], bool] | None = None,
    ) -> bool: ...
    def _set_state(self, state: str, *, blocked_reason: str | None = None) -> None: ...
    def _enter_startup_purge(self) -> None: ...
    def _exit_startup_purge(self) -> None: ...


class C4StartupPurgeStrategy:
    """Policy knobs for the classification-channel startup purge."""

    key = "c4_startup_purge"

    def __init__(
        self,
        *,
        enabled: bool = True,
        prime_step_deg: float = 6.0,
        prime_cooldown_ms: float = 250.0,
        max_prime_moves: int = 3,
        clear_hold_ms: float = 600.0,
    ) -> None:
        if prime_step_deg <= 0.0:
            raise ValueError(f"prime_step_deg must be > 0, got {prime_step_deg}")
        if prime_cooldown_ms < 0.0:
            raise ValueError(
                f"prime_cooldown_ms must be >= 0, got {prime_cooldown_ms}"
            )
        if max_prime_moves < 0:
            raise ValueError(f"max_prime_moves must be >= 0, got {max_prime_moves}")
        if clear_hold_ms < 0.0:
            raise ValueError(f"clear_hold_ms must be >= 0, got {clear_hold_ms}")
        self._enabled = bool(enabled)
        self._prime_step_deg = float(prime_step_deg)
        self._prime_cooldown_s = float(prime_cooldown_ms) / 1000.0
        self._max_prime_moves = int(max_prime_moves)
        self._clear_hold_s = float(clear_hold_ms) / 1000.0

    @property
    def enabled(self) -> bool:
        return self._enabled

    @property
    def prime_step_deg(self) -> float:
        return self._prime_step_deg

    @property
    def prime_cooldown_s(self) -> float:
        return self._prime_cooldown_s

    @property
    def max_prime_moves(self) -> int:
        return self._max_prime_moves

    @property
    def clear_hold_s(self) -> float:
        return self._clear_hold_s

    def needs_purge(
        self,
        *,
        raw_detection_count: int,
        owned_piece_count: int,
    ) -> bool:
        if not self._enabled:
            return False
        return int(raw_detection_count) > 0 or int(owned_piece_count) > 0

    def can_prime(
        self,
        *,
        raw_detection_count: int,
        owned_piece_count: int,
        prime_moves: int,
        hw_busy: bool,
        now_mono: float,
        next_prime_at: float,
    ) -> bool:
        if not self._enabled:
            return False
        if int(raw_detection_count) <= 0 or int(owned_piece_count) > 0:
            return False
        if int(prime_moves) >= self._max_prime_moves:
            return False
        if hw_busy:
            return False
        return float(now_mono) >= float(next_prime_at)

    def can_finish(
        self,
        *,
        raw_detection_count: int,
        owned_piece_count: int,
        prime_moves: int,
        clear_since: float | None,
        now_mono: float,
    ) -> bool:
        if not self._enabled:
            return True
        if int(owned_piece_count) > 0:
            return False
        if int(raw_detection_count) > 0:
            return False
        if clear_since is None:
            return False
        return (float(now_mono) - float(clear_since)) >= self._clear_hold_s

    def run(
        self,
        host: _PurgeHost,
        raw_tracks: list[Track],
        owned_tracks: list[Track],
        visible_detection_count: int,
        now_mono: float,
    ) -> bool:
        if not host._startup_purge_armed:
            return False

        host._enter_startup_purge()

        if host._startup_purge_commit_piece_uuid is not None:
            if host._hw.busy() or host._startup_purge_eject_ok is None:
                host._set_state("startup_purge", blocked_reason="ejecting")
                return True
            if host._startup_purge_eject_ok is False:
                host._startup_purge_commit_piece_uuid = None
                host._startup_purge_commit_deadline = None
                host._startup_purge_eject_ok = None
                host._set_state("startup_purge", blocked_reason="eject_failed")
                return True
            deadline = float(host._startup_purge_commit_deadline or now_mono)
            if now_mono < deadline:
                host._set_state("startup_purge", blocked_reason="fall_time")
                return True
            piece_uuid = host._startup_purge_commit_piece_uuid
            host._startup_purge_commit_piece_uuid = None
            host._startup_purge_commit_deadline = None
            host._startup_purge_eject_ok = None
            host._finalize_piece(piece_uuid, now_mono=None, arm_cooldown=False)
            owned_tracks = host._owned_tracks(raw_tracks)

        if not host._pieces:
            host._reconcile_visible_tracks(raw_tracks, now_mono)
            owned_tracks = host._owned_tracks(raw_tracks)

        raw_count = max(0, int(visible_detection_count))
        owned_count = len(host._pieces)
        if not self.needs_purge(
            raw_detection_count=raw_count,
            owned_piece_count=owned_count,
        ):
            if host._startup_purge_clear_since is None:
                host._startup_purge_clear_since = now_mono
            if self.can_finish(
                raw_detection_count=raw_count,
                owned_piece_count=owned_count,
                prime_moves=host._startup_purge_prime_moves,
                clear_since=host._startup_purge_clear_since,
                now_mono=now_mono,
            ):
                host._startup_purge_armed = False
                host._startup_purge_clear_since = None
                host._exit_startup_purge()
                return False
            host._set_state("startup_purge", blocked_reason="verifying_clear")
            return True

        host._startup_purge_clear_since = None

        if owned_count <= 0:
            ready_for_motion = (
                raw_count > 0
                and not host._hw.busy()
                and float(now_mono) >= float(host._startup_purge_next_prime_at)
            )
            if ready_for_motion:
                step = self.prime_step_deg
                budget_left = host._startup_purge_prime_moves < self._max_prime_moves
                label = (
                    "c4_startup_purge_prime"
                    if budget_left
                    else "c4_startup_purge_sweep"
                )

                def _do_prime() -> None:
                    try:
                        host._startup_purge_move(step)
                    except Exception:
                        host._logger.exception(
                            "RuntimeC4: startup purge motion raised"
                        )

                if host._hw.enqueue(_do_prime, label=label):
                    host._startup_purge_prime_moves += 1
                    host._startup_purge_next_prime_at = (
                        now_mono + self.prime_cooldown_s
                    )
                    host._set_state(
                        "startup_purge",
                        blocked_reason=None if budget_left else "sweeping_unowned",
                    )
                    return True
                host._set_state("startup_purge", blocked_reason="hw_queue_full")
                return True

            if self.can_finish(
                raw_detection_count=raw_count,
                owned_piece_count=owned_count,
                prime_moves=host._startup_purge_prime_moves,
                clear_since=host._startup_purge_clear_since,
                now_mono=now_mono,
            ):
                host._logger.info(
                    "RuntimeC4: startup purge completed with %d raw detection(s) left unowned",
                    raw_count,
                )
                host._startup_purge_armed = False
                host._exit_startup_purge()
                return False
            host._set_state("startup_purge", blocked_reason="awaiting_track_lock")
            return True

        exit_track = host._pick_exit_track(owned_tracks)
        if exit_track is not None and exit_track.global_id is not None:
            if host._hw.busy():
                host._set_state("startup_purge", blocked_reason="hw_busy")
                return True
            piece_uuid = host._track_to_piece.get(int(exit_track.global_id))
            if piece_uuid is None:
                host._set_state("startup_purge", blocked_reason="track_unowned")
                return True
            try:
                timing = host._ejection.timing_for(
                    {
                        "piece_uuid": piece_uuid,
                        "startup_purge": True,
                        "accepted": False,
                    }
                )
                fall_time_s = max(0.0, float(timing.fall_time_ms) / 1000.0)
            except Exception:
                host._logger.exception(
                    "RuntimeC4: startup purge timing_for raised; using no fall-time"
                )
                fall_time_s = 0.0

            host._startup_purge_eject_ok = None

            def _do_purge_eject() -> None:
                try:
                    host._startup_purge_eject_ok = bool(host._eject())
                except Exception:
                    host._logger.exception("RuntimeC4: startup purge eject raised")
                    host._startup_purge_eject_ok = False

            if not host._hw.enqueue(_do_purge_eject, label="c4_startup_purge_eject"):
                host._set_state("startup_purge", blocked_reason="hw_queue_full")
                return True
            host._startup_purge_commit_piece_uuid = piece_uuid
            host._startup_purge_commit_deadline = now_mono + fall_time_s
            host._set_state("startup_purge", blocked_reason="ejecting")
            return True

        transport_active = host._maybe_advance_transport(
            owned_tracks,
            now_mono,
            move_command=host._startup_purge_move,
        )
        if transport_active:
            host._set_state("startup_purge")
        else:
            host._set_state("startup_purge", blocked_reason="awaiting_exit")
        return True


__all__ = ["C4StartupPurgeStrategy"]
