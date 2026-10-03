from __future__ import annotations

import json
import sqlite3
import time
import uuid
from typing import Any

import db

# The feeder pulse-perception auto-tune's runs and their trials
# (subsystems/feeder/pulse_perception/autotune.py). Every finished trial across
# every run is the tuning dataset. Whether background exploration is on is a
# key/value state entry (local_state.getFeederAutotuneBackground).

_FEEDER_AUTOTUNE_RUN_COLUMNS = (
    "id, started_at, ended_at, status, baseline_config, settings_json, "
    "best_trial_id, notes"
)

_FEEDER_AUTOTUNE_TRIAL_COLUMNS = (
    "id, run_id, trial_index, kind, params_json, started_at, ended_at, status, "
    "measured_s, pieces_delivered, incidents, double_drops, pieces_per_min, "
    "double_drop_rate, feasible, score"
)


def _createTables(conn: sqlite3.Connection) -> None:
    conn.execute(
        "CREATE TABLE IF NOT EXISTS feeder_autotune_runs ("
        "id TEXT PRIMARY KEY, "
        "started_at REAL NOT NULL, "
        "ended_at REAL, "
        "status TEXT NOT NULL, "
        "baseline_config TEXT NOT NULL, "
        "settings_json TEXT NOT NULL, "
        "best_trial_id INTEGER, "
        "notes TEXT"
        ")"
    )
    conn.execute(
        "CREATE TABLE IF NOT EXISTS feeder_autotune_trials ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT, "
        "run_id TEXT NOT NULL, "
        "trial_index INTEGER NOT NULL, "
        "kind TEXT NOT NULL, "
        "params_json TEXT NOT NULL, "
        "started_at REAL NOT NULL, "
        "ended_at REAL, "
        "status TEXT NOT NULL, "
        "measured_s REAL NOT NULL DEFAULT 0, "
        "pieces_delivered INTEGER NOT NULL DEFAULT 0, "
        "incidents INTEGER NOT NULL DEFAULT 0, "
        "double_drops INTEGER NOT NULL DEFAULT 0, "
        "pieces_per_min REAL, "
        "double_drop_rate REAL, "
        "feasible INTEGER, "
        "score REAL, "
        "FOREIGN KEY(run_id) REFERENCES feeder_autotune_runs(id) ON DELETE CASCADE"
        ")"
    )
    db.add_columns(conn, "feeder_autotune_trials", {"double_drop_rate": "REAL", "feasible": "INTEGER"})
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_feeder_autotune_trials_run "
        "ON feeder_autotune_trials(run_id, trial_index)"
    )


def _connection():
    return db.connect(_createTables)


def _feederAutotuneRunRowToDict(row: sqlite3.Row | None) -> dict[str, Any] | None:
    if row is None:
        return None
    out = {key: row[key] for key in row.keys()}
    for json_key in ("baseline_config", "settings_json"):
        raw = out.get(json_key)
        try:
            out[json_key] = json.loads(raw) if isinstance(raw, str) and raw else None
        except json.JSONDecodeError:
            out[json_key] = None
    return out


def _feederAutotuneTrialRowToDict(row: sqlite3.Row | None) -> dict[str, Any] | None:
    if row is None:
        return None
    out = {key: row[key] for key in row.keys()}
    raw = out.get("params_json")
    try:
        out["params_json"] = json.loads(raw) if isinstance(raw, str) and raw else {}
    except json.JSONDecodeError:
        out["params_json"] = {}
    feasible = out.get("feasible")
    out["feasible"] = bool(feasible) if feasible is not None else None
    return out


def createFeederAutotuneRun(
    baseline_config: dict[str, Any], settings: dict[str, Any]
) -> dict[str, Any] | None:
    run_id = str(uuid.uuid4())
    with _connection() as conn:
        conn.execute(
            f"INSERT INTO feeder_autotune_runs({_FEEDER_AUTOTUNE_RUN_COLUMNS}) "
            "VALUES(?, ?, NULL, 'active', ?, ?, NULL, NULL)",
            (
                run_id,
                time.time(),
                json.dumps(baseline_config, sort_keys=True),
                json.dumps(settings, sort_keys=True),
            ),
        )
        conn.commit()
    return getFeederAutotuneRun(run_id)


