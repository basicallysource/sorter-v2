"""The chute's position check: every so many pieces, the chute goes up to its
home switch the way homing does and sees where it finds it.

Homing makes the switch's edge step 0, so the step count where the switch
triggers now is how far the chute has drifted since: steps it lost, or gained.
StallGuard can't see steps skipped while the chute speeds up or slows down, or
skipping that never loads the motor much. This sees all of them, after the
fact, so the pieces since the last check may have gone to the wrong bins.

The firmware stops the chute and zeroes its count the instant the switch
triggers (Stepper::stepgen_tick), so the count it had is read while the chute
moves: the last reading before the stop. At CHECK_SPEED that is within a few
microsteps, well under LOST_STEPS_DEG.

Finding the switch also puts the chute back on its true position, so a drift
is corrected as it is found. Not finding it leaves the chute unhomed, which
holds the machine until it is homed again (see stepper_stall_monitor.py).
"""

from __future__ import annotations

import math
import sqlite3
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import db

if TYPE_CHECKING:
    from .chute import Chute

# The approach starts this far above the switch, which is the most drift it
# can measure: a chute off by more finds the switch at once.
CHECK_FROM_DEG = 15.0
# Half the homing speed, in the homing direction (the sign of HOME_SPEED).
CHECK_SPEED = 500
CHECK_TIMEOUT_S = 5.0
# A drift this big is steps lost. The switch and the reading repeat within a
# fraction of it; one skipped electrical cycle of the motor is 1.5° of chute.
LOST_STEPS_DEG = 0.75
# The firmware can report "stopped" before a move it was just given starts.
START_GRACE_S = 0.3


@dataclass(frozen=True)
class PositionCheck:
    checked_at: float
    ok: bool
    # Where the switch triggered, in microsteps and chute degrees from the
    # zero the last homing set. Positive: the switch came early, so the chute
    # was nearer it than its count said (steps lost moving away from it).
    drift_steps: int | None = None
    drift_deg: float | None = None
    # It found the switch at once: off by at least CHECK_FROM_DEG.
    beyond_range: bool = False
    # How finely the drift was read: the chute's travel between two readings.
    precision_deg: float | None = None
    duration_s: float | None = None
    error: str | None = None

    @property
    def lost_steps(self) -> bool:
        return self.ok and self.drift_deg is not None and abs(self.drift_deg) >= LOST_STEPS_DEG


def checkPosition(chute: "Chute") -> PositionCheck:
    """Find the home switch from CHECK_FROM_DEG above it and return how far
    the chute had drifted. Blocks for about two seconds; the caller runs it
    off the main loop."""
    from .chute import GEAR_RATIO, HOME_SPEED_MICROSTEPS_PER_SEC

    started = time.monotonic()
    stepper = chute.stepper

    def failed(error: str) -> PositionCheck:
        chute.markUnhomed(f"position check: {error}")
        return PositionCheck(time.time(), False, duration_s=time.monotonic() - started, error=error)

    if chute.moveToAngleBlocking(CHECK_FROM_DEG, timeout_buffer_ms=1500) is None:
        return failed("the move up to the switch did not finish")
    speed = int(math.copysign(CHECK_SPEED, HOME_SPEED_MICROSTEPS_PER_SEC))
    stepper.home(speed, chute.home_pin, home_pin_active_high=chute.endstop_active_high)
    homing_from = time.monotonic()
    last: int | None = None
    reads = 0
    while True:
        now = time.monotonic()
        if stepper.stopped and now - homing_from >= START_GRACE_S:
            break
        if now - homing_from > CHECK_TIMEOUT_S:
            stepper.move_at_speed(0, force=True)
            return failed(f"no switch within {CHECK_TIMEOUT_S:g} s")
        position = stepper.position
        reads += 1
        # Once the switch has triggered the firmware's count reads 0.
        if position != 0:
            last = position
    homing_s = time.monotonic() - homing_from
    if not chute.endstop_triggered:
        return failed("it stopped before the switch")

    def chuteDeg(steps: float) -> float:
        return stepper.degrees_for_microsteps(steps) / GEAR_RATIO

    interval_s = homing_s / reads if reads else None
    precision = round(chuteDeg(abs(speed) * interval_s), 3) if interval_s else None
    duration = round(time.monotonic() - started, 2)
    if last is None or abs(chuteDeg(last)) >= CHECK_FROM_DEG:
        steps = stepper.microsteps_for_degrees(CHECK_FROM_DEG * GEAR_RATIO)
        return PositionCheck(
            time.time(), True, steps, CHECK_FROM_DEG, beyond_range=True,
            precision_deg=precision, duration_s=duration,
        )
    return PositionCheck(
        time.time(), True, last, round(chuteDeg(last), 3), precision_deg=precision, duration_s=duration,
    )


# --- What the checks found, for the chute's StallGuard tab ---


def _createTables(conn: sqlite3.Connection) -> None:
    conn.execute(
        "CREATE TABLE IF NOT EXISTS chute_position_checks ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT, "
        "checked_at REAL NOT NULL, "
        "ok INTEGER NOT NULL, "
        "drift_steps INTEGER, "
        "drift_deg REAL, "
        "beyond_range INTEGER NOT NULL DEFAULT 0, "
        "precision_deg REAL, "
        "duration_s REAL, "
        "error TEXT"
        ")"
    )


def recordCheck(check: PositionCheck) -> None:
    with db.connect(_createTables) as conn:
        conn.execute(
            "INSERT INTO chute_position_checks "
            "(checked_at, ok, drift_steps, drift_deg, beyond_range, precision_deg, duration_s, error) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                check.checked_at, int(check.ok), check.drift_steps, check.drift_deg,
                int(check.beyond_range), check.precision_deg, check.duration_s, check.error,
            ),
        )
        conn.commit()


def summary(limit: int = 20) -> dict[str, Any]:
    """The checks so far: how many, how many found lost steps, the largest
    drift, and the latest ones, newest first."""
    with db.connect(_createTables) as conn:
        totals = conn.execute(
            "SELECT COUNT(*) AS checks, "
            "SUM(CASE WHEN ok = 0 THEN 1 ELSE 0 END) AS failed, "
            "SUM(CASE WHEN ok = 1 AND ABS(drift_deg) >= ? THEN 1 ELSE 0 END) AS lost_steps, "
            "MAX(CASE WHEN ok = 1 THEN ABS(drift_deg) END) AS largest_deg "
            "FROM chute_position_checks",
            (LOST_STEPS_DEG,),
        ).fetchone()
        rows = conn.execute(
            "SELECT * FROM chute_position_checks ORDER BY checked_at DESC LIMIT ?", (limit,)
        ).fetchall()
    return {
        "checks": int(totals["checks"] or 0),
        "failed": int(totals["failed"] or 0),
        "lost_steps": int(totals["lost_steps"] or 0),
        "largest_deg": totals["largest_deg"],
        "lost_steps_deg": LOST_STEPS_DEG,
        "recent": [
            {**dict(r), "ok": bool(r["ok"]), "beyond_range": bool(r["beyond_range"])} for r in rows
        ],
    }
