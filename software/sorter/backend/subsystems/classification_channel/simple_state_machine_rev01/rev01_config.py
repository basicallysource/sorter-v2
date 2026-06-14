from dataclasses import dataclass


@dataclass
class Rev01Config:
    rotate_speed_usteps_per_s: int = 7000
    # Active-path UNUSED: the reverse capture-at-rest flow no longer sweeps the
    # carousel while photographing. Kept only for the legacy non-perception
    # fallback (a single fixed move).
    capture_sweep_output_deg: float = 180.0
    # How long CAPTURING photographs the piece AT REST before spawning the
    # Brickognize request and starting the reverse move to the precise zone. The
    # burst denoises / lets selectRecognitionCrops pick the sharpest frames; the
    # piece does not rotate, so the views are near-identical.
    capture_at_rest_ms: float = 350.0
    # Reverse converge to the precise staging zone (MOVING_TO_PRECISE). Slower
    # than the discharge converge so the approach into the narrow precise band is
    # gentle; tolerance is the |gap-to-precise-centre| at which we call it parked.
    precise_converge_speed_usteps_per_s: int = 5000
    precise_center_tolerance_deg: float = 4.0
    # Legacy fixed discharge kick (only used on the non-perception fallback path).
    # The active perception path closed-loops onto the fall-off centre instead;
    # see ``discharge_*`` fields below.
    kick_off_output_deg: float = 180.0
    discharge_speed_usteps_per_s: int = 5000
    crop_padding_px: int = 15
    # How many burst frames to GRAB at rest. Capped to the Brickognize
    # per-request image limit (8) by selectRecognitionCrops.
    max_captures: int = 8
    # Of the captured burst, how many of the most-recent (last-N, most-settled)
    # frames to actually USE for classification — anchored for the upstream
    # similarity search and sent to Brickognize. The rest of the burst is kept on
    # the piece for review but did not influence the result. 1 = last frame only.
    classify_burst_count: int = 1
    # Alongside the fused "combined" call, fire extra single-image Brickognize
    # requests IN PARALLEL and keep whichever result scores highest. These are
    # redundant, not sequential retries: a lone clean frame frequently recognizes
    # a piece the fused set confuses, and firing every variant concurrently costs
    # the same wall-clock as the slowest single call. A single-image request that
    # would duplicate the combined call (e.g. combined is already one burst frame)
    # is skipped.
    # single_burst: also send just the last (most-settled) C4 burst frame, alone.
    classify_parallel_single_burst: bool = True
    # single_upstream: also send just the single highest-similarity upstream
    # (C2/C3) match crop, alone. A no-op when no upstream was injected.
    classify_parallel_single_upstream: bool = True
    rotate_timeout_s: float = 30.0
    classify_timeout_s: float = 30.0
    presence_streak_to_start: int = 2
    empty_streak_to_abort: int = 3
    # Consecutive zero-piece reads in IDLE required before declaring the channel
    # clear and opening the C3->C4 feed gate. Without this a single detector
    # dropout (the bbox blinks off for a frame while a piece is still there)
    # flips ready=True and C3 pushes a second piece in → double feed. Symmetric
    # to presence_streak_to_start on the arrival side.
    idle_clear_confirm_reads: int = 3
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
    # How long the exit must read clear CONTINUOUSLY before we believe the piece
    # dropped and commit it. Time-based, not a stopped-read count: a piece is
    # only in the exit for a detection or two, so requiring N stopped reads
    # stalled it. The detector blinks, so the window must be unbroken — a single
    # non-clear frame resets it — which rejects one-frame blinks without needing
    # the carousel to be at rest.
    discharge_clear_confirm_ms: int = 500
    # When convergence + jitter exhaust without a confirmed clear, the piece has
    # almost always already dropped (a newcomer at the entry is holding n>0). We
    # no longer raise an operator incident; instead we wait this long for the
    # channel to settle (the confirmed-clear success path still fires if
    # perception sees it clear in this window), then credit the piece and return
    # to IDLE — exactly what an operator clicking Resolve-without-removing did.
    discharge_giveup_settle_ms: int = 1500
    # Consecutive distinct-frame reads with >=2 on-channel pieces required
    # before latching a multi-feed (which forces the whole cycle to MISC). The
    # detector regularly splits one piece into two boxes or emits a one-frame
    # spurious second box; a single such frame used to mis-flag a multi-drop.
    # Mirror the clear-confirm debounce so one noisy frame can't trip it.
    multi_feed_confirm_reads: int = 3

    # Jitter unstick: the ONLY trigger. If a piece sits in the FALL-OFF region
    # (the exit-only sub-arc, NOT the precise staging band — perception's
    # ``in_exit_majority``) continuously for this long, shake it loose. A piece
    # that drops on its own is in the fall-off for only a frame or two, so it
    # never reaches this; only a genuinely parked piece does.
    discharge_jitter_dwell_ms: int = 250

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
    {"key": "capture_sweep_output_deg", "label": "Capture sweep (output deg, legacy)", "type": "float", "default": _DEFAULTS.capture_sweep_output_deg},
    {"key": "capture_at_rest_ms", "label": "Capture-at-rest window (ms)", "type": "float", "default": _DEFAULTS.capture_at_rest_ms},
    {"key": "precise_converge_speed_usteps_per_s", "label": "Move-to-precise converge speed (µsteps/s)", "type": "int", "default": _DEFAULTS.precise_converge_speed_usteps_per_s},
    {"key": "precise_center_tolerance_deg", "label": "Move-to-precise: precise-centre tolerance (output deg)", "type": "float", "default": _DEFAULTS.precise_center_tolerance_deg},
    {"key": "kick_off_output_deg", "label": "Kick-off move (output deg)", "type": "float", "default": _DEFAULTS.kick_off_output_deg},
    {"key": "discharge_speed_usteps_per_s", "label": "Discharge speed (µsteps/s)", "type": "int", "default": _DEFAULTS.discharge_speed_usteps_per_s},
    {"key": "crop_padding_px", "label": "Crop padding (px)", "type": "int", "default": _DEFAULTS.crop_padding_px},
    {"key": "max_captures", "label": "Burst frames to grab per piece", "type": "int", "default": _DEFAULTS.max_captures},
    {"key": "classify_burst_count", "label": "Burst frames to use for classification (last N)", "type": "int", "default": _DEFAULTS.classify_burst_count},
    {"key": "classify_parallel_single_burst", "label": "Also classify the last burst frame alone, in parallel (keep best)", "type": "bool", "default": _DEFAULTS.classify_parallel_single_burst},
    {"key": "classify_parallel_single_upstream", "label": "Also classify the top upstream crop alone, in parallel (keep best)", "type": "bool", "default": _DEFAULTS.classify_parallel_single_upstream},
    {"key": "rotate_timeout_s", "label": "Rotate timeout (s)", "type": "float", "default": _DEFAULTS.rotate_timeout_s},
    {"key": "classify_timeout_s", "label": "Classify timeout (s)", "type": "float", "default": _DEFAULTS.classify_timeout_s},
    {"key": "presence_streak_to_start", "label": "Presence streak to start rotation", "type": "int", "default": _DEFAULTS.presence_streak_to_start},
    {"key": "empty_streak_to_abort", "label": "Empty streak to abort rotation", "type": "int", "default": _DEFAULTS.empty_streak_to_abort},
    {"key": "idle_clear_confirm_reads", "label": "Idle: zero-read streak to confirm clear (open feed gate)", "type": "int", "default": _DEFAULTS.idle_clear_confirm_reads},
    {"key": "stuck_in_exit_zone_timeout_s", "label": "Stuck-in-exit-zone warn timeout (s)", "type": "float", "default": _DEFAULTS.stuck_in_exit_zone_timeout_s},
    {"key": "home_offset_output_deg", "label": "Home offset (output deg)", "type": "float", "default": _DEFAULTS.home_offset_output_deg},
    {"key": "post_discharge_pause_ms", "label": "Post-discharge pause (ms)", "type": "float", "default": _DEFAULTS.post_discharge_pause_ms},
    {"key": "discharge_center_tolerance_deg", "label": "Discharge: fall-off centre tolerance (output deg)", "type": "float", "default": _DEFAULTS.discharge_center_tolerance_deg},
    {"key": "discharge_max_move_output_deg", "label": "Discharge: max single converge move (output deg)", "type": "float", "default": _DEFAULTS.discharge_max_move_output_deg},
    {"key": "discharge_total_timeout_ms", "label": "Discharge: total budget before give-up (ms)", "type": "int", "default": _DEFAULTS.discharge_total_timeout_ms},
    {"key": "discharge_clear_confirm_ms", "label": "Discharge: continuous-clear window to confirm drop (ms)", "type": "int", "default": _DEFAULTS.discharge_clear_confirm_ms},
    {"key": "discharge_giveup_settle_ms", "label": "Discharge: settle delay before auto-crediting on give-up (ms)", "type": "int", "default": _DEFAULTS.discharge_giveup_settle_ms},
    {"key": "multi_feed_confirm_reads", "label": "Multi-feed: frames of >=2 pieces to confirm", "type": "int", "default": _DEFAULTS.multi_feed_confirm_reads},
    {"key": "discharge_jitter_dwell_ms", "label": "Discharge: dwell in fall-off region before jitter (ms)", "type": "int", "default": _DEFAULTS.discharge_jitter_dwell_ms},
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
            elif meta["type"] == "bool":
                setattr(cfg, k, bool(raw))
            else:
                setattr(cfg, k, float(raw))
        except (TypeError, ValueError):
            pass
    return cfg


def configToDict(cfg: Rev01Config) -> dict:
    return {meta["key"]: getattr(cfg, meta["key"]) for meta in FIELD_META}
