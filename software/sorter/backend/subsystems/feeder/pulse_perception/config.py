from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from hardware_settings.feeder import FeederDrive


@dataclass
class PulsePerceptionConfig:
    # +1 carries pieces toward the exit (camera-clockwise = forward motor
    # direction). Flip to -1 if a channel's stepper is wired the other way.
    forward_direction_sign: int = 1
    # Move speed per channel, in motor microsteps a second, as tuned on the
    # geared feeder; another drive's are scaled to match (defaultConfig).
    # Each channel drives a different mass — C1 pushes a
    # whole bulk hopper, C3 meters single pieces into classification — so they
    # want different speeds. These are independent: nothing phase-locks the
    # channels to each other (each channel's pulse cooldown is keyed on its own
    # stepper and derived from its own move time), so changing one never desyncs
    # another.
    ch1_move_speed_usteps_per_s: int = 2000
    ch2_move_speed_usteps_per_s: int = 2000
    ch3_move_speed_usteps_per_s: int = 2000
    # Ignore moves smaller than this (noise).
    min_move_output_deg: float = 0.1
    # Clamp on any single move, per channel, so a bad config value can never
    # spin a channel wildly. Per channel because the clamp has to sit just above
    # the largest legitimate pulse for THAT channel, and those differ by an order
    # of magnitude: C2/C3 meter pieces in small nudges, while C1 shifts the bulk
    # pile and may be driving something with completely different gearing (a belt
    # rather than a c-channel rotor), where a useful pulse is far longer.
    ch1_max_move_output_deg: float = 120.0
    ch2_max_move_output_deg: float = 120.0
    ch3_max_move_output_deg: float = 120.0
    # Drop-zone region: a piece is on the channel but not yet at the exit.
    # Pulse it forward this far, then pause this long, to carry the train
    # toward the exit. The advance is capped so it can never shove the leading
    # piece off the edge into the exit zone in one move (downstream-gated exit
    # handling owns that).
    drop_pulse_output_deg: float = 30.0
    drop_pulse_pause_ms: int = 100
    # Exit region: a piece is at the exit edge and the downstream channel can
    # accept it. Nudge it off the edge one small pulse at a time, pausing
    # between pulses so the downstream channel registers the piece before we
    # push again. When downstream is NOT ready the channel holds still.
    exit_pulse_output_deg: float = 2.0
    exit_pulse_pause_ms: int = 100
    # With room behind the lead piece, one exit move goes further, up to this
    # much, so the piece drops in one go instead of pulse by pulse; it stops
    # exit_move_margin_deg short of letting the next piece reach the exit.
    # Equal to exit_pulse_output_deg: always the small pulse.
    exit_move_max_deg: float = 10.0
    exit_move_margin_deg: float = 4.0
    # While the lead piece is in a channel's exit opening, the exit never turns
    # so far that the next piece's center comes within this many degrees of the
    # opening: it shakes the lead loose instead (exit_step.py). 0 = off.
    ch2_exit_next_clear_deg: float = 2.0
    ch3_exit_next_clear_deg: float = 0.0
    # The arc of each channel's ring that its camera cannot see (sections,
    # start -> end in the travel direction; equal = none). A piece that
    # vanishes where it starts is expected where it ends, and the channel keeps
    # advancing meanwhile (blind_arc.py).
    ch2_blind_arc_start_deg: float = 0.0
    ch2_blind_arc_end_deg: float = 0.0
    ch3_blind_arc_start_deg: float = 0.0
    ch3_blind_arc_end_deg: float = 0.0
    # C1 (bulk feeder) has no vision zones: pulse it forward a fixed amount
    # whenever C2's drop zone is clear.
    ch1_pulse_output_deg: float = 1.0
    ch1_pulse_pause_ms: int = 300
    # Gate C3 forward motion on the downstream classification channel being
    # ready to accept a piece (avoids double-drops into the same sector).
    gate_ch3_on_classification_ready: bool = True
    # While the classification channel is busy (turning, or a piece in its drop
    # zone), C3's advance stops this far short of its exit instead of at the
    # exit edge. A piece carried right up to the lip falls onto C4 mid-turn and
    # lands beside the piece already there: a double feed. 0 = no stand-off.
    ch3_busy_standoff_deg: float = 0.0
    # While the classification channel is busy, C3 carries its lead piece on
    # into the exit until its center is this far short of where pieces fall,
    # so that when C4 asks, one short push drops it. 0 = off: the lead waits
    # at the exit's near edge.
    ch3_stage_short_deg: float = 0.0
    # After a piece was last seen in a channel's exit, the channel makes no
    # free advance for this long: a piece at the exit that the camera misses
    # for a frame must not be pushed off by a long advance meant for an empty
    # exit. 0 = off.
    exit_latch_ms: int = 0
    # Clumps: pieces near a channel's exit that touch, or whose centers are
    # closer than clump_gap_deg, while the channel is not handing a piece on.
    # The channel is vibrated in place this far each way (output degrees),
    # clump_shake_cycles times, to spread them before the lead reaches the
    # exit; at most clump_shake_tries times for one clump. 0 = off.
    ch2_clump_shake_deg: float = 0.0
    ch3_clump_shake_deg: float = 0.0
    clump_shake_cycles: int = 4
    # Motor microsteps, as the motor turns (not scaled for the drive).
    clump_shake_speed_usteps_per_s: int = 1500
    clump_shake_accel_usteps_per_s2: int = 30000
    clump_gap_deg: float = 8.0
    clump_zone_deg: float = 60.0
    clump_shake_tries: int = 2
    ch2_max_pieces: int = 0
    ch3_max_pieces: int = 0
    # Hand-off: once the piece a channel is pushing off has fallen (its track id
    # stays gone this long), the exit pushes nothing for the hold. Stops a second
    # exit pulse from pushing the piece behind it off before the next channel's
    # camera has seen the first one.
    dispense_vanish_confirm_ms: int = 150
    dispense_hold_ms: int = 1500
    # The hold follows how long pieces have taken to land on the next channel,
    # once enough falls have been seen to land (landing_hold.py); until then, the hold
    # above.
    hold_follows_landings: bool = True
    enable_ch1: bool = True
    enable_ch2: bool = True
    enable_ch3: bool = True
    # Latch C2/C3 drop-zone occupancy: once a piece is seen in the drop zone,
    # keep reporting that zone occupied until this many ms have passed with NO
    # drop-zone detection. Smooths over one/two-frame detector dropouts so the
    # upstream channel doesn't read the zone as empty and pulse another piece in
    # on top of one that's still there. Only ``in_drop`` is latched (not exit),
    # and only for C2 and C3. 0 disables (raw per-frame state).
    drop_zone_persistence_ms: int = 500
    # Greedy mode (per channel). In the default flow a channel only pulses a
    # piece forward while it sits in the drop zone, then idles until the piece
    # has reached the exit zone. In greedy mode the channel keeps pulsing a piece
    # toward the exit as soon as it is seen ANYWHERE on the channel, so the piece
    # is staged at the exit edge immediately and the drop zone clears sooner
    # (letting the upstream channel feed again). The advance is still capped at
    # the exit edge (advance_clearance_deg) and the exit hand-off stays
    # downstream-gated, so all the usual protections hold. C1 has no zones and is
    # unaffected. Settable independently per channel.
    ch2_greedy_enabled: bool = True
    ch3_greedy_enabled: bool = True
    # Pulse params used while greedily advancing a piece that has ALREADY left
    # the drop zone (the part of greedy mode the default flow doesn't do). A
    # piece still in the drop zone uses drop_pulse_* above; once it's past the
    # drop zone these take over until it reaches the exit edge. Defaulted to the
    # drop-zone values so greedy mode behaves identically until tuned apart.
    greedy_pulse_output_deg: float = 30.0
    greedy_pulse_pause_ms: int = 250

