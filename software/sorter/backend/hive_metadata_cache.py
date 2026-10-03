from __future__ import annotations

import json
import sqlite3
import time
from typing import Any

import db

# Write-through cache of per-piece metadata + pricing fetched from Hive
# (hive_metadata.py). Keyed by (part_num, color_id); payload_json is the full
# flattened metadata dict (NULL for price-only rows filled by the batch price
# path). cached_at lets us serve offline and optionally refresh stale entries.
# Disposable — safe to wipe.


def _createTables(conn: sqlite3.Connection) -> None:
    conn.execute(
        "CREATE TABLE IF NOT EXISTS hive_part_metadata_cache ("
        "part_num TEXT NOT NULL, "
        "color_id TEXT NOT NULL, "
        "payload_json TEXT, "
        "moving_avg_price REAL, "
        "cached_at REAL NOT NULL, "
        "PRIMARY KEY(part_num, color_id)"
        ")"
    )


def _connection():
    return db.connect(_createTables)


def _normalize_cache_color_id(color_id: Any) -> str:
    if color_id is None:
        return "any_color"
    text = str(color_id).strip()
    return text if text and text != "any_color" else "any_color"


def get_cached_part_metadata(
    part_num: str, color_id: Any
) -> tuple[dict[str, Any] | None, float | None, float | None]:
    """Return (payload, moving_avg_price, cached_at) for a (part, color) from the
    Hive metadata cache. payload is None when only a price-only row exists (or on
    a full miss); cached_at is None only on a full miss."""
    if not part_num:
        return None, None, None
    with _connection() as conn:
        row = conn.execute(
            "SELECT payload_json, moving_avg_price, cached_at "
            "FROM hive_part_metadata_cache WHERE part_num = ? AND color_id = ?",
            (part_num, _normalize_cache_color_id(color_id)),
        ).fetchone()
    if row is None:
        return None, None, None
    payload = None
    if row["payload_json"]:
        try:
            payload = json.loads(str(row["payload_json"]))
        except (TypeError, ValueError):
            payload = None
    moving_avg = row["moving_avg_price"]
    return payload, (float(moving_avg) if isinstance(moving_avg, (int, float)) else None), float(row["cached_at"])


def put_cached_part_metadata(
    part_num: str, color_id: Any, payload: dict[str, Any] | None, moving_avg_price: float | None
) -> None:
    if not part_num:
        return
    with _connection() as conn:
        conn.execute(
            "INSERT INTO hive_part_metadata_cache"
            "(part_num, color_id, payload_json, moving_avg_price, cached_at) "
            "VALUES(?, ?, ?, ?, ?) "
            "ON CONFLICT(part_num, color_id) DO UPDATE SET "
            "payload_json = excluded.payload_json, "
            "moving_avg_price = excluded.moving_avg_price, "
            "cached_at = excluded.cached_at",
            (
                part_num,
                _normalize_cache_color_id(color_id),
                json.dumps(payload) if payload is not None else None,
                float(moving_avg_price) if isinstance(moving_avg_price, (int, float)) else None,
                time.time(),
            ),
        )
        conn.commit()


def get_cached_part_prices(
    pairs: list[tuple[str | None, Any]]
) -> dict[tuple[str, str], tuple[float | None, float]]:
    """Bulk-read moving-average prices for many (part_num, color_id) pairs.
    Returns {(part_num, normalized_color_id): (moving_avg_price, cached_at)} for
    the pairs present in the cache."""
    out: dict[tuple[str, str], tuple[float | None, float]] = {}
    with _connection() as conn:
        for part_num, color_id in pairs:
            if not part_num:
                continue
            norm = _normalize_cache_color_id(color_id)
            row = conn.execute(
                "SELECT moving_avg_price, cached_at FROM hive_part_metadata_cache "
                "WHERE part_num = ? AND color_id = ?",
                (part_num, norm),
            ).fetchone()
            if row is None:
                continue
            mv = row["moving_avg_price"]
            out[(part_num, norm)] = (
                float(mv) if isinstance(mv, (int, float)) else None,
                float(row["cached_at"]),
            )
    return out


def put_cached_part_prices(rows: list[tuple[str | None, Any, float | None]]) -> None:
    """Bulk write-through of price-only cache rows (payload_json left untouched on
    an existing full entry)."""
    valid = [r for r in rows if r[0]]
    if not valid:
        return
    now = time.time()
    with _connection() as conn:
        for part_num, color_id, moving_avg_price in valid:
            conn.execute(
                "INSERT INTO hive_part_metadata_cache"
                "(part_num, color_id, payload_json, moving_avg_price, cached_at) "
                "VALUES(?, ?, NULL, ?, ?) "
                "ON CONFLICT(part_num, color_id) DO UPDATE SET "
                "moving_avg_price = excluded.moving_avg_price, "
                "cached_at = excluded.cached_at",
                (
                    part_num,
                    _normalize_cache_color_id(color_id),
                    float(moving_avg_price) if isinstance(moving_avg_price, (int, float)) else None,
                    now,
                ),
            )
        conn.commit()
