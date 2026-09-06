import time
from dataclasses import dataclass
from dataclasses import replace, dataclass
from typing import Any, Callable, Optional, TYPE_CHECKING

from states.base_state import BaseState
from subsystems.shared_variables import SharedVariables
from subsystems.bus import StationId
from irl.config import IRLInterface, IRLConfig
from global_config import GlobalConfig
from vision import VisionManager

from ..states import FeederState
from .config import (
    PulsePerceptionConfig,
    channelMaxMoveOutputDeg,
    channelMoveSpeed,
)
from .stuck_watchdog import FeederStuckWatchdog
from subsystems.feeder.incidents import feeder_jam_incident_active

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

# After a C3 exit dispense, keep C3 blocked this long so the in-flight piece
# can register downstream before we consider another move.
CLASSIFICATION_PENDING_ADMISSION_MS = 1500

# PieceObservation.zone_code values that lie in the exit arc (exit-only and
# the precise sub-arc); see perception.arcs._region_lookup.
_EXIT_ZONE_CODES = (2, 3)


def _exitPieceCount(state) -> int:
    return sum(
        1
        for po in getattr(state, "pieces", ())
        if int(getattr(po, "zone_code", 0)) in _EXIT_ZONE_CODES
    )


# PieceObservation.zone_code of the exit-only band — the lip, where a piece
# tips over on the next pulse (perception.arcs._region_lookup: 2).
_ZONE_EXIT_ONLY = 2
# After a tip-over pulse the exit-only band can look empty before the
# departure detector confirms; keep pulsing small this long so a neighbour is
# not flung after the piece that just left.
TIP_OVER_HOLD_S = 1.5
# The approach pulse stops this far short of the exit-only entry edge.
APPROACH_MARGIN_DEG = 14.0


def exitPulseOutputDeg(cfg, state) -> float:
    """Gate-open pulse size. Zone order in travel direction: drop -> precise
    (approach band) -> exit-only (the lip). The large approach pulse applies
    only while NO piece is in the exit-only band; once one is at the lip every
    pulse is the small tip-over pulse, whatever else is behind it."""
    tip = float(cfg.exit_pulse_output_deg)
    approach = float(getattr(cfg, "exit_approach_output_deg", 0.0) or 0.0)
    pieces = getattr(state, "pieces", None)
    if pieces is None:
        return tip
    at_lip = exitOnlyCount(state)
    if at_lip >= 2:
        # Bunched at the lip: the smallest pulse there is, so the leader goes
        # over alone (the speed drops too, see exitPulseSpeed).
        crowded = float(getattr(cfg, "crowded_tip_output_deg", 0.0) or 0.0)
        return min(tip, crowded) if crowded > 0.0 else tip
    if approach <= 0.0 or at_lip:
        return tip
    # Never carry the leading piece INTO the exit-only band with an approach
    # pulse (two adjacent pieces went over together that way): stop
    # APPROACH_MARGIN_DEG short of the entry edge and let the tip-over pulse
    # take it from there.
    gaps = [
        float(g)
        for g in (getattr(po, "com_forward_to_exit_deg", None) for po in pieces)
        if g is not None and float(g) > 0.0
    ]
    output = max(approach, tip)
    if gaps:
        lead = min(gaps)
        if lead <= APPROACH_MARGIN_DEG + tip:
            return tip  # too close to the fall-off for anything but the tip-over pulse
        output = min(output, lead - APPROACH_MARGIN_DEG)
    return max(output, tip)


# A follower this close behind the lip (gap to the exit-only entry edge, in
# output degrees) goes over with the leader on a normal tip: the night's
# pairs sat 12–25° apart.
CROWDED_FOLLOWER_GAP_DEG = 20.0


def exitOnlyCount(state) -> int:
    """Pieces at the lip this frame: in the exit-only band, plus followers
    within CROWDED_FOLLOWER_GAP_DEG of its entry edge."""
    pieces = getattr(state, "pieces", ()) or ()
    at_lip = sum(1 for po in pieces if int(getattr(po, "zone_code", 0)) == _ZONE_EXIT_ONLY)
    if at_lip == 0:
        return 0
    close = 0
    for po in pieces:
        gap = getattr(po, "com_forward_to_exit_deg", None)
        if int(getattr(po, "zone_code", 0)) != _ZONE_EXIT_ONLY and gap is not None and 0.0 < float(gap) <= CROWDED_FOLLOWER_GAP_DEG:
            close += 1
    return at_lip + close