_DEFAULTS = PulsePerceptionConfig()

# ``section`` groups fields under a denoted subheader in the tuning UI. Order
# within a section is preserved; sections appear in first-seen order.
FIELD_META: list[dict] = [
    {"section": "Motion", "key": "forward_direction_sign", "label": "Forward direction sign (+1/-1)", "type": "int", "default": _DEFAULTS.forward_direction_sign, "description": "Which way the motor turns to carry pieces toward the exit. Leave at +1; use -1 only if this channel's stepper is wired backwards and pieces move the wrong way."},
    {"section": "Speeds", "key": "ch1_move_speed_usteps_per_s", "label": "C1 move speed (µsteps/s)", "type": "int", "default": _DEFAULTS.ch1_move_speed_usteps_per_s, "description": "Motor speed used for every C1 (bulk) pulse, in microsteps per second. Higher = snappier moves. C1 shifts the whole bulk pile, so it usually wants a different speed than the metering channels."},
    {"section": "Speeds", "key": "ch2_move_speed_usteps_per_s", "label": "C2 move speed (µsteps/s)", "type": "int", "default": _DEFAULTS.ch2_move_speed_usteps_per_s, "description": "Motor speed used for every C2 pulse, in microsteps per second. Higher = snappier moves."},
    {"section": "Speeds", "key": "ch3_move_speed_usteps_per_s", "label": "C3 move speed (µsteps/s)", "type": "int", "default": _DEFAULTS.ch3_move_speed_usteps_per_s, "description": "Motor speed used for every C3 pulse, in microsteps per second. C3 meters single pieces into the classification channel, so a slower speed here trades throughput for fewer double-drops."},
    {"section": "Max move", "key": "ch1_max_move_output_deg", "label": "C1 max move clamp (output deg)", "type": "float", "default": _DEFAULTS.ch1_max_move_output_deg, "description": "Hard cap on any single C1 (bulk) pulse, so a bad value can never spin the channel wildly. Raise this if C1 drives something that wants long moves — a conveyor belt rather than a c-channel rotor — and the bulk pulse distance is being clamped."},
    {"section": "Max move", "key": "ch2_max_move_output_deg", "label": "C2 max move clamp (output deg)", "type": "float", "default": _DEFAULTS.ch2_max_move_output_deg, "description": "Hard cap on any single C2 pulse, so a bad value can never spin the channel wildly."},
    {"section": "Max move", "key": "ch3_max_move_output_deg", "label": "C3 max move clamp (output deg)", "type": "float", "default": _DEFAULTS.ch3_max_move_output_deg, "description": "Hard cap on any single C3 pulse, so a bad value can never spin the channel wildly."},
    {"section": "Motion", "key": "min_move_output_deg", "label": "Min move (output deg)", "type": "float", "default": _DEFAULTS.min_move_output_deg, "description": "Moves smaller than this are treated as noise and skipped."},
    {"section": "Drop-zone pulse", "key": "drop_pulse_output_deg", "label": "Drop-zone pulse distance (output deg)", "type": "float", "default": _DEFAULTS.drop_pulse_output_deg, "description": "How far a piece is nudged per pulse while it is still back in the drop zone (not yet at the exit edge)."},
    {"section": "Drop-zone pulse", "key": "drop_pulse_pause_ms", "label": "Drop-zone pause between pulses (ms)", "type": "int", "default": _DEFAULTS.drop_pulse_pause_ms, "description": "Pause after each drop-zone pulse so vision can re-read the piece before the next nudge."},
    {"section": "Exit pulse", "key": "exit_pulse_output_deg", "label": "Exit pulse distance (output deg)", "type": "float", "default": _DEFAULTS.exit_pulse_output_deg, "description": "How far a piece is nudged per pulse once it reaches the exit edge and is being metered into the next channel. Smaller is gentler and less likely to push two pieces through at once. Use the speed presets above to set this."},
    {"section": "Exit pulse", "key": "exit_move_max_deg", "label": "Longest exit move (output deg)", "type": "float", "default": _DEFAULTS.exit_move_max_deg, "description": "When nothing is close behind the piece at the exit, one move pushes it this far so it drops in one go. The move always stops short of letting the next piece reach the exit. Set it equal to the exit pulse distance to always pulse."},
    {"section": "Exit pulse", "key": "exit_move_margin_deg", "label": "Room kept for the next piece (output deg)", "type": "float", "default": _DEFAULTS.exit_move_margin_deg, "description": "A longer exit move stops this far before the next piece's front edge would reach the exit."},
    {"section": "Exit pulse", "key": "ch2_exit_next_clear_deg", "label": "C2: keep the next piece back (deg)", "type": "float", "default": _DEFAULTS.ch2_exit_next_clear_deg, "description": "While the piece at C2's exit is in the opening, C2 never turns so far that the next piece's center comes within this many degrees of the opening: it shakes the piece at the exit loose instead (back a little, then forward as far), so the two do not fall together. 0 = off: the next piece is pushed in after it."},
    {"section": "Exit pulse", "key": "ch3_exit_next_clear_deg", "label": "C3: keep the next piece back (deg)", "type": "float", "default": _DEFAULTS.ch3_exit_next_clear_deg, "description": "The same for C3's exit onto the classification channel. 0 = off."},
    {"section": "Out of view", "key": "ch2_blind_arc_start_deg", "label": "C2 unseen arc start (deg)", "type": "float", "default": _DEFAULTS.ch2_blind_arc_start_deg, "description": "Where pieces on C2 go out of the camera's picture, in the channel's zone angles. Equal start and end: C2's camera sees its whole ring."},
    {"section": "Out of view", "key": "ch2_blind_arc_end_deg", "label": "C2 unseen arc end (deg)", "type": "float", "default": _DEFAULTS.ch2_blind_arc_end_deg, "description": "Where pieces on C2 come back into the picture. While a piece is out of view between the two, C2 keeps advancing, never so far it could pass the staging zone unseen."},
    {"section": "Out of view", "key": "ch3_blind_arc_start_deg", "label": "C3 unseen arc start (deg)", "type": "float", "default": _DEFAULTS.ch3_blind_arc_start_deg, "description": "Where pieces on C3 go out of the camera's picture, in the channel's zone angles. Equal start and end: C3's camera sees its whole ring."},
    {"section": "Out of view", "key": "ch3_blind_arc_end_deg", "label": "C3 unseen arc end (deg)", "type": "float", "default": _DEFAULTS.ch3_blind_arc_end_deg, "description": "Where pieces on C3 come back into the picture. While a piece is out of view between the two, C3 keeps advancing, never so far it could pass the staging zone unseen."},
    {"section": "Exit pulse", "key": "exit_pulse_pause_ms", "label": "Exit pause between pulses (ms)", "type": "int", "default": _DEFAULTS.exit_pulse_pause_ms, "description": "Pause after each exit pulse so the downstream channel registers the piece before another nudge."},
    {"section": "C1 (bulk)", "key": "ch1_pulse_output_deg", "label": "C1 bulk pulse distance (output deg)", "type": "float", "default": _DEFAULTS.ch1_pulse_output_deg, "description": "C1 (bulk) has no camera — it just pulses forward this far whenever C2's drop zone is clear."},
    {"section": "C1 (bulk)", "key": "ch1_pulse_pause_ms", "label": "C1 pause between pulses (ms)", "type": "int", "default": _DEFAULTS.ch1_pulse_pause_ms, "description": "Pause between C1 bulk pulses."},
    {"section": "Channels", "key": "gate_ch3_on_classification_ready", "label": "Gate C3 on classification ready", "type": "bool", "default": _DEFAULTS.gate_ch3_on_classification_ready, "description": "Hold C3 from pushing a piece into the classification channel (C4) until C4 reports it is ready to accept one. Prevents two pieces landing in the same spot."},
    {"section": "Hand-off", "key": "ch3_max_pieces", "label": "Most pieces on C3", "type": "int", "default": _DEFAULTS.ch3_max_pieces, "description": "C2 hands C3 no new piece while C3 holds this many. Crowded pieces on C3 sit touching, and C3's exit then drops two at once onto the classification channel. 0 = no limit."},
    {"section": "Hand-off", "key": "ch2_max_pieces", "label": "Most pieces on C2", "type": "int", "default": _DEFAULTS.ch2_max_pieces, "description": "C1 adds nothing to C2 while C2 holds this many, so a heavy pour from the hopper does not flood C2 and pack C3 behind it. 0 = no limit."},
    {"section": "Hand-off", "key": "ch3_busy_standoff_deg", "label": "C3 stand-off while C4 is busy (output deg)", "type": "float", "default": _DEFAULTS.ch3_busy_standoff_deg, "description": "While the classification channel is turning or has a piece in its drop zone, C3 advances its lead piece only to this far short of the exit, so nothing waits at the lip to fall onto C4 mid-turn. 0 = advance right up to the exit edge."},
    {"section": "Hand-off", "key": "ch3_stage_short_deg", "label": "C3 waits this close to the drop (output deg)", "type": "float", "default": _DEFAULTS.ch3_stage_short_deg, "description": "While the classification channel is busy, C3 carries its lead piece on into the exit until the piece's center is this far short of where pieces fall, never letting the piece behind it reach the exit. When the classification channel asks, one short push drops it. 0 = off: the lead waits at the exit's near edge."},
    {"section": "Hand-off", "key": "exit_latch_ms", "label": "No free advance after a piece at the exit (ms)", "type": "int", "default": _DEFAULTS.exit_latch_ms, "description": "After a piece was last seen in a channel's exit, the channel makes no free advance for this long, so a piece the camera misses for a frame is not pushed off by a long advance. 0 = off."},
    {"section": "Clumps", "key": "ch3_clump_shake_deg", "label": "C3: shake a clump (output deg each way)", "type": "float", "default": _DEFAULTS.ch3_clump_shake_deg, "description": "When pieces near C3's exit touch or lie closer than the clump gap, and C3 is not handing a piece on, C3 is vibrated in place this far each way to spread them before the lead reaches the exit. 0 = off."},
    {"section": "Clumps", "key": "ch2_clump_shake_deg", "label": "C2: shake a clump (output deg each way)", "type": "float", "default": _DEFAULTS.ch2_clump_shake_deg, "description": "The same for C2. 0 = off."},
    {"section": "Clumps", "key": "clump_shake_cycles", "label": "Shake strokes", "type": "int", "default": _DEFAULTS.clump_shake_cycles, "description": "How many times back and forth one clump shake goes."},
    {"section": "Clumps", "key": "clump_shake_speed_usteps_per_s", "label": "Shake speed (motor µsteps/s)", "type": "int", "default": _DEFAULTS.clump_shake_speed_usteps_per_s, "description": "Top speed of a clump shake's strokes, as the motor turns."},
    {"section": "Clumps", "key": "clump_shake_accel_usteps_per_s2", "label": "Shake acceleration (motor µsteps/s²)", "type": "int", "default": _DEFAULTS.clump_shake_accel_usteps_per_s2, "description": "How sharp a clump shake's strokes are, as the motor turns. Higher jolts the pieces harder."},
    {"section": "Clumps", "key": "clump_gap_deg", "label": "Clump gap (output deg)", "type": "float", "default": _DEFAULTS.clump_gap_deg, "description": "Two pieces whose centers are closer than this, or whose boxes touch, are a clump."},
    {"section": "Clumps", "key": "clump_zone_deg", "label": "Clumps looked for within (output deg of the exit)", "type": "float", "default": _DEFAULTS.clump_zone_deg, "description": "Only clumps whose lead piece is within this of the exit are shaken."},
    {"section": "Clumps", "key": "clump_shake_tries", "label": "Shakes for one clump", "type": "int", "default": _DEFAULTS.clump_shake_tries, "description": "How many times one clump is shaken before it is left to the exit."},
    {"section": "Hand-off", "key": "dispense_vanish_confirm_ms", "label": "Fallen after gone for (ms)", "type": "int", "default": _DEFAULTS.dispense_vanish_confirm_ms, "description": "The piece being pushed off the exit counts as fallen once the camera has not seen it for this long. Longer ignores detector blinks; shorter reacts sooner."},
    {"section": "Hand-off", "key": "dispense_hold_ms", "label": "Hold after a piece falls (ms)", "type": "int", "default": _DEFAULTS.dispense_hold_ms, "description": "After the piece being pushed off falls, the exit pushes nothing for this long, so the next channel sees it before another piece can follow."},
    {"section": "Hand-off", "key": "hold_follows_landings", "label": "Hold follows how long pieces take to land", "type": "bool", "default": _DEFAULTS.hold_follows_landings, "description": "Once 20 pieces have been seen to fall and land, each exit holds for the time 9 in 10 of them took to land on the next channel, plus 0.3 s (0.5 to 2.5 s): a long drop or a ramp holds longer, a short one no longer than it needs. Until then, and when off, the hold above."},
    {"section": "Channels", "key": "enable_ch1", "label": "Enable C1 (bulk)", "type": "bool", "default": _DEFAULTS.enable_ch1, "description": "Run the C1 (bulk) channel. Off = this channel never moves."},
    {"section": "Channels", "key": "enable_ch2", "label": "Enable C2", "type": "bool", "default": _DEFAULTS.enable_ch2, "description": "Run the C2 channel. Off = this channel never moves."},
    {"section": "Channels", "key": "enable_ch3", "label": "Enable C3", "type": "bool", "default": _DEFAULTS.enable_ch3, "description": "Run the C3 channel. Off = this channel never moves."},
    {"section": "Detection persistence", "key": "drop_zone_persistence_ms", "label": "C2/C3 drop-zone occupancy hold (ms)", "type": "int", "default": _DEFAULTS.drop_zone_persistence_ms, "description": "After a piece is seen in C2 or C3's drop zone, keep treating that zone as occupied for this long even if the detector misses the piece for a frame or two. Stops the upstream channel from dropping another piece on top during a brief detection flicker. 0 = trust raw per-frame detection."},
    {"section": "Greedy mode", "key": "ch2_greedy_enabled", "label": "C2 greedy (advance piece anywhere on channel)", "type": "bool", "default": _DEFAULTS.ch2_greedy_enabled, "description": "Greedy: start pushing a piece toward the exit as soon as it is seen anywhere on C2, instead of waiting for it to settle in the drop zone — clears the channel for the next piece sooner."},
    {"section": "Greedy mode", "key": "ch3_greedy_enabled", "label": "C3 greedy (advance piece anywhere on channel)", "type": "bool", "default": _DEFAULTS.ch3_greedy_enabled, "description": "Greedy: start pushing a piece toward the exit as soon as it is seen anywhere on C3, instead of waiting for it to settle in the drop zone — clears the channel for the next piece sooner."},
    {"section": "Greedy mode", "key": "greedy_pulse_output_deg", "label": "Greedy advance pulse distance (output deg)", "type": "float", "default": _DEFAULTS.greedy_pulse_output_deg, "description": "Pulse distance used while greedily advancing a piece that has left the drop zone but not yet reached the exit edge."},
    {"section": "Greedy mode", "key": "greedy_pulse_pause_ms", "label": "Greedy advance pause between pulses (ms)", "type": "int", "default": _DEFAULTS.greedy_pulse_pause_ms, "description": "Pause between greedy advance pulses."},
]


