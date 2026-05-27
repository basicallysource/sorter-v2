from dataclasses import dataclass


@dataclass
class Rev01Config:
    rotate_speed_usteps_per_s: int = 5000
    capture_sweep_output_deg: float = 180.0
    kick_off_output_deg: float = 72.0
    discharge_speed_usteps_per_s: int = 3000
    crop_padding_px: int = 15
    max_captures: int = 8
    rotate_timeout_s: float = 30.0
    classify_timeout_s: float = 30.0
    presence_streak_to_start: int = 2
    empty_streak_to_abort: int = 3
    stuck_in_exit_zone_timeout_s: float = 30.0
    home_offset_output_deg: float = 22.0
    # Pause between stepper completion and DISCHARGING -> IDLE. This is the
    # quiet window before the SSM can advertise classification_ready again.
    post_discharge_pause_ms: float = 300.0


_DEFAULTS = Rev01Config()

FIELD_META: list[dict] = [
    {"key": "rotate_speed_usteps_per_s", "label": "Rotate speed (µsteps/s)", "type": "int", "default": _DEFAULTS.rotate_speed_usteps_per_s},
    {"key": "capture_sweep_output_deg", "label": "Capture sweep (output deg)", "type": "float", "default": _DEFAULTS.capture_sweep_output_deg},
    {"key": "kick_off_output_deg", "label": "Kick-off (output deg)", "type": "float", "default": _DEFAULTS.kick_off_output_deg},
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