def exitPieceLayout(state) -> str:
    """(zone, gap) per piece for the pulse log, leading first."""
    rows = []
    for po in getattr(state, "pieces", ()) or ():
        gap = getattr(po, "com_forward_to_exit_deg", None)
        rows.append((999.0 if gap is None else float(gap), int(getattr(po, "zone_code", 0))))
    rows.sort()
    return " ".join(f"z{z}@{g:.0f}" if g != 999.0 else f"z{z}@?" for g, z in rows)


def exitPulseSpeed(cfg, channel: int, state) -> int:
    """Move speed for an exit pulse: the channel's speed, or the slower crowded
    tip speed when two or more pieces sit at the lip."""
    speed = channelMoveSpeed(cfg, channel)
    crowded = int(getattr(cfg, "crowded_tip_speed_usteps_per_s", 0) or 0)
    if crowded > 0 and exitOnlyCount(state) >= 2:
        return min(speed, crowded)
    return speed


# Arming / release (see c3ExitMotionPlan). The arm band starts at the existing
# approach margin — one safety margin, not two — and the fast release stops at
# +8°, where no piece has ever been seen to drop (departure histogram
# 2026-09-06: all departures were last seen below +5°).
ARM_TOLERANCE_DEG = 2.0
RELEASE_FLOOR_GAP_DEG = 8.0
RELEASE_MAX_OUTPUT_DEG = 8.0
FAST_RELEASE_FOLLOWER_SEPARATION_DEG = 25.0


@dataclass(frozen=True)
class C3ExitPlan:
    kind: str  # hold | arm | approach | release | tip | crowded_tip
    output_deg: float
    pause_ms: int
    speed: int
    dispense_capable: bool
    wants_advance: bool


def armGapDeg(cfg) -> Optional[float]:
    """Gap (to the exit-only entry edge) at which an armed lead is held while
    C4 is busy; None when arming is off."""
    return APPROACH_MARGIN_DEG if bool(getattr(cfg, "exit_arm_enabled", False)) else None


def c3ExitMotionPlan(cfg, state, downstream_ready: bool, channel: int = 3) -> C3ExitPlan:
    """What C3 does with a piece in its exit arc this frame.

    C4 busy: walk the lead to the arm band (APPROACH_MARGIN_DEG short of the
    exit-only edge) and hold — arming moves nothing off the channel. C4 open:
    approach as before while the lead is beyond the arm band; from the arm band
    one bounded fast move to RELEASE_FLOOR_GAP_DEG, then the normal tips; a
    follower within FAST_RELEASE_FOLLOWER_SEPARATION_DEG or a crowded lip gets
    the gentle ladder instead. Releases and tips carry the tip pause and count
    as dispense-capable."""
    tip = float(cfg.exit_pulse_output_deg)
    approach = float(getattr(cfg, "exit_approach_output_deg", 0.0) or 0.0)
    speed = channelMoveSpeed(cfg, channel)
    short = int(cfg.exit_pulse_pause_ms)
    long = exitPulsePauseMs(cfg, tip)
    hold = C3ExitPlan("hold", 0.0, 0, speed, False, False)
    raw_pieces = getattr(state, "pieces", None)
    pieces = list(raw_pieces or ())
    gaps = sorted(float(g) for g in (getattr(po, "com_forward_to_exit_deg", None) for po in pieces) if g is not None)
    lead = gaps[0] if gaps else getattr(state, "exit_com_forward_deg", None)
    if lead is None:
        if downstream_ready and raw_pieces is None:
            return C3ExitPlan("tip", tip, long, speed, True, True)  # no per-piece data: legacy tip
        return hold  # fail safe
    lead = float(lead)
    arm_gap = armGapDeg(cfg)
    if not downstream_ready:
        if arm_gap is None or lead <= arm_gap + ARM_TOLERANCE_DEG:
            return hold
        return C3ExitPlan("arm", max(0.0, min(max(approach, tip), lead - arm_gap)), short, speed, False, True)
    at_lip = exitOnlyCount(state)
    follower_close = len(gaps) >= 2 and (gaps[1] - gaps[0]) <= FAST_RELEASE_FOLLOWER_SEPARATION_DEG
    gentle = float(getattr(cfg, "crowded_tip_output_deg", 0.0) or 0.0)
    gentle_speed = min(speed, int(getattr(cfg, "crowded_tip_speed_usteps_per_s", 0) or speed) or speed)
    band = (arm_gap if arm_gap is not None else APPROACH_MARGIN_DEG) + ARM_TOLERANCE_DEG
    if arm_gap is not None and lead > band and at_lip == 0:
        return C3ExitPlan("approach", exitPulseOutputDeg(cfg, state), short, speed, False, True)
    if at_lip >= 2 or (follower_close and 0.0 < lead <= band):
        return C3ExitPlan("crowded_tip", min(tip, gentle) if gentle > 0.0 else tip, long, gentle_speed, True, True)
    if arm_gap is not None and lead > RELEASE_FLOOR_GAP_DEG + tip and at_lip == 0:
        return C3ExitPlan("release", min(RELEASE_MAX_OUTPUT_DEG, lead - RELEASE_FLOOR_GAP_DEG), long, speed, True, True)
    output = exitPulseOutputDeg(cfg, state)
    return C3ExitPlan("tip" if output <= tip else "approach", output, exitPulsePauseMs(cfg, output), speed, output <= tip, True)


