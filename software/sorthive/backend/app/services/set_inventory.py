"""Rebrickable set search and inventory caching via the profile-builder SQLite DB."""

from __future__ import annotations

import json
import re
import sqlite3
from datetime import datetime, UTC
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

_YEAR_RE = re.compile(r"\b(19\d{2}|20\d{2}|21\d{2})\b")

_theme_records_cache: list[dict[str, Any]] | None = None
_theme_match_cache: dict[str, list[int]] = {}
_theme_children_cache: dict[int | None, list[int]] = {}


def _normalize_theme_key(value: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9]+", " ", value.lower())).strip()


def _load_themes(api_key: str) -> list[dict[str, Any]]:
    global _theme_records_cache, _theme_children_cache

    if _theme_records_cache is not None:
        return _theme_records_cache

    records: list[dict[str, Any]] = []
    page = 1
    while True:
        resp = requests.get(
            "https://rebrickable.com/api/v3/lego/themes/",
            params={"key": api_key, "page_size": 1000, "page": page},
            timeout=15,
        )
        resp.raise_for_status()
        payload = resp.json()
        for raw_theme in payload.get("results", []):
            theme_id = raw_theme.get("id")
            if theme_id is None:
                continue
            record = {
                "id": int(theme_id),
                "name": str(raw_theme.get("name") or ""),
                "parent_id": raw_theme.get("parent_id"),
                "key": _normalize_theme_key(str(raw_theme.get("name") or "")),
            }
            records.append(record)
            parent_id = record["parent_id"]
            _theme_children_cache.setdefault(parent_id, []).append(record["id"])
        if not payload.get("next"):
            break
        page += 1

    _theme_records_cache = records
    _theme_match_cache.clear()
    return records


def _collect_descendant_theme_ids(theme_id: int, collected: set[int]) -> None:
    if theme_id in collected:
        return
    collected.add(theme_id)
    for child_id in _theme_children_cache.get(theme_id, []):
        _collect_descendant_theme_ids(child_id, collected)


def _theme_matches_query(query_key: str, theme_key: str) -> bool:
    if not query_key or not theme_key:
        return False
    if query_key == theme_key:
        return True

    query_tokens = query_key.split()
    theme_tokens = theme_key.split()
    if not query_tokens or not theme_tokens:
        return False

    if len(query_tokens) == 1:
        return query_tokens[0] in theme_tokens

    return theme_tokens[: len(query_tokens)] == query_tokens


def _resolve_theme_ids(api_key: str, query: str) -> list[int]:
    """Resolve *query* to exact or close theme matches, including descendants."""
    key = _normalize_theme_key(query)
    if not key:
        return []
    if key in _theme_match_cache:
        return _theme_match_cache[key]

    themes = _load_themes(api_key)
    exact_matches = [theme["id"] for theme in themes if theme["key"] == key]
    matched_theme_ids = exact_matches
    if not matched_theme_ids:
        matched_theme_ids = [
            theme["id"]
            for theme in themes
            if _theme_matches_query(key, theme["key"])
        ]

    resolved_ids: set[int] = set()
    for theme_id in matched_theme_ids[:12]:
        _collect_descendant_theme_ids(theme_id, resolved_ids)

    result = sorted(resolved_ids)
    _theme_match_cache[key] = result
    return result


def _infer_year_filters(
    query: str,
    min_year: int | None,
    max_year: int | None,
) -> tuple[str, int | None, int | None]:
    years = [
        int(match)
        for match in _YEAR_RE.findall(query)
        if 1950 <= int(match) <= datetime.now(UTC).year + 1
    ]

    inferred_min_year = min_year
    inferred_max_year = max_year
    if years and min_year is None and max_year is None:
        inferred_min_year = min(years)
        inferred_max_year = max(years)

    cleaned_query = _YEAR_RE.sub(" ", query)
    cleaned_query = re.sub(r"\s+", " ", cleaned_query).strip(" -_,")
    return cleaned_query or query.strip(), inferred_min_year, inferred_max_year


def _normalize_set_entry(raw_set: dict[str, Any]) -> dict[str, Any]:
    return {
        "set_num": raw_set["set_num"],
        "name": raw_set["name"],
        "year": raw_set.get("year"),
        "num_parts": raw_set.get("num_parts"),
        "set_img_url": raw_set.get("set_img_url"),
        "theme_id": raw_set.get("theme_id"),
    }


def _fetch_sets(api_key: str, *, params: dict[str, Any]) -> list[dict[str, Any]]:
    url = "https://rebrickable.com/api/v3/lego/sets/"
    page = 1
    results: list[dict[str, Any]] = []
    while True:
        resp = requests.get(url, params={**params, "key": api_key, "page": page}, timeout=15)
        resp.raise_for_status()
        payload = resp.json()
        results.extend(_normalize_set_entry(raw_set) for raw_set in payload.get("results", []))
        if not payload.get("next"):
            break
        page += 1
    return results


def search_sets(
    api_key: str,
    query: str,
    *,
    min_year: int | None = None,
    max_year: int | None = None,
    min_parts: int = 1,
) -> list[dict[str, Any]]:
    """Search Rebrickable for LEGO sets matching *query*.

    If *query* matches a theme name exactly, searches by theme_id instead of
    text search — this is necessary because many sets don't include the theme
    name in their title. Year filtering is always applied locally because the
    Rebrickable API ignores min_year/max_year when combined with ``search``.
    """
    if not api_key:
        return []

    normalized_query, min_year, max_year = _infer_year_filters(query, min_year, max_year)

    params: dict[str, Any] = {
        "page_size": 100,
        "ordering": "-year",
    }
    if min_parts > 0:
        params["min_parts"] = min_parts

    if min_year is not None:
        params["min_year"] = min_year
    if max_year is not None:
        params["max_year"] = max_year

    theme_ids = _resolve_theme_ids(api_key, normalized_query)
    if theme_ids:
        out: list[dict[str, Any]] = []
        for theme_id in theme_ids:
            out.extend(_fetch_sets(api_key, params={**params, "theme_id": theme_id}))
    else:
        out = _fetch_sets(api_key, params={**params, "search": normalized_query})

    deduped: dict[str, dict[str, Any]] = {}
    for lego_set in out:
        set_num = lego_set.get("set_num")
        if not set_num:
            continue
        deduped[str(set_num)] = lego_set

    filtered = list(deduped.values())
    if min_year is not None:
        filtered = [lego_set for lego_set in filtered if lego_set.get("year") is not None and lego_set["year"] >= min_year]
    if max_year is not None:
        filtered = [lego_set for lego_set in filtered if lego_set.get("year") is not None and lego_set["year"] <= max_year]

    filtered.sort(key=lambda lego_set: (lego_set.get("year") or 0, lego_set.get("name") or ""), reverse=True)
    return filtered


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
