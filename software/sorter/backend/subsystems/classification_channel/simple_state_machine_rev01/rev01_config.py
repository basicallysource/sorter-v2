from dataclasses import dataclass


@dataclass
class Rev01Config:
    rotate_speed_usteps_per_s: int = 7000
    capture_sweep_output_deg: float = 180.0
    # Legacy fixed discharge kick (only used on the non-perception fallback path).
    # The active perception path closed-loops onto the fall-off centre instead;
    # see ``discharge_*`` fields below.
    kick_off_output_deg: float = 180.0
    discharge_speed_usteps_per_s: int = 5000
    crop_padding_px: int = 15
    # Capped to the Brickognize per-request image limit (8) by selectRecognitionCrops.
    max_captures: int = 8
    rotate_timeout_s: float = 30.0
    classify_timeout_s: float = 30.0
    presence_streak_to_start: int = 2
    empty_streak_to_abort: int = 3
    stuck_in_exit_zone_timeout_s: float = 30.0
    home_offset_output_deg: float = 22.0
    # Legacy non-perception fallback only: pause after the fixed kick-off move
    # before returning to IDLE so the carousel settles.
    post_discharge_pause_ms: float = 300.0

    # Closed-loop discharge (active perception path). Drive the leading piece's
    # COM onto the centre of the fall-off zone with repeated bounded moves until
    # the channel reads physically clear. Success is confirmed-clear only; the
    # piece is committed to distribution there and nowhere else.
    discharge_center_tolerance_deg: float = 3.0
    discharge_max_move_output_deg: float = 270.0
    # One overall budget for the whole discharge of a piece-set, NOT reset per
    # move. When it runs out with the channel still occupied, raise the stuck
    # incident and hold (works from anywhere on the channel, not just the exit).
    discharge_total_timeout_ms: int = 30000
    # No-forward-progress window: if the COM-to-centre gap hasn't improved by
    # more than discharge_progress_eps_deg for this long, the piece is stalled
    # (parked at the exit and won't drop, or jammed earlier) — fire a jitter
    # burst to unstick it.
    discharge_stall_ms: int = 2000
    discharge_progress_eps_deg: float = 2.0
    # Consecutive stopped-carousel zero-detection reads required before the
    # channel is believed clear. The runtime detector blinks to 0 constantly;
    # 1 read used to false-finish the discharge before the piece had moved.
    discharge_clear_confirm_reads: int = 4
    # Consecutive distinct-frame reads with >=2 on-channel pieces required
    # before latching a multi-feed (which forces the whole cycle to MISC). The
    # detector regularly splits one piece into two boxes or emits a one-frame
    # spurious second box; a single such frame used to mis-flag a multi-drop.
    # Mirror the clear-confirm debounce so one noisy frame can't trip it.
    multi_feed_confirm_reads: int = 3

    # Verifying-discharge: after the move-to-angle settles, wait this long
    # before the first exit-zone re-check, then on stuck run up to N jitter
    # attempts using the shared jitter sequence.
    verify_discharge_wait_ms: int = 1000
    verify_discharge_max_jitter_attempts: int = 3
    jitter_pause_ms: int = 350
    jitter_amplitude_motor_deg: float = 8.0
    jitter_cycles: int = 6
    jitter_speed_usteps_per_s: int = 4000
    jitter_accel_usteps_per_s2: int = 80000


_DEFAULTS = Rev01Config()

