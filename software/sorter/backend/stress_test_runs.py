from __future__ import annotations

import json
import sqlite3
from typing import Any

import db

# The runs of the two hardware stress tests: the chute stress test (the chute
# driven back and forth for endurance, subsystems/distribution/chute_stress.py)
# and the power stress test (steppers and chute driven together in phases,
# subsystems/power_stress.py), with the power test's event log.

_POWER_STRESS_RUN_COLUMNS = (
    "id, started_at, ended_at, duration_target_s, "
    "stepper_speed_microsteps_per_sec, chute_speed_microsteps_per_sec, "
    "chute_max_deg, status, current_phase, total_time_s, config_json, error"
)


def _createTables(conn: sqlite3.Connection) -> None:
    conn.execute(
        "CREATE TABLE IF NOT EXISTS chute_stress_runs ("
        "id TEXT PRIMARY KEY, "
        "started_at REAL NOT NULL, "
        "ended_at REAL, "
        "mode TEXT NOT NULL, "
        "target_max_deg REAL NOT NULL, "
        "duration_target_s REAL NOT NULL, "
        "speed_microsteps_per_sec INTEGER NOT NULL, "
        "status TEXT NOT NULL, "
        "total_distance_deg REAL NOT NULL DEFAULT 0, "
        "total_time_s REAL NOT NULL DEFAULT 0, "
        "error TEXT"
        ")"
    )
    conn.execute(
        "CREATE TABLE IF NOT EXISTS power_stress_runs ("
        "id TEXT PRIMARY KEY, "
        "started_at REAL NOT NULL, "
        "ended_at REAL, "
        "duration_target_s REAL NOT NULL, "
        "stepper_speed_microsteps_per_sec INTEGER NOT NULL, "
        "chute_speed_microsteps_per_sec INTEGER NOT NULL, "
        "chute_max_deg REAL NOT NULL, "
        "status TEXT NOT NULL, "
        "current_phase TEXT, "
        "total_time_s REAL NOT NULL DEFAULT 0, "
        "config_json TEXT NOT NULL, "
        "error TEXT"
        ")"
    )
    conn.execute(
        "CREATE TABLE IF NOT EXISTS power_stress_events ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT, "
        "run_id TEXT NOT NULL, "
        "created_at REAL NOT NULL, "
        "event_type TEXT NOT NULL, "
        "phase TEXT, "
        "details_json TEXT NOT NULL, "
        "FOREIGN KEY(run_id) REFERENCES power_stress_runs(id) ON DELETE CASCADE"
        ")"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_power_stress_events_run "
        "ON power_stress_events(run_id, created_at)"
    )


def _connection():
    return db.connect(_createTables)


# ---------------------------------------------------------------------------
# Chute stress test runs
# ---------------------------------------------------------------------------


def _chuteStressRowToDict(row: sqlite3.Row | None) -> dict[str, Any] | None:
    if row is None:
        return None
    return {
        "id": row["id"],
        "started_at": row["started_at"],
        "ended_at": row["ended_at"],
        "mode": row["mode"],
        "target_max_deg": row["target_max_deg"],
        "duration_target_s": row["duration_target_s"],
        "speed_microsteps_per_sec": row["speed_microsteps_per_sec"],
        "status": row["status"],
        "total_distance_deg": row["total_distance_deg"],
        "total_time_s": row["total_time_s"],
        "error": row["error"],
    }


def recordChuteStressRunStart(
    *,
    run_id: str,
    started_at: float,
    mode: str,
    target_max_deg: float,
    duration_target_s: float,
    speed_microsteps_per_sec: int,
) -> None:
    with _connection() as conn:
        conn.execute(
            "INSERT INTO chute_stress_runs("
            "id, started_at, mode, target_max_deg, duration_target_s, "
            "speed_microsteps_per_sec, status, total_distance_deg, total_time_s"
            ") VALUES(?, ?, ?, ?, ?, ?, 'running', 0, 0)",
            (
                run_id,
                started_at,
                mode,
                float(target_max_deg),
                float(duration_target_s),
                int(speed_microsteps_per_sec),
            ),
        )
        conn.commit()


def updateChuteStressRunProgress(
    *,
    run_id: str,
    total_distance_deg: float,
    total_time_s: float,
) -> None:
    with _connection() as conn:
        conn.execute(
            "UPDATE chute_stress_runs SET total_distance_deg = ?, total_time_s = ? "
            "WHERE id = ?",
            (float(total_distance_deg), float(total_time_s), run_id),
        )
        conn.commit()


def finalizeChuteStressRun(
    *,
    run_id: str,
    ended_at: float,
    status: str,
    total_distance_deg: float,
    total_time_s: float,
    error: str | None,
) -> None:
    with _connection() as conn:
        conn.execute(
            "UPDATE chute_stress_runs SET ended_at = ?, status = ?, "
            "total_distance_deg = ?, total_time_s = ?, error = ? WHERE id = ?",
            (
                float(ended_at),
                status,
                float(total_distance_deg),
                float(total_time_s),
                error,
                run_id,
            ),
        )
        conn.commit()


