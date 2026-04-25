"""Hardware callable factories — the ONE place rt/ touches ``irl.*``.

Each builder returns the small set of closures a runtime needs to drive
its channel's stepper + related hardware. Keeping all five builders in
one module is deliberate — it makes the rt->legacy bridge **visible**
(Principle 9) and co-locates the ``TODO_PHASE5_WIRING`` markers that
track which branches still need live hardware verification.

The closures hold onto the ``irl`` root and a logger so runtimes can
call them without knowing how the legacy stepper/feeder config is
organised. All errors are swallowed and logged — a hardware failure
must never crash the runtime tick.
"""

from __future__ import annotations

import logging
from typing import Any, Callable

import math
import os
import time

from rt.hardware.motion_profiles import (
    DEFAULT_ACCELERATION_USTEPS_PER_S2,
    DEFAULT_MIN_SPEED_USTEPS_PER_S,
    MotionDiagnostics,
    PROFILE_CONTINUOUS,
    PROFILE_DIRECT,
    PROFILE_EJECT,
    PROFILE_GENTLE,
    PROFILE_PURGE,
    PROFILE_TRANSPORT,
    PROFILE_TRANSPORT_PULSED,
    PROFILE_UNJAM,
    PROFILE_WIGGLE,
    move_degrees_with_profile,
    profile_from_rotor_config,
    profile_from_values,
)


# Pulse-settle-pulse tuning for the C4 carousel. The observed failure mode
# on live hardware: a single ``transport_move(6°)`` call peaks at ~3% of the
# configured max speed (too short to exit the acceleration ramp) but the
# abrupt start/stop still imparts enough inertia that pieces slide out of
# position. Splitting the move into smaller sub-pulses with an explicit
# settle pause between them lets friction re-engage between each kick —
# the pattern Marc observed working better in manual tuning.
#
# Defaults are conservative; both knobs are env-tunable so Marc can A/B
# without a rebuild.
C4_TRANSPORT_SUB_PULSE_DEG_ENV = "RT_C4_TRANSPORT_SUB_PULSE_DEG"
C4_TRANSPORT_SETTLE_MS_ENV = "RT_C4_TRANSPORT_SETTLE_MS"
C4_TRANSPORT_PROFILE_ENV = "RT_C4_TRANSPORT_PROFILE"  # "transport" | "transport_pulsed"

_DEFAULT_C4_SUB_PULSE_DEG = 2.0
_DEFAULT_C4_SETTLE_MS = 120.0


def _wait_until_stepper_stopped(
    stepper: Any,
    *,
    logger: logging.Logger,
    channel: str,
    stepper_deg: float,
    speed_limit: int | None,
    timeout_cap_s: float = 8.0,
) -> None:
    if not hasattr(stepper, "stopped"):
        return
    try:
        distance = abs(int(stepper.microsteps_for_degrees(stepper_deg)))
    except Exception:
        distance = 0
    speed = max(1, int(speed_limit or 1))
    timeout_s = min(timeout_cap_s, max(0.25, (distance / speed) * 3.0 + 0.5))
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        try:
            if bool(getattr(stepper, "stopped")):
                return
        except Exception:
            logger.exception("Runtime%s: stepper stopped probe raised", channel.upper())
            return
        time.sleep(0.01)
    logger.warning(
        "Runtime%s: stepper did not report stopped within %.2fs after %.2f motor degrees",
        channel.upper(),
        timeout_s,
        stepper_deg,
    )


def _env_float(name: str, default: float) -> float:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        value = float(raw)
    except ValueError:
        return default
    return value if value > 0.0 else default


