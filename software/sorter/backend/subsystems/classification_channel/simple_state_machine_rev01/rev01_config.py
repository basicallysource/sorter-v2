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
    # Hard ceiling on burst frames GRABBED at rest. With require_sharp_capture
    # off (the default) this is what ends the burst — 4 frames ≈ 130 ms at
    # 30 fps, well inside the capture_at_rest_ms window — so every piece gets
    # exactly this many frames. With require_sharp_capture on it's only the
    # fallback cap; capture stops the instant a sharp frame lands.
    max_captures: int = 4
    # Motion-blur gate. Keep grabbing frames AT REST until at least one crop is
    # sharp — Laplacian variance of the bbox crop >= min_sharpness_laplacian_var —
    # then stop and classify. Bounds: never exceed max_captures frames or
    # capture_max_wait_ms. If no frame ever clears the floor, the sharpest crop
    # captured is still what gets sent (sharpest-frame selection below), so a
    # mis-tuned floor only costs latency, never correctness. The floor is
    # camera/lighting/piece dependent — watch the per-capture "sharp=" log values
    # and tune. Off by default: a sharp first frame ends the burst at ONE image,
    # so classify_burst_count > 1 never gets its frames; the fixed-window
    # behavior (stop at capture_at_rest_ms / max_captures) guarantees the full
    # burst instead.
    require_sharp_capture: bool = False
    min_sharpness_laplacian_var: float = 25.0
    # Hard time cap on the keep-waiting-for-sharp loop (only used when
    # require_sharp_capture is on).
    capture_max_wait_ms: float = 1000.0
    # Of the captured burst, how many frames to actually USE for classification —
    # i.e. sent to Brickognize. With require_sharp_capture on these are the
    # SHARPEST N crops (least motion blur);
    # otherwise the most-recent (last-N, most-settled) N. The rest of the burst is
    # kept on the piece for review but did not influence the result. Default
    # matches max_captures so the whole burst is used.
    classify_burst_count: int = 4
    # Alongside the "combined" call, fire an extra single-image Brickognize
    # request IN PARALLEL and keep whichever result scores highest. These are
    # redundant, not sequential retries: a lone clean frame frequently recognizes
    # a piece the combined set confuses, and firing every variant concurrently
    # costs the same wall-clock as the slowest single call. A single-image request
    # that would duplicate the combined call (e.g. combined is already one burst
    # frame) is skipped.
    # single_burst: also send just the last (most-settled) C4 burst frame, alone.
    classify_parallel_single_burst: bool = True
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
    {"key": "rotate_speed_usteps_per_s", "label": "Rotate speed (µsteps/s)", "type": "int", "default": _DEFAULTS.rotate_speed_usteps_per_s, "description": "Motor speed for normal C4 platter rotation (microsteps per second). Higher moves pieces faster but can fling light pieces."},
    {"key": "capture_sweep_output_deg", "label": "Capture sweep (output deg, legacy)", "type": "float", "default": _DEFAULTS.capture_sweep_output_deg, "description": "Legacy non-perception fallback only: single fixed move used to sweep a piece past the camera. Unused on the active perception path."},
    {"key": "capture_at_rest_ms", "label": "Capture-at-rest window (ms)", "type": "float", "default": _DEFAULTS.capture_at_rest_ms, "description": "With the sharp-frame gate OFF, how long the piece is photographed at rest. The burst ends at this window or the frame ceiling, whichever comes first (~30 fps, so 350 ms fits ~10 frames)."},
    {"key": "precise_converge_speed_usteps_per_s", "label": "Move-to-precise converge speed (µsteps/s)", "type": "int", "default": _DEFAULTS.precise_converge_speed_usteps_per_s, "description": "Motor speed for the reverse converge into the narrow precise staging band. Slower than normal rotation so the approach is gentle."},
    {"key": "precise_center_tolerance_deg", "label": "Move-to-precise: precise-centre tolerance (output deg)", "type": "float", "default": _DEFAULTS.precise_center_tolerance_deg, "description": "How close (in output degrees) the piece must be to the centre of the precise band to count as parked."},
    {"key": "kick_off_output_deg", "label": "Kick-off move (output deg)", "type": "float", "default": _DEFAULTS.kick_off_output_deg, "description": "Legacy non-perception fallback only: fixed move that shoves the piece off the channel at discharge. The active path closed-loops onto the fall-off centre instead."},
    {"key": "discharge_speed_usteps_per_s", "label": "Discharge speed (µsteps/s)", "type": "int", "default": _DEFAULTS.discharge_speed_usteps_per_s, "description": "Motor speed for discharge moves (driving the piece into the fall-off zone)."},
    {"key": "crop_padding_px", "label": "Crop padding (px)", "type": "int", "default": _DEFAULTS.crop_padding_px, "description": "Extra pixels added around the detected bounding box when cropping the piece image sent to classification."},
    {"key": "max_captures", "label": "Burst frames to grab per piece (hard ceiling)", "type": "int", "default": _DEFAULTS.max_captures, "description": "Most frames the at-rest burst will ever grab for one piece. With the sharp-frame gate off (the default) this is what ends the burst, so every piece gets exactly this many frames; with it on, this is only the fallback cap."},
    {"key": "require_sharp_capture", "label": "Keep capturing until a sharp (non-blurry) frame", "type": "bool", "default": _DEFAULTS.require_sharp_capture, "description": "On: keep grabbing frames until one clears the sharpness floor, then stop immediately — which can end the burst at a single image under good lighting. Off: grab a fixed burst (frame ceiling / at-rest window) with no blur check."},
    {"key": "min_sharpness_laplacian_var", "label": "Sharpness floor (Laplacian variance of bbox crop)", "type": "float", "default": _DEFAULTS.min_sharpness_laplacian_var, "description": "Blur threshold for the sharp-frame gate: a crop must score at least this (Laplacian variance) to count as sharp. Camera/lighting dependent — watch the per-capture \"sharp=\" log values to tune. Only used when the gate is on."},
    {"key": "capture_max_wait_ms", "label": "Max wait for a sharp frame (ms)", "type": "float", "default": _DEFAULTS.capture_max_wait_ms, "description": "Hard time cap on waiting for a sharp frame. If nothing clears the floor in time, the sharpest crop captured is used anyway. Only used when the sharp-frame gate is on."},
    {"key": "classify_burst_count", "label": "Burst frames to use for classification (last N)", "type": "int", "default": _DEFAULTS.classify_burst_count, "description": "Of the captured burst, how many frames are actually sent to Brickognize. Picks the sharpest N when the sharp-frame gate is on, the last (most settled) N otherwise. Can't exceed what the burst captured."},
    {"key": "classify_parallel_single_burst", "label": "Also classify the last burst frame alone, in parallel (keep best)", "type": "bool", "default": _DEFAULTS.classify_parallel_single_burst, "description": "Alongside the combined multi-image request, also send just the last burst frame as its own Brickognize call and keep whichever result scores highest. A lone clean frame often recognizes a piece the fused set confuses; costs no extra wall-clock."},
    {"key": "rotate_timeout_s", "label": "Rotate timeout (s)", "type": "float", "default": _DEFAULTS.rotate_timeout_s, "description": "Give up on a rotation move if the stepper hasn't reported done within this long (raises an incident instead of hanging)."},
    {"key": "classify_timeout_s", "label": "Classify timeout (s)", "type": "float", "default": _DEFAULTS.classify_timeout_s, "description": "Give up on the Brickognize classification request after this long; the piece is sent to MISC."},
    {"key": "presence_streak_to_start", "label": "Presence streak to start rotation", "type": "int", "default": _DEFAULTS.presence_streak_to_start, "description": "Consecutive frames a piece must be detected before the channel starts processing it. Filters one-frame detector blips."},
    {"key": "empty_streak_to_abort", "label": "Empty streak to abort rotation", "type": "int", "default": _DEFAULTS.empty_streak_to_abort, "description": "Consecutive empty frames during rotation before concluding the piece is gone and aborting the cycle."},
    {"key": "idle_clear_confirm_reads", "label": "Idle: zero-read streak to confirm clear (open feed gate)", "type": "int", "default": _DEFAULTS.idle_clear_confirm_reads, "description": "Consecutive zero-piece reads in IDLE required before declaring the channel clear and letting C3 feed the next piece. Guards against a one-frame detector dropout causing a double feed."},
    {"key": "stuck_in_exit_zone_timeout_s", "label": "Stuck-in-exit-zone warn timeout (s)", "type": "float", "default": _DEFAULTS.stuck_in_exit_zone_timeout_s, "description": "If a piece sits in the exit zone this long without dropping, warn the operator."},
    {"key": "home_offset_output_deg", "label": "Home offset (output deg)", "type": "float", "default": _DEFAULTS.home_offset_output_deg, "description": "Offset from the homing sensor position to the channel's actual zero, in output degrees."},
    {"key": "post_discharge_pause_ms", "label": "Post-discharge pause (ms)", "type": "float", "default": _DEFAULTS.post_discharge_pause_ms, "description": "Legacy non-perception fallback only: pause after the fixed kick-off move before returning to IDLE so the carousel settles."},
    {"key": "discharge_center_tolerance_deg", "label": "Discharge: fall-off centre tolerance (output deg)", "type": "float", "default": _DEFAULTS.discharge_center_tolerance_deg, "description": "How close the piece must be driven to the centre of the fall-off zone before the closed-loop discharge stops commanding moves."},
    {"key": "discharge_max_move_output_deg", "label": "Discharge: max single converge move (output deg)", "type": "float", "default": _DEFAULTS.discharge_max_move_output_deg, "description": "Clamp on any single discharge converge move, so a bad angle reading can never spin the platter wildly."},
    {"key": "discharge_total_timeout_ms", "label": "Discharge: total budget before give-up (ms)", "type": "int", "default": _DEFAULTS.discharge_total_timeout_ms, "description": "One overall time budget for discharging a piece-set (not per move). If it runs out with the channel still occupied, the stuck-piece handling kicks in."},
    {"key": "discharge_clear_confirm_ms", "label": "Discharge: continuous-clear window to confirm drop (ms)", "type": "int", "default": _DEFAULTS.discharge_clear_confirm_ms, "description": "How long the exit must read clear WITHOUT interruption before the piece counts as dropped. A single non-clear frame resets the window, so one-frame detector blinks can't fake a drop."},
    {"key": "discharge_giveup_settle_ms", "label": "Discharge: settle delay before auto-crediting on give-up (ms)", "type": "int", "default": _DEFAULTS.discharge_giveup_settle_ms, "description": "When discharge exhausts its attempts without a confirmed clear (usually the piece actually dropped and a newcomer is holding the count up), wait this long for the channel to settle, then credit the piece and return to IDLE."},
    {"key": "multi_feed_confirm_reads", "label": "Multi-feed: frames of >=2 pieces to confirm", "type": "int", "default": _DEFAULTS.multi_feed_confirm_reads, "description": "Consecutive distinct frames showing 2+ pieces on the channel before latching a multi-feed (which sends the whole cycle to MISC). Stops a one-frame split detection from mis-flagging."},
    {"key": "discharge_jitter_dwell_ms", "label": "Discharge: dwell in fall-off region before jitter (ms)", "type": "int", "default": _DEFAULTS.discharge_jitter_dwell_ms, "description": "If a piece sits continuously in the fall-off region this long, it's parked — shake it loose with a jitter. A piece dropping normally is only there for a frame or two, so it never triggers this."},
    {"key": "verify_discharge_wait_ms", "label": "Verify-discharge: settle wait before re-check (ms)", "type": "int", "default": _DEFAULTS.verify_discharge_wait_ms, "description": "After a discharge move settles, wait this long before the first exit-zone re-check."},
    {"key": "verify_discharge_max_jitter_attempts", "label": "Verify-discharge: max jitter attempts", "type": "int", "default": _DEFAULTS.verify_discharge_max_jitter_attempts, "description": "If the piece still reads stuck after the settle wait, run up to this many jitter attempts before giving up."},
    {"key": "jitter_pause_ms", "label": "Jitter: pause between attempts (ms)", "type": "int", "default": _DEFAULTS.jitter_pause_ms, "description": "Pause between jitter attempts, giving the piece time to fall before shaking again."},
    {"key": "jitter_amplitude_motor_deg", "label": "Jitter amplitude (motor deg)", "type": "float", "default": _DEFAULTS.jitter_amplitude_motor_deg, "description": "Size of each back-and-forth jitter oscillation, in motor degrees."},
    {"key": "jitter_cycles", "label": "Jitter cycles per burst", "type": "int", "default": _DEFAULTS.jitter_cycles, "description": "Back-and-forth oscillations per jitter attempt."},
    {"key": "jitter_speed_usteps_per_s", "label": "Jitter speed (\u00b5steps/s)", "type": "int", "default": _DEFAULTS.jitter_speed_usteps_per_s, "description": "Motor speed during jitter oscillations."},
    {"key": "jitter_accel_usteps_per_s2", "label": "Jitter accel (\u00b5steps/s\u00b2)", "type": "int", "default": _DEFAULTS.jitter_accel_usteps_per_s2, "description": "Motor acceleration during jitter oscillations — high, so the shake is sharp enough to unstick a piece."},
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
