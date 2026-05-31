from dataclasses import dataclass


@dataclass
class GoToAngleConfig:
    # +1 carries pieces toward the exit (camera-clockwise = forward motor
    # direction). Flip to -1 if a channel's stepper is wired the other way.
    forward_direction_sign: int = 1
    move_speed_usteps_per_s: int = 1997
    # Normal advance per move when pieces are present but none is at the exit
    # yet — carries the train forward toward the exit zone (output degrees).
    advance_output_deg: float = 30.0
    # Ignore moves smaller than this (noise) and clamp any single move to the
    # max so a bad angle calc can never spin a channel wildly.
    min_move_output_deg: float = 2.0
    max_move_output_deg: float = 120.0
    # Cooldown after a normal advance move before the channel is re-evaluated.
    settle_after_move_ms: int = 250
    # Precise (at-exit) mode. Instead of shoving a piece past the exit edge in
    # one move, nudge it forward one small fixed angle at a time, pausing
    # between pulses so the downstream channel can confirm receipt before we
    # push again. Mirrors the reactive flow's precise pulsing.
    precise_pulse_output_deg: float = 3.0
    precise_pulse_pause_ms: int = 300
    # Bulk feeder (c_channel_1) has no vision zones: nudge it forward by a fixed
    # amount whenever c_channel_2's drop zone is clear.
    ch1_advance_output_deg: float = 5.0
    ch1_settle_after_move_ms: int = 800
    # Gate c_channel_3 forward motion on the downstream classification channel
    # being ready to accept a piece (avoids double-drops into the same sector).
    gate_ch3_on_classification_ready: bool = True
    enable_ch1: bool = True
    enable_ch2: bool = True
    enable_ch3: bool = True

    # --- Fast eject -----------------------------------------------------
    # Per-channel exit-handling strategy. When fast-eject is enabled for a
    # channel, instead of metering the piece into the exit with precise pulses,
    # the EjectController drives the leading piece's bbox center-of-mass forward
    # in a CLOSED LOOP — re-reading the actual COM position after every move — to
    # the entry edge of the real exit (fall-off) region, i.e. until the piece is
    # >= 50% into the exit. Re-measuring each move makes it robust to piece
    # slippage. Then it watches for the piece to register DOWNSTREAM. When
    # disabled the channel keeps the precise-pulse hand-off. C3 uses fast-eject.
    ch2_fast_eject_enabled: bool = False
    ch3_fast_eject_enabled: bool = True
    # The eject starts only when the leading piece's COM is in the PRECISE zone
    # (an exact membership test derived from the live saved arc) — there is no
    # distance-threshold knob; the precise zone IS the trigger region.
    # Smallest advance command. Each ADVANCING iteration commands the measured
    # remaining gap; this floors it so we don't emit ever-shrinking sub-degree
    # moves as the COM asymptotically approaches the edge. A control param, not a
    # zone angle.
    fast_eject_min_step_deg: float = 2.0
    # Safety cap: if this many advance moves pass without the COM reaching the
    # exit zone (the piece is stuck/slipping badly), kick to jitter recovery
    # instead of advancing forever.
    fast_eject_max_advance_iterations: int = 12
    # The eject moves are completely normal moves at move_speed_usteps_per_s. They
    # NEVER set acceleration (no move in this flow does) — the motor keeps
    # whatever acceleration it already has. Each move completes when the firmware
    # reports the stepper has stopped.
    # Once the piece is >= 50% in we enter AWAITING_FALL. If no NEW detection
    # appears in the downstream channel's region within this window (the piece
    # didn't arrive downstream — it's stuck, or vision lost it in the
    # over-exposed exit), we kick off jitter recovery.
    fall_confirm_timeout_ms: int = 700
    # Recovery: jitter-and-pause up to this many attempts. If the piece still
    # hasn't registered downstream after the last attempt, give up and resume
    # the normal flow (assume what we saw was a vision glitch).
    fall_recovery_max_jitter_attempts: int = 3

    # --- Jitter (fall recovery) ----------------------------------------
    # Shared jitter oscillation parameters. Used ONLY by the C3 fast-eject
    # fall-recovery procedure (the old exit-dwell jitter has been removed —
    # jitter no longer fires anywhere else in the feeder flow).
    jitter_pause_ms: int = 750
    jitter_amplitude_motor_deg: float = 6.0
    jitter_cycles: int = 8
    jitter_speed_usteps_per_s: int = 6500
    jitter_accel_usteps_per_s2: int = 180000


_DEFAULTS = GoToAngleConfig()