def build_c1_callables(
    irl: Any,
    logger: logging.Logger,
    *,
    motion_diagnostics: MotionDiagnostics | None = None,
) -> tuple[Callable[[], bool], Callable[[int], bool], Callable[[float, int | None, int | None], bool]]:
    """Return (pulse, recovery) closures for RuntimeC1.

    Bridge: ``irl.c_channel_1_rotor_stepper.move_degrees`` /
    ``irl.feeder_config.first_rotor`` for pulse sizing.
    """

    def _pulse_degrees() -> float | None:
        stepper = getattr(irl, "c_channel_1_rotor_stepper", None)
        cfg = getattr(irl, "feeder_config", None) or getattr(
            getattr(irl, "irl_config", None), "feeder_config", None
        )
        pulse_cfg = getattr(cfg, "first_rotor", None) if cfg is not None else None
        if stepper is None or pulse_cfg is None:
            return None
        try:
            return float(stepper.degrees_for_microsteps(pulse_cfg.steps_per_pulse))
        except Exception:
            return None

    def pulse() -> bool:
        stepper = getattr(irl, "c_channel_1_rotor_stepper", None)
        if stepper is None:
            logger.error("TODO_PHASE5_WIRING: c1 pulse - c_channel_1_rotor_stepper missing")
            return False
        cfg = getattr(irl, "feeder_config", None) or getattr(
            getattr(irl, "irl_config", None), "feeder_config", None
        )
        if cfg is None:
            logger.error("TODO_PHASE5_WIRING: c1 pulse - feeder_config missing")
            return False
        pulse_cfg = getattr(cfg, "first_rotor", None)
        if pulse_cfg is None:
            logger.error("TODO_PHASE5_WIRING: c1 pulse - feeder_config.first_rotor missing")
            return False
        try:
            deg = stepper.degrees_for_microsteps(pulse_cfg.steps_per_pulse)
            profile = profile_from_rotor_config(
                channel="c1",
                name=PROFILE_TRANSPORT,
                cfg=pulse_cfg,
            )
            ok = move_degrees_with_profile(
                stepper,
                profile,
                deg,
                source="c1_pulse",
                logger=logger,
                diagnostics=motion_diagnostics,
            )
            _wait_until_stepper_stopped(
                stepper,
                logger=logger,
                channel="c1",
                stepper_deg=float(deg),
                speed_limit=profile.max_speed_usteps_per_s,
            )
            return ok
        except Exception:
            logger.exception("RuntimeC1: pulse raised")
            return False

    pulse.nominal_degrees_per_step = _pulse_degrees  # type: ignore[attr-defined]

    # 5-level escalating shake-then-push jam recovery, ported from the
    # legacy ``subsystems/feeder/strategies/c1_jam_recovery.py`` (deleted
    # in commit 09605a9 during the rt/ cutover and stubbed to a constant
    # False return until now). Documented behaviour from
    # ``docs/lab/c-channel-singulation``: progressively stronger
    # back-and-forth shake to free a stuck piece, followed by a forward
    # push that grows with the recovery level. RuntimeC1 calls this once
    # per attempt and bumps ``level`` itself; the cooldown between
    # attempts is owned by the runtime via ``jam_cooldown_s``.
    #
    # Push degrees retuned 2026-04-25: legacy stack escalated to 360 deg
    # at level 4 — a complete hopper dump — which under live tuning
    # appeared as bursts of 50+ pieces hitting C2 at once and
    # overwhelmed the entire downstream pipeline. The new schedule
    # caps at 90 deg so even a worst-case escalation does not collapse
    # singulation downstream.
    _RECOVERY_PUSH_OUTPUT_DEGREES = (10.0, 20.0, 35.0, 60.0, 90.0)
    _RECOVERY_GEAR_RATIO = 130.0 / 12.0

    def _recovery_shake_degrees(cfg: Any, level: int) -> float:
        base = float(getattr(cfg, "first_rotor_jam_backtrack_output_degrees", 18.0))
        max_deg = float(getattr(cfg, "first_rotor_jam_max_output_degrees", 30.0))
        return max(15.0, min(max_deg, base + level * 6.0))

    def _recovery_push_degrees(level: int) -> float:
        idx = max(0, min(level, len(_RECOVERY_PUSH_OUTPUT_DEGREES) - 1))
        return float(_RECOVERY_PUSH_OUTPUT_DEGREES[idx])

    def recovery(level: int) -> bool:
        stepper = getattr(irl, "c_channel_1_rotor_stepper", None)
        if stepper is None:
            logger.warning(
                "RuntimeC1: jam recovery — c_channel_1_rotor_stepper missing"
            )
            return False
        cfg = getattr(irl, "feeder_config", None) or getattr(
            getattr(irl, "irl_config", None), "feeder_config", None
        )
        if cfg is None:
            logger.warning("RuntimeC1: jam recovery — feeder_config missing")
            return False
        bounded_level = max(0, int(level))
        max_cycles = max(1, int(getattr(cfg, "first_rotor_jam_max_cycles", 5)))
        bounded_level = min(bounded_level, max_cycles - 1)
        shake_output_deg = _recovery_shake_degrees(cfg, bounded_level)
        shake_cycles = max(1, min(max_cycles, 1 + bounded_level))
        push_output_deg = _recovery_push_degrees(bounded_level)
        shake_motor_deg = shake_output_deg * _RECOVERY_GEAR_RATIO
        push_motor_deg = push_output_deg * _RECOVERY_GEAR_RATIO
        # Per-move timeout scales with travel — 90 ms per output deg is
        # the legacy heuristic and worked across the available stepper
        # profiles, with a 2.5 s floor so very small shakes still get
        # enough room to settle.
        shake_timeout_ms = max(2500, int(shake_output_deg * 90.0))
        push_timeout_ms = max(2500, int(push_output_deg * 90.0))
        logger.warning(
            "RuntimeC1: jam recovery level=%d — %d x ±%.1f° shake then %.1f° push",
            bounded_level + 1,
            shake_cycles,
            shake_output_deg,
            push_output_deg,
        )

        move_blocking = getattr(stepper, "move_degrees_blocking", None)
        if not callable(move_blocking):
            logger.warning(
                "RuntimeC1: jam recovery — stepper has no move_degrees_blocking"
            )
            return False

        for cycle in range(shake_cycles):
            if not bool(move_blocking(-shake_motor_deg, timeout_ms=shake_timeout_ms)):
                logger.warning(
                    "RuntimeC1: jam recovery shake reverse failed at cycle %d/%d",
                    cycle + 1,
                    shake_cycles,
                )
                return False
            if not bool(move_blocking(shake_motor_deg, timeout_ms=shake_timeout_ms)):
                logger.warning(
                    "RuntimeC1: jam recovery shake forward failed at cycle %d/%d",
                    cycle + 1,
                    shake_cycles,
                )
                return False
        if push_output_deg > 0.0:
            if not bool(move_blocking(push_motor_deg, timeout_ms=push_timeout_ms)):
                logger.warning(
                    "RuntimeC1: jam recovery push failed at level %d (%.0f°)",
                    bounded_level + 1,
                    push_output_deg,
                )
                return False
        logger.info(
            "RuntimeC1: jam recovery level=%d completed",
            bounded_level + 1,
        )
        return True

    def direct_move(
        deg: float,
        max_speed: int | None = None,
        acceleration: int | None = None,
    ) -> bool:
        stepper = getattr(irl, "c_channel_1_rotor_stepper", None)
        if stepper is None:
            logger.error("TODO_PHASE5_WIRING: c1 direct - c_channel_1_rotor_stepper missing")
            return False
        try:
            profile = profile_from_values(
                channel="c1",
                name=PROFILE_DIRECT,
                max_speed=max_speed,
                acceleration=acceleration,
            )
            ok = move_degrees_with_profile(
                stepper,
                profile,
                deg,
                source="c1_direct",
                logger=logger,
                diagnostics=motion_diagnostics,
            )
            _wait_until_stepper_stopped(
                stepper,
                logger=logger,
                channel="c1",
                stepper_deg=float(deg),
                speed_limit=profile.max_speed_usteps_per_s,
            )
            return ok
        except Exception:
            logger.exception("RuntimeC1: direct move raised")
            return False

    return pulse, recovery, direct_move


