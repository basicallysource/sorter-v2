import time
from dataclasses import replace
from typing import TYPE_CHECKING

from states.base_state import BaseState
from subsystems.shared_variables import SharedVariables
from subsystems.bus import StationId
from irl.config import IRLInterface, IRLConfig
from global_config import GlobalConfig
from vision import VisionManager
from hardware_settings.feeder import GEARED_RATIO
from hardware_settings.generation import machineGeneration

from .config import (
    PulsePerceptionConfig,
    channelMaxMoveOutputDeg,
    channelMoveSpeed,
)
from . import landing_hold
from .blind_arc import BlindArc, forward
from .bucket_unjam import BucketUnjam
from .dispense_gate import DispenseGate
from .exit_step import ExitStep, exitStep
from .fall_count import FallCount
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
# Back-offs and shakes at an exit count as one run of tries while none is more
# than this apart (exit_step.MAX_TRIES).
EXIT_TRIES_CALM_S = 5.0
# The smallest move that carries a lead on into the exit while C4 is busy.
_STAGE_MIN_DEG = 4.0
# A piece carried toward C3's exit can start to fall once its center is this
# close to where pieces fall (11/20, clean: the furthest back a piece stood
# before the push that dropped it was 14 degrees).
_EARLIEST_FALL_DEG = 15.0


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
        # Motor degrees per channel (output) degree: the feeder drive's gear
        # ratio, re-read with the config.
        self._gear_ratio: float = GEARED_RATIO
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
        # Per channel: the last exit move was cut short for the piece behind
        # the lead (exit_next_keep_back_deg).
        self._exit_next_close: dict[int, bool] = {}
        self._shake_owed: dict[int, float] = {}
        generation = machineGeneration()
        self._push_only = generation.feeder_push_only
        # C1 shaken and turned when the bucket gives no pieces (bucket_unjam.py).
        self._unjam = (
            BucketUnjam(
                gc,
                shared,
                motor=lambda cfg: self._recoveryMotor(1, cfg),
                hold=self._holdC1,
                record=self._recordControl,
            )
            if generation.bucket_unjam
            else None
        )
        self._fall3 = FallCount()
        self._fall2 = FallCount()
        self._c2_in_drop = False
        # Back-offs and shakes at each channel's exit in a row (none more than
        # EXIT_TRIES_CALM_S apart), and when the last was. Counted for the exit,
        # not one piece: a piece the camera draws as several boxes changes its
        # track number and seems to fall when a box flickers out, and neither
        # may start the count over.
        self._exit_tries: dict[int, tuple[int, float]] = {}
        # When each channel last saw a piece in its exit (monotonic).
        self._exit_seen_at: dict[int, float] = {}
        # For the control-data record only (nothing here decides a move): the
        # decision behind the move about to be made, each exit's last push and
        # its pushes since the last fall, and what each exit last waited on.
        self._move_ctx: dict | None = None
        self._last_push: dict[int, dict] = {}
        self._pushes: dict[int, int] = {}
        self._hold_seen: dict[int, tuple] = {}

    def _cfg(self) -> PulsePerceptionConfig:
        now = time.monotonic()
        if now - self._config_loaded_at >= _CONFIG_TTL_S:
            try:
                from hardware_settings.feeder import feederDrive
                from toml_config import getPulsePerceptionConfig
                from .config import configFromDict
                self._config = configFromDict(getPulsePerceptionConfig())
                self._gear_ratio = feederDrive().gear_ratio
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
        why = self.__dict__.pop("_move_ctx", None)
        if self._busy(stepper) or not stepper.stopped:
            return False
        speed = channelMoveSpeed(cfg, channel)
        output_deg = abs(output_deg)
        asked_deg = output_deg
        if enforce_min:
            output_deg = max(cfg.min_move_output_deg, output_deg)
        output_deg = min(channelMaxMoveOutputDeg(cfg, channel), output_deg)
        sign = 1 if cfg.forward_direction_sign >= 0 else -1
        if backwards:
            sign = -sign
        motor_deg = sign * output_deg * self._gear_ratio
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
        self._recordControl(
            {
                "kind": "feed_move",
                "ch": channel,
                "label": label,
                "deg": round(-output_deg if backwards else output_deg, 2),
                "asked_deg": round(asked_deg, 2),
                "ok": bool(success),
                "exec_ms": exec_ms,
                "pause_ms": pause_ms,
                **(why or {}),
            }
        )
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

    def _on_ch3_dispense(self, record: dict | None = None) -> None:
        self.shared.c3_fell_at = time.monotonic()
        try:
            from .autotune import noteDispense
            noteDispense(record)
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

    def _c4ReadyInTime(self, cfg: PulsePerceptionConfig, c3, now_mono: float) -> bool:
        """Whether C3's lead may be pushed while the classification channel is
        still on the turn that leaves it room: only when the piece cannot land
        before the channel says it will be at rest (c4_ready_at). It lands no
        sooner than C3 takes to carry it to where pieces start to fall, plus
        the shortest fall (ch3_early_push_fall_s; 0 = never push early)."""
        fall_s = float(getattr(cfg, "ch3_early_push_fall_s", 0.0) or 0.0)
        ready_at = getattr(self.shared, "c4_ready_at", None)
        if fall_s <= 0 or ready_at is None or not cfg.gate_ch3_on_classification_ready:
            return False
        pieces = getattr(c3, "pieces", ()) or ()
        if not pieces or pieces[0].com_forward_to_exit_deg is None:
            return False
        travel = max(0.0, float(pieces[0].com_forward_to_exit_deg) - _EARLIEST_FALL_DEG)
        try:
            # The first part of a longer move is covered sooner than a move of
            # just that length, which also brakes: about 0.7 of its time.
            reach_s = 0.7 * self.irl.c_channel_3_rotor_stepper.estimateMoveDegreesMs(travel, cfg.ch3_move_speed_usteps_per_s) / 1000.0
        except Exception:
            return False
        return now_mono + reach_s + fall_s >= float(ready_at)

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
        for channel, state in ((2, c2), (3, c3)):
            if state.in_exit:
                self._exit_seen_at[channel] = now_mono

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
            gone3 = gate3.missing_since
            fell3 = gate3.observe(c3, now_mono)
            if fell3:
                self._on_ch3_dispense(self._fallRecord(3, gate3, gone3, now_mono))
                self._noteFall(3, gate3)
            if self._fall3.observe(c3, now_mono, gate3.fell_track_id, fell3) or fell3:
                # How many pieces that fall took, for the classification
                # channel to tell two pieces from one drawn in parts.
                self.shared.c3_fall = (self._fall3.started, self._fall3.count)
                if self._fall3.count >= 2:
                    self.gc.logger.info(f"PulsePerception: {self._fall3.count} pieces fell off C3 together")
                    self._recordFallCount(3, self._fall3)
            clear3 = {
                "ready": self._classification_ready(cfg) or self._c4ReadyInTime(cfg, c3, now_mono),
                "gate": gate3.exitAllowed(now_mono),
            }
            self._recordHold(3, c3, clear3)
            action = feederChannelAction(
                c3,
                downstream_clear=clear3["ready"] and clear3["gate"],
                greedy=cfg.ch3_greedy_enabled,
            )
            action, hidden_cap = self._withHiddenPieces(3, c3, action, now_mono, cfg)
            self._apply_action(
                "ch3", 3, action, self.irl.c_channel_3_rotor_stepper, c3, cfg, hidden_cap, clear3
            )

        if cfg.enable_ch2:
            # C2's downstream is C3. "Clear" = C3's drop zone is not occupied,
            # so we never pulse a C2 piece off the edge into a busy C3; and once
            # a piece falls, nothing more goes for a while, so C3 sees it land.
            gate2 = self._gate(2, cfg)
            gone2 = gate2.missing_since
            fell2 = gate2.observe(c2, now_mono)
            if fell2:
                self._noteFall(2, gate2)
                self._recordControl({"kind": "c2_dispense", **self._fallRecord(2, gate2, gone2, now_mono)})
            if self._fall2.observe(c2, now_mono, gate2.fell_track_id, fell2):
                if self._fall2.count == 2:
                    self.gc.logger.info("PulsePerception: 2 pieces fell off C2 together")
                self._recordFallCount(2, self._fall2)
            clear2 = {
                "landing_clear": not c3.in_drop,
                "gate": gate2.exitAllowed(now_mono),
                "room": self._hasRoom(3, c3, cfg.ch3_max_pieces),
            }
            self._recordHold(2, c2, clear2)
            action = feederChannelAction(
                c2,
                downstream_clear=clear2["landing_clear"] and clear2["gate"] and clear2["room"],
                greedy=cfg.ch2_greedy_enabled,
            )
            action, hidden_cap = self._withHiddenPieces(2, c2, action, now_mono, cfg)
            self._apply_action(
                "ch2", 2, action, self.irl.c_channel_2_rotor_stepper, c2, cfg, hidden_cap, clear2
            )

        # A piece came off C1: C2's landing zone filled.
        if c2.in_drop and not self._c2_in_drop:
            self.shared.c1_fed_at = now_mono
        self._c2_in_drop = bool(c2.in_drop)

        if cfg.enable_ch1:
            # C1 has no exit zone of its own; it just advances unless C2's drop
            # zone is occupied.
            stepper = self.irl.c_channel_1_rotor_stepper
            wants = c1Action(c2) == Action.ADVANCE and self._hasRoom(2, c2, cfg.ch2_max_pieces)
            if self._unjam is not None:
                try:
                    taken = self._unjam.step(now_mono, wants, cfg)
                except Exception as exc:
                    # Freeing the bucket must never stop the feeder: it is
                    # switched off until the backend starts again.
                    self.gc.logger.error(f"PulsePerception: freeing the bucket failed and is off: {exc!r}")
                    self._unjam = None
                    taken = False
                if taken:
                    # The bucket is being shaken or turned: no pulse of C1's own.
                    return
            if wants and not self._busy(stepper):
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
                "landing_held_still" if self._push_only else "landing_held",
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
            gearedMicrosteps(stepper, self._gear_ratio, sign),
            speed=channelMoveSpeed(cfg, channel),
            gear_ratio=self._gear_ratio,
        )

    def _holdC1(self, until: float) -> None:
        """No pulse of C1's own before ``until`` (monotonic): its motor is on a
        shake or a turn that the bucket's freeing sent."""
        self._busy_until[self._rotor(1)._name] = until

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
        clear: dict | None = None,
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
            latch_s = max(0, int(getattr(cfg, "exit_latch_ms", 0) or 0)) / 1000.0
            if latch_s > 0 and time.monotonic() - self._exit_seen_at.get(channel, float("-inf")) < latch_s:
                # A piece was at the exit a moment ago: one the camera missed for
                # a frame would be pushed off by this advance.
                return
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
            want_deg, cap, standoff = output_deg, None, False
            clearance = getattr(state, "advance_clearance_deg", None)
            if clearance is not None and channel == 3 and not self._classification_ready(cfg):
                # C4 is busy: keep the lead piece back from the lip, where it
                # could fall onto C4 mid-turn beside the piece already there.
                clearance -= max(0.0, cfg.ch3_busy_standoff_deg)
                standoff = cfg.ch3_busy_standoff_deg > 0
                if clearance < cfg.min_move_output_deg:
                    return
            if clearance is not None and clearance < output_deg:
                output_deg = clearance
                enforce_min = False
                cap = "c4_busy_standoff" if standoff else "lead_to_exit"
            # Nor may a piece the camera cannot see be carried past the
            # staging point unseen. A cap of nothing is no cap: the expectation
            # is then wrong, and a channel that never moves never finds out.
            if hidden_cap is not None and 0 < hidden_cap < output_deg:
                output_deg = hidden_cap
                enforce_min = False
                cap = "hidden_piece"
            self._move_ctx = self._moveWhy("advance", state, clear, want_deg, cap)
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
            self._move_ctx = self._moveWhy(
                "precise", state, clear, cfg.exit_move_max_deg, _exitCap(step, state, cfg), what=step.kind, why=step.why
            )
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
            if channel == 3:
                # A piece pushed off now may still be falling: C4 holds its turn.
                self.shared.c3_pushed_at = time.monotonic()
            pieces = getattr(state, "pieces", ())
            lead = pieces[0] if pieces else None
            if step.kind == "shake":
                self._shake_owed[channel] = step.deg
            if step.kind != "push" or step.why:
                self._noteExitStep(channel, lead, pieces[1] if len(pieces) > 1 else None, step)
            if channel in self._gates:
                self._gates[channel].notePush(lead)
            self._notePush(channel, lead, pieces[1] if len(pieces) > 1 else None, step, clear)
        elif action == Action.FREEZE:
            deg = self._stageDeg(channel, state, cfg)
            if deg is not None:
                self._move_ctx = self._moveWhy("stage", state, clear, cfg.exit_move_max_deg, None)
                self._move(f"{label}_stage", channel, stepper, deg, cfg.exit_pulse_pause_ms, cfg, enforce_min=False)
        # IDLE: no move.

    def _recordControl(self, event: dict) -> None:
        try:
            import control_data_store

            control_data_store.record({"type": "event", **event, "t": time.time(), "mono": time.monotonic()})
        except Exception:
            pass

    # What follows only writes the control-data record: it reads what the flow
    # already worked out and never changes a move.

    def _moveWhy(self, action: str, state, clear: dict | None, want_deg: float, cap, **more) -> dict | None:
        """The decision behind the move about to be sent, for its feed_move
        record: the action, the degrees wanted before any cap and which cap cut
        them, the lead's and the next piece's gap to the exit, the pieces on the
        channel, whether the channel below was clear and what it waited on, and
        the time of the picture all of it was read from."""
        try:
            pieces = getattr(state, "pieces", ()) or ()
            gaps = [getattr(p, "com_forward_to_exit_deg", None) for p in pieces[:2]]
            return {
                "action": action,
                "want_deg": round(float(want_deg), 2),
                "cap": cap,
                "lead_deg": round(float(gaps[0]), 2) if gaps and gaps[0] is not None else None,
                "next_deg": round(float(gaps[1]), 2) if len(gaps) > 1 and gaps[1] is not None else None,
                "lead_track": getattr(pieces[0], "sv_bt_track_id", None) if pieces else None,
                "pieces": len(pieces),
                "in_drop": bool(getattr(state, "in_drop", False)),
                "in_exit": bool(getattr(state, "in_exit", False)),
                "clear": all(clear.values()) if clear else None,
                **(clear or {}),
                "frame_ts": getattr(state, "ts", None),
                **more,
            }
        except Exception:
            return None

    def _notePush(self, channel: int, lead, behind, step: ExitStep, clear: dict | None) -> None:
        """Remember an exit's push, for the record of the fall it causes."""
        try:
            self._pushes[channel] = self._pushes.get(channel, 0) + 1
            gap = getattr(lead, "com_forward_to_exit_deg", None)
            next_gap = getattr(behind, "com_forward_to_exit_deg", None)
            self._last_push[channel] = {
                "push_mono": time.monotonic(),
                "push_what": step.kind,
                "push_deg": round(float(step.deg), 2),
                "push_track": getattr(lead, "sv_bt_track_id", None),
                "push_lead_deg": round(float(gap), 2) if gap is not None else None,
                "push_next_deg": round(float(next_gap), 2) if next_gap is not None else None,
                "push_asked": bool(clear.get("ready")) if clear and "ready" in clear else None,
            }
        except Exception:
            pass

    def _fallRecord(self, channel: int, gate: DispenseGate, gone_since: float | None, now: float) -> dict:
        """What is known of a fall as the gate confirms it: the piece that fell,
        when it was last seen (the fall itself; the gate confirms it a moment
        later), the last push before it and the pushes since the fall before,
        how long the exit now holds, and for C3 whether C4 was asking."""
        try:
            record = {
                "ch": channel,
                "track": gate.fell_track_id,
                "gone_mono": gone_since if gone_since is not None else now,
                "hold_s": round(float(gate.hold_s), 3),
                "pushes": self._pushes.pop(channel, 0),
                **self._last_push.pop(channel, {}),
            }
            if channel == 3:
                record["asked"] = bool(self.shared.classification_ready)
            return record
        except Exception:
            return {"ch": channel}

    def _recordFallCount(self, channel: int, fall: FallCount) -> None:
        """A fall took more than its lead: how many pieces, and which."""
        try:
            self._recordControl(
                {
                    "kind": "fall_count",
                    "ch": channel,
                    "count": fall.count,
                    "tracks": sorted(fall._counted),
                    "started_mono": fall.started,
                }
            )
        except Exception:
            pass

    def _recordHold(self, channel: int, state, clear: dict) -> None:
        """One feed_hold record each time what an exit waits on changes: a piece
        at the exit or not, and each thing the channel below must be for a push."""
        try:
            seen = (bool(state.in_exit), *clear.values())
            if self._hold_seen.get(channel) == seen:
                return
            self._hold_seen[channel] = seen
            self._recordControl(
                {"kind": "feed_hold", "ch": channel, "in_exit": seen[0], "clear": all(clear.values()), **clear}
            )
        except Exception:
            pass

    def _stageDeg(self, channel: int, state, cfg: PulsePerceptionConfig) -> float | None:
        """How far to carry the lead piece on into the exit while the channel
        below is busy: until its center is ch{N}_stage_short_deg short of where
        pieces fall, one exit move at a time, never so far that the next piece
        reaches the exit. None: it stays."""
        short = float(getattr(cfg, f"ch{channel}_stage_short_deg", 0.0) or 0.0)
        if short <= 0:
            return None
        if float(getattr(state, "ts", 0.0) or 0.0) < self._moved_until.get(channel, 0.0):
            return None
        pieces = getattr(state, "pieces", ()) or ()
        if not pieces or pieces[0].com_forward_to_exit_deg is None:
            return None
        lead = pieces[0]
        deg = min(float(lead.com_forward_to_exit_deg) - short, cfg.exit_move_max_deg)
        behind = [p for p in pieces[1:] if not _boxesOverlap(p.bbox, lead.bbox)]
        if behind:
            perception_service = getattr(self.gc, "perception_service", None)
            channel_def = perception_service.channels().get(channel) if perception_service else None
            if channel_def is None:
                return None
            from perception.arcs import forwardGapToExitDeg

            room = min(forwardGapToExitDeg(p.bbox, channel_def) for p in behind) - cfg.exit_move_margin_deg
            deg = min(deg, room)
        # Small moves only creep: it is carried on in few, real steps.
        return deg if deg >= _STAGE_MIN_DEG else None

    def _exitStep(self, channel: int, state, cfg: PulsePerceptionConfig) -> ExitStep | None:
        """The exit's next move: a push, or with the lead in the opening and the
        next piece close behind it, a back-off or a shake (exit_step.py). None
        while the newest picture was taken before the last move ended."""
        push = self._exitMoveDeg(channel, state, cfg)
        pieces = getattr(state, "pieces", ()) or ()
        cap = float(cfg.exit_in_opening_max_deg)
        if cap > 0 and pieces and pieces[0].com_forward_to_exit_deg is not None and float(pieces[0].com_forward_to_exit_deg) <= 0:
            push = min(push, cap)
        if self._exit_next_close.get(channel) and float(getattr(state, "ts", 0.0) or 0.0) < self._moved_until.get(channel, 0.0):
            # The next piece is close behind: each push waits for a picture
            # taken after the last one, so none is sent once the lead has gone.
            return None
        clear = float(getattr(cfg, f"ch{channel}_exit_next_clear_deg", 0.0) or 0.0)
        if clear <= 0 or self._push_only:
            return ExitStep("push", push)
        if float(getattr(state, "ts", 0.0) or 0.0) < self._moved_until.get(channel, 0.0):
            return None
        pieces = getattr(state, "pieces", ()) or ()
        if not pieces:
            return ExitStep("push", push)
        lead = pieces[0]
        # A box on top of the lead's is the lead drawn twice, or a piece lying
        # on it that no back-off can part from it: the next piece is the first
        # one clear of it.
        nxt = next((p for p in pieces[1:] if not _boxesOverlap(p.bbox, lead.bbox)), None)
        return exitStep(
            float(lead.com_forward_to_exit_deg),
            float(nxt.com_forward_to_exit_deg) if nxt is not None else None,
            push,
            cfg.exit_pulse_output_deg,
            clear,
            self._exitTries(channel),
        )

    def _exitTries(self, channel: int) -> int:
        tries, last = self._exit_tries.get(channel, (0, 0.0))
        return tries if time.monotonic() - last < EXIT_TRIES_CALM_S else 0

    def _noteExitStep(self, channel: int, lead, behind, step: ExitStep) -> None:
        """Count a back-off or shake against the lead, and log every move the
        rule made or let through to the control data, so its effect can be
        measured."""
        lead_id = getattr(lead, "sv_bt_track_id", None)
        if step.kind != "push":
            self._exit_tries[channel] = (self._exitTries(channel) + 1, time.monotonic())
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
        longest = cfg.exit_move_max_deg
        past = float(getattr(cfg, "exit_move_past_deg", 0.0) or 0.0)
        if past > 0 and pieces and pieces[0].com_forward_to_exit_deg is not None:
            # No further than drops the lead: its way to the fall point and a
            # little past it, so a long move does not carry the next piece on.
            longest = max(small, min(longest, float(pieces[0].com_forward_to_exit_deg) + past))
        self._exit_next_close[channel] = False
        if len(pieces) < 2:
            return longest
        keep = float(getattr(cfg, "exit_next_keep_back_deg", 0.0) or 0.0)
        if keep > 0:
            # By centers: the piece behind the lead stays this far short of
            # where pieces fall, so the push that drops the lead cannot tip it
            # over too. (The rule below lets its box come within the margin of
            # the exit, where a piece is already falling.)
            lead = pieces[0]
            behind = [
                float(p.com_forward_to_exit_deg)
                for p in pieces[1:]
                if p.com_forward_to_exit_deg is not None and not _boxesOverlap(p.bbox, lead.bbox)
            ]
            if not behind:
                return longest
            room = min(behind) - keep
            if room < longest:
                self._exit_next_close[channel] = True
            return max(small, min(longest, room))
        perception_service = getattr(self.gc, "perception_service", None)
        channel_def = perception_service.channels().get(channel) if perception_service else None
        if channel_def is None:
            return small
        from perception.arcs import forwardGapToExitDeg

        room = min(forwardGapToExitDeg(p.bbox, channel_def) for p in pieces[1:])
        return max(small, min(longest, room - cfg.exit_move_margin_deg))

    def cleanup(self) -> None:
        for blind in self._blind.values():
            blind.clear()
        self._held.reset()
        if self._unjam is not None:
            self._unjam.pause(time.monotonic())
        super().cleanup()


