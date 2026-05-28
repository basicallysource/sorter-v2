from dataclasses import dataclass


@dataclass
class Rev01Config:
    rotate_speed_usteps_per_s: int = 5000
    capture_sweep_output_deg: float = 180.0
    kick_off_output_deg: float = 180.0
    discharge_speed_usteps_per_s: int = 3000
    crop_padding_px: int = 15
    max_captures: int = 8
    rotate_timeout_s: float = 30.0
    classify_timeout_s: float = 30.0
    presence_streak_to_start: int = 2
    empty_streak_to_abort: int = 3
    stuck_in_exit_zone_timeout_s: float = 30.0
    home_offset_output_deg: float = 22.0
    # Pause between stepper completion and DISCHARGING -> VERIFYING_DISCHARGE.
    # Settles the carousel before the verifier reads vision.
    post_discharge_pause_ms: float = 300.0

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
