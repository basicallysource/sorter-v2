from dataclasses import dataclass


@dataclass
class BeltFeederConfig:
    # Base (100%) belt speed. The controller scales this down as C3 fills up,
    # so this is the speed the belt runs at while C3 wants more pieces.
    belt_speed_usteps_per_s: int = 2000
    # +1 carries the cleats upward toward the drop-off into C3. Flip to -1 if
    # the belt motor is wired the other way.
    forward_direction_sign: int = 1
    # Fill-level controller on C3's perception piece count: at or below
    # ``c3_full_speed_pieces`` the belt runs at 100%; at or above
    # ``c3_stop_pieces`` it stops; linear ramp in between. Because the boat at
    # the belt's foot buffers and the cleats self-meter, this can be lazy —
    # the belt keeps running through cleat bursts instead of stop/go feeding.
    c3_full_speed_pieces: int = 1
    c3_stop_pieces: int = 3
    # Issue at most one speed change per interval so a flickering piece count
    # doesn't hammer the serial bus with move_at_speed commands.
    speed_update_interval_ms: int = 250
    # No new piece arrived in C3 although the belt has been running at speed
    # for this long -> boat empty or belt jammed; raise an operator incident.
    # 0 disables jam detection.
    jam_timeout_s: float = 20.0
    # Load watch without an encoder: while the belt runs, the TMC2209's
    # StallGuard result (SG_RESULT, 0..1023, high = free-running, towards 0 =
    # loaded/blocked) is read every ``load_poll_interval_ms``. Below
    # ``load_block_sg_threshold`` for ``load_block_samples`` consecutive reads the
    # belt stops and the operator incident is raised instead of pushing on: on
    # 2026-09-06 the belt drove 45 s plus three watchdog nudges into a blockage
    # and sheared its drive shaft. 0 = watch only (values are logged and shown
    # in the status) until the threshold has been read off the repaired machine.
    load_block_sg_threshold: int = 0
    load_block_samples: int = 3
    load_poll_interval_ms: int = 500
    enable_belt: bool = True


_DEFAULTS = BeltFeederConfig()

# ``section`` groups fields under a denoted subheader in the tuning UI. Order
# within a section is preserved; sections appear in first-seen order.
FIELD_META: list[dict] = [
    {"section": "Belt", "key": "enable_belt", "label": "Enable belt", "type": "bool", "default": _DEFAULTS.enable_belt, "description": "Master switch for the B1 belt motor. Off = the belt never moves; C3 keeps metering whatever is already on it."},
    {"section": "Belt", "key": "belt_speed_usteps_per_s", "label": "Belt base speed (µsteps/s)", "type": "int", "default": _DEFAULTS.belt_speed_usteps_per_s, "description": "Belt speed while C3 wants more pieces (the 100% point of the fill-level ramp). Cleat spacing × this speed sets the burst cadence into C3."},
    {"section": "Belt", "key": "forward_direction_sign", "label": "Forward direction sign (+1/-1)", "type": "int", "default": _DEFAULTS.forward_direction_sign, "description": "Which way the motor turns to carry cleats up toward the C3 drop-off. Use -1 only if the belt runs backwards."},
    {"section": "C3 fill-level control", "key": "c3_full_speed_pieces", "label": "C3 pieces for full speed", "type": "int", "default": _DEFAULTS.c3_full_speed_pieces, "description": "While C3 has at most this many pieces the belt runs at 100% base speed."},
    {"section": "C3 fill-level control", "key": "c3_stop_pieces", "label": "C3 pieces for full stop", "type": "int", "default": _DEFAULTS.c3_stop_pieces, "description": "Once C3 holds this many pieces (or more) the belt stops. Between the full-speed and stop counts the speed ramps down linearly."},
    {"section": "C3 fill-level control", "key": "speed_update_interval_ms", "label": "Speed update interval (ms)", "type": "int", "default": _DEFAULTS.speed_update_interval_ms, "description": "Minimum time between belt speed changes, so a flickering piece count doesn't spam the motor."},
    {"section": "Jam detection", "key": "jam_timeout_s", "label": "Jam timeout (s)", "type": "float", "default": _DEFAULTS.jam_timeout_s, "description": "If the belt has been running this long without a single new piece arriving in C3, raise a belt-stalled incident (boat empty or belt jammed). 0 disables."},
    {"key": "load_block_sg_threshold", "label": "Belt load: SG_RESULT block threshold", "type": "int", "default": _DEFAULTS.load_block_sg_threshold, "description": "StallGuard result below which the running belt counts as blocked (0..1023; high = free-running). 0 = watch only: the value is logged and shown in the status so the threshold can be read off the real machine before enabling."},
    {"key": "load_block_samples", "label": "Belt load: consecutive blocked reads", "type": "int", "default": _DEFAULTS.load_block_samples, "description": "How many consecutive reads below the threshold stop the belt and raise the incident."},
    {"key": "load_poll_interval_ms", "label": "Belt load: poll interval (ms)", "type": "int", "default": _DEFAULTS.load_poll_interval_ms, "description": "How often SG_RESULT is read while the belt runs."},
]


def configFromDict(d: dict) -> BeltFeederConfig:
    cfg = BeltFeederConfig()
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


def configToDict(cfg: BeltFeederConfig) -> dict[str, object]:
    return {meta["key"]: getattr(cfg, meta["key"]) for meta in FIELD_META}
