"""Track-derived transport velocity diagnostics and step recommendations."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Iterable

from rt.contracts.tracking import Track


_TWO_PI = math.tau


def wrap_rad(angle_rad: float) -> float:
    """Wrap an angle to (-pi, pi]."""
    return math.atan2(math.sin(angle_rad), math.cos(angle_rad))


def wrap_deg(angle_deg: float) -> float:
    """Wrap an angle to (-180, 180]."""
    return math.degrees(wrap_rad(math.radians(angle_deg)))


@dataclass(slots=True)
class TrackVelocityEstimate:
    key: int
    angle_rad: float
    angle_deg: float
    observed_rpm: float | None
    samples: int
    last_seen_ts: float


@dataclass(slots=True)
class TransportVelocitySnapshot:
    channel: str
    target_rpm: float
    live_track_count: int
    measured_track_count: int
    avg_rpm: float | None
    front_key: int | None
    front_angle_deg: float | None
    front_delta_to_exit_deg: float | None
    front_rpm: float | None
    front_samples: int
    recommendation: str
    recommended_step_deg: float | None
    base_step_deg: float | None

    def as_dict(self) -> dict[str, Any]:
        return {
            "channel": self.channel,
            "target_rpm": self.target_rpm,
            "live_track_count": self.live_track_count,
            "measured_track_count": self.measured_track_count,
            "avg_rpm": self.avg_rpm,
            "front_key": self.front_key,
            "front_angle_deg": self.front_angle_deg,
            "front_delta_to_exit_deg": self.front_delta_to_exit_deg,
            "front_rpm": self.front_rpm,
            "front_samples": self.front_samples,
            "recommendation": self.recommendation,
            "recommended_step_deg": self.recommended_step_deg,
            "base_step_deg": self.base_step_deg,
        }


@dataclass(slots=True)
class _TrackMotionState:
    angle_rad: float
    ts: float
    rpm_ewma: float | None = None
    samples: int = 0


class TransportVelocityObserver:
    """Estimate real piece speed from stable track angles.

    The observer is intentionally small and local-state only: runtimes feed it
    the currently actionable tracks, and it reports measured RPM plus a bounded
    movement recommendation. It does not own hardware policy.
    """

    def __init__(
        self,
        *,
        channel: str,
        exit_angle_deg: float = 0.0,
        target_rpm: float = 1.2,
        ewma_alpha: float = 0.35,
        stale_after_s: float = 3.0,
        min_dt_s: float = 0.03,
        max_dt_s: float = 1.5,
        max_jump_deg: float = 150.0,
    ) -> None:
        self.channel = channel
        self.exit_angle_rad = math.radians(exit_angle_deg)
        self.target_rpm = max(0.0, float(target_rpm))
        self.ewma_alpha = min(1.0, max(0.01, float(ewma_alpha)))
        self.stale_after_s = max(0.1, float(stale_after_s))
        self.min_dt_s = max(0.001, float(min_dt_s))
        self.max_dt_s = max(self.min_dt_s, float(max_dt_s))
        self.max_jump_rad = math.radians(max(1.0, float(max_jump_deg)))
        self._states: dict[int, _TrackMotionState] = {}
        self._last_snapshot = TransportVelocitySnapshot(
            channel=channel,
            target_rpm=self.target_rpm,
            live_track_count=0,
            measured_track_count=0,
            avg_rpm=None,
            front_key=None,
            front_angle_deg=None,
            front_delta_to_exit_deg=None,
            front_rpm=None,
            front_samples=0,
            recommendation="idle",
            recommended_step_deg=None,
            base_step_deg=None,
        )

    @property
    def snapshot(self) -> TransportVelocitySnapshot:
        return self._last_snapshot

    def update(
        self,
        tracks: Iterable[Track],
        *,
        now_mono: float,
        base_step_deg: float | None = None,
        max_step_deg: float | None = None,
        exit_slow_zone_deg: float | None = None,
    ) -> TransportVelocitySnapshot:
        estimates: list[TrackVelocityEstimate] = []
        live_keys: set[int] = set()
        for track in tracks:
            if track.angle_rad is None:
                continue
            key = int(track.global_id if track.global_id is not None else track.track_id)
            live_keys.add(key)
            angle_rad = float(track.angle_rad)
            sample_ts = float(now_mono)
            state = self._states.get(key)
            if state is not None:
                dt = sample_ts - state.ts
                if self.min_dt_s <= dt <= self.max_dt_s:
                    delta = abs(wrap_rad(angle_rad - state.angle_rad))
                    if delta <= self.max_jump_rad:
                        rpm = delta / _TWO_PI * 60.0 / dt
                        state.rpm_ewma = (
                            rpm
                            if state.rpm_ewma is None
                            else (self.ewma_alpha * rpm)
                            + ((1.0 - self.ewma_alpha) * state.rpm_ewma)
                        )
                        state.samples += 1
                if sample_ts >= state.ts:
                    state.angle_rad = angle_rad
                    state.ts = sample_ts
            else:
                state = _TrackMotionState(angle_rad=angle_rad, ts=sample_ts)
                self._states[key] = state
            estimates.append(
                TrackVelocityEstimate(
                    key=key,
                    angle_rad=angle_rad,
                    angle_deg=math.degrees(angle_rad),
                    observed_rpm=state.rpm_ewma,
                    samples=state.samples,
                    last_seen_ts=sample_ts,
                )
            )

        stale_before = now_mono - self.stale_after_s
        for key, state in list(self._states.items()):
            if key not in live_keys and state.ts < stale_before:
                self._states.pop(key, None)

        measured = [e for e in estimates if e.observed_rpm is not None]
        front = self._frontmost(estimates)
        avg_rpm = (
            sum(float(e.observed_rpm) for e in measured) / len(measured)
            if measured
            else None
        )
        front_rpm = front.observed_rpm if front is not None else None
        front_delta_deg = (
            wrap_deg(math.degrees(front.angle_rad - self.exit_angle_rad))
            if front is not None
            else None
        )
        recommended_step, recommendation = self._recommend(
            front_rpm=front_rpm,
            base_step_deg=base_step_deg,
            max_step_deg=max_step_deg,
            front_delta_to_exit_deg=front_delta_deg,
            exit_slow_zone_deg=exit_slow_zone_deg,
        )
        snapshot = TransportVelocitySnapshot(
            channel=self.channel,
            target_rpm=self.target_rpm,
            live_track_count=len(estimates),
            measured_track_count=len(measured),
            avg_rpm=avg_rpm,
            front_key=front.key if front is not None else None,
            front_angle_deg=front.angle_deg if front is not None else None,
            front_delta_to_exit_deg=front_delta_deg,
            front_rpm=front_rpm,
            front_samples=front.samples if front is not None else 0,
            recommendation=recommendation,
            recommended_step_deg=recommended_step,
            base_step_deg=base_step_deg,
        )
        self._last_snapshot = snapshot
        return snapshot

    def _frontmost(
        self, estimates: list[TrackVelocityEstimate]
    ) -> TrackVelocityEstimate | None:
        if not estimates:
            return None
        return min(
            estimates,
            key=lambda e: abs(wrap_rad(e.angle_rad - self.exit_angle_rad)),
        )

    def _recommend(
        self,
        *,
        front_rpm: float | None,
        base_step_deg: float | None,
        max_step_deg: float | None,
        front_delta_to_exit_deg: float | None,
        exit_slow_zone_deg: float | None,
    ) -> tuple[float | None, str]:
        if base_step_deg is None:
            return None, "observe"
        base = max(0.1, float(base_step_deg))
        cap = max(base, float(max_step_deg if max_step_deg is not None else base))
        if (
            front_delta_to_exit_deg is not None
            and exit_slow_zone_deg is not None
            and abs(front_delta_to_exit_deg) <= max(0.0, float(exit_slow_zone_deg))
        ):
            return base, "exit_approach_hold_small"
        if front_rpm is None or self.target_rpm <= 0.0:
            return base, "gathering_velocity"
        ratio = front_rpm / self.target_rpm
        if ratio < 0.45:
            return min(cap, base * 3.0), "extend_transport_window"
        if ratio < 0.75:
            return min(cap, base * 2.0), "lengthen_transport_window"
        if ratio > 1.35:
            return base, "hold_base_step"
        return min(cap, max(base, base * 1.25)), "near_target"


__all__ = [
    "TransportVelocityObserver",
    "TransportVelocitySnapshot",
    "TrackVelocityEstimate",
    "wrap_deg",
    "wrap_rad",
]
