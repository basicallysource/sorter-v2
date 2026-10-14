"""LEGO sets: Rebrickable's themes, sets and set inventories, from its CSV downloads.

The "sets" catalog sync imports the downloads whole into parts.db
(migration 011); set search and a set's inventory are queries on those
tables.
"""

from __future__ import annotations

import re
import sqlite3
from collections.abc import Callable
from datetime import datetime, UTC
from typing import Any

from app.services.rebrickable_downloads import downloads, rows

# Each table and the CSV it is a copy of, in the order they are imported.
_IMPORTS = (
    ("rebrickable_themes", "themes", ("id", "name", "parent_id")),
    ("rebrickable_sets", "sets", ("set_num", "name", "year", "theme_id", "num_parts", "img_url")),
    ("rebrickable_inventories", "inventories", ("id", "version", "set_num")),
    (
        "rebrickable_inventory_parts",
        "inventory_parts",
        ("inventory_id", "part_num", "color_id", "quantity", "is_spare", "img_url"),
    ),
)


# ---------------------------------------------------------------------------
# Import


def import_sets(db_path: str, progress_fn: Callable[[int, int, str], None] | None = None) -> dict[str, int]:
    """Replace the themes, sets and inventories with Rebrickable's current
    downloads. Everything is downloaded first and then written in one
    transaction, on a connection of its own, so a failed download changes
    nothing and readers see the old tables until the new ones are complete.
    Returns the rows imported per table."""
    counts: dict[str, int] = {}
    if progress_fn:
        progress_fn(0, len(_IMPORTS), "Downloading Rebrickable's sets")
    with downloads(*(name for _, name, _ in _IMPORTS)) as files:
        conn = sqlite3.connect(db_path, timeout=60)
        try:
            with conn:
                for index, (table, name, columns) in enumerate(_IMPORTS):
                    if progress_fn:
                        progress_fn(index, len(_IMPORTS), f"Importing {name}")
                    conn.execute(f"DELETE FROM {table}")
                    placeholders = ", ".join("?" for _ in columns)
                    cursor = conn.executemany(
                        f"INSERT INTO {table} ({', '.join(columns)}) VALUES ({placeholders})",
                        rows(files[name], columns),
                    )
                    counts[table] = cursor.rowcount
        finally:
            conn.close()
    return counts


# ---------------------------------------------------------------------------
# Search

_YEAR_RE = re.compile(r"\b(19\d{2}|20\d{2}|21\d{2})\b")


def _normalize_theme_key(value: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9]+", " ", value.lower())).strip()


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


def _resolve_theme_ids(conn: sqlite3.Connection, query: str) -> list[int]:
    """Resolve *query* to exact or close theme matches, including descendants."""
    key = _normalize_theme_key(query)
    if not key:
        return []

    themes = [
        {"id": row[0], "parent_id": row[1], "key": _normalize_theme_key(row[2])}
        for row in conn.execute("SELECT id, parent_id, name FROM rebrickable_themes")
    ]
    children: dict[int | None, list[int]] = {}
    for theme in themes:
        children.setdefault(theme["parent_id"], []).append(theme["id"])

    matched = [theme["id"] for theme in themes if theme["key"] == key]
    if not matched:
        matched = [theme["id"] for theme in themes if _theme_matches_query(key, theme["key"])]

    resolved: set[int] = set()
    pending = matched[:12]
    while pending:
        theme_id = pending.pop()
        if theme_id not in resolved:
            resolved.add(theme_id)
            pending.extend(children.get(theme_id, []))
    return sorted(resolved)


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


def _set_entry(row: tuple[Any, ...]) -> dict[str, Any]:
    return {
        "set_num": row[0],
        "name": row[1],
        "year": row[2],
        "theme_id": row[3],
        "num_parts": row[4],
        "img_url": row[5],
    }


_SET_COLUMNS = "set_num, name, year, theme_id, num_parts, img_url"


def search_sets(
    conn: sqlite3.Connection,
    query: str,
    *,
    min_year: int | None = None,
    max_year: int | None = None,
    min_parts: int = 1,
    limit: int = 20,
) -> list[dict[str, Any]]:
    """LEGO sets matching *query*, newest first.

    A query that names a theme ("Town Plan", "Star Wars") finds the sets in
    that theme and its sub-themes, since many sets do not carry their theme's
    name. Anything else matches sets whose name or number holds every word.
    A year in the query ("castle 1984") becomes a year filter.
    """
    normalized_query, min_year, max_year = _infer_year_filters(query, min_year, max_year)

    where = ["num_parts >= ?"]
    params: list[Any] = [min_parts]
    if min_year is not None:
        where.append("year >= ?")
        params.append(min_year)
    if max_year is not None:
        where.append("year <= ?")
        params.append(max_year)

    theme_ids = _resolve_theme_ids(conn, normalized_query)
    if theme_ids:
        where.append(f"theme_id IN ({', '.join('?' for _ in theme_ids)})")
        params.extend(theme_ids)
    else:
        for word in normalized_query.split():
            where.append("(name LIKE ? OR set_num LIKE ?)")
            params.extend([f"%{word}%", f"{word}%"])

    rows = conn.execute(
        f"SELECT {_SET_COLUMNS} FROM rebrickable_sets WHERE {' AND '.join(where)} "
        "ORDER BY year DESC, name DESC LIMIT ?",
        [*params, limit],
    ).fetchall()
    return [_set_entry(row) for row in rows]


# ---------------------------------------------------------------------------
# One set


def get_set(conn: sqlite3.Connection, set_num: str) -> dict[str, Any] | None:
    """A set's details, or None when Rebrickable has no such set."""
    row = conn.execute(f"SELECT {_SET_COLUMNS} FROM rebrickable_sets WHERE set_num = ?", (set_num,)).fetchone()
    return _set_entry(row) if row else None


def get_set_inventory(conn: sqlite3.Connection, set_num: str) -> list[dict[str, Any]]:
    """The parts of a set's first inventory, spares flagged. Not the parts of
    its minifigures, as Rebrickable lists a set's parts. Names come from the
    parts catalog (None for a part it does not have yet)."""
    rows = conn.execute(
        """SELECT ip.part_num, ip.color_id, ip.quantity, ip.is_spare,
                  p.name, COALESCE(ip.img_url, p.part_img_url), c.name, c.rgb
           FROM rebrickable_inventory_parts ip
           LEFT JOIN parts p ON p.part_num = ip.part_num
           LEFT JOIN colors c ON c.id = ip.color_id
           WHERE ip.inventory_id = (
               SELECT id FROM rebrickable_inventories WHERE set_num = ? ORDER BY version LIMIT 1
           )""",
        (set_num,),
    ).fetchall()
    return [
        {
            "part_num": r[0],
            "color_id": r[1],
            "quantity": r[2],
            "is_spare": bool(r[3]),
            "part_name": r[4],
            "part_img_url": r[5],
            "color_name": r[6],
            "color_rgb": r[7],
        }
        for r in rows
    ]


def set_count(conn: sqlite3.Connection) -> int:
    return int(conn.execute("SELECT COUNT(*) FROM rebrickable_sets").fetchone()[0])
