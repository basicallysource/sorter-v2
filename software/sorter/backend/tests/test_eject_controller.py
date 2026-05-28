"""EjectController state-machine transitions (closed-loop eject + fall recovery).

Pure-logic tests: the controller is driven with synthetic ChannelStates, a fake
stepper, and recorded callbacks — no hardware, no perception workers. The
harness models a piece whose ACTUAL forward gap to the exit zone shrinks by only
a FRACTION of each commanded move (simulated slippage), so the closed-loop
re-measurement is exercised the way it is on the machine.
"""

from dataclasses import dataclass, field

from perception.state import ChannelState
from subsystems.feeder.go_to_angle.config import GoToAngleConfig
from subsystems.feeder.go_to_angle.eject import EjectController, EjectPhase


class _SilentLogger:
    def info(self, *a, **k) -> None: ...
    def warning(self, *a, **k) -> None: ...
    def error(self, *a, **k) -> None: ...


class _FakeStepper:
    def __init__(self) -> None:
        self.jitter_calls = 0
        self._jittering = False

    def jitter_degrees(self, *args, **kwargs) -> bool:
        self.jitter_calls += 1
        self._jittering = True
        return True

    def is_jittering(self) -> bool:
        return self._jittering

    def finish_jitter(self) -> None:
        self._jittering = False


_MOVE_DURATION_S = 0.3


@dataclass
class _Harness:
    ctrl: EjectController
    stepper: _FakeStepper
    moves: list = field(default_factory=list)      # commanded step sizes (deg)
    successes: list = field(default_factory=list)
    now: list = field(default_factory=lambda: [100.0])
    gap: list = field(default_factory=lambda: [20.0])   # true forward gap (deg)
    move_done_at: list = field(default_factory=lambda: [0.0])
    slip: list = field(default_factory=lambda: [0.5])   # fraction of cmd actually moved
    present: list = field(default_factory=lambda: [True])
    in_precise: list = field(default_factory=lambda: [True])  # COM in precise zone

    def advance(self, dt: float) -> None:
        self.now[0] += dt

    def state(self) -> ChannelState:
        g = self.gap[0]
        present = self.present[0]
        return ChannelState(
            ts=1.0,
            in_drop=False,
            in_exit=present and g <= 0.0,
            n_pieces=1 if present else 0,
            exit_com_forward_deg=(g if present else None),
            exit_com_in_precise=present and self.in_precise[0],
        )

    def tick(self, *, down: int = 0, ready: bool = True, cfg: GoToAngleConfig) -> bool:
        downstream = ChannelState(ts=1.0, in_drop=False, in_exit=False, n_pieces=down)
        return self.ctrl.tick(
            state=self.state(),
            downstream=downstream,
            downstream_ready=ready,
            cfg=cfg,
            now=self.now[0],
        )


def _make(start_gap: float = 20.0, slip: float = 0.5, in_precise: bool = True) -> _Harness:
    h = _Harness(ctrl=None, stepper=_FakeStepper())  # type: ignore[arg-type]
    h.gap[0] = start_gap
    h.slip[0] = slip
    h.in_precise[0] = in_precise

    def advance_move(step: float) -> bool:
        h.moves.append(step)
        h.gap[0] -= h.slip[0] * step
        h.move_done_at[0] = h.now[0] + _MOVE_DURATION_S
        return True

    h.ctrl = EjectController(
        channel_id=3,
        stepper=h.stepper,
        is_stopped=lambda: h.now[0] >= h.move_done_at[0],
        advance_move=advance_move,
        on_success=lambda: h.successes.append(h.now[0]),
        logger=_SilentLogger(),
    )
    return h


def _cfg(**over) -> GoToAngleConfig:
    cfg = GoToAngleConfig()
    for k, v in over.items():
        setattr(cfg, k, v)
    return cfg


def _run_advance(h: _Harness, cfg: GoToAngleConfig, max_ticks: int = 60) -> None:
    """Tick until the controller leaves ADVANCING (or runs out of ticks),
    advancing time between ticks so each queued move 'completes'."""
    for _ in range(max_ticks):
        h.tick(cfg=cfg)
        if h.ctrl.phase != EjectPhase.ADVANCING:
            return
        h.advance(_MOVE_DURATION_S)


# --- IDLE -------------------------------------------------------------------


def test_idle_passes_when_piece_not_yet_in_precise_zone() -> None:
    # COM short of the precise zone (gap>0, not in precise) → controller must NOT
    # take the tick; the normal advance carries the piece in.
    h = _make(start_gap=40.0, in_precise=False)
    consumed = h.tick(cfg=_cfg())
    assert consumed is False
    assert h.ctrl.phase == EjectPhase.IDLE
    assert h.moves == []


def test_idle_triggers_when_com_in_precise_zone() -> None:
    # Same gap, but the COM is now in the precise zone → eject starts.
    h = _make(start_gap=40.0, in_precise=True)
    h.tick(cfg=_cfg())
    assert h.ctrl.phase == EjectPhase.ADVANCING


def test_idle_passes_when_no_piece() -> None:
    h = _make()
    h.present[0] = False
    assert h.tick(cfg=_cfg()) is False


def test_within_trigger_but_downstream_busy_holds() -> None:
    h = _make(start_gap=5.0)
    consumed = h.tick(down=0, ready=False, cfg=_cfg())
    assert consumed is True
    assert h.ctrl.phase == EjectPhase.IDLE  # holding, no move issued
    assert h.moves == []