# Move speed and the max-move clamp each used to be a single machine-wide
# value; both are now per channel. Machines that were tuned before the splits
# still have the old keys in their machine.toml, so they are migrated (see
# migrateLegacyKeys) rather than dropped — silently reverting a tuned machine to
# the stock default would change its behaviour on upgrade with nothing in the UI
# to explain it.
LEGACY_MOVE_SPEED_KEY = "move_speed_usteps_per_s"
LEGACY_MAX_MOVE_KEY = "max_move_output_deg"

CHANNEL_MOVE_SPEED_KEYS: dict[int, str] = {
    1: "ch1_move_speed_usteps_per_s",
    2: "ch2_move_speed_usteps_per_s",
    3: "ch3_move_speed_usteps_per_s",
}

CHANNEL_MAX_MOVE_KEYS: dict[int, str] = {
    1: "ch1_max_move_output_deg",
    2: "ch2_max_move_output_deg",
    3: "ch3_max_move_output_deg",
}


def channelMoveSpeed(cfg: PulsePerceptionConfig, channel: int) -> int:
    """Move speed for one feeder channel (1-3). Unknown channels fall back to
    C2's speed — the middle of the chain — so a caller that grows a new channel
    still gets a sane pulse rather than a zero-speed move (which wedges the
    firmware, see MIN_MOVE_SPEED_USTEPS_PER_S in flow.py)."""
    key = CHANNEL_MOVE_SPEED_KEYS.get(channel, CHANNEL_MOVE_SPEED_KEYS[2])
    return int(getattr(cfg, key))


