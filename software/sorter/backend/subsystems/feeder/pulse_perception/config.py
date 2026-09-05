from dataclasses import dataclass


@dataclass
class PulsePerceptionConfig:
    # +1 carries pieces toward the exit (camera-clockwise = forward motor
    # direction). Flip to -1 if a channel's stepper is wired the other way.
    forward_direction_sign: int = 1
    # Move speed per channel. Each channel drives a different mass — C1 pushes a
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
    # While the leading piece is in the exit arc but not yet in the precise
    # sub-arc (the lip), approach with this larger pulse; the small
    # exit_pulse_output_deg is only for the final tip-over.
    exit_approach_output_deg: float = 8.0
    # C1 (bulk feeder) has no vision zones: pulse it forward a fixed amount
    # whenever C2's drop zone is clear.
    ch1_pulse_output_deg: float = 1.0
    ch1_pulse_pause_ms: int = 300
    # Gate C3 forward motion on the downstream classification channel being
    # ready to accept a piece (avoids double-drops into the same sector).
    gate_ch3_on_classification_ready: bool = True
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
    # Inter-channel jam watchdog. A downstream feeder channel (C2/C3) can keep
    # pulsing a piece it sees in its drop zone that never advances, because the
    # piece is physically hung at the UPSTREAM channel's exit lip (its camera
    # read it as "arrived" while it is still on the upstream rotor). When a
    # channel makes no forward progress for the timeout while actively pulsing,
    # nudge the upstream rotor to free/seat the piece; after the max attempts,
    # raise the operator "Feeder Jam" incident.
    stuck_watchdog_enabled: bool = True
    # A channel must go this long with a piece on it, actively pulsing, and no
    # forward progress before the watchdog acts.
    stuck_no_progress_ms: int = 30000
    # The leading piece's travel position (channel-output degrees toward the
    # exit) must improve by at least this much to count as "moving." Smaller =
    # more sensitive to a truly stuck piece; larger tolerates detector jitter.
    stuck_progress_epsilon_deg: float = 3.0
    # How far to nudge the upstream rotor forward per recovery attempt.
    stuck_nudge_output_deg: float = 4.0
    # Upstream nudges to try before declaring a jam and calling the operator.
    stuck_max_nudge_attempts: int = 3


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
    {"section": "Exit pulse", "key": "exit_approach_output_deg", "label": "Exit approach pulse (output deg)", "type": "float", "default": _DEFAULTS.exit_approach_output_deg, "description": "Pulse size while the leading piece is inside the exit arc but not yet in the precise sub-arc at the lip. The small exit pulse takes over for the final tip-over."},
    {"section": "Exit pulse", "key": "exit_pulse_output_deg", "label": "Exit pulse distance (output deg)", "type": "float", "default": _DEFAULTS.exit_pulse_output_deg, "description": "How far a piece is nudged per pulse once it reaches the exit edge and is being metered into the next channel. Smaller is gentler and less likely to push two pieces through at once. Use the speed presets above to set this."},
    {"section": "Exit pulse", "key": "exit_pulse_pause_ms", "label": "Exit pause between pulses (ms)", "type": "int", "default": _DEFAULTS.exit_pulse_pause_ms, "description": "Pause after each exit pulse so the downstream channel registers the piece before another nudge."},
    {"section": "C1 (bulk)", "key": "ch1_pulse_output_deg", "label": "C1 bulk pulse distance (output deg)", "type": "float", "default": _DEFAULTS.ch1_pulse_output_deg, "description": "C1 (bulk) has no camera — it just pulses forward this far whenever C2's drop zone is clear."},
    {"section": "C1 (bulk)", "key": "ch1_pulse_pause_ms", "label": "C1 pause between pulses (ms)", "type": "int", "default": _DEFAULTS.ch1_pulse_pause_ms, "description": "Pause between C1 bulk pulses."},
    {"section": "Channels", "key": "gate_ch3_on_classification_ready", "label": "Gate C3 on classification ready", "type": "bool", "default": _DEFAULTS.gate_ch3_on_classification_ready, "description": "Hold C3 from pushing a piece into the classification channel (C4) until C4 reports it is ready to accept one. Prevents two pieces landing in the same spot."},
    {"section": "Channels", "key": "enable_ch1", "label": "Enable C1 (bulk)", "type": "bool", "default": _DEFAULTS.enable_ch1, "description": "Run the C1 (bulk) channel. Off = this channel never moves."},
    {"section": "Channels", "key": "enable_ch2", "label": "Enable C2", "type": "bool", "default": _DEFAULTS.enable_ch2, "description": "Run the C2 channel. Off = this channel never moves."},
    {"section": "Channels", "key": "enable_ch3", "label": "Enable C3", "type": "bool", "default": _DEFAULTS.enable_ch3, "description": "Run the C3 channel. Off = this channel never moves."},
    {"section": "Detection persistence", "key": "drop_zone_persistence_ms", "label": "C2/C3 drop-zone occupancy hold (ms)", "type": "int", "default": _DEFAULTS.drop_zone_persistence_ms, "description": "After a piece is seen in C2 or C3's drop zone, keep treating that zone as occupied for this long even if the detector misses the piece for a frame or two. Stops the upstream channel from dropping another piece on top during a brief detection flicker. 0 = trust raw per-frame detection."},
    {"section": "Greedy mode", "key": "ch2_greedy_enabled", "label": "C2 greedy (advance piece anywhere on channel)", "type": "bool", "default": _DEFAULTS.ch2_greedy_enabled, "description": "Greedy: start pushing a piece toward the exit as soon as it is seen anywhere on C2, instead of waiting for it to settle in the drop zone — clears the channel for the next piece sooner."},
    {"section": "Greedy mode", "key": "ch3_greedy_enabled", "label": "C3 greedy (advance piece anywhere on channel)", "type": "bool", "default": _DEFAULTS.ch3_greedy_enabled, "description": "Greedy: start pushing a piece toward the exit as soon as it is seen anywhere on C3, instead of waiting for it to settle in the drop zone — clears the channel for the next piece sooner."},
    {"section": "Greedy mode", "key": "greedy_pulse_output_deg", "label": "Greedy advance pulse distance (output deg)", "type": "float", "default": _DEFAULTS.greedy_pulse_output_deg, "description": "Pulse distance used while greedily advancing a piece that has left the drop zone but not yet reached the exit edge."},
    {"section": "Greedy mode", "key": "greedy_pulse_pause_ms", "label": "Greedy advance pause between pulses (ms)", "type": "int", "default": _DEFAULTS.greedy_pulse_pause_ms, "description": "Pause between greedy advance pulses."},
    {"section": "Jam watchdog", "key": "stuck_watchdog_enabled", "label": "Enable inter-channel jam watchdog", "type": "bool", "default": _DEFAULTS.stuck_watchdog_enabled, "description": "Detect a downstream channel (C2/C3) that keeps pulsing a piece that never moves — because it is hung at the previous channel's exit — and nudge the upstream channel to free it. If nudging fails, raise the Feeder Jam incident. (The 'Feeder Jam' entry on the Incidents page also gates this: set it to Off to disable entirely, Manual to skip the nudges and call the operator straight away.)"},
    {"section": "Jam watchdog", "key": "stuck_no_progress_ms", "label": "No-progress timeout (ms)", "type": "int", "default": _DEFAULTS.stuck_no_progress_ms, "description": "How long a channel must keep pulsing with the piece not advancing before the watchdog nudges the upstream channel."},
    {"section": "Jam watchdog", "key": "stuck_progress_epsilon_deg", "label": "Progress threshold (output deg)", "type": "float", "default": _DEFAULTS.stuck_progress_epsilon_deg, "description": "How far the leading piece must travel toward the exit to count as moving. Below this over the timeout window is treated as stuck. Larger tolerates detector jitter; smaller reacts to a truly stuck piece sooner."},
    {"section": "Jam watchdog", "key": "stuck_nudge_output_deg", "label": "Upstream nudge distance (output deg)", "type": "float", "default": _DEFAULTS.stuck_nudge_output_deg, "description": "How far the upstream channel is nudged forward each recovery attempt to push the hung piece the rest of the way onto this channel."},
    {"section": "Jam watchdog", "key": "stuck_max_nudge_attempts", "label": "Max nudge attempts before jam", "type": "int", "default": _DEFAULTS.stuck_max_nudge_attempts, "description": "How many upstream nudges to try before giving up and raising the Feeder Jam incident for the operator."},
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


def configFromDict(d: dict) -> PulsePerceptionConfig:
    cfg = PulsePerceptionConfig()
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
