from dataclasses import dataclass


@dataclass
class Rev01Config:
    rotate_speed_usteps_per_s: int = 5000
    capture_sweep_output_deg: float = 180.0
    discharge_speed_usteps_per_s: int = 3000
    crop_padding_px: int = 15
    max_captures: int = 8
    rotate_timeout_s: float = 30.0
    discharge_timeout_s: float = 15.0
    classify_timeout_s: float = 30.0
    presence_streak_to_start: int = 2
    empty_streak_to_abort: int = 3


_DEFAULTS = Rev01Config()

FIELD_META: list[dict] = [
    {"key": "rotate_speed_usteps_per_s", "label": "Rotate speed (µsteps/s)", "type": "int", "default": _DEFAULTS.rotate_speed_usteps_per_s},
    {"key": "capture_sweep_output_deg", "label": "Capture sweep (output deg)", "type": "float", "default": _DEFAULTS.capture_sweep_output_deg},
    {"key": "discharge_speed_usteps_per_s", "label": "Discharge speed (µsteps/s)", "type": "int", "default": _DEFAULTS.discharge_speed_usteps_per_s},
    {"key": "crop_padding_px", "label": "Crop padding (px)", "type": "int", "default": _DEFAULTS.crop_padding_px},
    {"key": "max_captures", "label": "Max captures per piece", "type": "int", "default": _DEFAULTS.max_captures},
    {"key": "rotate_timeout_s", "label": "Rotate timeout (s)", "type": "float", "default": _DEFAULTS.rotate_timeout_s},
    {"key": "discharge_timeout_s", "label": "Discharge timeout (s)", "type": "float", "default": _DEFAULTS.discharge_timeout_s},
    {"key": "classify_timeout_s", "label": "Classify timeout (s)", "type": "float", "default": _DEFAULTS.classify_timeout_s},
    {"key": "presence_streak_to_start", "label": "Presence streak to start rotation", "type": "int", "default": _DEFAULTS.presence_streak_to_start},
    {"key": "empty_streak_to_abort", "label": "Empty streak to abort rotation", "type": "int", "default": _DEFAULTS.empty_streak_to_abort},
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