def channelMaxMoveOutputDeg(cfg: PulsePerceptionConfig, channel: int) -> float:
    """Max single-move clamp for one feeder channel (1-3). Unknown channels fall
    back to C2's clamp, matching channelMoveSpeed — a missing-attribute zero here
    would clamp every move to nothing and freeze the channel."""
    key = CHANNEL_MAX_MOVE_KEYS.get(channel, CHANNEL_MAX_MOVE_KEYS[2])
    return float(getattr(cfg, key))


def migrateLegacyKeys(section: dict) -> dict:
    """Upgrade a stored config section in place-safe fashion (returns a copy).

    Seeds all three per-channel speeds from the retired single ``move_speed_usteps_per_s``,
    and all three per-channel clamps from the retired single ``max_move_output_deg``,
    when that is what the machine has. Per-channel values already present always
    win, so this is a no-op once a machine has been tuned since the splits."""
    migrated = dict(section)
    legacy_speed = migrated.pop(LEGACY_MOVE_SPEED_KEY, None)
    if isinstance(legacy_speed, (int, float)) and not isinstance(legacy_speed, bool):
        for key in CHANNEL_MOVE_SPEED_KEYS.values():
            migrated.setdefault(key, int(legacy_speed))
    legacy_max_move = migrated.pop(LEGACY_MAX_MOVE_KEY, None)
    if isinstance(legacy_max_move, (int, float)) and not isinstance(legacy_max_move, bool):
        for key in CHANNEL_MAX_MOVE_KEYS.values():
            migrated.setdefault(key, float(legacy_max_move))
    return migrated