def exitPulsePauseMs(cfg, output_deg: float) -> int:
    """Tip-over pulses (the small one, a piece at the lip) pace at
    tip_over_pause_ms; approach pulses at the shorter exit pause."""
    base = int(cfg.exit_pulse_pause_ms)
    if float(output_deg) <= float(cfg.exit_pulse_output_deg):
        return max(base, int(getattr(cfg, "tip_over_pause_ms", base) or base))
    return base


class ExitDepartureDetector:
    """Reports when the number of pieces in a channel's exit arc drops.

    Uses the rolling MAXIMUM of the count over the last ``hold_s`` seconds: a
    piece at the detection threshold flickers the count (3<->4 every second
    on 2026-09-05) and a two-read confirmation turned every dip into a
    'departure' that starved C3. Flicker keeps the maximum up; only a drop
    that lasts the whole window is a departure, reported at most once per
    ``min_interval_s``."""

    def __init__(self, hold_s: float = 0.8, min_interval_s: float = 1.0) -> None:
        self._hold_s = float(hold_s)
        self._min_interval_s = float(min_interval_s)
        self._samples: list[tuple[float, int]] = []
        self._last_max: int | None = None
        self._last_fired_at: float = -1e9

    def observe(self, count: int, now: float | None = None) -> bool:
        t = time.monotonic() if now is None else float(now)
        self._samples.append((t, int(count)))
        self._samples = [(ts, c) for ts, c in self._samples if t - ts <= self._hold_s]
        rolling_max = max(c for _, c in self._samples)
        if self._last_max is None:
            self._last_max = rolling_max
            return False
        departed = rolling_max < self._last_max and (t - self._last_fired_at) >= self._min_interval_s
        self._last_max = rolling_max
        if departed:
            self._last_fired_at = t
        return departed


def _leading_com(state) -> Optional[float]:
    # Leading (most-forward) on-channel piece's travel position toward the exit.
    # None when the channel reports no piece this frame. The jam watchdog treats
    # this as the channel's progress signal.
    pieces = getattr(state, "pieces", ())
    if pieces:
        return float(pieces[0].com_forward_to_exit_deg)
    return None


def _wants_advance(action) -> bool:
    # The channel is actively trying to move THIS piece (ADVANCE/PRECISE), vs.
    # intentionally holding for a busy downstream (FREEZE) or empty (IDLE).
    from perception.cascade import Action

    return action in (Action.ADVANCE, Action.PRECISE)