FIELD_META: list[dict] = [
    {"key": "rotate_speed_usteps_per_s", "label": "Rotate speed (µsteps/s)", "type": "int", "default": _DEFAULTS.rotate_speed_usteps_per_s},
    {"key": "capture_sweep_output_deg", "label": "Capture sweep (output deg)", "type": "float", "default": _DEFAULTS.capture_sweep_output_deg},
    {"key": "kick_off_output_deg", "label": "Kick-off move (output deg)", "type": "float", "default": _DEFAULTS.kick_off_output_deg},
    {"key": "discharge_speed_usteps_per_s", "label": "Discharge speed (µsteps/s)", "type": "int", "default": _DEFAULTS.discharge_speed_usteps_per_s},
    {"key": "crop_padding_px", "label": "Crop padding (px)", "type": "int", "default": _DEFAULTS.crop_padding_px},
    {"key": "max_captures", "label": "Max captures per piece", "type": "int", "default": _DEFAULTS.max_captures},
    {"key": "rotate_timeout_s", "label": "Rotate timeout (s)", "type": "float", "default": _DEFAULTS.rotate_timeout_s},
    {"key": "classify_timeout_s", "label": "Classify timeout (s)", "type": "float", "default": _DEFAULTS.classify_timeout_s},
    {"key": "presence_streak_to_start", "label": "Presence streak to start rotation", "type": "int", "default": _DEFAULTS.presence_streak_to_start},
    {"key": "empty_streak_to_abort", "label": "Empty streak to abort rotation", "type": "int", "default": _DEFAULTS.empty_streak_to_abort},
    {"key": "stuck_in_exit_zone_timeout_s", "label": "Stuck-in-exit-zone warn timeout (s)", "type": "float", "default": _DEFAULTS.stuck_in_exit_zone_timeout_s},
    {"key": "home_offset_output_deg", "label": "Home offset (output deg)", "type": "float", "default": _DEFAULTS.home_offset_output_deg},
    {"key": "post_discharge_pause_ms", "label": "Post-discharge pause (ms)", "type": "float", "default": _DEFAULTS.post_discharge_pause_ms},
    {"key": "discharge_center_tolerance_deg", "label": "Discharge: fall-off centre tolerance (output deg)", "type": "float", "default": _DEFAULTS.discharge_center_tolerance_deg},
    {"key": "discharge_max_move_output_deg", "label": "Discharge: max single converge move (output deg)", "type": "float", "default": _DEFAULTS.discharge_max_move_output_deg},
    {"key": "discharge_total_timeout_ms", "label": "Discharge: total budget before stuck incident (ms)", "type": "int", "default": _DEFAULTS.discharge_total_timeout_ms},
    {"key": "discharge_stall_ms", "label": "Discharge: no-progress window before jitter (ms)", "type": "int", "default": _DEFAULTS.discharge_stall_ms},
    {"key": "discharge_progress_eps_deg", "label": "Discharge: min gap improvement to count as progress (deg)", "type": "float", "default": _DEFAULTS.discharge_progress_eps_deg},
    {"key": "discharge_clear_confirm_reads", "label": "Discharge: zero-read streak to confirm clear", "type": "int", "default": _DEFAULTS.discharge_clear_confirm_reads},
    {"key": "multi_feed_confirm_reads", "label": "Multi-feed: frames of >=2 pieces to confirm", "type": "int", "default": _DEFAULTS.multi_feed_confirm_reads},
    {"key": "verify_discharge_wait_ms", "label": "Verify-discharge: settle wait before re-check (ms)", "type": "int", "default": _DEFAULTS.verify_discharge_wait_ms},
    {"key": "verify_discharge_max_jitter_attempts", "label": "Verify-discharge: max jitter attempts", "type": "int", "default": _DEFAULTS.verify_discharge_max_jitter_attempts},
    {"key": "jitter_pause_ms", "label": "Jitter: pause between attempts (ms)", "type": "int", "default": _DEFAULTS.jitter_pause_ms},
    {"key": "jitter_amplitude_motor_deg", "label": "Jitter amplitude (motor deg)", "type": "float", "default": _DEFAULTS.jitter_amplitude_motor_deg},
    {"key": "jitter_cycles", "label": "Jitter cycles per burst", "type": "int", "default": _DEFAULTS.jitter_cycles},
    {"key": "jitter_speed_usteps_per_s", "label": "Jitter speed (\u00b5steps/s)", "type": "int", "default": _DEFAULTS.jitter_speed_usteps_per_s},
    {"key": "jitter_accel_usteps_per_s2", "label": "Jitter accel (\u00b5steps/s\u00b2)", "type": "int", "default": _DEFAULTS.jitter_accel_usteps_per_s2},
]


def configFromDict(d: dict) -> Rev01Config:
    cfg = Rev01Config()
    for meta in FIELD_META:
        k = meta["key"]
        if k not in d:
            continue
        raw = d[k]
        try:
            if meta["type"] == "int":
                setattr(cfg, k, int(raw))
            else:
                setattr(cfg, k, float(raw))
        except (TypeError, ValueError):
            pass
    return cfg


def configToDict(cfg: Rev01Config) -> dict:
    return {meta["key"]: getattr(cfg, meta["key"]) for meta in FIELD_META}