# --- ADVANCING (closed loop + slippage) ------------------------------------


def test_advances_proportionally_and_reaches_exit() -> None:
    h = _make(start_gap=20.0, slip=0.5)
    cfg = _cfg(fast_eject_min_step_deg=2.0)
    _run_advance(h, cfg)
    assert h.ctrl.phase == EjectPhase.AWAITING_FALL
    assert h.gap[0] <= 0.0
    # Multiple moves were needed (slippage), and commanded steps shrank as the
    # measured gap closed — proving re-measurement each iteration.
    assert len(h.moves) >= 3
    assert h.moves[0] > h.moves[-1]


def test_advance_freezes_when_downstream_goes_busy() -> None:
    h = _make(start_gap=20.0)
    cfg = _cfg()
    h.tick(cfg=cfg)  # IDLE → ADVANCING, first move
    assert h.ctrl.phase == EjectPhase.ADVANCING
    n_before = len(h.moves)
    h.advance(_MOVE_DURATION_S)
    consumed = h.tick(ready=False, cfg=cfg)  # downstream busy mid-approach
    assert consumed is True
    assert len(h.moves) == n_before  # no new move while frozen


def test_advance_safety_cap_kicks_to_recovery() -> None:
    # Total slip (piece never moves) → gap never closes → safety cap fires.
    h = _make(start_gap=20.0, slip=0.0)
    cfg = _cfg(fast_eject_max_advance_iterations=3)
    _run_advance(h, cfg)
    assert h.ctrl.phase == EjectPhase.RECOVERING
    assert h.stepper.jitter_calls == 1


# --- AWAITING_FALL ----------------------------------------------------------


def test_success_only_on_downstream_appearance() -> None:
    h = _make(start_gap=20.0)
    cfg = _cfg(fall_confirm_timeout_ms=700)
    _run_advance(h, cfg)
    assert h.ctrl.phase == EjectPhase.AWAITING_FALL
    # Piece still sits in our exit (gap<=0) but nothing downstream → NOT success.
    h.advance(0.1)
    h.tick(down=0, cfg=cfg)
    assert h.ctrl.phase == EjectPhase.AWAITING_FALL
    assert h.successes == []
    # Downstream count rises → success.
    consumed = h.tick(down=1, cfg=cfg)
    assert consumed is True
    assert h.ctrl.phase == EjectPhase.IDLE
    assert len(h.successes) == 1


def test_timeout_starts_jitter_recovery() -> None:
    h = _make(start_gap=20.0)
    cfg = _cfg(fall_confirm_timeout_ms=200, fall_recovery_max_jitter_attempts=2)
    _run_advance(h, cfg)
    assert h.ctrl.phase == EjectPhase.AWAITING_FALL
    h.advance(0.3)  # > timeout
    consumed = h.tick(down=0, cfg=cfg)
    assert consumed is True
    assert h.ctrl.phase == EjectPhase.RECOVERING
    assert h.stepper.jitter_calls == 1


# --- RECOVERING -------------------------------------------------------------


def test_recovery_success_on_downstream() -> None:
    h = _make(start_gap=20.0)
    cfg = _cfg(fall_confirm_timeout_ms=100, fall_recovery_max_jitter_attempts=3)
    _run_advance(h, cfg)
    h.advance(0.2)
    h.tick(down=0, cfg=cfg)  # → RECOVERING
    assert h.ctrl.phase == EjectPhase.RECOVERING
    consumed = h.tick(down=1, cfg=cfg)  # downstream appears mid-recovery
    assert consumed is True
    assert h.ctrl.phase == EjectPhase.IDLE
    assert len(h.successes) == 1


def test_recovery_reapproaches_if_piece_knocked_out_of_exit() -> None:
    h = _make(start_gap=20.0)
    cfg = _cfg(fall_confirm_timeout_ms=100)
    _run_advance(h, cfg)
    h.advance(0.2)
    h.tick(down=0, cfg=cfg)  # → RECOVERING
    assert h.ctrl.phase == EjectPhase.RECOVERING
    # Jitter knocked the piece back out of the exit zone (gap positive again).
    h.gap[0] = 6.0
    h.tick(down=0, cfg=cfg)
    assert h.ctrl.phase == EjectPhase.ADVANCING


def test_recovery_exhausts_and_assumes_glitch() -> None:
    h = _make(start_gap=20.0)
    cfg = _cfg(
        fall_confirm_timeout_ms=100,
        fall_recovery_max_jitter_attempts=2,
        jitter_pause_ms=50,
    )
    _run_advance(h, cfg)
    h.gap[0] = -1.0  # piece sits in exit, never falls, never appears downstream
    h.advance(0.2)
    h.tick(down=0, cfg=cfg)  # → RECOVERING, jitter #1
    assert h.stepper.jitter_calls == 1
    for _ in range(40):
        if h.ctrl.phase != EjectPhase.RECOVERING:
            break
        h.stepper.finish_jitter()
        h.advance(0.1)  # > jitter_pause_ms
        h.tick(down=0, cfg=cfg)
    assert h.ctrl.phase == EjectPhase.IDLE
    assert h.stepper.jitter_calls == 2  # max_attempts, then give up
    assert h.successes == []