def build_c2_callables(
    irl: Any,
    logger: logging.Logger,
    *,
    motion_diagnostics: MotionDiagnostics | None = None,
) -> tuple[
    Callable[[Any, float, str | None], bool],
    Callable[[], bool],
    Callable[[float, int | None, int | None], bool],
]:
    # ``_pulse_ms`` is accepted for signature parity with RuntimeC2 /
    # RuntimeC3's ``pulse_command``. Rotation step size is governed by
    # ``steps_per_pulse`` in the feeder config, not by pulse_ms.
    def _pulse_degrees() -> float | None:
        stepper = getattr(irl, "c_channel_2_rotor_stepper", None)
        cfg = getattr(getattr(irl, "feeder_config", None) or getattr(
            getattr(irl, "irl_config", None), "feeder_config", None
        ), "second_rotor_normal", None)
        if stepper is None or cfg is None:
            return None
        try:
            return float(stepper.degrees_for_microsteps(cfg.steps_per_pulse))
        except Exception:
            return None

    def pulse(mode: Any, _pulse_ms: float, profile_name: str | None = None) -> bool:
        stepper = getattr(irl, "c_channel_2_rotor_stepper", None)
        feeder_cfg = getattr(irl, "feeder_config", None) or getattr(
            getattr(irl, "irl_config", None), "feeder_config", None
        )
        if stepper is None or feeder_cfg is None:
            logger.error("TODO_PHASE5_WIRING: c2 pulse - stepper/cfg missing")
            return False
        mode_value = getattr(mode, "value", mode)
        cfg = (
            feeder_cfg.second_rotor_precision
            if str(mode_value) == "precise"
            else feeder_cfg.second_rotor_normal
        )
        try:
            deg = stepper.degrees_for_microsteps(cfg.steps_per_pulse)
            default_profile = (
                PROFILE_GENTLE if str(mode_value) == "precise" else PROFILE_TRANSPORT
            )
            profile = profile_from_rotor_config(
                channel="c2",
                name=profile_name or default_profile,
                cfg=cfg,
            )
            ok = move_degrees_with_profile(
                stepper,
                profile,
                deg,
                source=f"c2_{profile.name}",
                logger=logger,
                diagnostics=motion_diagnostics,
                expected_duration_ms=_pulse_ms,
            )
            _wait_until_stepper_stopped(
                stepper,
                logger=logger,
                channel="c2",
                stepper_deg=float(deg),
                speed_limit=profile.max_speed_usteps_per_s,
            )
            return ok
        except Exception:
            logger.exception("RuntimeC2: pulse raised")
            return False

    pulse.nominal_degrees_per_step = _pulse_degrees  # type: ignore[attr-defined]

    def wiggle() -> bool:
        logger.warning(
            "TODO_PHASE5_WIRING: c2 wiggle — live verification needed"
        )
        return False

    def direct_move(
        deg: float,
        max_speed: int | None = None,
        acceleration: int | None = None,
    ) -> bool:
        stepper = getattr(irl, "c_channel_2_rotor_stepper", None)
        if stepper is None:
            logger.error("TODO_PHASE5_WIRING: c2 direct - stepper missing")
            return False
        try:
            profile = profile_from_values(
                channel="c2",
                name=PROFILE_DIRECT,
                max_speed=max_speed,
                acceleration=acceleration,
            )
            ok = move_degrees_with_profile(
                stepper,
                profile,
                deg,
                source="c2_direct",
                logger=logger,
                diagnostics=motion_diagnostics,
            )
            _wait_until_stepper_stopped(
                stepper,
                logger=logger,
                channel="c2",
                stepper_deg=float(deg),
                speed_limit=profile.max_speed_usteps_per_s,
            )
            return ok
        except Exception:
            logger.exception("RuntimeC2: direct move raised")
            return False

    return pulse, wiggle, direct_move


