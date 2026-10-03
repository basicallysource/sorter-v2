"""StallGuard stall detection: load sweeps, thresholds, and clearing stalls."""

from __future__ import annotations

import math
import random
import threading
import time
from typing import Any, Dict, List, Optional

import stepper_telemetry

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from server import shared_state
from server.routers.steppers import (
    TMC_REG_DRV_STATUS, TMC_REG_GCONF, TMC_REG_SG_RESULT, TMC_REG_SGTHRS, TMC_REG_TCOOLTHRS, TMC_REG_TSTEP,
    _STEPPER_API_TO_TOML_NAME, _ensure_manual_motion_allowed, _ensure_not_homing, _halt_stepper,
    _resolve_stepper, _safe_read_register, _stepper_mapping, _write_stepper_settings,
)
from stepper_stall_monitor import CHUTE_NEEDS_HOMING_INCIDENT_KIND, STEPPER_STALL_INCIDENT_KIND

router = APIRouter()


# ---------------------------------------------------------------------------
# StallGuard tuning — data collection sweep + threshold persistence
# ---------------------------------------------------------------------------

# A sweep is a pure measurement: it runs the motor at constant speed, polls
# SG_RESULT (load proxy, 0-510; drops toward 0 as load rises) plus CS_ACTUAL and
# TSTEP, then stops. It never writes SGTHRS and restores TCOOLTHRS=0 on exit, so
# it cannot leave stall enforcement half-configured. StallGuard only reports
# while running above the TCOOLTHRS velocity floor, so we raise TCOOLTHRS for the
# duration to keep SG_RESULT live across the operating range.
DEFAULT_STALLGUARD_TCOOLTHRS = 0xFFFFF


class StallGuardSample(BaseModel):
    t: float
    sg_result: int
    cs_actual: int
    tstep: int


class StallGuardSweepStats(BaseModel):
    samples: int
    sg_min: int
    sg_max: int
    sg_mean: float
    suggested_sgthrs: int
    suggested_trigger_level: int


class StallGuardSweepResponse(BaseModel):
    success: bool
    stepper: str
    speed: int
    duration_s: float
    sample_interval_s: float
    tcoolthrs: int
    run_id: str
    samples: List[StallGuardSample]
    stats: Optional[StallGuardSweepStats]


