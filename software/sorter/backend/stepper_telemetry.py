from __future__ import annotations

import json
import sqlite3
import time
import uuid
from typing import Any, Iterable, Optional

import db

# Stepper / TMC2209 StallGuard telemetry. Lives in the shared local_state SQLite
# DB (same file as the rest of the machine's persistent state) but owns its own
# tables and module so the high-volume sample writes stay self-contained. Two
# tables, mirroring the power_stress_runs + power_stress_events pattern in
# stress_test_runs.py: a run row groups a recording session (a targeted sweep, a
# stall test, or a passive logging window), and many sample rows hang off it.

# Recording sources.
SOURCE_SWEEP = "sweep"          # constant-speed targeted test
SOURCE_STALL_TEST = "stall_test"  # deliberate-load test to find the stall floor
SOURCE_PASSIVE = "passive"      # background logging during normal operation
SOURCE_CHUTE_STRESS = "chute_stress"  # telemetry captured during a chute stress run

RUN_STATUS_RUNNING = "running"
RUN_STATUS_COMPLETED = "completed"
RUN_STATUS_ABORTED = "aborted"
RUN_STATUS_ERROR = "error"


def _createTables(conn: sqlite3.Connection) -> None:
    conn.execute(
        "CREATE TABLE IF NOT EXISTS stepper_telemetry_runs ("
        "id TEXT PRIMARY KEY, "
        "started_at REAL NOT NULL, "
        "ended_at REAL, "
        "source TEXT NOT NULL, "
        "stepper_name TEXT, "
        "label TEXT, "
        "status TEXT NOT NULL, "
        "params_json TEXT, "
        "machine_id TEXT, "
        "sorting_session_id TEXT, "
        "sample_count INTEGER NOT NULL DEFAULT 0, "
        "sg_min INTEGER, "
        "sg_max INTEGER, "
        "sg_mean REAL, "
        "suggested_sgthrs INTEGER, "
        "notes TEXT, "
        "error TEXT, "
        "chute_stress_run_id TEXT"
        ")"
    )
    db.add_columns(conn, "stepper_telemetry_runs", {"chute_stress_run_id": "TEXT"})
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_stepper_telemetry_runs_time "
        "ON stepper_telemetry_runs(started_at)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_stepper_telemetry_runs_stepper "
        "ON stepper_telemetry_runs(stepper_name, started_at)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_stepper_telemetry_runs_chute_stress "
        "ON stepper_telemetry_runs(chute_stress_run_id)"
    )
    conn.execute(
        "CREATE TABLE IF NOT EXISTS stepper_telemetry_samples ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT, "
        "run_id TEXT NOT NULL, "
        "recorded_at REAL NOT NULL, "
        "stepper_name TEXT NOT NULL, "
        "channel INTEGER, "
        "sg_result INTEGER, "
        "cs_actual INTEGER, "
        "tstep INTEGER, "
        "drv_status_raw INTEGER, "
        "commanded_speed INTEGER, "
        "irun INTEGER, "
        "microsteps INTEGER, "
        "stealthchop INTEGER, "
        "loaded INTEGER, "
        "acceleration INTEGER, "
        "pwm_scale INTEGER, "
        "ioin INTEGER"
        ")"
    )
    # Migration: add columns introduced after the table first shipped, so
    # DBs created by earlier versions gain them without a manual rebuild.
    db.add_columns(conn, "stepper_telemetry_samples", {
        "acceleration": "INTEGER", "pwm_scale": "INTEGER", "ioin": "INTEGER",
    })
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_stepper_telemetry_samples_run "
        "ON stepper_telemetry_samples(run_id, recorded_at)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_stepper_telemetry_samples_stepper "
        "ON stepper_telemetry_samples(stepper_name, recorded_at)"
    )


def _connection():
    return db.connect(_createTables)


def createRun(
    source: str,
    *,
    stepper_name: Optional[str] = None,
    label: Optional[str] = None,
    params: Optional[dict[str, Any]] = None,
    machine_id: Optional[str] = None,
    sorting_session_id: Optional[str] = None,
    notes: Optional[str] = None,
    chute_stress_run_id: Optional[str] = None,
) -> str:
    run_id = uuid.uuid4().hex
    with _connection() as conn:
        conn.execute(
            "INSERT INTO stepper_telemetry_runs "
            "(id, started_at, source, stepper_name, label, status, params_json, "
            "machine_id, sorting_session_id, notes, chute_stress_run_id) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                run_id,
                time.time(),
                source,
                stepper_name,
                label,
                RUN_STATUS_RUNNING,
                json.dumps(params) if params is not None else None,
                machine_id,
                sorting_session_id,
                notes,
                chute_stress_run_id,
            ),
        )
        conn.commit()
    return run_id


def insertSamples(run_id: str, samples: Iterable[dict[str, Any]]) -> int:
    rows = [
        (
            run_id,
            s.get("recorded_at", time.time()),
            s.get("stepper_name"),
            s.get("channel"),
            s.get("sg_result"),
            s.get("cs_actual"),
            s.get("tstep"),
            s.get("drv_status_raw"),
            s.get("commanded_speed"),
            s.get("irun"),
            s.get("microsteps"),
            1 if s.get("stealthchop") else 0 if s.get("stealthchop") is not None else None,
            1 if s.get("loaded") else 0 if s.get("loaded") is not None else None,
            s.get("acceleration"),
            s.get("pwm_scale"),
            s.get("ioin"),
        )
        for s in samples
    ]
    if not rows:
        return 0
    with _connection() as conn:
        conn.executemany(
            "INSERT INTO stepper_telemetry_samples "
            "(run_id, recorded_at, stepper_name, channel, sg_result, cs_actual, "
            "tstep, drv_status_raw, commanded_speed, irun, microsteps, stealthchop, loaded, acceleration, pwm_scale, ioin) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            rows,
        )
        conn.commit()
    return len(rows)