# ``section`` groups fields under a denoted subheader in the tuning UI. Order
# within a section is preserved; sections appear in first-seen order.
FIELD_META: list[dict] = [
    {"section": "Motion", "key": "forward_direction_sign", "label": "Forward direction sign (+1/-1)", "type": "int", "default": _DEFAULTS.forward_direction_sign},
    {"section": "Motion", "key": "move_speed_usteps_per_s", "label": "Move speed (µsteps/s)", "type": "int", "default": _DEFAULTS.move_speed_usteps_per_s},
    {"section": "Motion", "key": "advance_output_deg", "label": "Normal advance (output deg)", "type": "float", "default": _DEFAULTS.advance_output_deg},
    {"section": "Motion", "key": "min_move_output_deg", "label": "Min move (output deg)", "type": "float", "default": _DEFAULTS.min_move_output_deg},
    {"section": "Motion", "key": "max_move_output_deg", "label": "Max move clamp (output deg)", "type": "float", "default": _DEFAULTS.max_move_output_deg},
    {"section": "Motion", "key": "settle_after_move_ms", "label": "Settle after advance (ms)", "type": "int", "default": _DEFAULTS.settle_after_move_ms},
    {"section": "Precise hand-off", "key": "precise_pulse_output_deg", "label": "Precise pulse angle (output deg)", "type": "float", "default": _DEFAULTS.precise_pulse_output_deg},
    {"section": "Precise hand-off", "key": "precise_pulse_pause_ms", "label": "Precise pulse pause between pulses (ms)", "type": "int", "default": _DEFAULTS.precise_pulse_pause_ms},
    {"section": "C1 (bulk)", "key": "ch1_advance_output_deg", "label": "C1 bulk advance (output deg)", "type": "float", "default": _DEFAULTS.ch1_advance_output_deg},
    {"section": "C1 (bulk)", "key": "ch1_settle_after_move_ms", "label": "C1 settle after move (ms)", "type": "int", "default": _DEFAULTS.ch1_settle_after_move_ms},
    {"section": "Channels", "key": "gate_ch3_on_classification_ready", "label": "Gate C3 on classification ready", "type": "bool", "default": _DEFAULTS.gate_ch3_on_classification_ready},
    {"section": "Channels", "key": "enable_ch1", "label": "Enable C1 (bulk)", "type": "bool", "default": _DEFAULTS.enable_ch1},
    {"section": "Channels", "key": "enable_ch2", "label": "Enable C2", "type": "bool", "default": _DEFAULTS.enable_ch2},
    {"section": "Channels", "key": "enable_ch3", "label": "Enable C3", "type": "bool", "default": _DEFAULTS.enable_ch3},
    {"section": "Fast eject (C3)", "key": "ch2_fast_eject_enabled", "label": "C2 fast eject", "type": "bool", "default": _DEFAULTS.ch2_fast_eject_enabled},
    {"section": "Fast eject (C3)", "key": "ch3_fast_eject_enabled", "label": "C3 fast eject", "type": "bool", "default": _DEFAULTS.ch3_fast_eject_enabled},
    {"section": "Fast eject (C3)", "key": "fast_eject_min_step_deg", "label": "Min advance step (output deg)", "type": "float", "default": _DEFAULTS.fast_eject_min_step_deg},
    {"section": "Fast eject (C3)", "key": "fast_eject_max_advance_iterations", "label": "Max advance moves before recovery", "type": "int", "default": _DEFAULTS.fast_eject_max_advance_iterations},
    {"section": "Fast eject (C3)", "key": "fall_confirm_timeout_ms", "label": "Await-fall timeout before recovery (ms)", "type": "int", "default": _DEFAULTS.fall_confirm_timeout_ms},
    {"section": "Fast eject (C3)", "key": "fall_recovery_max_jitter_attempts", "label": "Fall recovery: max jitter attempts", "type": "int", "default": _DEFAULTS.fall_recovery_max_jitter_attempts},
    {"section": "Jitter (fall recovery)", "key": "jitter_pause_ms", "label": "Jitter: pause between attempts (ms)", "type": "int", "default": _DEFAULTS.jitter_pause_ms},
    {"section": "Jitter (fall recovery)", "key": "jitter_amplitude_motor_deg", "label": "Jitter amplitude (motor deg)", "type": "float", "default": _DEFAULTS.jitter_amplitude_motor_deg},
    {"section": "Jitter (fall recovery)", "key": "jitter_cycles", "label": "Jitter cycles per burst", "type": "int", "default": _DEFAULTS.jitter_cycles},
    {"section": "Jitter (fall recovery)", "key": "jitter_speed_usteps_per_s", "label": "Jitter speed (µsteps/s)", "type": "int", "default": _DEFAULTS.jitter_speed_usteps_per_s},
    {"section": "Jitter (fall recovery)", "key": "jitter_accel_usteps_per_s2", "label": "Jitter accel (µsteps/s²)", "type": "int", "default": _DEFAULTS.jitter_accel_usteps_per_s2},
]


def configFromDict(d: dict) -> GoToAngleConfig:
    cfg = GoToAngleConfig()
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


def configToDict(cfg: GoToAngleConfig) -> dict[str, object]:
    return {meta["key"]: getattr(cfg, meta["key"]) for meta in FIELD_META}