def _exitCap(step: ExitStep, state, cfg: PulsePerceptionConfig) -> str | None:
    """For the record: what kept an exit push under exit_move_max_deg. The lead
    already in the opening ("in_opening", exit_in_opening_max_deg), or else the
    piece behind it ("next_piece": its room to the exit, or the clear-of-the-
    opening rule). None for a full push, a back-off or a shake."""
    try:
        if step.kind != "push" or step.deg >= cfg.exit_move_max_deg:
            return None
        pieces = getattr(state, "pieces", ()) or ()
        gap = pieces[0].com_forward_to_exit_deg if pieces else None
        opening = float(cfg.exit_in_opening_max_deg)
        if gap is not None and float(gap) <= 0 and opening > 0 and abs(step.deg - opening) < 1e-6:
            return "in_opening"
        past = float(getattr(cfg, "exit_move_past_deg", 0.0) or 0.0)
        if gap is not None and past > 0 and abs(step.deg - (float(gap) + past)) < 1e-6:
            return "lead_reach"
        return "next_piece"
    except Exception:
        return None


def _boxesOverlap(a, b) -> bool:
    """Whether two (x1, y1, x2, y2) boxes share any area."""
    if a is None or b is None:
        return False
    return min(a[2], b[2]) > max(a[0], b[0]) and min(a[3], b[3]) > max(a[1], b[1])
