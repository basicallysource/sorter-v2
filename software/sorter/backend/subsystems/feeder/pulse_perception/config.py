from dataclasses import dataclass


@dataclass
class PulsePerceptionConfig:
    # +1 carries pieces toward the exit (camera-clockwise = forward motor
    # direction). Flip to -1 if a channel's stepper is wired the other way.
    forward_direction_sign: int = 1
    move_speed_usteps_per_s: int = 2000
    # Ignore moves smaller than this (noise) and clamp any single move to the
    # max so a bad config value can never spin a channel wildly.
    min_move_output_deg: float = 0.1
    max_move_output_deg: float = 120.0
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


_DEFAULTS = PulsePerceptionConfig()

# ``section`` groups fields under a denoted subheader in the tuning UI. Order
# within a section is preserved; sections appear in first-seen order.
FIELD_META: list[dict] = [
    {"section": "Motion", "key": "forward_direction_sign", "label": "Forward direction sign (+1/-1)", "type": "int", "default": _DEFAULTS.forward_direction_sign},
    {"section": "Motion", "key": "move_speed_usteps_per_s", "label": "Move speed (µsteps/s)", "type": "int", "default": _DEFAULTS.move_speed_usteps_per_s},
    {"section": "Motion", "key": "min_move_output_deg", "label": "Min move (output deg)", "type": "float", "default": _DEFAULTS.min_move_output_deg},
    {"section": "Motion", "key": "max_move_output_deg", "label": "Max move clamp (output deg)", "type": "float", "default": _DEFAULTS.max_move_output_deg},
    {"section": "Drop-zone pulse", "key": "drop_pulse_output_deg", "label": "Drop-zone pulse distance (output deg)", "type": "float", "default": _DEFAULTS.drop_pulse_output_deg},
    {"section": "Drop-zone pulse", "key": "drop_pulse_pause_ms", "label": "Drop-zone pause between pulses (ms)", "type": "int", "default": _DEFAULTS.drop_pulse_pause_ms},
    {"section": "Exit pulse", "key": "exit_pulse_output_deg", "label": "Exit pulse distance (output deg)", "type": "float", "default": _DEFAULTS.exit_pulse_output_deg},
    {"section": "Exit pulse", "key": "exit_pulse_pause_ms", "label": "Exit pause between pulses (ms)", "type": "int", "default": _DEFAULTS.exit_pulse_pause_ms},
    {"section": "C1 (bulk)", "key": "ch1_pulse_output_deg", "label": "C1 bulk pulse distance (output deg)", "type": "float", "default": _DEFAULTS.ch1_pulse_output_deg},
    {"section": "C1 (bulk)", "key": "ch1_pulse_pause_ms", "label": "C1 pause between pulses (ms)", "type": "int", "default": _DEFAULTS.ch1_pulse_pause_ms},
    {"section": "Channels", "key": "gate_ch3_on_classification_ready", "label": "Gate C3 on classification ready", "type": "bool", "default": _DEFAULTS.gate_ch3_on_classification_ready},
    {"section": "Channels", "key": "enable_ch1", "label": "Enable C1 (bulk)", "type": "bool", "default": _DEFAULTS.enable_ch1},
    {"section": "Channels", "key": "enable_ch2", "label": "Enable C2", "type": "bool", "default": _DEFAULTS.enable_ch2},
    {"section": "Channels", "key": "enable_ch3", "label": "Enable C3", "type": "bool", "default": _DEFAULTS.enable_ch3},
    {"section": "Detection persistence", "key": "drop_zone_persistence_ms", "label": "C2/C3 drop-zone occupancy hold (ms)", "type": "int", "default": _DEFAULTS.drop_zone_persistence_ms},
    {"section": "Greedy mode", "key": "ch2_greedy_enabled", "label": "C2 greedy (advance piece anywhere on channel)", "type": "bool", "default": _DEFAULTS.ch2_greedy_enabled},
    {"section": "Greedy mode", "key": "ch3_greedy_enabled", "label": "C3 greedy (advance piece anywhere on channel)", "type": "bool", "default": _DEFAULTS.ch3_greedy_enabled},
    {"section": "Greedy mode", "key": "greedy_pulse_output_deg", "label": "Greedy advance pulse distance (output deg)", "type": "float", "default": _DEFAULTS.greedy_pulse_output_deg},
    {"section": "Greedy mode", "key": "greedy_pulse_pause_ms", "label": "Greedy advance pause between pulses (ms)", "type": "int", "default": _DEFAULTS.greedy_pulse_pause_ms},
]


def configFromDict(d: dict) -> PulsePerceptionConfig:
    cfg = PulsePerceptionConfig()
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