def defaultConfig(drive: "FeederDrive | None" = None) -> PulsePerceptionConfig:
    """The built-in tuning for the machine's feeder drive: the move speeds,
    tuned on the geared feeder, scaled to turn the channels as fast on another."""
    from hardware_settings.feeder import feederDrive

    drive = drive or feederDrive()
    cfg = PulsePerceptionConfig()
    for key in CHANNEL_MOVE_SPEED_KEYS.values():
        setattr(cfg, key, drive.motorRate(getattr(cfg, key)))
    return cfg


def fieldMeta(drive: "FeederDrive | None" = None) -> list[dict]:
    """FIELD_META with each default the machine's feeder drive takes."""
    defaults = configToDict(defaultConfig(drive))
    return [{**meta, "default": defaults[meta["key"]]} for meta in FIELD_META]


def configFromDict(d: dict) -> PulsePerceptionConfig:
    cfg = defaultConfig()
    d = migrateLegacyKeys(d)
    for meta in FIELD_META:
        k = meta["key"]
        if k not in d:
            continue
        raw = d[k]
        try:
            if meta["type"] == "int":
                setattr(cfg, k, int(raw))
            elif meta["type"] == "bool":
                setattr(cfg, k, bool(raw))
            else:
                setattr(cfg, k, float(raw))
        except (TypeError, ValueError):
            pass
    return cfg


def configToDict(cfg: PulsePerceptionConfig) -> dict[str, object]:
    return {meta["key"]: getattr(cfg, meta["key"]) for meta in FIELD_META}