def build_c3_callables(
    irl: Any,
    logger: logging.Logger,
    *,
    motion_diagnostics: MotionDiagnostics | None = None,
) -> tuple[Callable[[Any, float, str | None], bool], Callable[[], bool], Callable[[float, int | None, int | None], bool]]:
    def _pulse_degrees() -> float | None:
        stepper = getattr(irl, "c_channel_3_rotor_stepper", None)
        feeder_cfg = getattr(irl, "feeder_config", None) or getattr(
            getattr(irl, "irl_config", None), "feeder_config", None
        )
        cfg = getattr(feeder_cfg, "third_rotor_precision", None)
        if stepper is None or cfg is None:
            return None
        try:
            return float(stepper.degrees_for_microsteps(cfg.steps_per_pulse))
        except Exception:
            return None

    def pulse(mode: Any, _pulse_ms: float, profile_name: str | None = None) -> bool:
        stepper = getattr(irl, "c_channel_3_rotor_stepper", None)
        feeder_cfg = getattr(irl, "feeder_config", None) or getattr(
            getattr(irl, "irl_config", None), "feeder_config", None
        )
        if stepper is None or feeder_cfg is None:
            logger.error("TODO_PHASE5_WIRING: c3 pulse - stepper/cfg missing")
            return False
        mode_value = getattr(mode, "value", mode)
        cfg = (
            feeder_cfg.third_rotor_precision
            if str(mode_value) == "precise"
            else feeder_cfg.third_rotor_normal
        )
        try:
            deg = stepper.degrees_for_microsteps(cfg.steps_per_pulse)
            default_profile = (
                PROFILE_GENTLE if str(mode_value) == "precise" else PROFILE_TRANSPORT
            )
            profile = profile_from_rotor_config(
                channel="c3",
                name=profile_name or default_profile,
                cfg=cfg,
            )
            ok = move_degrees_with_profile(
                stepper,
                profile,
                deg,
                source=f"c3_{profile.name}",
                logger=logger,
                diagnostics=motion_diagnostics,
                expected_duration_ms=_pulse_ms,
            )
            _wait_until_stepper_stopped(
                stepper,
                logger=logger,
                channel="c3",
                stepper_deg=float(deg),
                speed_limit=profile.max_speed_usteps_per_s,
            )
            return ok
        except Exception:
            logger.exception("RuntimeC3: pulse raised")
            return False

    pulse.nominal_degrees_per_step = _pulse_degrees  # type: ignore[attr-defined]

    def wiggle() -> bool:
        logger.warning(
            "TODO_PHASE5_WIRING: c3 wiggle — live verification needed"
        )
        return False

    def direct_move(
        deg: float,
        max_speed: int | None = None,
        acceleration: int | None = None,
    ) -> bool:
        stepper = getattr(irl, "c_channel_3_rotor_stepper", None)
        if stepper is None:
            logger.error("TODO_PHASE5_WIRING: c3 direct - stepper missing")
            return False
        try:
            profile = profile_from_values(
                channel="c3",
                name=PROFILE_DIRECT,
                max_speed=max_speed,
                acceleration=acceleration,
            )
            ok = move_degrees_with_profile(
                stepper,
                profile,
                deg,
                source="c3_direct",
                logger=logger,
                diagnostics=motion_diagnostics,
            )
            _wait_until_stepper_stopped(
                stepper,
                logger=logger,
                channel="c3",
                stepper_deg=float(deg),
                speed_limit=profile.max_speed_usteps_per_s,
            )
            return ok
        except Exception:
            logger.exception("RuntimeC3: direct move raised")
            return False

    return pulse, wiggle, direct_move