def finishRun(
    run_id: str,
    *,
    status: str = RUN_STATUS_COMPLETED,
    sg_min: Optional[int] = None,
    sg_max: Optional[int] = None,
    sg_mean: Optional[float] = None,
    suggested_sgthrs: Optional[int] = None,
    error: Optional[str] = None,
) -> None:
    with _connection() as conn:
        count_row = conn.execute(
            "SELECT COUNT(*) AS c FROM stepper_telemetry_samples WHERE run_id = ?",
            (run_id,),
        ).fetchone()
        sample_count = int(count_row["c"]) if count_row else 0
        conn.execute(
            "UPDATE stepper_telemetry_runs SET "
            "ended_at = ?, status = ?, sample_count = ?, sg_min = ?, sg_max = ?, "
            "sg_mean = ?, suggested_sgthrs = ?, error = ? "
            "WHERE id = ?",
            (
                time.time(),
                status,
                sample_count,
                sg_min,
                sg_max,
                sg_mean,
                suggested_sgthrs,
                error,
                run_id,
            ),
        )
        conn.commit()


def _runRowToDict(row: sqlite3.Row) -> dict[str, Any]:
    d = dict(row)
    params = d.pop("params_json", None)
    try:
        d["params"] = json.loads(params) if params else None
    except Exception:
        d["params"] = None
    return d


def listRuns(
    *,
    limit: int = 100,
    source: Optional[str] = None,
    stepper_name: Optional[str] = None,
) -> list[dict[str, Any]]:
    clauses: list[str] = []
    args: list[Any] = []
    if source:
        clauses.append("source = ?")
        args.append(source)
    if stepper_name:
        clauses.append("stepper_name = ?")
        args.append(stepper_name)
    where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
    args.append(max(1, min(limit, 2000)))
    with _connection() as conn:
        rows = conn.execute(
            "SELECT * FROM stepper_telemetry_runs"
            + where
            + " ORDER BY started_at DESC LIMIT ?",
            args,
        ).fetchall()
    return [_runRowToDict(r) for r in rows]


def getRun(run_id: str) -> Optional[dict[str, Any]]:
    with _connection() as conn:
        row = conn.execute(
            "SELECT * FROM stepper_telemetry_runs WHERE id = ?", (run_id,)
        ).fetchone()
    return _runRowToDict(row) if row else None


def getRunByChuteStressRunId(chute_stress_run_id: str) -> Optional[dict[str, Any]]:
    with _connection() as conn:
        row = conn.execute(
            "SELECT * FROM stepper_telemetry_runs WHERE chute_stress_run_id = ? "
            "ORDER BY started_at DESC LIMIT 1",
            (chute_stress_run_id,),
        ).fetchone()
    return _runRowToDict(row) if row else None


def getRunSamples(run_id: str, *, max_points: int = 5000) -> list[dict[str, Any]]:
    # Downsample by row stride when a run holds more than max_points so the
    # frontend never has to render an unbounded series.
    with _connection() as conn:
        total_row = conn.execute(
            "SELECT COUNT(*) AS c FROM stepper_telemetry_samples WHERE run_id = ?",
            (run_id,),
        ).fetchone()
        total = int(total_row["c"]) if total_row else 0
        if total <= max_points:
            rows = conn.execute(
                "SELECT * FROM stepper_telemetry_samples WHERE run_id = ? "
                "ORDER BY recorded_at ASC",
                (run_id,),
            ).fetchall()
        else:
            stride = (total // max_points) + 1
            rows = conn.execute(
                "SELECT * FROM ("
                "SELECT *, ROW_NUMBER() OVER (ORDER BY recorded_at ASC) AS rn "
                "FROM stepper_telemetry_samples WHERE run_id = ?"
                ") WHERE rn % ? = 0 ORDER BY recorded_at ASC",
                (run_id, stride),
            ).fetchall()
    return [dict(r) for r in rows]


def getStepperSummary() -> list[dict[str, Any]]:
    # Per-stepper rollup across all recorded samples — the at-a-glance table for
    # the telemetry page (how each motor's SG_RESULT distribution looks overall).
    with _connection() as conn:
        rows = conn.execute(
            "SELECT stepper_name, COUNT(*) AS samples, "
            "MIN(sg_result) AS sg_min, MAX(sg_result) AS sg_max, "
            "AVG(sg_result) AS sg_mean, MAX(recorded_at) AS last_seen "
            "FROM stepper_telemetry_samples "
            "WHERE sg_result IS NOT NULL AND sg_result >= 0 "
            "GROUP BY stepper_name ORDER BY stepper_name"
        ).fetchall()
    return [dict(r) for r in rows]


def deleteRun(run_id: str) -> None:
    with _connection() as conn:
        conn.execute("DELETE FROM stepper_telemetry_samples WHERE run_id = ?", (run_id,))
        conn.execute("DELETE FROM stepper_telemetry_runs WHERE id = ?", (run_id,))
        conn.commit()