def listChuteStressRuns(limit: int = 100) -> list[dict[str, Any]]:
    with _connection() as conn:
        rows = conn.execute(
            "SELECT id, started_at, ended_at, mode, target_max_deg, duration_target_s, "
            "speed_microsteps_per_sec, status, total_distance_deg, total_time_s, error "
            "FROM chute_stress_runs ORDER BY started_at DESC LIMIT ?",
            (int(limit),),
        ).fetchall()
    return [d for d in (_chuteStressRowToDict(r) for r in rows) if d is not None]


# ---------------------------------------------------------------------------
# Power stress test runs and their events
# ---------------------------------------------------------------------------


def _powerStressRowToDict(row: sqlite3.Row | None) -> dict[str, Any] | None:
    if row is None:
        return None
    try:
        config = json.loads(row["config_json"])
    except (TypeError, json.JSONDecodeError):
        config = {}
    return {
        "id": row["id"],
        "started_at": row["started_at"],
        "ended_at": row["ended_at"],
        "duration_target_s": row["duration_target_s"],
        "stepper_speed_microsteps_per_sec": row["stepper_speed_microsteps_per_sec"],
        "chute_speed_microsteps_per_sec": row["chute_speed_microsteps_per_sec"],
        "chute_max_deg": row["chute_max_deg"],
        "status": row["status"],
        "current_phase": row["current_phase"],
        "total_time_s": row["total_time_s"],
        "config": config,
        "error": row["error"],
    }


def recordPowerStressRunStart(
    *,
    run_id: str,
    started_at: float,
    duration_target_s: float,
    stepper_speed_microsteps_per_sec: int,
    chute_speed_microsteps_per_sec: int,
    chute_max_deg: float,
    config: dict[str, Any],
) -> None:
    with _connection() as conn:
        conn.execute(
            "INSERT INTO power_stress_runs("
            "id, started_at, duration_target_s, stepper_speed_microsteps_per_sec, "
            "chute_speed_microsteps_per_sec, chute_max_deg, status, config_json"
            ") VALUES(?, ?, ?, ?, ?, ?, 'running', ?)",
            (
                run_id,
                float(started_at),
                float(duration_target_s),
                int(stepper_speed_microsteps_per_sec),
                int(chute_speed_microsteps_per_sec),
                float(chute_max_deg),
                json.dumps(config, sort_keys=True),
            ),
        )
        conn.commit()


def updatePowerStressRunProgress(
    *, run_id: str, current_phase: str | None, total_time_s: float
) -> None:
    with _connection() as conn:
        conn.execute(
            "UPDATE power_stress_runs SET current_phase = ?, total_time_s = ? WHERE id = ?",
            (current_phase, float(total_time_s), run_id),
        )
        conn.commit()


def finalizePowerStressRun(
    *,
    run_id: str,
    ended_at: float,
    status: str,
    total_time_s: float,
    error: str | None,
) -> None:
    with _connection() as conn:
        conn.execute(
            "UPDATE power_stress_runs SET ended_at = ?, status = ?, "
            "total_time_s = ?, error = ? WHERE id = ?",
            (float(ended_at), status, float(total_time_s), error, run_id),
        )
        conn.commit()


def recordPowerStressEvent(
    *,
    run_id: str,
    created_at: float,
    event_type: str,
    phase: str | None,
    details: dict[str, Any],
) -> dict[str, Any]:
    with _connection() as conn:
        cursor = conn.execute(
            "INSERT INTO power_stress_events("
            "run_id, created_at, event_type, phase, details_json"
            ") VALUES(?, ?, ?, ?, ?)",
            (
                run_id,
                float(created_at),
                event_type,
                phase,
                json.dumps(details, sort_keys=True),
            ),
        )
        conn.commit()
        event_id = cursor.lastrowid
    return {
        "id": event_id,
        "run_id": run_id,
        "created_at": float(created_at),
        "event_type": event_type,
        "phase": phase,
        "details": details,
    }


def listPowerStressEvents(run_id: str) -> list[dict[str, Any]]:
    with _connection() as conn:
        rows = conn.execute(
            "SELECT id, run_id, created_at, event_type, phase, details_json "
            "FROM power_stress_events WHERE run_id = ? ORDER BY created_at, id",
            (run_id,),
        ).fetchall()
    events: list[dict[str, Any]] = []
    for row in rows:
        try:
            details = json.loads(row["details_json"])
        except (TypeError, json.JSONDecodeError):
            details = {}
        events.append(
            {
                "id": row["id"],
                "run_id": row["run_id"],
                "created_at": row["created_at"],
                "event_type": row["event_type"],
                "phase": row["phase"],
                "details": details,
            }
        )
    return events


def listPowerStressRuns(limit: int = 100) -> list[dict[str, Any]]:
    with _connection() as conn:
        rows = conn.execute(
            f"SELECT {_POWER_STRESS_RUN_COLUMNS} "
            "FROM power_stress_runs ORDER BY started_at DESC LIMIT ?",
            (int(limit),),
        ).fetchall()
    return [d for d in (_powerStressRowToDict(row) for row in rows) if d is not None]


def getPowerStressRun(run_id: str) -> dict[str, Any] | None:
    with _connection() as conn:
        row = conn.execute(
            f"SELECT {_POWER_STRESS_RUN_COLUMNS} "
            "FROM power_stress_runs WHERE id = ?",
            (run_id,),
        ).fetchone()
    run = _powerStressRowToDict(row)
    if run is not None:
        run["events"] = listPowerStressEvents(run_id)
    return run