def _suggested_sgthrs(sg_min: int) -> int:
    # Heuristic validated on the stall-01 bring-up: place the trigger well below
    # the unloaded minimum so normal running never trips, but high enough that a
    # real stall (SG_RESULT -> ~0) does. DIAG fires at SG_RESULT <= 2*SGTHRS.
    return max(1, int(sg_min * 0.4) // 2)


# ---------------------------------------------------------------------------
# Sweep motion profiles
#
# A constant-speed spin is a poor stand-in for how a motor is actually loaded in
# service: the chute aims to angles and reverses (a constant spin just rams its
# endstop and reads SG_RESULT=0), and the rotors/carousel run in discrete pulses
# with dwells and the odd unstick jitter — not a steady cruise. These profiles
# reproduce that so the recorded SG_RESULT reflects real operating load.
#
# Each profile models its own timeline from estimated move durations and exposes
# moving(now): the sampler only records load-bearing motion phases and ignores
# idle dwells, so dwell zeros don't pollute the threshold. No extra UART status
# reads — the sample loop is already bus-bound.
# ---------------------------------------------------------------------------

SWEEP_PROFILES = ("constant", "chute_random", "pulsed")

# Defaults for the unstick jitter folded into the pulsed profile, matching the
# feeder's fall-recovery values.
_PULSED_JITTER_AMPLITUDE_DEG = 6.0
_PULSED_JITTER_CYCLES = 8
_PULSED_JITTER_SPEED = 6500
_PULSED_JITTER_ACCEL = 180000


class _SweepMotion:
    def start(self, now: float) -> None: ...
    def tick(self, now: float) -> None: ...
    def moving(self, now: float) -> bool:
        return True


class _ConstantMotion(_SweepMotion):
    def __init__(self, target: Any, signed_speed: int) -> None:
        self._target = target
        self._signed_speed = signed_speed

    def start(self, now: float) -> None:
        if not bool(self._target.move_at_speed(self._signed_speed, force=True)):
            raise RuntimeError("move_at_speed was not acknowledged")


# The chute hits HARD STOPS at 0 and 360 deg of output travel (it can cross
# neither). Stay well inside that with the same cap the stress test uses.
CHUTE_SAFE_MAX_DEG = 345.0


class _ChuteRandomMotion(_SweepMotion):
    """Random go-to-angle with immediate turnaround on the real chute, like the
    chute stress test. Operates on the homed Chute object in ABSOLUTE output
    degrees clamped to [min_deg, max_deg] within [0, CHUTE_SAFE_MAX_DEG], so it
    can never reach an endstop. Homes first if the chute lacks a reference —
    without that, "0 deg" is wherever it powered on and the clamp is meaningless.
    Targets are at least min_delta_deg apart so every move is a real excursion."""

    def __init__(self, chute: Any, speed: int, min_delta_deg: float, min_deg: float, max_deg: float) -> None:
        self._chute = chute
        self._speed = speed
        self._min_delta = max(1.0, min_delta_deg)
        self._min = max(0.0, min(min_deg, CHUTE_SAFE_MAX_DEG))
        self._max = max(self._min, min(max_deg, CHUTE_SAFE_MAX_DEG))
        # Don't re-check stopped for a beat after issuing a move, so we don't read
        # a stale "stopped" before the firmware has started the move.
        self._next_check_at = 0.0

    def _home_if_needed(self) -> None:
        if bool(getattr(self._chute, "homed", False)):
            return
        from subsystems.distribution.chute import HOME_SPEED_MICROSTEPS_PER_SEC, HOME_TIMEOUT_MS

        st = self._chute.stepper
        st.enabled = True
        st.home(
            HOME_SPEED_MICROSTEPS_PER_SEC,
            self._chute.home_pin,
            home_pin_active_high=self._chute.endstop_active_high,
        )
        deadline = time.monotonic() + HOME_TIMEOUT_MS / 1000.0 + 5.0
        while time.monotonic() < deadline:
            try:
                if st.stopped:
                    break
            except Exception:
                break
            time.sleep(0.02)

    def _pick(self, current: float) -> float:
        for _ in range(20):
            cand = random.uniform(self._min, self._max)
            if abs(cand - current) >= self._min_delta:
                return cand
        mid = (self._min + self._max) / 2.0
        return self._max if current < mid else self._min

    def _go(self, now: float) -> None:
        current = float(self._chute.current_angle)
        target_deg = self._pick(current)
        self._chute.moveToAngle(target_deg)  # absolute, clamps to [0,360]
        self._next_check_at = now + 0.05

    def start(self, now: float) -> None:
        self._chute.stepper.set_speed_limits(0, self._speed)
        self._home_if_needed()
        self._go(now)

    def tick(self, now: float) -> None:
        # Issue the next target only once the previous move has actually finished.
        # Re-issuing on a guessed timer floods the chute with overlapping reversals
        # it can't follow (it stalls in place); waiting for a real stop gives clean
        # go-to-angle moves. Immediate turnaround on stop = the quick reversal.
        if now < self._next_check_at:
            return
        try:
            if self._chute.stepper.stopped:
                self._go(now)
        except Exception:
            pass


class _PulsedMotion(_SweepMotion):
    """Discrete forward pulses with a dwell between (how the rotors and carousel
    actually run), with an unstick jitter folded in every jitter_every pulses.
    moving() is true only during the move/jitter phase, not the dwell."""

    def __init__(
        self,
        target: Any,
        speed: int,
        pulse_deg: float,
        dwell_ms: float,
        jitter_every: int,
        sign: int,
    ) -> None:
        self._target = target
        self._speed = speed
        self._pulse_deg = abs(pulse_deg) * (1 if sign >= 0 else -1)
        self._dwell = max(0.0, dwell_ms) / 1000.0
        self._jitter_every = max(0, jitter_every)
        self._count = 0
        self._phase_end = 0.0
        self._dwell_end = 0.0

    def _next(self, now: float) -> None:
        self._count += 1
        if self._jitter_every and self._count % self._jitter_every == 0:
            self._target.jitter_degrees(
                _PULSED_JITTER_AMPLITUDE_DEG,
                _PULSED_JITTER_CYCLES,
                _PULSED_JITTER_SPEED,
                _PULSED_JITTER_ACCEL,
                force=True,
            )
            # Rough upper bound on jitter duration; only gates sampling, not motion.
            dur_ms = max(200, _PULSED_JITTER_CYCLES * 60)
        else:
            self._target.set_speed_limits(0, self._speed)
            self._target.move_degrees(self._pulse_deg, force=True)
            dur_ms = self._target.estimateMoveDegreesMs(abs(self._pulse_deg), max_speed=self._speed)
        self._phase_end = now + max(dur_ms, 1) / 1000.0
        self._dwell_end = self._phase_end + self._dwell

    def start(self, now: float) -> None:
        self._next(now)

    def tick(self, now: float) -> None:
        if now >= self._dwell_end:
            self._next(now)

    def moving(self, now: float) -> bool:
        return now < self._phase_end


@router.post("/stepper/stallguard-sweep", response_model=StallGuardSweepResponse)
def stallguard_sweep(
    stepper: str,
    speed: int,
    direction: str = "cw",
    duration_s: float = 4.0,
    sample_interval_s: float = 0.02,
    spin_up_s: float = 0.3,
    tcoolthrs: int = DEFAULT_STALLGUARD_TCOOLTHRS,
    cruise_tstep: int = 150,
    loaded: bool = False,
    label: Optional[str] = None,
    profile: str = "constant",
    chute_min_deg: float = 10.0,
    chute_max_deg: float = 340.0,
    min_delta_deg: float = 30.0,
    pulse_deg: float = 30.0,
    dwell_ms: float = 250.0,
    jitter_every: int = 5,
) -> StallGuardSweepResponse:
    _ensure_manual_motion_allowed("run a StallGuard sweep")
    if speed <= 0:
        raise HTTPException(status_code=400, detail="speed must be > 0")
    if direction not in ("cw", "ccw"):
        raise HTTPException(status_code=400, detail="direction must be 'cw' or 'ccw'")
    if profile not in SWEEP_PROFILES:
        raise HTTPException(
            status_code=400, detail=f"profile must be one of {', '.join(SWEEP_PROFILES)}"
        )
    if cruise_tstep <= 0:
        raise HTTPException(status_code=400, detail="cruise_tstep must be > 0")
    if duration_s <= 0:
        raise HTTPException(status_code=400, detail="duration_s must be > 0")
    if sample_interval_s <= 0:
        raise HTTPException(status_code=400, detail="sample_interval_s must be > 0")

    target = _resolve_stepper(stepper)

    lock = shared_state.pulse_locks.setdefault(stepper, threading.Lock())
    if not lock.acquire(blocking=False):
        raise HTTPException(status_code=409, detail=f"Stepper '{stepper}' is busy")

    signed_speed = speed if direction == "cw" else -speed
    sign = 1 if direction == "cw" else -1
    samples: List[StallGuardSample] = []
    telemetry_rows: List[Dict[str, Any]] = []

    chute_restore_speed: Optional[int] = None
    if profile == "chute_random":
        # The chute has hard endstops, so its motion must run on the homed Chute
        # object (absolute, clamped angles) — never a raw open-loop spin.
        irl = shared_state.getActiveIRL()
        chute = getattr(irl, "chute", None) if irl is not None else None
        if chute is None:
            lock.release()
            raise HTTPException(
                status_code=409,
                detail="chute_random needs the initialized chute; initialize hardware first.",
            )
        chute_restore_speed = int(getattr(chute, "operating_speed_microsteps_per_second", speed))
        motion: _SweepMotion = _ChuteRandomMotion(
            chute, speed, min_delta_deg, chute_min_deg, chute_max_deg
        )
    elif profile == "pulsed":
        motion = _PulsedMotion(target, speed, pulse_deg, dwell_ms, jitter_every, sign)
    else:
        motion = _ConstantMotion(target, signed_speed)

    # Static per-run context, captured once (these don't change mid-sweep).
    channel_ctx = getattr(target, "channel", None)
    microsteps_ctx = getattr(target, "_microsteps", None)
    last_current = getattr(target, "last_set_current", None)
    irun_ctx = last_current.get("irun") if isinstance(last_current, dict) else None
    # Acceleration the sweep runs at: move_at_speed re-asserts the stepper's
    # configured default acceleration, so that's the value in effect per sample.
    accel_ctx = getattr(target, "default_acceleration", None)
    gconf = _safe_read_register(target, TMC_REG_GCONF)
    stealth_ctx = (not bool(gconf & (1 << 2))) if isinstance(gconf, int) else None

    source = stepper_telemetry.SOURCE_STALL_TEST if loaded else stepper_telemetry.SOURCE_SWEEP
    run_id = stepper_telemetry.createRun(
        source,
        stepper_name=stepper,
        label=label,
        params={
            "speed": signed_speed,
            "direction": direction,
            "duration_s": duration_s,
            "sample_interval_s": sample_interval_s,
            "tcoolthrs": tcoolthrs,
            "cruise_tstep": cruise_tstep,
            "loaded": loaded,
            "irun": irun_ctx,
            "acceleration": accel_ctx,
            "microsteps": microsteps_ctx,
            "stealthchop": stealth_ctx,
            "profile": profile,
            "chute_min_deg": chute_min_deg if profile == "chute_random" else None,
            "chute_max_deg": chute_max_deg if profile == "chute_random" else None,
            "min_delta_deg": min_delta_deg if profile == "chute_random" else None,
            "pulse_deg": pulse_deg if profile == "pulsed" else None,
            "dwell_ms": dwell_ms if profile == "pulsed" else None,
            "jitter_every": jitter_every if profile == "pulsed" else None,
        },
    )

    try:
        # The sweep deliberately stalls the motor (loaded test) and opens the
        # velocity floor wide — so turn live stall detection OFF for the duration,
        # or an enabled motor would trip its own incident mid-sweep. This is the
        # ONE place detection is suppressed; it's restored in the finally.
        try:
            target.enable_stall_detection(False)
        except Exception:
            pass
        # Measure with SG reported across the whole speed range; the cruise_tstep
        # filter is applied at analysis time so we still see the transients in the
        # chart but don't let them set the threshold.
        target.write_driver_register(TMC_REG_TCOOLTHRS, tcoolthrs)
        target.enable_force(True)
        motion.start(time.monotonic())

        # A constant spin needs a moment to reach speed before SG_RESULT is valid;
        # the pulsed/chute profiles are sampled per-move via moving(), so skip it.
        if profile == "constant":
            time.sleep(min(max(spin_up_s, 0.0), 2.0))

        wall_start = time.time()
        t_start = time.monotonic()
        while True:
            now = time.monotonic()
            t = now - t_start
            if t >= duration_s:
                break
            motion.tick(now)
            if not motion.moving(now):
                # Idle dwell between pulses — its SG_RESULT isn't load data.
                remaining = sample_interval_s - (time.monotonic() - t_start - t)
                if remaining > 0:
                    time.sleep(remaining)
                continue
            sg = _safe_read_register(target, TMC_REG_SG_RESULT)
            drv = _safe_read_register(target, TMC_REG_DRV_STATUS)
            tstep = _safe_read_register(target, TMC_REG_TSTEP)
            sg_val = sg if isinstance(sg, int) else None
            cs_val = ((drv >> 16) & 0x1F) if isinstance(drv, int) else None
            tstep_val = tstep if isinstance(tstep, int) else None
            samples.append(
                StallGuardSample(
                    t=round(t, 4),
                    sg_result=sg_val if sg_val is not None else -1,
                    cs_actual=cs_val if cs_val is not None else -1,
                    tstep=tstep_val if tstep_val is not None else -1,
                )
            )
            telemetry_rows.append(
                {
                    "recorded_at": wall_start + t,
                    "stepper_name": stepper,
                    "channel": channel_ctx,
                    "sg_result": sg_val,
                    "cs_actual": cs_val,
                    "tstep": tstep_val,
                    "drv_status_raw": drv if isinstance(drv, int) else None,
                    "commanded_speed": signed_speed,
                    "irun": irun_ctx,
                    "acceleration": accel_ctx,
                    "microsteps": microsteps_ctx,
                    "stealthchop": stealth_ctx,
                    "loaded": loaded,
                }
            )
            remaining = sample_interval_s - (time.monotonic() - t_start - t)
            if remaining > 0:
                time.sleep(remaining)
    except Exception as e:
        # Best-effort save of partial data, but never let a DB error mask the
        # underlying motor failure we're about to surface.
        try:
            stepper_telemetry.insertSamples(run_id, telemetry_rows)
            stepper_telemetry.finishRun(
                run_id, status=stepper_telemetry.RUN_STATUS_ERROR, error=str(e)
            )
        except Exception:
            pass
        raise HTTPException(status_code=500, detail=f"StallGuard sweep failed: {e}")
    finally:
        try:
            _halt_stepper(target, force=True)
        except Exception:
            pass
        # Restore the motor's resting state. If it has live stall detection
        # configured, put its enforcement velocity floor back and re-enable
        # detection (we turned it off above); otherwise just zero the floor so the
        # sweep leaves nothing half-configured.
        try:
            if getattr(target, "stallguard_enabled", False) and target.stallguard_sgthrs is not None:
                target.write_driver_register(TMC_REG_TCOOLTHRS, target.stallguard_tcoolthrs)
                target.clear_stall()
                target.enable_stall_detection(True)
            else:
                target.write_driver_register(TMC_REG_TCOOLTHRS, 0)
        except Exception:
            pass
        # chute_random retunes the chute stepper's speed limits; restore them to
        # the chute's operating speed so normal aiming isn't left at sweep speed.
        if chute_restore_speed is not None:
            try:
                target.set_speed_limits(16, chute_restore_speed)
            except Exception:
                pass
        try:
            lock.release()
        except RuntimeError:
            pass

    valid = [s.sg_result for s in samples if s.sg_result >= 0]
    # Threshold tuning only considers CRUISE samples (TSTEP <= cruise_tstep). At
    # accel/decel/reversal the velocity is low and SG_RESULT dips even unloaded,
    # which would drag the floor down and produce a uselessly low threshold. The
    # chart still shows every sample; only the suggestion is cruise-filtered.
    cruise = [s.sg_result for s in samples if s.sg_result >= 0 and 0 <= s.tstep <= cruise_tstep]
    basis = cruise if cruise else valid
    stats: Optional[StallGuardSweepStats] = None
    sgthrs: Optional[int] = None
    if basis:
        sg_min = min(basis)
        sgthrs = _suggested_sgthrs(sg_min)
        stats = StallGuardSweepStats(
            samples=len(basis),
            sg_min=sg_min,
            sg_max=max(basis),
            sg_mean=round(sum(basis) / len(basis), 1),
            suggested_sgthrs=sgthrs,
            suggested_trigger_level=sgthrs * 2,
        )

    stepper_telemetry.insertSamples(run_id, telemetry_rows)
    stepper_telemetry.finishRun(
        run_id,
        status=stepper_telemetry.RUN_STATUS_COMPLETED,
        sg_min=stats.sg_min if stats else None,
        sg_max=stats.sg_max if stats else None,
        sg_mean=stats.sg_mean if stats else None,
        suggested_sgthrs=sgthrs,
    )

    return StallGuardSweepResponse(
        success=True,
        stepper=stepper,
        speed=speed,
        duration_s=duration_s,
        sample_interval_s=sample_interval_s,
        tcoolthrs=tcoolthrs,
        run_id=run_id,
        samples=samples,
        stats=stats,
    )


class StallGuardConfigBody(BaseModel):
    sgthrs: int = Field(..., ge=0, le=255)
    tcoolthrs: int = Field(DEFAULT_STALLGUARD_TCOOLTHRS, ge=0)
    enabled: bool = True


class StallGuardConfigResponse(BaseModel):
    success: bool
    stepper: str
    toml_name: str
    sgthrs: int
    tcoolthrs: int
    enabled: bool


@router.post("/stepper/{stepper}/stallguard-config", response_model=StallGuardConfigResponse)
def set_stallguard_config(stepper: str, body: StallGuardConfigBody) -> StallGuardConfigResponse:
    target = _resolve_stepper(stepper)
    toml_name = _STEPPER_API_TO_TOML_NAME.get(stepper, stepper)
    _write_stepper_settings("stepper_stallguard", stepper, sgthrs=body.sgthrs, tcoolthrs=body.tcoolthrs, enabled=body.enabled)

    # Apply live so the change takes effect on the very next move — no reinit
    # needed. Stamp the attrs the stall monitor reads, write the driver registers,
    # and turn detection on/off. When disabled, drop the velocity floor to 0 so
    # DIAG can never fire. Best-effort: a UART hiccup here still leaves the config
    # persisted, and hardware init will re-apply it.
    try:
        target.stallguard_sgthrs = body.sgthrs
        target.stallguard_tcoolthrs = body.tcoolthrs
        target.stallguard_enabled = body.enabled
        target.write_driver_register(TMC_REG_SGTHRS, body.sgthrs)
        target.write_driver_register(TMC_REG_TCOOLTHRS, body.tcoolthrs if body.enabled else 0)
        target.clear_stall()
        target.enable_stall_detection(bool(body.enabled))
    except Exception:
        pass

    return StallGuardConfigResponse(
        success=True,
        stepper=stepper,
        toml_name=toml_name,
        sgthrs=body.sgthrs,
        tcoolthrs=body.tcoolthrs,
        enabled=body.enabled,
    )


# ---------------------------------------------------------------------------
# Threshold suggestion — pair-based, from the measured unloaded/loaded gap
#
# A single run can't set an accurate SGTHRS: an unloaded run only shows the floor
# (the ceiling the trigger must stay under) and a loaded run only shows the stall
# dip (the level the trigger must clear). The accurate trigger sits in the gap
# between the two, so we take cruise samples from the LATEST run of BOTH kinds for
# the motor and place the trigger at the geometric midpoint — equal ratio margin
# above the stall dip and below the normal floor. SGTHRS = trigger / 2 because
# DIAG fires at SG_RESULT <= 2*SGTHRS.
#
# Deliberately the *latest* run of each kind, not a pool of recent ones: pooling
# sweeps in stale runs at other speeds or from a since-changed driver config
# (e.g. the old SpreadCycle-hybrid runs whose floor collapsed to ~6), which drags
# the pooled floor down and yields a uselessly low threshold. The freshest run is
# the one tuned to the current config. Percentiles within that run still guard
# against single-sample outliers.
# ---------------------------------------------------------------------------

_FLOOR_PERCENTILE = 0.05   # unloaded: worst-case normal cruise (low end of floor)
_DIP_PERCENTILE = 0.10     # loaded: representative stall dip (low end)

# Cruise TSTEP / TCOOLTHRS derivation. The single biggest tuning trap was leaving
# TCOOLTHRS (the velocity gate) as a typed guess: if it sits below the motor's real
# cruise TSTEP at the operating speed, the gate is shut the whole move and DIAG
# never fires no matter the SGTHRS. So we MEASURE it. The fastest-sustained TSTEP
# (a low percentile of the moving samples) is the cruise floor; the enforcement
# gate is set a margin above it so it stays open through cruise (incl. a slightly
# slower loaded cruise) but closed during accel/decel/reversal, where SG is junk.
# Margin 1.75 reproduces the empirically-good chute value (cruise ~114 -> ~200).
_CRUISE_TSTEP_PERCENTILE = 0.10  # fastest-sustained TSTEP = cruise floor
_TCOOLTHRS_CRUISE_MARGIN = 1.75  # gate = this * measured cruise floor
_TSTEP_STANDSTILL = 1_000_000    # >= this is the TMC standstill reading, not motion

# Reliability cross-check. A gentle unloaded sweep gives an optimistically clean
# floor; real reversing motion at the same speed can dip cruise SG far lower
# (StealthChop's SG baseline isn't always stable run-to-run). So we cross-check the
# proposed trigger against the worst in-gate SG seen in recent REAL motion (the
# stress-test runs). If normal motion gets within this margin of the trip line,
# no SGTHRS is safe at this speed and we say so loudly instead of pretending.
_REALISTIC_RUNS = 6              # recent stress runs to scan for the worst floor
_REALISTIC_FLOOR_PERCENTILE = 0.02
_RELIABLE_MARGIN = 1.5          # realistic floor must clear the trigger by this much
_STALL_CAPTURE_RATIO = 0.5     # a loaded run must dip to <= this * floor to count


class StallGuardSuggestionResponse(BaseModel):
    success: bool
    stepper: str
    cruise_tstep: int            # recommended TCOOLTHRS (derived, or override)
    measured_cruise_tstep: Optional[int]  # raw fastest-sustained TSTEP from the data
    unloaded_floor: Optional[int]
    loaded_dip: Optional[int]
    trigger_level: Optional[int]
    suggested_sgthrs: Optional[int]
    enough_data: bool
    # reliable=False means a threshold CAN be computed but the data says it won't
    # actually work at this speed — show a hard warning, not a confident Save.
    reliable: bool
    realistic_floor: Optional[int]  # lowest cruise SG seen in real (stress) motion
    speed: Optional[int]            # operating speed of the unloaded run, for messaging
    unloaded_runs: int
    loaded_runs: int
    detail: str


def _percentile(sorted_vals: List[int], q: float) -> Optional[int]:
    if not sorted_vals:
        return None
    idx = int(round(q * (len(sorted_vals) - 1)))
    return sorted_vals[max(0, min(len(sorted_vals) - 1, idx))]


def _moving_tstep(run: Optional[Dict[str, Any]]) -> List[int]:
    if run is None:
        return []
    out: List[int] = []
    for s in stepper_telemetry.getRunSamples(run["id"]):
        ts = s.get("tstep")
        if isinstance(ts, int) and 0 < ts < _TSTEP_STANDSTILL:
            out.append(ts)
    return sorted(out)


def _measured_cruise_tstep(*runs: Optional[Dict[str, Any]]) -> Optional[int]:
    """Fastest-sustained TSTEP (cruise floor) from the first run that has motion."""
    for run in runs:
        ts = _moving_tstep(run)
        if ts:
            return _percentile(ts, _CRUISE_TSTEP_PERCENTILE)
    return None


def _cruise_sg(run: Optional[Dict[str, Any]], cruise_tstep: int) -> List[int]:
    if run is None:
        return []
    out: List[int] = []
    for s in stepper_telemetry.getRunSamples(run["id"]):
        sg = s.get("sg_result")
        ts = s.get("tstep")
        if (
            isinstance(sg, int)
            and sg >= 0
            and isinstance(ts, int)
            and 0 <= ts <= cruise_tstep
        ):
            out.append(sg)
    return sorted(out)


def _realistic_in_gate_floor(
    toml_name: str, cruise_tstep: int, speed: Optional[int]
) -> Optional[int]:
    """Worst-case cruise SG seen in recent REAL (stress-test) motion, AT THIS SPEED.
    The pessimistic p02 across the last few stress runs — what ordinary reversing
    motion actually produces in-gate, vs the cleaner number a gentle sweep reports.
    Filtered to samples whose commanded_speed matches so a run at another speed can't
    poison the verdict. None if there's no matching stress data (only the chute has it)."""
    runs = stepper_telemetry.listRuns(
        stepper_name=toml_name,
        source=stepper_telemetry.SOURCE_CHUTE_STRESS,
        limit=_REALISTIC_RUNS,
    )
    worst: Optional[int] = None
    for r in runs:
        vals: List[int] = []
        for s in stepper_telemetry.getRunSamples(r["id"]):
            sg = s.get("sg_result")
            ts = s.get("tstep")
            cs = s.get("commanded_speed")
            if not (isinstance(sg, int) and sg >= 0 and isinstance(ts, int) and 0 <= ts <= cruise_tstep):
                continue
            if speed is not None and (not isinstance(cs, int) or cs != speed):
                continue
            vals.append(sg)
        p = _percentile(sorted(vals), _REALISTIC_FLOOR_PERCENTILE)
        if p is not None:
            worst = p if worst is None else min(worst, p)
    return worst


@router.get(
    "/stepper/{stepper}/stallguard-suggestion",
    response_model=StallGuardSuggestionResponse,
)
def stallguard_suggestion(
    stepper: str, cruise_tstep: Optional[int] = None, speed: Optional[int] = None
) -> StallGuardSuggestionResponse:
    """Pure DB analysis — no hardware. Takes cruise SG from the latest unloaded
    (sweep) and latest loaded (stall_test) run for this motor and returns the
    geometric-midpoint trigger between the normal floor and the stall dip.

    SG floor/dip/baseline all shift with speed, so when `speed` is given every input
    (unloaded, loaded, stress) is filtered to that speed — otherwise a 2000 sweep
    could get paired with an old 3000 stall test and a clean run wrongly flagged.
    The UI passes the selected run's speed so the suggestion matches what you see."""
    if stepper not in _STEPPER_API_TO_TOML_NAME:
        raise HTTPException(status_code=400, detail=f"Unknown stepper '{stepper}'")

    def _run_speed(r: Dict[str, Any]) -> Optional[int]:
        p = r.get("params")
        sp = p.get("speed") if isinstance(p, dict) else None
        return int(sp) if isinstance(sp, (int, float)) else None

    def _latest(source: str) -> Optional[Dict[str, Any]]:
        rows = stepper_telemetry.listRuns(
            stepper_name=stepper, source=source, limit=50
        )
        for r in rows:  # listRuns is newest-first
            if r.get("status") != stepper_telemetry.RUN_STATUS_COMPLETED:
                continue
            if speed is not None and _run_speed(r) != speed:
                continue
            return r
        return None

    unloaded_run = _latest(stepper_telemetry.SOURCE_SWEEP)
    loaded_run = _latest(stepper_telemetry.SOURCE_STALL_TEST)

    # Measure the cruise floor from the data (unloaded preferred), then set the
    # recommended TCOOLTHRS a margin above it. An explicit ?cruise_tstep= overrides
    # the derivation (manual tuning); otherwise everything below — including the
    # cruise filter for the SG floor/dip — uses the measured gate, so the threshold
    # is computed within the exact velocity window enforcement will use.
    measured_ct = _measured_cruise_tstep(unloaded_run, loaded_run)
    if cruise_tstep is not None:
        ct = max(1, cruise_tstep)
    elif measured_ct is not None:
        ct = max(1, int(round(measured_ct * _TCOOLTHRS_CRUISE_MARGIN)))
    else:
        ct = 150  # no motion data yet — harmless fallback

    unloaded_cruise = _cruise_sg(unloaded_run, ct)
    loaded_cruise = _cruise_sg(loaded_run, ct)
    floor = _percentile(unloaded_cruise, _FLOOR_PERCENTILE)
    dip = _percentile(loaded_cruise, _DIP_PERCENTILE)

    eff_speed = speed if speed is not None else (_run_speed(unloaded_run) if unloaded_run else None)
    speed_txt = f"{eff_speed} µs/s" if eff_speed else "this speed"

    toml_name = _STEPPER_API_TO_TOML_NAME.get(stepper, stepper)
    realistic_floor = _realistic_in_gate_floor(toml_name, ct, eff_speed)

    trigger: Optional[int] = None
    sgthrs: Optional[int] = None
    enough = False
    reliable = False
    if floor is not None and dip is not None:
        # Geometric midpoint of the gap. Clamp dip to >=1 so a stall floor that
        # reaches 0 doesn't collapse the geo-mean to 0.
        trigger = int(round(math.sqrt(float(floor) * float(max(1, dip)))))
        sgthrs = max(1, min(255, round(trigger / 2)))
        enough = True
        gate_note = (
            f"; gate TCOOLTHRS {ct} = cruise {measured_ct}×{_TCOOLTHRS_CRUISE_MARGIN:g}"
            if measured_ct is not None
            else f"; gate TCOOLTHRS {ct} (manual)"
        )
        # Did the loaded run actually stall? If it never dipped well below the
        # floor, it's not a real stall reference and the trigger is guesswork.
        loaded_min = loaded_cruise[0] if loaded_cruise else None
        captured_stall = loaded_min is not None and loaded_min <= floor * _STALL_CAPTURE_RATIO

        if realistic_floor is not None and realistic_floor < trigger * _RELIABLE_MARGIN:
            # The killer case: real reversing motion dips into the trip range, so no
            # SGTHRS separates a stall from an ordinary move at this speed.
            reliable = False
            detail = (
                f"⚠ NOT reliably tunable at {speed_txt}. Real (stress-test) motion dips to "
                f"SG {realistic_floor} at cruise — at/near the {trigger} trip line — so this "
                f"threshold WILL false-trip on ordinary moves. The cruise SG baseline isn't "
                f"stable enough at this speed to separate normal motion from a stall. Lower the "
                f"speed for a steadier baseline and re-characterize, or accept it's unreliable."
            )
        elif not captured_stall:
            reliable = False
            detail = (
                f"⚠ The loaded run never actually stalled — its cruise SG only reached "
                f"{loaded_min} vs the {floor} unloaded floor. Hold/resist the motor until it "
                f"bogs down, then re-run the loaded sweep so there's a real stall to tune to."
            )
        else:
            reliable = True
            extra = (
                f" Real-motion floor {realistic_floor} clears it."
                if realistic_floor is not None
                else ""
            )
            detail = (
                f"Balanced trigger {trigger} = geo-mean(floor {floor}, dip {dip}) "
                f"from the latest unloaded + latest loaded run{gate_note}.{extra}"
            )
    elif floor is not None:
        # Provisional: no loaded stall test yet, so we can't see the dip. Fall
        # back to a fraction of the floor and flag it as unvalidated.
        trigger = int(round(floor * 0.4))
        sgthrs = max(1, min(255, round(trigger / 2)))
        detail = (
            f"No loaded stall test at {speed_txt} yet — provisional SGTHRS from the "
            "unloaded floor only. Run a loaded (held/resisted) sweep at this speed to validate."
        )
    elif dip is not None:
        detail = "Only loaded runs found — run an unloaded sweep to measure the normal floor."
    elif unloaded_run is not None or loaded_run is not None:
        # Runs exist and completed, but the cruise filter kept nothing from either
        # — every sample was below cruise velocity (TSTEP > cruise_tstep). This is
        # what the pulsed/jitter profiles produce: the motor never sustains cruise,
        # so SG_RESULT is all accel/decel and there's no valid load reading to tune
        # from. Don't tell the user to re-run sweeps they already ran.
        have = " + ".join(
            kind
            for kind, run in (("unloaded", unloaded_run), ("loaded", loaded_run))
            if run is not None
        )
        detail = (
            f"Latest {have} run completed but produced 0 cruise samples "
            f"(none reached TSTEP <= {ct}) — the profile never sustained cruise "
            "velocity. StallGuard only reads load at constant cruise; use the "
            "constant profile to calibrate SGTHRS."
        )
    else:
        detail = "No completed runs for this motor yet — run an unloaded and a loaded sweep."

    return StallGuardSuggestionResponse(
        success=True,
        stepper=stepper,
        cruise_tstep=ct,
        measured_cruise_tstep=measured_ct,
        unloaded_floor=floor,
        loaded_dip=dip,
        trigger_level=trigger,
        suggested_sgthrs=sgthrs,
        enough_data=enough,
        reliable=reliable,
        realistic_floor=realistic_floor,
        speed=eff_speed,
        unloaded_runs=1 if unloaded_run else 0,
        loaded_runs=1 if loaded_run else 0,
        detail=detail,
    )


def _armed_steppers() -> List[Any]:
    """Every stall-armed StepperMotor across all boards (raw per-board objects)."""
    irl = shared_state.getActiveIRL()
    out: List[Any] = []
    interfaces = getattr(irl, "interfaces", None) or {}
    for iface in interfaces.values():
        for st in getattr(iface, "steppers", ()):
            if getattr(st, "stallguard_enabled", False):
                out.append(st)
    return out


def _clear_one_stall(stepper: Any) -> None:
    """Clear a stepper's firmware DIAG latch and re-arm detection. The monitor's
    next poll mirrors the now-cleared state and the derived incident follows."""
    stepper.clear_stall()
    stepper.enable_stall_detection(bool(getattr(stepper, "stallguard_enabled", False)))
    stepper.stalled = False


@router.get("/steppers/stall-state")
def steppers_stall_state() -> Dict[str, Any]:
    """Live per-stepper stall latch, keyed by API stepper name (the same name the
    station pages use) — what the UI polls to show stall badges and resolve
    incidents indirectly. Keyed by API name, NOT the raw firmware name, so the
    frontend's stepperKey lookups match."""
    state: Dict[str, Any] = {}
    try:
        mapping = _stepper_mapping()
    except HTTPException:
        return {"steppers": state}
    for api_name, stepper in mapping.items():
        if stepper is None or not getattr(stepper, "stallguard_enabled", False):
            continue
        state[api_name] = {
            "stalled": bool(getattr(stepper, "stalled", False)),
            "enabled": True,
        }
    return {"steppers": state}


@router.post("/stepper/{stepper}/clear-stall")
def clear_stepper_stall(stepper: str) -> Dict[str, Any]:
    """Clear ONE motor's stall latch (from its station page). The blocking incident
    is derived from the latch state, so it resolves on the next monitor poll once no
    motor is still latched — no separate ack needed."""
    target = _resolve_stepper(stepper)
    try:
        _clear_one_stall(target)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Failed to clear stall: {e}")
    return {"ok": True, "stepper": stepper, "stalled": False}


def clear_stall_incident() -> Dict[str, Any]:
    """Clear ALL motors' stall latches (the global 'Acknowledge'). Resets every
    armed driver's firmware latch + re-arms, then drops the blocking incident; the
    monitor confirms the cleared state on its next poll."""
    gc = shared_state.gc_ref
    runtime_stats = getattr(gc, "runtime_stats", None) if gc is not None else None
    if runtime_stats is None or not hasattr(runtime_stats, "clearActiveIncident"):
        raise HTTPException(status_code=503, detail="runtime stats unavailable")

    for st in _armed_steppers():
        try:
            _clear_one_stall(st)
        except Exception:
            pass  # best-effort; the monitor re-reads and a stuck latch re-raises

    active = runtime_stats.activeIncident() if hasattr(runtime_stats, "activeIncident") else None
    runtime_stats.clearActiveIncident(kind=STEPPER_STALL_INCIDENT_KIND, resolved_by="operator")
    cleared = isinstance(active, dict) and active.get("kind") == STEPPER_STALL_INCIDENT_KIND
    return {"ok": True, "cleared": cleared, "kind": STEPPER_STALL_INCIDENT_KIND}


def rehome_after_stall() -> Dict[str, Any]:
    """Clear stall latches AND re-home the chute in place, then drop the hold.

    A chute stall loses the home reference, so 'clear the stall' alone leaves the
    machine in a `chute_needs_homing` hold. This is the one-shot 'clear + re-home'
    the operator gets on the stall/needs-homing cards. The blocking incident is
    kept active across the (blocking) home so the coordinator — which skips
    distribution while any incident is active — never commands the chute out from
    under the homing move. Only proceeds when such a hold is active, which
    guarantees the coordinator is already parked."""
    _ensure_not_homing("re-home the chute")

    gc = shared_state.gc_ref
    runtime_stats = getattr(gc, "runtime_stats", None) if gc is not None else None
    if runtime_stats is None or not hasattr(runtime_stats, "clearActiveIncident"):
        raise HTTPException(status_code=503, detail="runtime stats unavailable")

    ours = {STEPPER_STALL_INCIDENT_KIND, CHUTE_NEEDS_HOMING_INCIDENT_KIND}
    active = runtime_stats.activeIncident() if hasattr(runtime_stats, "activeIncident") else None
    active_kind = active.get("kind") if isinstance(active, dict) else None
    if active_kind not in ours:
        raise HTTPException(
            status_code=409,
            detail="No stall or needs-homing hold is active; nothing to re-home.",
        )

    irl = shared_state.getActiveIRL()
    if irl is None:
        raise HTTPException(status_code=503, detail="Hardware not initialized.")
    chute = getattr(irl, "chute", None)
    if chute is None or not hasattr(chute, "home"):
        raise HTTPException(status_code=503, detail="Chute subsystem unavailable.")

    for st in _armed_steppers():
        try:
            _clear_one_stall(st)
        except Exception:
            pass  # best-effort; a stuck latch just re-raises the stall hold

    try:
        irl.enableSteppers()
    except Exception:
        pass

    try:
        homed = bool(chute.home())
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Chute re-home failed: {e}")
    if not homed:
        raise HTTPException(
            status_code=409,
            detail=(
                "Chute homing stopped before the endstop triggered. Clear any "
                "obstruction and try again."
            ),
        )

    # The chute is homed now; drop our hold immediately (the monitor would clear
    # it on its next poll anyway, but don't make the operator watch it linger).
    active_kind = runtime_stats.activeIncident()
    active_kind = active_kind.get("kind") if isinstance(active_kind, dict) else None
    if active_kind in ours:
        runtime_stats.clearActiveIncident(kind=active_kind, resolved_by="operator")
    return {"ok": True, "homed": True}
