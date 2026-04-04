"""Rebrickable set search and inventory caching via the profile-builder SQLite DB."""

from __future__ import annotations

import json
import sqlite3
from typing import Any

import requests


_SETS_TABLE_DDL = """
CREATE TABLE IF NOT EXISTS rebrickable_sets (
    set_num   TEXT PRIMARY KEY,
    name      TEXT,
    year      INTEGER,
    num_parts INTEGER,
    set_img_url TEXT,
    theme_id  INTEGER,
    raw_json  TEXT,
    fetched_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
)
"""

_INVENTORY_TABLE_DDL = """
CREATE TABLE IF NOT EXISTS rebrickable_set_inventory (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    set_num    TEXT NOT NULL,
    part_num   TEXT NOT NULL,
    color_id   INTEGER NOT NULL,
    quantity   INTEGER NOT NULL DEFAULT 1,
    is_spare   INTEGER NOT NULL DEFAULT 0,
    element_id TEXT,
    part_name  TEXT,
    part_img_url TEXT,
    color_name TEXT,
    color_rgb  TEXT,
    UNIQUE(set_num, part_num, color_id, is_spare)
)
"""


def _ensure_tables(conn: sqlite3.Connection) -> None:
    conn.execute(_SETS_TABLE_DDL)
    conn.execute(_INVENTORY_TABLE_DDL)
    conn.commit()


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def search_sets(api_key: str, query: str) -> list[dict[str, Any]]:
    """Search Rebrickable for LEGO sets matching *query*."""
    if not api_key:
        return []
    url = "https://rebrickable.com/api/v3/lego/sets/"
    params = {"key": api_key, "search": query, "page_size": 20, "ordering": "-year"}
    resp = requests.get(url, params=params, timeout=15)
    resp.raise_for_status()
    results = resp.json().get("results", [])
    return [
        {
            "set_num": s["set_num"],
            "name": s["name"],
            "year": s.get("year"),
            "num_parts": s.get("num_parts"),
            "set_img_url": s.get("set_img_url"),
            "theme_id": s.get("theme_id"),
        }
        for s in results
    ]


def fetch_set_inventory(conn: sqlite3.Connection, api_key: str, set_num: str) -> None:
    """Fetch a set's metadata and full inventory from Rebrickable and cache locally."""
    _ensure_tables(conn)
    if not api_key:
        return

    # Fetch set metadata
    url = f"https://rebrickable.com/api/v3/lego/sets/{set_num}/"
    resp = requests.get(url, params={"key": api_key}, timeout=15)
    resp.raise_for_status()
    data = resp.json()

    conn.execute(
        """INSERT OR REPLACE INTO rebrickable_sets
           (set_num, name, year, num_parts, set_img_url, theme_id, raw_json, fetched_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)""",
        (
            data["set_num"],
            data["name"],
            data.get("year"),
            data.get("num_parts"),
            data.get("set_img_url"),
            data.get("theme_id"),
            json.dumps(data),
        ),
    )

    # Clear old inventory rows for this set
    conn.execute("DELETE FROM rebrickable_set_inventory WHERE set_num = ?", (set_num,))

    # Fetch inventory (paginated)
    inv_url = f"https://rebrickable.com/api/v3/lego/sets/{set_num}/parts/"
    page = 1
    while True:
        r = requests.get(inv_url, params={"key": api_key, "page": page, "page_size": 500}, timeout=15)
        r.raise_for_status()
        body = r.json()
        for item in body.get("results", []):
            part = item.get("part", {})
            color = item.get("color", {})
            conn.execute(
                """INSERT OR REPLACE INTO rebrickable_set_inventory
                   (set_num, part_num, color_id, quantity, is_spare, element_id,
                    part_name, part_img_url, color_name, color_rgb)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    set_num,
                    part.get("part_num", ""),
                    color.get("id", 0),
                    item.get("quantity", 1),
                    1 if item.get("is_spare") else 0,
                    item.get("element_id"),
                    part.get("name"),
                    part.get("part_img_url"),
                    color.get("name"),
                    color.get("rgb"),
                ),
            )
        if not body.get("next"):
            break
        page += 1

    conn.commit()


def get_cached_set(conn: sqlite3.Connection, set_num: str) -> dict[str, Any] | None:
    """Return cached set metadata or None."""
    _ensure_tables(conn)
    row = conn.execute(
        "SELECT set_num, name, year, num_parts, set_img_url, theme_id FROM rebrickable_sets WHERE set_num = ?",
        (set_num,),
    ).fetchone()
    if row is None:
        return None
    return {
        "set_num": row[0],
        "name": row[1],
        "year": row[2],
        "num_parts": row[3],
        "set_img_url": row[4],
        "theme_id": row[5],
    }


def get_cached_inventory(conn: sqlite3.Connection, set_num: str) -> list[dict[str, Any]]:
    """Return cached inventory parts for a set."""
    _ensure_tables(conn)
    rows = conn.execute(
        """SELECT part_num, color_id, quantity, is_spare, element_id,
                  part_name, part_img_url, color_name, color_rgb
           FROM rebrickable_set_inventory WHERE set_num = ?""",
        (set_num,),
    ).fetchall()
    return [
        {
            "part_num": r[0],
            "color_id": r[1],
            "quantity": r[2],
            "is_spare": bool(r[3]),
            "element_id": r[4],
            "part_name": r[5],
            "part_img_url": r[6],
            "color_name": r[7],
            "color_rgb": r[8],
        }
        for r in rows
    ]