def getFeederAutotuneRun(run_id: str) -> dict[str, Any] | None:
    with _connection() as conn:
        row = conn.execute(
            f"SELECT {_FEEDER_AUTOTUNE_RUN_COLUMNS} FROM feeder_autotune_runs "
            "WHERE id = ?",
            (run_id,),
        ).fetchone()
    return _feederAutotuneRunRowToDict(row)


def finishFeederAutotuneRun(run_id: str, status: str) -> None:
    with _connection() as conn:
        conn.execute(
            "UPDATE feeder_autotune_runs SET status = ?, ended_at = ? "
            "WHERE id = ? AND status = 'active'",
            (status, time.time(), run_id),
        )
        conn.commit()


def setFeederAutotuneBestTrial(run_id: str, trial_id: int) -> None:
    with _connection() as conn:
        conn.execute(
            "UPDATE feeder_autotune_runs SET best_trial_id = ? WHERE id = ?",
            (int(trial_id), run_id),
        )
        conn.commit()


def interruptActiveFeederAutotuneRuns() -> list[dict[str, Any]]:
    with _connection() as conn:
        rows = conn.execute(
            f"SELECT {_FEEDER_AUTOTUNE_RUN_COLUMNS} FROM feeder_autotune_runs "
            "WHERE status = 'active'"
        ).fetchall()
        interrupted = [
            d for d in (_feederAutotuneRunRowToDict(r) for r in rows) if d is not None
        ]
        if interrupted:
            now = time.time()
            conn.execute(
                "UPDATE feeder_autotune_runs SET status = 'interrupted', ended_at = ? "
                "WHERE status = 'active'",
                (now,),
            )
            conn.execute(
                "UPDATE feeder_autotune_trials SET status = 'aborted', ended_at = ? "
                "WHERE status = 'running'",
                (now,),
            )
            conn.commit()
    return interrupted


def insertFeederAutotuneTrial(
    run_id: str, trial_index: int, kind: str, params: dict[str, Any]
) -> int:
    with _connection() as conn:
        cur = conn.execute(
            "INSERT INTO feeder_autotune_trials"
            "(run_id, trial_index, kind, params_json, started_at, status) "
            "VALUES(?, ?, ?, ?, ?, 'running')",
            (run_id, int(trial_index), kind, json.dumps(params, sort_keys=True), time.time()),
        )
        conn.commit()
        return int(cur.lastrowid)


def finalizeFeederAutotuneTrial(
    trial_id: int,
    *,
    status: str,
    measured_s: float,
    pieces_delivered: int,
    incidents: int,
    double_drops: int,
    pieces_per_min: float | None,
    double_drop_rate: float | None = None,
    feasible: bool | None = None,
    score: float | None,
) -> None:
    with _connection() as conn:
        conn.execute(
            "UPDATE feeder_autotune_trials SET status = ?, ended_at = ?, "
            "measured_s = ?, pieces_delivered = ?, incidents = ?, double_drops = ?, "
            "pieces_per_min = ?, double_drop_rate = ?, feasible = ?, score = ? "
            "WHERE id = ?",
            (
                status,
                time.time(),
                float(measured_s),
                int(pieces_delivered),
                int(incidents),
                int(double_drops),
                pieces_per_min,
                double_drop_rate,
                None if feasible is None else int(feasible),
                score,
                int(trial_id),
            ),
        )
        conn.commit()


def listFeederAutotuneTrials(run_id: str, limit: int = 500) -> list[dict[str, Any]]:
    with _connection() as conn:
        rows = conn.execute(
            f"SELECT {_FEEDER_AUTOTUNE_TRIAL_COLUMNS} FROM feeder_autotune_trials "
            "WHERE run_id = ? ORDER BY trial_index DESC LIMIT ?",
            (run_id, int(limit)),
        ).fetchall()
    return [
        d for d in (_feederAutotuneTrialRowToDict(r) for r in rows) if d is not None
    ]


def listFeederAutotuneDataset(limit: int = 5000) -> list[dict[str, Any]]:
    """All completed trials across every run — the accumulated tuning dataset."""
    with _connection() as conn:
        rows = conn.execute(
            f"SELECT {_FEEDER_AUTOTUNE_TRIAL_COLUMNS} FROM feeder_autotune_trials "
            "WHERE status = 'done' ORDER BY started_at DESC LIMIT ?",
            (int(limit),),
        ).fetchall()
    return [
        d for d in (_feederAutotuneTrialRowToDict(r) for r in rows) if d is not None
    ]
