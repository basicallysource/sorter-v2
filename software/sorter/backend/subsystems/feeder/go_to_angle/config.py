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

    # --- Drop-zone detection persistence --------------------------------
    # Latch C2/C3 drop-zone occupancy: once a piece is seen in the drop zone,
    # keep reporting that zone occupied until this many ms have passed with NO
    # drop-zone detection. Smooths over one/two-frame detector dropouts so the
    # upstream channel doesn't read the zone as empty and feed another piece in
    # on top of one that's still there. Only ``in_drop`` is latched (not exit /
    # precise / COM), and only for C2 and C3. 0 disables (raw per-frame state).
    drop_zone_persistence_ms: int = 1000

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
    {"section": "Motion", "key": "forward_direction_sign", "label": "Forward direction sign (+1/-1)", "type": "int", "default": _DEFAULTS.forward_direction_sign, "description": "Which way the motor turns to carry pieces toward the exit. Leave at +1; use -1 only if a channel's stepper is wired backwards and pieces move the wrong way."},
    {"section": "Motion", "key": "move_speed_usteps_per_s", "label": "Move speed (µsteps/s)", "type": "int", "default": _DEFAULTS.move_speed_usteps_per_s, "description": "Motor speed for every move on this page (microsteps per second). Higher = snappier moves."},
    {"section": "Motion", "key": "advance_output_deg", "label": "Normal advance (output deg)", "type": "float", "default": _DEFAULTS.advance_output_deg, "description": "Normal advance per move when pieces are present but none is at the exit yet — carries the train forward toward the exit zone."},
    {"section": "Motion", "key": "min_move_output_deg", "label": "Min move (output deg)", "type": "float", "default": _DEFAULTS.min_move_output_deg, "description": "Moves smaller than this are treated as noise and skipped."},
    {"section": "Motion", "key": "max_move_output_deg", "label": "Max move clamp (output deg)", "type": "float", "default": _DEFAULTS.max_move_output_deg, "description": "Clamp on any single move, so a bad angle calculation can never spin a channel wildly."},
    {"section": "Motion", "key": "settle_after_move_ms", "label": "Settle after advance (ms)", "type": "int", "default": _DEFAULTS.settle_after_move_ms, "description": "Cooldown after a normal advance before the channel is re-evaluated, giving pieces time to stop sliding."},
    {"section": "Precise hand-off", "key": "precise_pulse_output_deg", "label": "Precise pulse angle (output deg)", "type": "float", "default": _DEFAULTS.precise_pulse_output_deg, "description": "At the exit, the piece is nudged forward by this small fixed angle per pulse instead of being shoved past the edge in one move."},
    {"section": "Precise hand-off", "key": "precise_pulse_pause_ms", "label": "Precise pulse pause between pulses (ms)", "type": "int", "default": _DEFAULTS.precise_pulse_pause_ms, "description": "Pause between precise pulses so the downstream channel can confirm receipt before the next push."},
    {"section": "C1 (bulk)", "key": "ch1_advance_output_deg", "label": "C1 bulk advance (output deg)", "type": "float", "default": _DEFAULTS.ch1_advance_output_deg, "description": "C1 (the bulk feeder) has no vision zones: it advances by this fixed amount whenever C2's drop zone is clear."},
    {"section": "C1 (bulk)", "key": "ch1_settle_after_move_ms", "label": "C1 settle after move (ms)", "type": "int", "default": _DEFAULTS.ch1_settle_after_move_ms, "description": "Cooldown after each C1 bulk advance before it may move again."},
    {"section": "Channels", "key": "gate_ch3_on_classification_ready", "label": "Gate C3 on classification ready", "type": "bool", "default": _DEFAULTS.gate_ch3_on_classification_ready, "description": "Only let C3 move forward when the classification channel is ready to accept a piece. Prevents double-drops into the same sector."},
    {"section": "Channels", "key": "enable_ch1", "label": "Enable C1 (bulk)", "type": "bool", "default": _DEFAULTS.enable_ch1, "description": "Run the C1 (bulk) channel. Off = this channel never moves."},
    {"section": "Channels", "key": "enable_ch2", "label": "Enable C2", "type": "bool", "default": _DEFAULTS.enable_ch2, "description": "Run the C2 channel. Off = this channel never moves."},
    {"section": "Channels", "key": "enable_ch3", "label": "Enable C3", "type": "bool", "default": _DEFAULTS.enable_ch3, "description": "Run the C3 channel. Off = this channel never moves."},
    {"section": "Detection persistence", "key": "drop_zone_persistence_ms", "label": "C2/C3 drop-zone occupancy hold (ms)", "type": "int", "default": _DEFAULTS.drop_zone_persistence_ms, "description": "Once a piece is seen in the C2/C3 drop zone, keep reporting the zone occupied until this many ms pass with NO detection. Smooths over one/two-frame detector dropouts so the upstream channel doesn't feed a second piece on top of one that's still there. 0 disables."},
    {"section": "Fast eject (C3)", "key": "ch2_fast_eject_enabled", "label": "C2 fast eject", "type": "bool", "default": _DEFAULTS.ch2_fast_eject_enabled, "description": "Use the closed-loop fast eject on C2 instead of precise pulsing: drive the leading piece's centre-of-mass to the exit edge, re-measuring after every move, then watch for it downstream."},
    {"section": "Fast eject (C3)", "key": "ch3_fast_eject_enabled", "label": "C3 fast eject", "type": "bool", "default": _DEFAULTS.ch3_fast_eject_enabled, "description": "Use the closed-loop fast eject on C3 instead of precise pulsing: drive the leading piece's centre-of-mass to the exit edge, re-measuring after every move, then watch for it downstream."},
    {"section": "Fast eject (C3)", "key": "fast_eject_min_step_deg", "label": "Min advance step (output deg)", "type": "float", "default": _DEFAULTS.fast_eject_min_step_deg, "description": "Smallest advance command during a fast eject. Each iteration commands the measured remaining gap; this floors it so the loop doesn't emit ever-shrinking sub-degree moves."},
    {"section": "Fast eject (C3)", "key": "fast_eject_max_advance_iterations", "label": "Max advance moves before recovery", "type": "int", "default": _DEFAULTS.fast_eject_max_advance_iterations, "description": "Safety cap: if this many advance moves pass without the piece reaching the exit zone (stuck or slipping badly), kick to jitter recovery instead of advancing forever."},
    {"section": "Fast eject (C3)", "key": "fall_confirm_timeout_ms", "label": "Await-fall timeout before recovery (ms)", "type": "int", "default": _DEFAULTS.fall_confirm_timeout_ms, "description": "After the piece is ejected, how long to wait for a NEW detection in the downstream channel before concluding it didn't arrive and starting jitter recovery."},
    {"section": "Fast eject (C3)", "key": "fall_recovery_max_jitter_attempts", "label": "Fall recovery: max jitter attempts", "type": "int", "default": _DEFAULTS.fall_recovery_max_jitter_attempts, "description": "Jitter-and-pause up to this many times waiting for the piece to register downstream. After the last attempt, give up and resume normal flow (assume a vision glitch)."},
    {"section": "Jitter (fall recovery)", "key": "jitter_pause_ms", "label": "Jitter: pause between attempts (ms)", "type": "int", "default": _DEFAULTS.jitter_pause_ms, "description": "Pause between jitter attempts, giving the piece time to fall before shaking again."},
    {"section": "Jitter (fall recovery)", "key": "jitter_amplitude_motor_deg", "label": "Jitter amplitude (motor deg)", "type": "float", "default": _DEFAULTS.jitter_amplitude_motor_deg, "description": "Size of each back-and-forth jitter oscillation, in motor degrees."},
    {"section": "Jitter (fall recovery)", "key": "jitter_cycles", "label": "Jitter cycles per burst", "type": "int", "default": _DEFAULTS.jitter_cycles, "description": "Back-and-forth oscillations per jitter attempt."},
    {"section": "Jitter (fall recovery)", "key": "jitter_speed_usteps_per_s", "label": "Jitter speed (µsteps/s)", "type": "int", "default": _DEFAULTS.jitter_speed_usteps_per_s, "description": "Motor speed during jitter oscillations."},
    {"section": "Jitter (fall recovery)", "key": "jitter_accel_usteps_per_s2", "label": "Jitter accel (µsteps/s²)", "type": "int", "default": _DEFAULTS.jitter_accel_usteps_per_s2, "description": "Motor acceleration during jitter oscillations — high, so the shake is sharp enough to unstick a piece."},
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