def build_c4_callables(
    irl: Any,
    logger: logging.Logger,
    *,
    startup_purge_speed_scale: float = 1.0,
    transport_speed_scale: float = 1.0,
    carousel_acceleration: int | None = 9000,
    transport_acceleration: int | None = DEFAULT_ACCELERATION_USTEPS_PER_S2,
    continuous_acceleration: int | None = None,
    startup_purge_acceleration: int | None = DEFAULT_ACCELERATION_USTEPS_PER_S2,
    motion_diagnostics: MotionDiagnostics | None = None,
) -> tuple[
    Callable[[float], bool],
    Callable[[float], bool],
    Callable[[float], bool],
    Callable[[float], bool],
    Callable[[bool], bool],
    Callable[[], bool],
    Callable[[float], bool],
    Callable[[float], bool],
    Callable[[float, int | None, int | None], bool],
]:
    def _classification_cfg() -> Any | None:
        return getattr(irl, "classification_channel_config", None) or getattr(
            getattr(irl, "irl_config", None), "classification_channel_config", None
        )

    def _default_speed_limit() -> int | None:
        cfg_root = getattr(irl, "irl_config", None) or irl
        cfg = getattr(cfg_root, "carousel_stepper", None)
        speed = getattr(cfg, "default_steps_per_second", None)
        return int(speed) if isinstance(speed, int) and speed > 0 else None

    def _cfg_float(name: str, fallback: float) -> float:
        cfg = _classification_cfg()
        value = getattr(cfg, name, None) if cfg is not None else None
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return float(value)
        return float(fallback)

    def _cfg_optional_int(name: str, fallback: int | None) -> int | None:
        cfg = _classification_cfg()
        value = getattr(cfg, name, None) if cfg is not None else None
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            coerced = int(value)
            return coerced if coerced > 0 else None
        return fallback

    def _stepper_degrees_per_tray_degree() -> float:
        return _cfg_float("stepper_degrees_per_tray_degree", 1.0)

    def _to_stepper_degrees(tray_degrees: float) -> float:
        return float(tray_degrees) * _stepper_degrees_per_tray_degree()

    def _scaled_speed_limit(scale: float) -> int | None:
        default_speed = _default_speed_limit()
        if default_speed is not None and scale > 1.0:
            return max(
                default_speed,
                int(round(float(default_speed) * float(scale))),
            )
        return None

    def _transport_speed_limit() -> int | None:
        return _scaled_speed_limit(
            _cfg_float("transport_speed_scale", transport_speed_scale)
        )

    def _transport_acceleration() -> int | None:
        return _cfg_optional_int(
            "transport_acceleration_microsteps_per_second_sq",
            transport_acceleration,
        )

    def _purge_speed_limit() -> int | None:
        return _scaled_speed_limit(
            _cfg_float("startup_purge_speed_scale", startup_purge_speed_scale)
        )

    def _startup_purge_acceleration() -> int | None:
        return _cfg_optional_int(
            "startup_purge_acceleration_microsteps_per_second_sq",
            startup_purge_acceleration,
        )

    def _carousel_acceleration() -> int | None:
        return _cfg_optional_int(
            "exit_release_shimmy_acceleration_microsteps_per_second_sq",
            carousel_acceleration,
        )

    def _exit_release_speed_limit() -> int | None:
        return _cfg_optional_int("exit_release_shimmy_microsteps_per_second", None)

    def _exit_release_amplitude_deg() -> float:
        value = _cfg_float("exit_release_shimmy_amplitude_deg", 1.5)
        return max(0.1, min(12.0, value))

    def _exit_release_cycles() -> int:
        value = _cfg_float("exit_release_shimmy_cycles", 2.0)
        return max(1, min(8, int(round(value))))

    def _continuous_acceleration() -> int | None:
        configured = _cfg_optional_int(
            "continuous_acceleration_microsteps_per_second_sq",
            continuous_acceleration,
        )
        if configured is not None:
            return configured
        return max(
            int(_transport_acceleration() or DEFAULT_ACCELERATION_USTEPS_PER_S2),
            30000,
        )

    def _profile_move(
        deg: float,
        *,
        profile_name: str,
        speed_limit: int | None,
        acceleration: int | None,
    ) -> bool:
        stepper = getattr(irl, "carousel_stepper", None)
        if stepper is None:
            logger.error("TODO_PHASE5_WIRING: c4 carousel move - stepper missing")
            return False
        default_speed = _default_speed_limit()
        target_speed = speed_limit or default_speed
        stepper_deg = _to_stepper_degrees(float(deg))
        try:
            profile = profile_from_values(
                channel="c4",
                name=profile_name,
                max_speed=target_speed,
                acceleration=acceleration,
            )
            ok = move_degrees_with_profile(
                stepper,
                profile,
                stepper_deg,
                source=f"c4_{profile_name}",
                logger=logger,
                diagnostics=motion_diagnostics,
            )
            _wait_until_stepper_stopped(
                stepper,
                logger=logger,
                channel="c4",
                stepper_deg=stepper_deg,
                speed_limit=target_speed or _default_speed_limit(),
                timeout_cap_s=5.0,
            )
            return ok
        except Exception:
            logger.exception("RuntimeC4: carousel_move raised")
            return False

    def carousel_move(deg: float) -> bool:
        return _profile_move(
            deg,
            profile_name=PROFILE_GENTLE,
            speed_limit=None,
            acceleration=_carousel_acceleration(),
        )

    def _transport_single(deg: float) -> bool:
        return _profile_move(
            deg,
            profile_name=PROFILE_TRANSPORT,
            speed_limit=_transport_speed_limit(),
            acceleration=_transport_acceleration(),
        )

    def _transport_pulsed(deg: float) -> bool:
        """Split ``deg`` into sub-pulses with a settle pause between them.

        Reads configuration from env on every call so the operator can retune
        without restarting the backend. Settle uses a blocking ``time.sleep``
        — this closure is already dispatched on the C4 HwWorker thread, so
        sleeping here does not stall the perception/runtime tick loop.
        """
        total = float(deg)
        if not math.isfinite(total) or total == 0.0:
            return _transport_single(total)
        sub_pulse = _env_float(C4_TRANSPORT_SUB_PULSE_DEG_ENV, _DEFAULT_C4_SUB_PULSE_DEG)
        settle_ms = _env_float(C4_TRANSPORT_SETTLE_MS_ENV, _DEFAULT_C4_SETTLE_MS)
        sign = 1.0 if total > 0.0 else -1.0
        remaining = abs(total)
        # If the move is smaller than one sub-pulse, just do it as a single
        # call — no point sprinkling sleeps onto a 1° nudge.
        if remaining <= sub_pulse + 1e-6:
            return _transport_single(total)
        first = True
        while remaining > 1e-6:
            step = min(sub_pulse, remaining)
            if not first and settle_ms > 0.0:
                time.sleep(settle_ms / 1000.0)
            first = False
            if not _transport_single(sign * step):
                return False
            remaining -= step
        return True

    def _transport_profile_key() -> str:
        raw = os.environ.get(C4_TRANSPORT_PROFILE_ENV, "").strip().lower()
        if raw in {"pulsed", "pulse", PROFILE_TRANSPORT_PULSED}:
            return PROFILE_TRANSPORT_PULSED
        return PROFILE_TRANSPORT

    def transport_move(deg: float) -> bool:
        if _transport_profile_key() == PROFILE_TRANSPORT_PULSED:
            return _transport_pulsed(deg)
        return _transport_single(deg)

    def continuous_move(deg: float) -> bool:
        return _profile_move(
            deg,
            profile_name=PROFILE_CONTINUOUS,
            speed_limit=_transport_speed_limit(),
            acceleration=_continuous_acceleration(),
        )

    def direct_move(
        deg: float,
        max_speed: int | None = None,
        acceleration: int | None = None,
    ) -> bool:
        return _profile_move(
            deg,
            profile_name=PROFILE_DIRECT,
            speed_limit=max_speed,
            acceleration=acceleration,
        )

    def startup_purge_move(deg: float) -> bool:
        return _profile_move(
            deg,
            profile_name=PROFILE_PURGE,
            speed_limit=_purge_speed_limit(),
            acceleration=_startup_purge_acceleration(),
        )

    def wiggle_move(deg: float) -> bool:
        return _profile_move(
            deg,
            profile_name=PROFILE_WIGGLE,
            speed_limit=_exit_release_speed_limit(),
            acceleration=_carousel_acceleration(),
        )

    def unjam_move(deg: float) -> bool:
        return _profile_move(
            deg,
            profile_name=PROFILE_UNJAM,
            speed_limit=_purge_speed_limit() or _transport_speed_limit(),
            acceleration=_startup_purge_acceleration(),
        )

    def startup_purge_mode(enabled: bool) -> bool:
        stepper = getattr(irl, "carousel_stepper", None)
        default_speed = _default_speed_limit()
        if stepper is None or default_speed is None:
            return True
        live_purge_limit = _purge_speed_limit()
        speed_limit = live_purge_limit if enabled and live_purge_limit is not None else default_speed
        try:
            stepper.set_speed_limits(
                DEFAULT_MIN_SPEED_USTEPS_PER_S,
                int(speed_limit),
            )
            return True
        except Exception:
            logger.exception("RuntimeC4: startup purge mode speed-limit change raised")
            return False

    def eject() -> bool:
        # Normal exit release is a narrow shimmy around the current tray
        # position. The distributor gate already authorized exactly one
        # matched piece; this motion should shake that piece off the edge
        # without advancing followers into the same bin.
        amplitude = _exit_release_amplitude_deg()
        speed = _exit_release_speed_limit()
        acceleration = _carousel_acceleration()
        for _ in range(_exit_release_cycles()):
            if not _profile_move(
                amplitude,
                profile_name=PROFILE_EJECT,
                speed_limit=speed,
                acceleration=acceleration,
            ):
                return False
            if not _profile_move(
                -amplitude,
                profile_name=PROFILE_EJECT,
                speed_limit=speed,
                acceleration=acceleration,
            ):
                return False
        return True

    return (
        carousel_move,
        transport_move,
        continuous_move,
        startup_purge_move,
        startup_purge_mode,
        eject,
        wiggle_move,
        unjam_move,
        direct_move,
    )


