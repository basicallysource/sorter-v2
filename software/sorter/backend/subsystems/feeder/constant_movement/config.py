from dataclasses import dataclass


@dataclass
class ConstantMovementConfig:
    # +1 carries pieces toward the exit (camera-clockwise = forward motor
    # direction). Flip to -1 if a channel's stepper is wired the other way.
    forward_direction_sign: int = 1
    # Per-channel constant speed in OUTPUT degrees per second. The channels run
    # continuously at these speeds and are only stopped by the gate conditions
    # below. C1 (bulk) meters admission for the whole machine, so it is by far
    # the slowest; each later channel runs faster than the one before it so the
    # gap between consecutive pieces grows at every hand-off.
    ch1_speed_output_deg_per_s: float = 2.0
    ch2_speed_output_deg_per_s: float = 6.0
    ch3_speed_output_deg_per_s: float = 10.0
    enable_ch1: bool = True
    enable_ch2: bool = True
    enable_ch3: bool = True
    # Hold C3 whenever it has a piece at the exit edge and the classification
    # channel reports it cannot accept one.
    gate_ch3_on_classification_ready: bool = True
    # After a stop condition clears, wait this long before restarting the
    # channel so a flickering detection can't chatter the motor on/off.
    resume_delay_ms: int = 200
    # Latch C2/C3/C4 drop-zone occupancy: once a piece is seen in the drop zone,
    # keep reporting that zone occupied until this many ms have passed with NO
    # drop-zone detection. Smooths over one/two-frame detector dropouts so an
    # upstream channel doesn't restart into a still-occupied zone. 0 disables.
    drop_zone_persistence_ms: int = 500
    # After a C3 dispense, keep C3's downstream considered not-ready this long
    # so the in-flight piece can register on the classification camera first.
    post_dispense_block_ms: int = 1500


_DEFAULTS = ConstantMovementConfig()

# ``section`` groups fields under a denoted subheader in the tuning UI. Order
# within a section is preserved; sections appear in first-seen order.
FIELD_META: list[dict] = [
    {"section": "Channel speeds", "key": "ch1_speed_output_deg_per_s", "label": "C1 (bulk) speed (output deg/s)", "type": "float", "default": _DEFAULTS.ch1_speed_output_deg_per_s, "description": "Constant speed for the bulk feeder. This is the admission valve for the whole machine — keep it very slow. C1 runs whenever C2's drop zone is clear."},
    {"section": "Channel speeds", "key": "ch2_speed_output_deg_per_s", "label": "C2 speed (output deg/s)", "type": "float", "default": _DEFAULTS.ch2_speed_output_deg_per_s, "description": "Constant speed for C2. Stops only when a piece is at C2's exit edge while C3's drop zone is occupied. Faster than C1 so the gap between consecutive pieces grows."},
    {"section": "Channel speeds", "key": "ch3_speed_output_deg_per_s", "label": "C3 speed (output deg/s)", "type": "float", "default": _DEFAULTS.ch3_speed_output_deg_per_s, "description": "Constant speed for C3. Fastest channel, for maximum separation. Stops only when a piece is at its exit edge and the classification channel can't take it (occupied drop zone or not ready)."},
    {"section": "Motion", "key": "forward_direction_sign", "label": "Forward direction sign (+1/-1)", "type": "int", "default": _DEFAULTS.forward_direction_sign, "description": "Which way the motors turn to carry pieces toward the exit. Leave at +1; use -1 only if the channel steppers are wired backwards and pieces move the wrong way."},
    {"section": "Channels", "key": "enable_ch1", "label": "Enable C1 (bulk)", "type": "bool", "default": _DEFAULTS.enable_ch1},
    {"section": "Channels", "key": "enable_ch2", "label": "Enable C2", "type": "bool", "default": _DEFAULTS.enable_ch2},
    {"section": "Channels", "key": "enable_ch3", "label": "Enable C3", "type": "bool", "default": _DEFAULTS.enable_ch3},
    {"section": "Channels", "key": "gate_ch3_on_classification_ready", "label": "Gate C3 on classification ready", "type": "bool", "default": _DEFAULTS.gate_ch3_on_classification_ready, "description": "Stop C3 from dispensing a piece into the classification channel (C4) until C4 reports it is ready to accept one. Prevents two pieces landing in the same spot."},
    {"section": "Stop/start behavior", "key": "resume_delay_ms", "label": "Resume delay after stop clears (ms)", "type": "int", "default": _DEFAULTS.resume_delay_ms, "description": "Once a channel's stop condition clears, wait this long before spinning it back up. Prevents rapid on/off chatter from detection flicker."},
    {"section": "Stop/start behavior", "key": "drop_zone_persistence_ms", "label": "Drop-zone occupancy hold (ms)", "type": "int", "default": _DEFAULTS.drop_zone_persistence_ms, "description": "After a piece is seen in a drop zone, keep treating that zone as occupied for this long even if the detector misses it for a frame or two. 0 = trust raw per-frame detection."},
    {"section": "Stop/start behavior", "key": "post_dispense_block_ms", "label": "Post-dispense block (ms)", "type": "int", "default": _DEFAULTS.post_dispense_block_ms, "description": "After C3 dispenses a piece, treat the classification channel as not-ready for this long so the in-flight piece can register on the C4 camera before C3 pushes another one."},
]


def configFromDict(d: dict) -> ConstantMovementConfig:
    cfg = ConstantMovementConfig()
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


def configToDict(cfg: ConstantMovementConfig) -> dict[str, object]:
    return {meta["key"]: getattr(cfg, meta["key"]) for meta in FIELD_META}
