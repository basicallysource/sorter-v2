import time
from dataclasses import replace
from typing import TYPE_CHECKING

from states.base_state import BaseState
from subsystems.shared_variables import SharedVariables
from subsystems.bus import StationId
from irl.config import IRLInterface, IRLConfig
from global_config import GlobalConfig
from vision import VisionManager

from .config import (
    PulsePerceptionConfig,
    channelMaxMoveOutputDeg,
    channelMoveSpeed,
)
from . import landing_hold
from .blind_arc import BlindArc, forward
from .dispense_gate import DispenseGate
from .exit_step import ExitStep, exitStep
from .held import FreeTurn, HeldAtLanding, HeldPieces

# A deliberately simple pulsing state machine on the new perception stack.
#
# It reads ChannelState booleans from the perception service (exactly like the
# go-to-angle flow's perception path) and, per channel, does one of three
# things each tick:
#   - piece in the EXIT zone + downstream ready   -> pulse exit_pulse_output_deg,
#                                                     pause exit_pulse_pause_ms
#   - piece in the EXIT zone + downstream NOT ready -> hold still (never pulse a
#                                                     piece off the edge into a
#                                                     busy downstream channel)
#   - piece in the DROP zone only                 -> pulse drop_pulse_output_deg,
#                                                     pause drop_pulse_pause_ms
#   - empty channel                               -> idle
#
# No fast-eject, no COM closed loop, no jitter recovery — that all lives in the
# go-to-angle flow. "The other stack will be removed in time"; this is the
# minimal perception-native feeder.

if TYPE_CHECKING:
    from hardware.sorter_interface import StepperMotor

# Motor-shaft to channel-output gear ratio. One output (LEGO wheel) degree
# requires this many motor degrees. Matches the go-to-angle flow's constant.
CHANNEL_OUTPUT_GEAR_RATIO = 130.0 / 12.0

# Minimum stepper speed floor for pulse moves. MUST stay > 0: a min_speed of 0
# wedges the firmware on a distance move — braking clamps _current_speed to 0
# before the step target is reached, the move never transitions back to STOPPED,
# and every subsequent move_steps is rejected (motor frozen until a manual UI
# move re-stops it). 16 matches the firmware default and the exit-pulse path in
# detection.py.
MIN_MOVE_SPEED_USTEPS_PER_S = 16

# Re-read the tuning config from disk at most this often so the tuning page
# takes effect live without a restart, without hammering the filesystem.
_CONFIG_TTL_S = 1.0


