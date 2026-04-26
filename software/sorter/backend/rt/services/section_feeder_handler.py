"""Section-based feeder handler — alternative primary path for C1/C2/C3.

Inspired by the legacy ``main`` branch's
``software/client/subsystems/feeder/feeding.py`` analysis loop. Treats
each C-channel purely as a state machine over the live track angle
distribution: pieces in the *exit* arc → ``PULSE_PRECISE``, any pieces
on the platter → ``PULSE_NORMAL``, otherwise ``IDLE``. Backpressure is
the simple Main rule: a channel only pulses when the next channel's
intake (dropzone) arc is clear. C4 admission state is the gate for C3.

The handler does **not** ride on the existing RuntimeC1/C2/C3 tick path
— in section mode the orchestrator skips those runtimes and lets this
handler issue the pulse commands directly. BoxMot tracking and the C4
runtime stay untouched, so image collection and classification still
work unchanged.

This module is intentionally small: the entire decision logic on Main
fits in ~50 lines of Python, and that's what we're trying to recover
here.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable

from rt.runtimes.base import HwWorker
from rt.services.sector_shadow_observer import (
    ACTION_IDLE,
    ACTION_PULSE_NORMAL,
    ACTION_PULSE_PRECISE,
    ChannelGeometry,
    classify_channel,
)


class PulseMode(Enum):
    """Mirrors ``rt.runtimes.c2._PulseMode`` so we can call the existing
    pulse_command callables (which select the rotor profile based on the
    enum's ``value`` string)."""

    NORMAL = "normal"
    PRECISE = "precise"


# Pulse callable shape: ``pulse(mode, pulse_ms, profile_name) -> bool``.
# ``pulse_ms`` is accepted for parity with the legacy callables but the
# rotor advance distance is governed by ``steps_per_pulse`` in the
# feeder config — we pass through a sensible default and let the
# hardware layer pick the corresponding profile.
PulseCallable = Callable[[PulseMode, float, str | None], bool]


# Track items the handler accepts. Either dicts with ``angle_deg`` or
# tuples of ``(angle_deg, _)``. Keep it primitive so the handler can
# also be exercised in tests with plain numbers.
TrackEntry = Any


@dataclass(slots=True)
class _ChannelState:
    # ``-inf`` means "never pulsed" so the first cooldown check always
    # passes regardless of how the orchestrator's monotonic clock is
    # seeded.
    last_pulse_at_mono: float = -float("inf")
    last_action: str = ACTION_IDLE
    pulse_count_normal: int = 0
    pulse_count_precise: int = 0
    pulse_count_skipped_busy: int = 0
    pulse_count_skipped_cooldown: int = 0
    pulse_count_skipped_intake_blocked: int = 0


@dataclass(slots=True)
class _SectionDecision:
    """Cross-channel decision derived at one tick."""

    c2_action: str = ACTION_IDLE
    c3_action: str = ACTION_IDLE
    c2_intake_occupied: bool = False
    c3_intake_occupied: bool = False
    c4_admission_allowed: bool = False
    c1_can_pulse: bool = False
    c2_can_pulse: bool = False
    c3_can_pulse: bool = False


class SectionFeederHandler:
    """Active section-based handler for the C1/C2/C3 feeder chain.

    Lifecycle: built once at bootstrap, ``start()`` enables ticking,
    ``stop()`` disables it. The orchestrator only invokes ``tick()`` when
    its ``feeder_mode`` is set to ``"section"`` — otherwise the legacy
    RuntimeC1/C2/C3 path runs as before.
    """

    DEFAULT_C1_COOLDOWN_S = 1.5
    DEFAULT_C2_COOLDOWN_S = 0.5
    DEFAULT_C3_COOLDOWN_S = 0.3
    # Hard piece-count caps. Main's discrete carousel had only 4 slots so
    # this gate was implicit. Our platters can hold many more pieces, so
    # without an explicit cap the section feeder will pile up C3 (live
    # measurement saw 29 tracks queued before the gate finally tripped on
    # intake-arc occupancy). Cap upstream pulses on the *downstream* piece
    # count so the chain self-regulates without leases.
    DEFAULT_C2_PIECE_CAP = 8
    DEFAULT_C3_PIECE_CAP = 8

    def __init__(
        self,
        *,
        c1_pulse: Callable[[], bool],
        c2_pulse: PulseCallable,
        c3_pulse: PulseCallable,
        c1_hw: HwWorker | None,
        c2_hw: HwWorker | None,
        c3_hw: HwWorker | None,
        c2_geometry: ChannelGeometry,
        c3_geometry: ChannelGeometry,
        c1_cooldown_s: float = DEFAULT_C1_COOLDOWN_S,
        c2_cooldown_s: float = DEFAULT_C2_COOLDOWN_S,
        c3_cooldown_s: float = DEFAULT_C3_COOLDOWN_S,
        c2_piece_cap: int = DEFAULT_C2_PIECE_CAP,
        c3_piece_cap: int = DEFAULT_C3_PIECE_CAP,
        logger: logging.Logger | None = None,
    ) -> None:
        self._c1_pulse = c1_pulse
        self._c2_pulse = c2_pulse
        self._c3_pulse = c3_pulse
        self._c1_hw = c1_hw
        self._c2_hw = c2_hw
        self._c3_hw = c3_hw
        self._c2_geom = c2_geometry
        self._c3_geom = c3_geometry
        self._c1_cooldown_s = max(0.0, float(c1_cooldown_s))
        self._c2_cooldown_s = max(0.0, float(c2_cooldown_s))
        self._c3_cooldown_s = max(0.0, float(c3_cooldown_s))
        self._c2_piece_cap = max(1, int(c2_piece_cap))
        self._c3_piece_cap = max(1, int(c3_piece_cap))
        self._logger = logger or logging.getLogger("rt.section_feeder")
        self._enabled = False
        self._inhibit_reason: str | None = None
        self._c1 = _ChannelState()
        self._c2 = _ChannelState()
        self._c3 = _ChannelState()
        self._last_decision = _SectionDecision()

    # ------------------------------------------------------------------
    # Lifecycle / inhibit

    def enable(self) -> None:
        self._enabled = True

    def disable(self) -> None:
        self._enabled = False

    def is_enabled(self) -> bool:
        return self._enabled

    def set_inhibit(self, reason: str | None) -> None:
        """Operator-facing pause without disabling the handler entirely.

        Mirrors the existing ``c1.feed_inhibit`` semantic so a single
        ``feed_inhibit`` toggle still freezes new feed even in section
        mode.
        """
        self._inhibit_reason = str(reason) if reason else None

    def update_cooldowns(
        self,
        *,
        c1_s: float | None = None,
        c2_s: float | None = None,
        c3_s: float | None = None,
    ) -> None:
        if c1_s is not None:
            self._c1_cooldown_s = max(0.0, float(c1_s))
        if c2_s is not None:
            self._c2_cooldown_s = max(0.0, float(c2_s))
        if c3_s is not None:
            self._c3_cooldown_s = max(0.0, float(c3_s))

    def update_piece_caps(
        self,
        *,
        c2: int | None = None,
        c3: int | None = None,
    ) -> None:
        if c2 is not None:
            self._c2_piece_cap = max(1, int(c2))
        if c3 is not None:
            self._c3_piece_cap = max(1, int(c3))

    def update_geometry(
        self,
        *,
        channel: str,
        exit_arc_deg: float | None = None,
        intake_center_deg: float | None = None,
        intake_arc_deg: float | None = None,
    ) -> ChannelGeometry:
        """Replace one channel's sector geometry live.

        Useful for calibrating ``intake_center_deg`` from a track-angle
        histogram without rebuilding the handler. Returns the new
        geometry so callers can echo it back.
        """
        ch = str(channel).strip().lower()
        if ch == "c2":
            current = self._c2_geom
        elif ch == "c3":
            current = self._c3_geom
        else:
            raise ValueError("channel must be 'c2' or 'c3'")
        new = ChannelGeometry(
            name=current.name,
            exit_arc_deg=(
                float(exit_arc_deg)
                if exit_arc_deg is not None
                else current.exit_arc_deg
            ),
            intake_center_deg=(
                float(intake_center_deg)
                if intake_center_deg is not None
                else current.intake_center_deg
            ),
            intake_arc_deg=(
                float(intake_arc_deg)
                if intake_arc_deg is not None
                else current.intake_arc_deg
            ),
        )
        if ch == "c2":
            self._c2_geom = new
        else:
            self._c3_geom = new
        return new

    # ------------------------------------------------------------------
    # Tick

    def tick(
        self,
        *,
        c2_tracks: list[TrackEntry],
        c3_tracks: list[TrackEntry],
        c4_admission_allowed: bool,
        now_mono: float | None = None,
    ) -> _SectionDecision:
        ts = time.monotonic() if now_mono is None else float(now_mono)
        decision = _SectionDecision()
        if not self._enabled:
            self._last_decision = decision
            return decision

        c2_obs = classify_channel(self._c2_geom, _angles_from(c2_tracks))
        c3_obs = classify_channel(self._c3_geom, _angles_from(c3_tracks))
        decision.c2_action = c2_obs.action
        decision.c3_action = c3_obs.action
        decision.c2_intake_occupied = c2_obs.intake_occupied
        decision.c3_intake_occupied = c3_obs.intake_occupied
        decision.c4_admission_allowed = bool(c4_admission_allowed)

        if self._inhibit_reason:
            self._last_decision = decision
            return decision

        # Hard piece-count caps on the *downstream* channel (Main's
        # discrete carousel had this implicitly via the 4-slot geometry;
        # we add it explicitly so a continuous platter can self-regulate).
        c2_full = c2_obs.piece_count >= self._c2_piece_cap
        c3_full = c3_obs.piece_count >= self._c3_piece_cap

        # C3 first: pulse if C4 will admit. Section choice from track
        # distribution. Run downstream-first to mirror the orchestrator
        # tick order — C3's pulse can clear C2's intake-block this tick.
        decision.c3_can_pulse = self._tick_channel(
            label="c3",
            state=self._c3,
            action=c3_obs.action,
            allowed=c4_admission_allowed,
            cooldown_s=self._c3_cooldown_s,
            now=ts,
            hw=self._c3_hw,
            pulse=lambda mode: self._c3_pulse(mode, 0.0, None),
        )
        decision.c2_can_pulse = self._tick_channel(
            label="c2",
            state=self._c2,
            action=c2_obs.action,
            allowed=(not c3_obs.intake_occupied) and (not c3_full),
            cooldown_s=self._c2_cooldown_s,
            now=ts,
            hw=self._c2_hw,
            pulse=lambda mode: self._c2_pulse(mode, 0.0, None),
        )
        decision.c1_can_pulse = self._tick_c1(
            allowed=(not c2_obs.intake_occupied) and (not c2_full),
            now=ts,
        )
        self._last_decision = decision
        return decision

    # ------------------------------------------------------------------
    # Snapshot / debug

    def snapshot(self) -> dict[str, Any]:
        d = self._last_decision
        return {
            "enabled": self._enabled,
            "inhibit_reason": self._inhibit_reason,
            "cooldowns_s": {
                "c1": self._c1_cooldown_s,
                "c2": self._c2_cooldown_s,
                "c3": self._c3_cooldown_s,
            },
            "piece_caps": {
                "c2": int(self._c2_piece_cap),
                "c3": int(self._c3_piece_cap),
            },
            "geometry": {
                "c2": {
                    "exit_arc_deg": self._c2_geom.exit_arc_deg,
                    "intake_center_deg": self._c2_geom.intake_center_deg,
                    "intake_arc_deg": self._c2_geom.intake_arc_deg,
                },
                "c3": {
                    "exit_arc_deg": self._c3_geom.exit_arc_deg,
                    "intake_center_deg": self._c3_geom.intake_center_deg,
                    "intake_arc_deg": self._c3_geom.intake_arc_deg,
                },
            },
            "last_decision": {
                "c2_action": d.c2_action,
                "c3_action": d.c3_action,
                "c2_intake_occupied": d.c2_intake_occupied,
                "c3_intake_occupied": d.c3_intake_occupied,
                "c4_admission_allowed": d.c4_admission_allowed,
                "c1_can_pulse": d.c1_can_pulse,
                "c2_can_pulse": d.c2_can_pulse,
                "c3_can_pulse": d.c3_can_pulse,
            },
            "counters": {
                "c1": _state_counters(self._c1),
                "c2": _state_counters(self._c2),
                "c3": _state_counters(self._c3),
            },
        }

    # ------------------------------------------------------------------
    # Internals

    def _tick_channel(
        self,
        *,
        label: str,
        state: _ChannelState,
        action: str,
        allowed: bool,
        cooldown_s: float,
        now: float,
        hw: HwWorker | None,
        pulse: Callable[[PulseMode], bool],
    ) -> bool:
        state.last_action = action
        if action == ACTION_IDLE:
            return False
        if not allowed:
            state.pulse_count_skipped_intake_blocked += 1
            return False
        if (now - state.last_pulse_at_mono) < cooldown_s:
            state.pulse_count_skipped_cooldown += 1
            return False
        if hw is not None and (hw.busy() or hw.pending() > 0):
            state.pulse_count_skipped_busy += 1
            return False

        mode = (
            PulseMode.PRECISE if action == ACTION_PULSE_PRECISE else PulseMode.NORMAL
        )
        try:
            ok = bool(pulse(mode))
        except Exception:
            self._logger.exception(
                "SectionFeederHandler: %s pulse callable raised", label
            )
            ok = False
        state.last_pulse_at_mono = now
        if ok:
            if mode is PulseMode.PRECISE:
                state.pulse_count_precise += 1
            else:
                state.pulse_count_normal += 1
        return ok

    def _tick_c1(self, *, allowed: bool, now: float) -> bool:
        state = self._c1
        if not allowed:
            state.pulse_count_skipped_intake_blocked += 1
            return False
        if (now - state.last_pulse_at_mono) < self._c1_cooldown_s:
            state.pulse_count_skipped_cooldown += 1
            return False
        if self._c1_hw is not None and (
            self._c1_hw.busy() or self._c1_hw.pending() > 0
        ):
            state.pulse_count_skipped_busy += 1
            return False
        try:
            ok = bool(self._c1_pulse())
        except Exception:
            self._logger.exception(
                "SectionFeederHandler: c1 pulse callable raised"
            )
            ok = False
        state.last_pulse_at_mono = now
        if ok:
            state.pulse_count_normal += 1
        return ok


def _angles_from(items: list[Any]) -> list[float]:
    out: list[float] = []
    for item in items:
        if isinstance(item, dict):
            angle = item.get("angle_deg")
        elif isinstance(item, (tuple, list)) and item:
            angle = item[0]
        else:
            angle = item
        if isinstance(angle, (int, float)):
            out.append(float(angle))
    return out


def _state_counters(state: _ChannelState) -> dict[str, int]:
    return {
        "last_action": state.last_action,
        "pulse_count_normal": int(state.pulse_count_normal),
        "pulse_count_precise": int(state.pulse_count_precise),
        "pulse_count_skipped_busy": int(state.pulse_count_skipped_busy),
        "pulse_count_skipped_cooldown": int(state.pulse_count_skipped_cooldown),
        "pulse_count_skipped_intake_blocked": int(
            state.pulse_count_skipped_intake_blocked
        ),
    }


__all__ = [
    "SectionFeederHandler",
    "PulseMode",
]