@dataclass(frozen=True)
class C3Upstream:
    """Who feeds C3, for the stuck watchdog: the label used in the jam
    incident, the rotor to nudge (or a topology-specific ``nudge`` callable),
    and whether nudging is possible at all."""

    label: str
    channel_id: int
    stepper: Any
    enabled: bool
    nudge: Optional[Callable[[], bool]] = None


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
        self._stuck_watchdog = FeederStuckWatchdog(gc)
        self._config: PulsePerceptionConfig = PulsePerceptionConfig()
        self._config_loaded_at: float = 0.0
        self._classification_pending_until: float = 0.0
        self._ch3_was_at_exit: bool = False
        self._ch3_departures = ExitDepartureDetector()
        self._ch3_last_tip_pulse_at: float = -1e9
        self._ch3_last_cmd_frame_ts: float = 0.0
        # Per-channel monotonic timestamp of the last frame that reported a piece
        # in the drop zone. Drives the C2/C3 drop-zone occupancy latch.
        self._drop_seen_at: dict[int, float] = {}
        machine_setup = getattr(irl_config, "machine_setup", None)
        self._classification_setup = bool(
            machine_setup is not None
            and getattr(machine_setup, "uses_classification_channel", False)
        )

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
        speed: int | None = None,
    ) -> bool:
        if self._busy(stepper):
            return False
        if speed is None:
            speed = channelMoveSpeed(cfg, channel)
        output_deg = abs(output_deg)
        if enforce_min:
            output_deg = max(cfg.min_move_output_deg, output_deg)
        output_deg = min(channelMaxMoveOutputDeg(cfg, channel), output_deg)
        sign = 1 if cfg.forward_direction_sign >= 0 else -1
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
        cooldown_ms = (max(0, exec_ms) + max(0, pause_ms)) if success else 500
        self._busy_until[stepper._name] = time.monotonic() + cooldown_ms / 1000.0
        self.gc.logger.info(
            f"PulsePerception: {label} pulse ch={channel} speed={speed} "
            f"output={output_deg:.1f}° motor={motor_deg:.1f}° "
            f"success={success} exec_ms={exec_ms} pause_ms={pause_ms}"
        )
        return success

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
        self._classification_pending_until = (
            time.monotonic() + CLASSIFICATION_PENDING_ADMISSION_MS / 1000.0
        )

    def _classification_ready(self, cfg: PulsePerceptionConfig) -> bool:
        if not cfg.gate_ch3_on_classification_ready or not self._classification_setup:
            return True
        if time.monotonic() < self._classification_pending_until:
            return False
        return bool(self.shared.classification_ready)

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

    def _c3_upstream(self, cfg: PulsePerceptionConfig) -> C3Upstream:
        """C2 feeds C3 in the C-channel topology. The belt topology overrides
        this with the belt (there is no C2 to blame or to nudge)."""
        return C3Upstream(
            label="C2",
            channel_id=2,
            stepper=getattr(self.irl, "c_channel_2_rotor_stepper", None),
            enabled=bool(cfg.enable_ch2),
        )

    def step(self) -> Optional[FeederState]:
        cfg = self._cfg()

        can_run = self.gc.rotary_channel_steppers_can_operate_in_parallel or (
            not self.shared.chute_move_in_progress
        )
        if not can_run:
            return FeederState.FEEDING

        perception_service = getattr(self.gc, "perception_service", None)
        if perception_service is None:
            return FeederState.FEEDING

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

        if cfg.enable_ch3:
            # C3's downstream is the classification channel (C4). The feeder does
            # NOT define "ready" itself — that determination is owned and exposed
            # by the classification channel (shared.classification_ready, set per
            # its active mode: single-piece = whole channel empty, two-piece = drop
            # zone clear). The feeder just asks. The only feeder-side gate is the
            # post-dispense admission window (let an in-flight piece register first).
            c3_downstream_ready = (
                now_mono >= self._classification_pending_until
                and self._classification_ready(cfg)
            )
            action = feederChannelAction(
                c3,
                downstream_clear=c3_downstream_ready,
                greedy=cfg.ch3_greedy_enabled,
                arm_gap_deg=(armGapDeg(cfg) + ARM_TOLERANCE_DEG) if armGapDeg(cfg) is not None else None,
            )
            # C3 hung at the C2->C3 hand-off: keep C3 from hammering a piece it
            # can't move; nudge C2 (its upstream) to free it, escalate on failure.
            upstream = self._c3_upstream(cfg)
            self._stuck_watchdog.observe(
                channel_id=3,
                channel_label="C3",
                upstream_label=upstream.label,
                upstream_channel_id=upstream.channel_id,
                upstream_stepper=upstream.stepper,
                upstream_enabled=upstream.enabled,
                nudge=upstream.nudge,
                leading_pos_deg=_leading_com(c3),
                wants_advance=_wants_advance(action),
                cfg=cfg,
                now=now_mono,
            )
            if not feeder_jam_incident_active(self.gc, channel_label="C3"):
                self._apply_action(
                    "ch3", 3, action, self.irl.c_channel_3_rotor_stepper, c3, cfg,
                    downstream_ready=c3_downstream_ready,
                )
            # A piece counts as delivered the moment it clears C3's exit zone
            # (the precise pulses stop on their own once perception no longer
            # sees it there). Fire the downstream notification + admission window
            # once on that falling edge, not on every micro-pulse.
            # …and equally the moment ONE of several pieces at the lip leaves:
            # the zone stays occupied, the edge never falls, and without the
            # admission window the next pulse sends the neighbour after it
            # before C4's gate can close (triple feed, 2026-09-05 10:31).
            ch3_at_exit_now = c3.in_exit
            departed = self._ch3_departures.observe(_exitPieceCount(c3))
            # The raw in_exit falling edge is a single-frame signal; with arming
            # moves in the exit arc it is only trusted when there is no per-piece
            # count to debounce (the detector owns it otherwise).
            raw_edge = getattr(c3, "pieces", None) is None and self._ch3_was_at_exit and not ch3_at_exit_now
            if departed or raw_edge:
                self._on_ch3_dispense()
            self._ch3_was_at_exit = ch3_at_exit_now

        if cfg.enable_ch2:
            # C2's downstream is C3. "Clear" = C3's drop zone is not occupied,
            # so we never pulse a C2 piece off the edge into a busy C3.
            action = feederChannelAction(
                c2, downstream_clear=not c3.in_drop, greedy=cfg.ch2_greedy_enabled
            )
            # C2 hung at the C1->C2 hand-off: nudge C1 (its upstream) to free the
            # piece, escalate to the operator jam incident if that keeps failing.
            self._stuck_watchdog.observe(
                channel_id=2,
                channel_label="C2",
                upstream_label="C1",
                upstream_channel_id=1,
                upstream_stepper=self.irl.c_channel_1_rotor_stepper,
                upstream_enabled=bool(cfg.enable_ch1),
                leading_pos_deg=_leading_com(c2),
                wants_advance=_wants_advance(action),
                cfg=cfg,
                now=now_mono,
            )
            if not feeder_jam_incident_active(self.gc, channel_label="C2"):
                self._apply_action(
                    "ch2", 2, action, self.irl.c_channel_2_rotor_stepper, c2, cfg
                )

        if cfg.enable_ch1:
            # C1 has no exit zone of its own; it just advances unless C2's drop
            # zone is occupied.
            stepper = self.irl.c_channel_1_rotor_stepper
            if c1Action(c2) == Action.ADVANCE and not self._busy(stepper):
                self._move(
                    "ch1",
                    1,
                    stepper,
                    cfg.ch1_pulse_output_deg,
                    cfg.ch1_pulse_pause_ms,
                    cfg,
                )

        return FeederState.FEEDING

    def _apply_action(
        self,
        label: str,
        channel: int,
        action,
        stepper: "StepperMotor",
        state,
        cfg: PulsePerceptionConfig,
        downstream_ready: bool = True,
    ) -> None:
        from perception.cascade import Action

        if self._busy(stepper):
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
            if clearance is not None and clearance < output_deg:
                output_deg = clearance
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
            now = time.monotonic()
            frame_ts = float(getattr(state, "ts", 0.0) or 0.0)
            if channel == 3 and frame_ts and frame_ts <= self._ch3_last_cmd_frame_ts:
                return  # one C3 exit command per fresh frame: never act twice on one reading
            plan = c3ExitMotionPlan(cfg, state, downstream_ready, channel)
            if plan.output_deg <= 0.0:
                return  # holding (armed, or nothing safe to do)
            output, pause_ms, speed = plan.output_deg, plan.pause_ms, plan.speed
            tip = float(cfg.exit_pulse_output_deg)
            if channel == 3 and output > tip and (now - self._ch3_last_tip_pulse_at) < TIP_OVER_HOLD_S:
                output, pause_ms = tip, exitPulsePauseMs(cfg, tip)  # the piece that just tipped over is on its way to C4
            moved = self._move(
                f"{label}_exit",
                channel,
                stepper,
                output,
                pause_ms,
                cfg,
                enforce_min=False,
                speed=speed,
            )
            if moved and channel == 3:
                self._ch3_last_cmd_frame_ts = frame_ts
                if plan.dispense_capable or output <= tip:
                    self._ch3_last_tip_pulse_at = now
                if plan.kind != "approach":
                    self.gc.logger.info(
                        f"PulsePerception: ch3 {plan.kind} {output:.1f}° @ {speed} with {exitOnlyCount(state)} at the lip "
                        f"[{exitPieceLayout(state)}]"
                    )
        # IDLE / FREEZE: no move.

    def cleanup(self) -> None:
        super().cleanup()