def build_chute_callables(
    irl: Any,
    rules_engine: Any,
    logger: logging.Logger,
) -> tuple[Callable[[str], bool], Callable[[], str | None]]:
    """Chute move + position-query bridging legacy ``Chute.moveToBin``.

    Bin id format: ``L{layer}-S{section}-B{bin}`` (see LegoRulesEngine).
    """
    from irl.bin_layout import BinSize  # noqa: F401 — bridge type

    def _parse(bin_id: str) -> tuple[int, int, int] | None:
        try:
            parts = bin_id.split("-")
            if len(parts) != 3:
                return None
            return (
                int(parts[0][1:]),
                int(parts[1][1:]),
                int(parts[2][1:]),
            )
        except ValueError:
            return None

    def _servos() -> list[Any]:
        return list(getattr(irl, "servos", []) or [])

    def _close_open_servos() -> None:
        for servo in _servos():
            try:
                if hasattr(servo, "isOpen") and servo.isOpen() and hasattr(servo, "close"):
                    servo.close()
            except Exception:
                logger.exception("distributor: layer servo close raised")

    def _open_layer(layer_index: int) -> bool:
        servos = _servos()
        if layer_index < 0 or layer_index >= len(servos):
            logger.error("distributor: invalid layer_index=%s for available servos", layer_index)
            return False
        servo = servos[layer_index]
        try:
            if hasattr(servo, "open"):
                servo.open()
            return True
        except Exception:
            logger.exception("distributor: layer servo open raised (layer=%s)", layer_index)
            return False

    def move(bin_id: str) -> bool:
        chute = getattr(irl, "chute", None)
        if chute is None:
            logger.error(
                "TODO_PHASE5_WIRING: distributor chute move - irl.chute missing (bin=%s)",
                bin_id,
            )
            return False
        if bin_id == getattr(rules_engine, "reject_bin_id", lambda: "reject")() or bin_id == "reject":
            try:
                _close_open_servos()
                passthrough = float(getattr(chute, "first_bin_center", 0.0) or 0.0)
                chute.moveToAngle(passthrough)
                return True
            except Exception:
                logger.exception("distributor: reject-bin move raised")
                return False
        parsed = _parse(bin_id)
        if parsed is None:
            logger.error("distributor: unparseable bin_id=%s", bin_id)
            return False
        layer, section, bin_idx = parsed
        try:
            from irl.chute import BinAddress

            addr = BinAddress(
                layer_index=layer, section_index=section, bin_index=bin_idx
            )
            target_angle = (
                chute.getAngleForBin(addr) if hasattr(chute, "getAngleForBin") else 0.0
            )
            if target_angle is None:
                logger.error("distributor: unreachable bin_id=%s", bin_id)
                return False
            _close_open_servos()
            chute.moveToBin(addr)
            return _open_layer(layer)
        except Exception:
            logger.exception("distributor: chute.moveToBin raised (bin=%s)", bin_id)
            return False

    _last_target: dict[str, str | None] = {"v": None}

    def position_query() -> str | None:
        chute = getattr(irl, "chute", None)
        if chute is None:
            return None
        # Heuristic: if the chute stepper is "stopped" we report the last
        # commanded bin. Otherwise None = "still moving". This is good
        # enough for the settle window; real angle->bin mapping is
        # chute-specific.
        stepper = getattr(chute, "stepper", None)
        if stepper is None:
            return None
        if bool(getattr(stepper, "stopped", True)):
            return _last_target.get("v")
        return None

    # Wrap move to record the last commanded target so position_query
    # can return it after the stepper settles.
    def _move_and_record(bin_id: str) -> bool:
        ok = move(bin_id)
        if ok:
            _last_target["v"] = bin_id
        return ok

    return _move_and_record, position_query


__all__ = [
    "build_c1_callables",
    "build_c2_callables",
    "build_c3_callables",
    "build_c4_callables",
    "build_chute_callables",
]
