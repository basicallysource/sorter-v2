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


def build_c1_callables(
    irl: Any, logger: logging.Logger
) -> tuple[Callable[[], bool], Callable[[int], bool]]:
    """Return (pulse, recovery) closures for RuntimeC1.

    Bridge: ``irl.c_channel_1_rotor_stepper.move_degrees`` /
    ``irl.feeder_config.first_rotor`` for pulse sizing.
    """

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
            return bool(stepper.move_degrees(deg))
        except Exception:
            logger.exception("RuntimeC1: pulse raised")
            return False

    def recovery(level: int) -> bool:
        logger.warning(
            "TODO_PHASE5_WIRING: c1 jam recovery level=%d — live verification needed "
            "(stepper.move_degrees_blocking shake sequence)",
            level,
        )
        return False

    return pulse, recovery


def build_c2_callables(
    irl: Any, logger: logging.Logger
) -> tuple[Callable[[], bool], Callable[[], bool]]:
    def pulse() -> bool:
        stepper = getattr(irl, "c_channel_2_rotor_stepper", None)
        cfg = getattr(getattr(irl, "feeder_config", None) or getattr(
            getattr(irl, "irl_config", None), "feeder_config", None
        ), "second_rotor_normal", None)
        if stepper is None or cfg is None:
            logger.error("TODO_PHASE5_WIRING: c2 pulse - stepper/cfg missing")
            return False
        try:
            deg = stepper.degrees_for_microsteps(cfg.steps_per_pulse)
            return bool(stepper.move_degrees(deg))
        except Exception:
            logger.exception("RuntimeC2: pulse raised")
            return False

    def wiggle() -> bool:
        logger.warning(
            "TODO_PHASE5_WIRING: c2 wiggle — live verification needed"
        )
        return False

    return pulse, wiggle


def build_c3_callables(
    irl: Any, logger: logging.Logger
) -> tuple[Callable[[Any, float], bool], Callable[[], bool]]:
    def pulse(mode: Any, _pulse_ms: float) -> bool:
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
            return bool(stepper.move_degrees(deg))
        except Exception:
            logger.exception("RuntimeC3: pulse raised")
            return False

    def wiggle() -> bool:
        logger.warning(
            "TODO_PHASE5_WIRING: c3 wiggle — live verification needed"
        )
        return False

    return pulse, wiggle


def build_c4_callables(
    irl: Any,
    logger: logging.Logger,
    *,
    startup_purge_speed_scale: float = 1.0,
) -> tuple[
    Callable[[float], bool],
    Callable[[float], bool],
    Callable[[bool], bool],
    Callable[[], bool],
]:
    def _default_speed_limit() -> int | None:
        cfg_root = getattr(irl, "irl_config", None) or irl
        cfg = getattr(cfg_root, "carousel_stepper", None)
        speed = getattr(cfg, "default_steps_per_second", None)
        return int(speed) if isinstance(speed, int) and speed > 0 else None

    def _move_with_speed_limit(deg: float, *, speed_limit: int | None) -> bool:
        stepper = getattr(irl, "carousel_stepper", None)
        if stepper is None:
            logger.error("TODO_PHASE5_WIRING: c4 carousel move - stepper missing")
            return False
        default_speed = _default_speed_limit()
        if (
            speed_limit is None
            or default_speed is None
            or speed_limit <= default_speed
        ):
            try:
                return bool(stepper.move_degrees(deg))
            except Exception:
                logger.exception("RuntimeC4: carousel_move raised")
                return False
        try:
            stepper.set_speed_limits(16, int(speed_limit))
            return bool(stepper.move_degrees(deg))
        except Exception:
            logger.exception("RuntimeC4: fast carousel_move raised")
            return False

    def carousel_move(deg: float) -> bool:
        return _move_with_speed_limit(deg, speed_limit=None)

    purge_speed_limit = None
    default_speed = _default_speed_limit()
    if default_speed is not None and startup_purge_speed_scale > 1.0:
        purge_speed_limit = max(
            default_speed,
            int(round(float(default_speed) * float(startup_purge_speed_scale))),
        )

    def startup_purge_move(deg: float) -> bool:
        return carousel_move(deg)

    def startup_purge_mode(enabled: bool) -> bool:
        stepper = getattr(irl, "carousel_stepper", None)
        default_speed = _default_speed_limit()
        if stepper is None or default_speed is None:
            return True
        speed_limit = purge_speed_limit if enabled and purge_speed_limit is not None else default_speed
        try:
            stepper.set_speed_limits(16, int(speed_limit))
            return True
        except Exception:
            logger.exception("RuntimeC4: startup purge mode speed-limit change raised")
            return False

    def eject() -> bool:
        # Legacy ejection lives in the classification_channel_eject RotorPulseConfig
        # applied against the carousel stepper at high speed.
        stepper = getattr(irl, "carousel_stepper", None)
        feeder_cfg = getattr(irl, "feeder_config", None) or getattr(
            getattr(irl, "irl_config", None), "feeder_config", None
        )
        cfg = (
            getattr(feeder_cfg, "classification_channel_eject", None)
            if feeder_cfg
            else None
        )
        if stepper is None or cfg is None:
            logger.error(
                "TODO_PHASE5_WIRING: c4 eject - stepper or classification_channel_eject cfg missing"
            )
            return False
        try:
            deg = stepper.degrees_for_microsteps(cfg.steps_per_pulse)
            return bool(stepper.move_degrees(deg))
        except Exception:
            logger.exception("RuntimeC4: eject raised")
            return False

    return carousel_move, startup_purge_move, startup_purge_mode, eject


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
            chute.moveToBin(addr)
            return True
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
        _last_target["v"] = bin_id
        return move(bin_id)

    return _move_and_record, position_query


__all__ = [
    "build_c1_callables",
    "build_c2_callables",
    "build_c3_callables",
    "build_c4_callables",
    "build_chute_callables",
]