class PulsePerceptionFeeding(BaseState):
    def __init__(
        self,
        irl: IRLInterface,
        irl_config: IRLConfig,
        gc: GlobalConfig,
        shared: SharedVariables,
        vision: VisionManager,
    ):
        super().__init__(irl, gc)
        self.irl_config = irl_config
        self.shared = shared
        self.vision = vision
        self._busy_until: dict[str, float] = {}
        self._config: PulsePerceptionConfig = PulsePerceptionConfig()
        self._config_loaded_at: float = 0.0
        # One piece per hand-off: C2 into C3, C3 into the classification channel.
        self._gates: dict[int, DispenseGate] = {2: DispenseGate(), 3: DispenseGate()}
        # Output degrees each channel has been moved forward, and the pieces
        # it carries through the part of its ring its camera cannot see.
        self._odometer: dict[int, float] = {1: 0.0, 2: 0.0, 3: 0.0}
        self._blind: dict[int, BlindArc] = {2: BlindArc(), 3: BlindArc()}
        # Pieces their own channel cannot move (held.py).
        self._held = HeldPieces(gc)
        # Per-channel monotonic timestamp of the last frame that reported a piece
        # in the drop zone. Drives the C2/C3 drop-zone occupancy latch.
        self._drop_seen_at: dict[int, float] = {}
        # One piece in the opening at a time (exit_step.py): when each channel's
        # last move ends (wall clock, like a frame's time), the forward stroke a
        # shake still owes, and the back-offs and shakes made for the lead.
        self._moved_until: dict[int, float] = {}
        self._shake_owed: dict[int, float] = {}
        self._exit_tries: dict[int, tuple[int | None, int]] = {}

    def _cfg(self) -> PulsePerceptionConfig:
        now = time.monotonic()
        if now - self._config_loaded_at >= _CONFIG_TTL_S:
            try:
                from toml_config import getPulsePerceptionConfig
                from .config import configFromDict
                self._config = configFromDict(getPulsePerceptionConfig())
            except Exception as exc:
                self.gc.logger.warning(f"PulsePerception: config load failed: {exc}")
            self._config_loaded_at = now
        return self._config

    def _busy(self, stepper: "StepperMotor") -> bool:
        return time.monotonic() < self._busy_until.get(stepper._name, 0.0)

    def _move(
        self,
        label: str,
        channel: int,
        stepper: "StepperMotor",
        output_deg: float,
        pause_ms: int,
        cfg: PulsePerceptionConfig,
        enforce_min: bool = True,
        backwards: bool = False,
    ) -> bool:
        # The window is the ramp-aware move time plus the pause, so the pause
        # follows the end of the move; the board's own stopped state is the
        # check, since the firmware refuses a pulse on an axis still moving.
        if self._busy(stepper) or not stepper.stopped:
            return False
        speed = channelMoveSpeed(cfg, channel)
        output_deg = abs(output_deg)
        if enforce_min:
            output_deg = max(cfg.min_move_output_deg, output_deg)
        output_deg = min(channelMaxMoveOutputDeg(cfg, channel), output_deg)
        sign = 1 if cfg.forward_direction_sign >= 0 else -1
        if backwards:
            sign = -sign
        motor_deg = sign * output_deg * CHANNEL_OUTPUT_GEAR_RATIO
        # Set the move speed and tell the motor to move to the angle — that's it.
        # We NEVER set acceleration here; the motor keeps whatever acceleration it
        # already has.
        try:
            stepper.set_speed_limits(MIN_MOVE_SPEED_USTEPS_PER_S, speed)
        except Exception as exc:
            self.gc.logger.warning(f"PulsePerception: {label} speed set failed: {exc}")
        success = stepper.move_degrees(motor_deg)
        exec_ms = stepper.estimateMoveDegreesMs(abs(motor_deg), max_speed=speed or 5000)
        if success:
            self._odometer[channel] = self._odometer.get(channel, 0.0) + (-output_deg if backwards else output_deg)
            self.shared.feeder_moving_until[channel] = time.monotonic() + max(0, exec_ms) / 1000.0
            self._moved_until[channel] = time.time() + max(0, exec_ms) / 1000.0
        cooldown_ms = (max(0, exec_ms) + max(0, pause_ms)) if success else 500
        self._busy_until[stepper._name] = time.monotonic() + cooldown_ms / 1000.0
        self.gc.logger.debug(
            f"PulsePerception: {label} pulse ch={channel} speed={speed} "
            f"output={output_deg:.1f}° motor={motor_deg:.1f}° "
            f"success={success} exec_ms={exec_ms} pause_ms={pause_ms}"
        )
        return success

    def _noteFall(self, channel: int, gate: DispenseGate) -> None:
        # Which piece fell off the exit, so the landing that follows can be timed.
        if gate.fell_track_id is None:
            return
        from zones import watch

        watch.noteFall(channel, gate.fell_track_id)

    def _on_ch3_dispense(self) -> None:
        try:
            from .autotune import noteDispense
            noteDispense()
        except Exception:
            pass
        if hasattr(self.shared, "publish_piece_delivered"):
            try:
                self.shared.publish_piece_delivered(
                    source=StationId.C3,
                    target=StationId.CLASSIFICATION,
                    delivered_at_mono=time.monotonic(),
                )
            except Exception:
                pass

    def _classification_ready(self, cfg: PulsePerceptionConfig) -> bool:
        if not cfg.gate_ch3_on_classification_ready:
            return True
        return bool(self.shared.classification_ready)

    def _gate(self, channel: int, cfg: PulsePerceptionConfig) -> DispenseGate:
        gate = self._gates[channel]
        gate.vanish_confirm_s = max(0, cfg.dispense_vanish_confirm_ms) / 1000.0
        gate.hold_s = landing_hold.get().holdS(
            channel,
            max(0, cfg.dispense_hold_ms) / 1000.0,
            cfg.hold_follows_landings,
            time.monotonic(),
        )
        return gate

    def _latch_drop(self, ch: int, state, now: float, cfg: PulsePerceptionConfig):
        """Persist drop-zone occupancy for one feeder channel.

        Once a piece is seen in the drop zone we consider the zone occupied for
        ``drop_zone_persistence_ms`` after the last positive frame — a one/two
        frame detection dropout no longer reads as 'empty'. Only ``in_drop`` is
        latched; the exit fields pass through untouched so exit handling still
        sees the live state. 0 disables the latch."""
        window_ms = cfg.drop_zone_persistence_ms
        if window_ms <= 0:
            return state
        if state.in_drop:
            self._drop_seen_at[ch] = now
            return state
        last = self._drop_seen_at.get(ch)
        if last is not None and (now - last) * 1000.0 <= window_ms:
            return replace(state, in_drop=True)
        return state

    def step(self) -> None:
        cfg = self._cfg()

        # The feeder runs while the chute moves: nothing it does puts a piece
        # in the chute. The classification channel ejects only once the chute
        # is aimed.
        perception_service = getattr(self.gc, "perception_service", None)
        if perception_service is None:
            return

        from perception.cascade import Action, feederChannelAction, c1Action
        from perception.state import EMPTY_STATE

        states = perception_service.read_states()
        c2 = states.get(2, EMPTY_STATE)
        c3 = states.get(3, EMPTY_STATE)

        now_mono = time.monotonic()
        # Hold C2/C3 drop-zone occupancy across brief detector dropouts so the
        # per-channel action (and the ``not c3.in_drop`` upstream gate below) see
        # a stable "occupied" instead of flickering empty for a frame.
        c2 = self._latch_drop(2, c2, now_mono, cfg)
        c3 = self._latch_drop(3, c3, now_mono, cfg)

        # A piece its own channel cannot move rests on the channel next to it.
        # Where pieces land it hangs off the channel above: its incident holds
        # the machine while a recovery procedure frees it. At the exit, the
        # channel below turns a little.
        for channel, state in ((3, c3), (2, c2)):
            turn = self._held.check(
                channel, state, self._odometer.get(channel, 0.0), now_mono, self._frameSize(channel)
            )
            if isinstance(turn, HeldAtLanding):
                if self._reportHeld(turn, cfg):
                    return
                continue
            if turn is not None and self._canFreeTurn(turn, c3, cfg):
                if self._move(
                    f"ch{turn.channel}_free",
                    turn.channel,
                    self._rotor(turn.channel),
                    turn.degrees,
                    cfg.drop_pulse_pause_ms,
                    cfg,
                    enforce_min=False,
                ):
                    self._held.turned(turn, now_mono)

        if cfg.enable_ch3:
            # C3's downstream is the classification channel (C4). The feeder does
            # NOT define "ready" itself — that determination is owned and exposed
            # by the classification channel (shared.classification_ready, set per
            # its active mode: single-piece = whole channel empty, two-piece = drop
            # zone clear). The feeder just asks. The only feeder-side gate is the
            # hand-off: once a piece falls, C3 pushes nothing more off for a
            # while, so C4 sees it before the next one can follow.
            gate3 = self._gate(3, cfg)
            if gate3.observe(c3, now_mono):
                self._on_ch3_dispense()
                self._noteFall(3, gate3)
            action = feederChannelAction(
                c3,
                downstream_clear=self._classification_ready(cfg) and gate3.exitAllowed(now_mono),
                greedy=cfg.ch3_greedy_enabled,
            )
            action, hidden_cap = self._withHiddenPieces(3, c3, action, now_mono, cfg)
            self._apply_action(
                "ch3", 3, action, self.irl.c_channel_3_rotor_stepper, c3, cfg, hidden_cap
            )

        if cfg.enable_ch2:
            # C2's downstream is C3. "Clear" = C3's drop zone is not occupied,
            # so we never pulse a C2 piece off the edge into a busy C3; and once
            # a piece falls, nothing more goes for a while, so C3 sees it land.
            gate2 = self._gate(2, cfg)
            if gate2.observe(c2, now_mono):
                self._noteFall(2, gate2)
            action = feederChannelAction(
                c2,
                downstream_clear=(not c3.in_drop)
                and gate2.exitAllowed(now_mono)
                and self._hasRoom(3, c3, cfg.ch3_max_pieces),
                greedy=cfg.ch2_greedy_enabled,
            )
            action, hidden_cap = self._withHiddenPieces(2, c2, action, now_mono, cfg)
            self._apply_action(
                "ch2", 2, action, self.irl.c_channel_2_rotor_stepper, c2, cfg, hidden_cap
            )

        if cfg.enable_ch1:
            # C1 has no exit zone of its own; it just advances unless C2's drop
            # zone is occupied.
            stepper = self.irl.c_channel_1_rotor_stepper
            if (
                c1Action(c2) == Action.ADVANCE
                and self._hasRoom(2, c2, cfg.ch2_max_pieces)
                and not self._busy(stepper)
            ):
                self._move(
                    "ch1",
                    1,
                    stepper,
                    cfg.ch1_pulse_output_deg,
                    cfg.ch1_pulse_pause_ms,
                    cfg,
                )

    def _frameSize(self, channel: int) -> tuple[int, int] | None:
        perception_service = getattr(self.gc, "perception_service", None)
        channel_def = perception_service.channels().get(channel) if perception_service else None
        mask = getattr(channel_def, "mask", None)
        return (int(mask.shape[1]), int(mask.shape[0])) if mask is not None else None

    def _reportHeld(self, held: HeldAtLanding, cfg: PulsePerceptionConfig) -> bool:
        """Open the piece_held incident for a piece held where pieces land and,
        when the machine is to handle it, start freeing it (recovery/). True
        when the incident is open: it holds the machine from now on."""
        import incidents
        import recovery
        from recovery.judges import pieceGoneFrom

        mode = incidents.handling("piece_held")
        if mode == incidents.OFF:
            return False
        label = f"C{held.channel}"
        if not incidents.report(
            self.gc,
            "piece_held",
            subject=label,
            channel=f"c{held.channel}",
            channel_label=label,
            track_id=held.track_id,
            box=list(held.box),
        ):
            return False
        if mode == incidents.AUTOMATIC:
            recovery.start(
                self.gc,
                "landing_held",
                kind="piece_held",
                motors={
                    "this": self._recoveryMotor(held.channel, cfg),
                    "above": self._recoveryMotor(held.channel - 1, cfg),
                },
                judge=pieceGoneFrom(self.gc.perception_service, held.channel, held.box),
            )
        return True

    def _recoveryMotor(self, channel: int, cfg: PulsePerceptionConfig):
        from recovery.motors import ChannelMotor, gearedMicrosteps

        stepper = self._rotor(channel)
        sign = 1 if cfg.forward_direction_sign >= 0 else -1
        return ChannelMotor(
            f"C{channel}",
            stepper,
            gearedMicrosteps(stepper, CHANNEL_OUTPUT_GEAR_RATIO, sign),
            speed=channelMoveSpeed(cfg, channel),
        )

    def _hasRoom(self, channel: int, state, most: int) -> bool:
        """Fewer than ``most`` pieces on the channel, counting the ones it is
        known to hold out of sight (0 = no limit)."""
        if most <= 0:
            return True
        hidden = int(self.shared.feeder_hidden_pieces.get(channel, 0) or 0)
        return int(getattr(state, "n_pieces", 0) or 0) + hidden < most

    def _rotor(self, channel: int) -> "StepperMotor":
        return {
            1: self.irl.c_channel_1_rotor_stepper,
            2: self.irl.c_channel_2_rotor_stepper,
            3: self.irl.c_channel_3_rotor_stepper,
        }[channel]

    def _canFreeTurn(self, turn: FreeTurn, c3, cfg: PulsePerceptionConfig) -> bool:
        if not getattr(cfg, f"enable_ch{turn.channel}", True):
            return False
        # Turning C3 with a piece at its own edge would drop that piece on the
        # classification channel out of turn: wait until C3's edge is clear.
        return not (turn.channel == 3 and c3.in_exit)

    def _apply_action(
        self,
        label: str,
        channel: int,
        action,
        stepper: "StepperMotor",
        state,
        cfg: PulsePerceptionConfig,
        hidden_cap: float | None = None,
    ) -> None:
        from perception.cascade import Action

        if self._busy(stepper):
            return
        # A shake goes backwards, then forward as far: finish it first, so the
        # pieces end where they were.
        owed = self._shake_owed.get(channel)
        if owed is not None:
            if self._move(f"{label}_exit_shake", channel, stepper, owed, cfg.exit_pulse_pause_ms, cfg, enforce_min=False):
                del self._shake_owed[channel]
            return
        if action == Action.ADVANCE:
            # Free advance pulse, but never push the most-forward piece off the
            # edge into the exit zone: cap the move to its forward clearance to
            # the exit edge. Once a piece reaches the exit, the PRECISE/FREEZE
            # branch (gated on downstream readiness) meters it out instead.
            # A piece still in the drop zone uses the drop-zone params; a greedy
            # advance of a piece that has already left the drop zone uses the
            # greedy params (only reachable when greedy mode is on for this
            # channel — the cascade returns IDLE here otherwise).
            if state.in_drop:
                output_deg = cfg.drop_pulse_output_deg
                pause_ms = cfg.drop_pulse_pause_ms
                move_label = f"{label}_drop"
            else:
                output_deg = cfg.greedy_pulse_output_deg
                pause_ms = cfg.greedy_pulse_pause_ms
                move_label = f"{label}_greedy"
            enforce_min = True
            clearance = getattr(state, "advance_clearance_deg", None)
            if clearance is not None and channel == 3 and not self._classification_ready(cfg):
                # C4 is busy: keep the lead piece back from the lip, where it
                # could fall onto C4 mid-turn beside the piece already there.
                clearance -= max(0.0, cfg.ch3_busy_standoff_deg)
                if clearance < cfg.min_move_output_deg:
                    return
            if clearance is not None and clearance < output_deg:
                output_deg = clearance
                enforce_min = False
            # Nor may a piece the camera cannot see be carried past the
            # staging point unseen. A cap of nothing is no cap: the expectation
            # is then wrong, and a channel that never moves never finds out.
            if hidden_cap is not None and 0 < hidden_cap < output_deg:
                output_deg = hidden_cap
                enforce_min = False
            self._move(
                move_label,
                channel,
                stepper,
                output_deg,
                pause_ms,
                cfg,
                enforce_min=enforce_min,
            )
        elif action == Action.PRECISE:
            step = self._exitStep(channel, state, cfg)
            if step is None:
                return
            moved = self._move(
                f"{label}_exit" if step.kind == "push" else f"{label}_exit_{step.kind}",
                channel,
                stepper,
                step.deg,
                cfg.exit_pulse_pause_ms,
                cfg,
                enforce_min=False,
                backwards=step.kind != "push",
            )
            if not moved:
                return
            pieces = getattr(state, "pieces", ())
            lead = pieces[0] if pieces else None
            if step.kind == "shake":
                self._shake_owed[channel] = step.deg
            if step.kind != "push" or step.why:
                self._noteExitStep(channel, lead, pieces[1] if len(pieces) > 1 else None, step)
            if channel in self._gates:
                self._gates[channel].notePush(lead)
        # IDLE / FREEZE: no move.

    def _exitStep(self, channel: int, state, cfg: PulsePerceptionConfig) -> ExitStep | None:
        """The exit's next move: a push, or with the lead in the opening and the
        next piece close behind it, a back-off or a shake (exit_step.py). None
        while the newest picture was taken before the last move ended."""
        push = self._exitMoveDeg(channel, state, cfg)
        clear = float(getattr(cfg, f"ch{channel}_exit_next_clear_deg", 0.0) or 0.0)
        if clear <= 0:
            return ExitStep("push", push)
        if float(getattr(state, "ts", 0.0) or 0.0) < self._moved_until.get(channel, 0.0):
            return None
        pieces = getattr(state, "pieces", ()) or ()
        if not pieces:
            return ExitStep("push", push)
        lead_id = getattr(pieces[0], "sv_bt_track_id", None)
        tried_id, tries = self._exit_tries.get(channel, (None, 0))
        if tried_id != lead_id:
            tries = 0
        return exitStep(
            float(pieces[0].com_forward_to_exit_deg),
            float(pieces[1].com_forward_to_exit_deg) if len(pieces) > 1 else None,
            push,
            cfg.exit_pulse_output_deg,
            clear,
            tries,
        )

    def _noteExitStep(self, channel: int, lead, behind, step: ExitStep) -> None:
        """Count a back-off or shake against the lead, and log every move the
        rule made or let through to the control data, so its effect can be
        measured."""
        lead_id = getattr(lead, "sv_bt_track_id", None)
        if step.kind != "push":
            tried_id, tries = self._exit_tries.get(channel, (None, 0))
            self._exit_tries[channel] = (lead_id, (tries if tried_id == lead_id else 0) + 1)
        try:
            import control_data_store

            control_data_store.record(
                {
                    "type": "event",
                    "kind": "exit_step",
                    "what": step.kind,
                    "why": step.why,
                    "ch": channel,
                    "track": lead_id,
                    "deg": round(step.deg, 2),
                    "lead_deg": round(float(getattr(lead, "com_forward_to_exit_deg", 0.0)), 2),
                    "next_deg": round(float(getattr(behind, "com_forward_to_exit_deg", 0.0)), 2) if behind else None,
                    "t": time.time(),
                    "mono": time.monotonic(),
                }
            )
        except Exception:
            pass

    def _withHiddenPieces(self, channel: int, state, action, now: float, cfg: PulsePerceptionConfig):
        """Keep advancing while a piece rides the part of the ring the camera
        cannot see, and cap the advance so it cannot come out of there and run
        past the staging point unseen. Returns (action, cap or None)."""
        from perception.arcs import exitNearEdgeSection
        from perception.cascade import Action

        blind = self._blind[channel]
        blind.start_deg = getattr(cfg, f"ch{channel}_blind_arc_start_deg")
        blind.end_deg = getattr(cfg, f"ch{channel}_blind_arc_end_deg")
        odometer = self._odometer.get(channel, 0.0)
        blind.update(state, now, odometer)
        expected = blind.expected(odometer)
        self.shared.feeder_hidden_pieces[channel] = len(expected)
        if not expected:
            return action, None
        perception_service = getattr(self.gc, "perception_service", None)
        channel_def = perception_service.channels().get(channel) if perception_service else None
        near = exitNearEdgeSection(channel_def) if channel_def is not None else None
        if near is None:
            return action, None
        cap = min(forward(pos, float(near)) for pos in expected) - cfg.exit_move_margin_deg
        greedy = getattr(cfg, f"ch{channel}_greedy_enabled")
        if action == Action.IDLE and greedy:
            action = Action.ADVANCE
        return action, cap

    def _exitMoveDeg(self, channel: int, state, cfg: PulsePerceptionConfig) -> float:
        """One exit move: as far as it takes to drop the lead piece, up to
        exit_move_max_deg, but never so far that a piece behind it reaches the
        exit. With a piece close behind, that is the small exit pulse."""
        small = cfg.exit_pulse_output_deg
        if cfg.exit_move_max_deg <= small:
            return small
        pieces = getattr(state, "pieces", ())
        if len(pieces) < 2:
            return cfg.exit_move_max_deg
        perception_service = getattr(self.gc, "perception_service", None)
        channel_def = perception_service.channels().get(channel) if perception_service else None
        if channel_def is None:
            return small
        from perception.arcs import forwardGapToExitDeg

        room = min(forwardGapToExitDeg(p.bbox, channel_def) for p in pieces[1:])
        return max(small, min(cfg.exit_move_max_deg, room - cfg.exit_move_margin_deg))

    def cleanup(self) -> None:
        for blind in self._blind.values():
            blind.clear()
        self._held.reset()
        super().cleanup()
