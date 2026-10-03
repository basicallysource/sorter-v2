from __future__ import annotations

import json
import sqlite3
import time
import uuid
from typing import Any

import db

# Every chute calibration taken (section count, width and offset, and the
# measurements behind them), with the one locked in marked active. The geometry
# the chute runs with lives in machine.toml; locking in an instance writes it
# there (server/routers/chute.py).

_CHUTE_CALIBRATION_COLUMNS = (
    "id, created_at, label, num_sections, section_width_deg, "
    "first_section_offset_deg, measurements, is_active, updated_at"
)


def _createTables(conn: sqlite3.Connection) -> None:
    conn.execute(
        "CREATE TABLE IF NOT EXISTS chute_calibrations ("
        "id TEXT PRIMARY KEY, "
        "created_at REAL NOT NULL, "
        "label TEXT, "
        "num_sections INTEGER NOT NULL, "
        "section_width_deg REAL NOT NULL, "
        "first_section_offset_deg REAL NOT NULL, "
        "measurements TEXT, "
        "is_active INTEGER NOT NULL DEFAULT 0, "
        "updated_at REAL NOT NULL"
        ")"
    )


def _connection():
    return db.connect(_createTables)


def _chuteCalibrationRowToDict(row: sqlite3.Row | None) -> dict[str, Any] | None:
    if row is None:
        return None
    measurements: Any = None
    raw = row["measurements"]
    if isinstance(raw, str) and raw:
        try:
            measurements = json.loads(raw)
        except json.JSONDecodeError:
            measurements = None
    return {
        "id": row["id"],
        "created_at": row["created_at"],
        "label": row["label"],
        "num_sections": row["num_sections"],
        "section_width_deg": row["section_width_deg"],
        "first_section_offset_deg": row["first_section_offset_deg"],
        "measurements": measurements,
        "is_active": bool(row["is_active"]),
        "updated_at": row["updated_at"],
    }


def recordChuteCalibrationInstance(
    *,
    label: str | None,
    num_sections: int,
    section_width_deg: float,
    first_section_offset_deg: float,
    measurements: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    calibration_id = str(uuid.uuid4())
    now = time.time()
    measurements_json = json.dumps(measurements) if measurements is not None else None
    with _connection() as conn:
        conn.execute("UPDATE chute_calibrations SET is_active = 0 WHERE is_active = 1")
        conn.execute(
            f"INSERT INTO chute_calibrations({_CHUTE_CALIBRATION_COLUMNS}) "
            "VALUES(?, ?, ?, ?, ?, ?, ?, 1, ?)",
            (
                calibration_id,
                now,
                label,
                int(num_sections),
                float(section_width_deg),
                float(first_section_offset_deg),
                measurements_json,
                now,
            ),
        )
        conn.commit()
    return getChuteCalibrationInstance(calibration_id)


def listChuteCalibrationInstances(limit: int = 100) -> list[dict[str, Any]]:
    with _connection() as conn:
        rows = conn.execute(
            f"SELECT {_CHUTE_CALIBRATION_COLUMNS} FROM chute_calibrations "
            "ORDER BY created_at DESC LIMIT ?",
            (int(limit),),
        ).fetchall()
    return [d for d in (_chuteCalibrationRowToDict(r) for r in rows) if d is not None]


def getChuteCalibrationInstance(calibration_id: str) -> dict[str, Any] | None:
    with _connection() as conn:
        row = conn.execute(
            f"SELECT {_CHUTE_CALIBRATION_COLUMNS} FROM chute_calibrations WHERE id = ?",
            (calibration_id,),
        ).fetchone()
    return _chuteCalibrationRowToDict(row)


def activateChuteCalibrationInstance(calibration_id: str) -> dict[str, Any] | None:
    now = time.time()
    with _connection() as conn:
        existing = conn.execute(
            "SELECT id FROM chute_calibrations WHERE id = ?", (calibration_id,)
        ).fetchone()
        if existing is None:
            return None
        conn.execute("UPDATE chute_calibrations SET is_active = 0 WHERE is_active = 1")
        conn.execute(
            "UPDATE chute_calibrations SET is_active = 1, updated_at = ? WHERE id = ?",
            (now, calibration_id),
        )
        conn.commit()
    return getChuteCalibrationInstance(calibration_id)


def deleteChuteCalibrationInstance(calibration_id: str) -> bool:
    with _connection() as conn:
        cur = conn.execute(
            "DELETE FROM chute_calibrations WHERE id = ?", (calibration_id,)
        )
        conn.commit()
        return cur.rowcount > 0
