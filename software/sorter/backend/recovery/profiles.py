"""Shakes: short, sharp back-and-forth runs of a channel's motor that break a
stuck piece loose and end where they began.

The one list behind the recovery procedures and the dashboard's Shake menu, so
a shake chosen by hand is exactly the one a procedure runs. The firmware runs a
shake on its own and returns to the start; it cannot be cut short.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ShakeProfile:
    key: str
    label: str
    blurb: str
    # Each stroke, in motor degrees (before the channel's gearing).
    amplitude_deg: float
    cycles: int
    speed: int  # microsteps a second
    acceleration: int  # microsteps a second squared


# Gentlest to strongest. Tried on the jitter test page; "Heavy stuck" is the
# one that freed most stuck pieces there.
SHAKES: tuple[ShakeProfile, ...] = (
    ShakeProfile("brief", "Brief", "A short, sharp burst", 6.0, 3, 5000, 100000),
    ShakeProfile("heavy", "Heavy stuck", "Medium throw, medium length", 6.0, 12, 5000, 100000),
    ShakeProfile("long", "Soft and long", "Gentle but long", 5.0, 30, 3500, 55000),
    ShakeProfile("hard", "Big and hard", "Big throw, strong jerk", 9.0, 8, 6500, 200000),
    ShakeProfile("max", "Max shake", "The largest throw, strong", 13.0, 12, 6500, 190000),
)

_BY_KEY = {p.key: p for p in SHAKES}


def shakeProfile(key: str) -> ShakeProfile:
    try:
        return _BY_KEY[key]
    except KeyError:
        raise ValueError(f"No shake called {key!r}.") from None


def shakeSeconds(profile: ShakeProfile, microsteps: int) -> float:
    """About how long a shake of ``microsteps`` a stroke takes: each stroke a
    trapezoidal (or, when short, triangular) move."""
    accel = max(profile.acceleration, 1)
    ramp = profile.speed * profile.speed / (2.0 * accel)
    if 2.0 * ramp >= microsteps:
        stroke = 2.0 * (max(microsteps, 1) / accel) ** 0.5
    else:
        stroke = 2.0 * profile.speed / accel + (microsteps - 2.0 * ramp) / profile.speed
    return 2 * profile.cycles * (stroke + 0.001)
