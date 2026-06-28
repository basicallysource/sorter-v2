from __future__ import annotations

import os
import re
import sqlite3
import threading
from typing import Any, Optional

from global_config import GlobalConfig

# Local, read-only copy of the profile-builder parts catalog (parts.db from the
# Hive profile_builder). This is a TEMPORARY, additive convenience path: piece
# metadata + BrickLink price guides are already fetched over the network via
# hive_metadata.getMetadataForPieceFromHive; this module serves the same kind of
# data straight off a local SQLite file pointed at by PIECE_METADATA_DB_PATH, so
# pricing shows up without a round-trip to Hive. It never writes and never falls
# back to the network. Path/connection live on GlobalConfig.piece_metadata_db_path.

# BrickLink price-guide values in parts.db are synced in USD (see the Hive
# profile_engine sync: currency_code="USD").
PRICE_CURRENCY = "USD"

# The four BrickLink price-guide buckets, each carrying lots/qty/min/max/avg/wavg.
# inv_* = current open listings ("Items For Sale"); ord_* = the last 6 months of
# completed sales ("Price Guide" / sold). new/used is the item condition.
_PRICE_GROUPS = ("inv_new", "inv_used", "ord_new", "ord_used")

# Headline "moving average price": prefer the 6-month sold, NEW, qty-weighted
# average, then sold-used, then fall back to current listings so we surface
# *something* whenever the guide has any data at all. (Sold is always preferred
# over listed; within each, new before used.)
_MOVING_AVG_PREFERENCE = (
    ("ord_new", "wavg"),
    ("ord_new", "avg"),
    ("ord_used", "wavg"),
    ("ord_used", "avg"),
    ("inv_new", "wavg"),
    ("inv_new", "avg"),
    ("inv_used", "wavg"),
    ("inv_used", "avg"),
)

_conn: Optional[sqlite3.Connection] = None
_conn_failed = False
_conn_lock = threading.Lock()

# Per-process cache keyed by (part_num, color_key). Stores the resolved metadata
# dict, or None for parts the local DB doesn't know about, so repeated event
# serializations for the same piece never re-hit SQLite.
_cache: dict[tuple[str, Optional[int]], Optional[dict[str, Any]]] = {}
_cache_lock = threading.Lock()


def _getConn(gc: GlobalConfig) -> Optional[sqlite3.Connection]:
    global _conn, _conn_failed
    path = getattr(gc, "piece_metadata_db_path", None)
    if not path:
        return None
    with _conn_lock:
        if _conn is not None:
            return _conn
        if _conn_failed:
            return None
        if not os.path.exists(path):
            gc.logger.warn(f"piece metadata db not found at {path}")
            _conn_failed = True
            return None
        try:
            # immutable=1: the file is a static snapshot we only read, so skip
            # all locking/WAL machinery. check_same_thread=False because the
            # backend queries from multiple worker threads; sqlite serializes
            # reads internally and every access here is read-only.
            _conn = sqlite3.connect(
                f"file:{path}?mode=ro&immutable=1", uri=True, check_same_thread=False
            )
            _conn.row_factory = sqlite3.Row
            gc.logger.info(f"piece metadata db opened: {path}")
        except Exception as exc:
            gc.logger.warn(f"piece metadata db open failed ({path}): {exc}")
            _conn_failed = True
            return None
        return _conn


def _parseColorKey(color_id: Optional[str]) -> Optional[int]:
    if color_id is None:
        return None
    text = str(color_id).strip()
    if not text or text == "any_color":
        return None
    try:
        return int(text)
    except ValueError:
        return None


def _priceGroup(row: sqlite3.Row, group: str) -> dict[str, Any]:
    return {
        "lots": row[f"{group}_lots"],
        "qty": row[f"{group}_qty"],
        "min": row[f"{group}_min"],
        "max": row[f"{group}_max"],
        "avg": row[f"{group}_avg"],
        "wavg": row[f"{group}_wavg"],
    }


def _movingAvg(price: dict[str, dict[str, Any]]) -> Optional[float]:
    for group, field in _MOVING_AVG_PREFERENCE:
        value = price.get(group, {}).get(field)
        if isinstance(value, (int, float)) and value > 0:
            return round(float(value), 4)
    return None


def _selectPriceRow(
    rows: list[sqlite3.Row], color_key: Optional[int]
) -> tuple[Optional[sqlite3.Row], bool]:
    if not rows:
        return None, False
    if color_key is not None:
        # Brickognize reports a BrickLink color id; match that first, then fall
        # back to the Rebrickable color id (parts.db carries both per row).
        for field in ("bl_color_id", "rb_color_id"):
            matched = [r for r in rows if r[field] == color_key]
            if matched:
                return matched[0], True
    # No usable color: pick the most-liquid color as the representative price,
    # the same heuristic Hive's profile engine uses to collapse per-color rows.
    best = max(rows, key=lambda r: (r["inv_new_qty"] or 0) + (r["inv_used_qty"] or 0))
    return best, False


# BrickLink printed/patterned-part suffix (e.g. 6201pb01, 3068bpr0223, 970c00px1).
# Stripping it yields the base mold (6201, 3068b, 970c00). Used only as a price
# fallback when the exact printed item has no market data of its own.
_PRINT_SUFFIX_RE = re.compile(r"(pb|pr|px|pat)\d.*$")


def _baseMold(item_no: str) -> Optional[str]:
    base = _PRINT_SUFFIX_RE.sub("", item_no)
    return base if base and base != item_no else None


def _resolvePrice(
    conn: sqlite3.Connection, item_no: str, color_key: Optional[int]
) -> Optional[dict[str, Any]]:
    rows = conn.execute(
        "SELECT * FROM price_guides WHERE item_no = ?", (item_no,)
    ).fetchall()
    row, color_specific = _selectPriceRow(rows, color_key)
    if row is None:
        return None
    price = {group: _priceGroup(row, group) for group in _PRICE_GROUPS}
    return {
        "price": price,
        "color_specific": color_specific,
        "updated_at": row["updated_at"],
        "moving_avg": _movingAvg(price),
    }


def _query(
    conn: sqlite3.Connection, part_num: str, color_key: Optional[int]
) -> Optional[dict[str, Any]]:
    part = conn.execute(
        "SELECT p.part_num, p.name, p.year_from, p.year_to, p.part_img_url, "
        "p.part_url, c.name AS category "
        "FROM parts p LEFT JOIN categories c ON c.id = p.part_cat_id "
        "WHERE p.part_num = ?",
        (part_num,),
    ).fetchone()

    # Resolve the BrickLink item_no that carries the price. Brickognize returns a
    # BrickLink-style catalog number; for plain parts it equals the Rebrickable
    # part_num (e.g. "3001"), but for printed parts it diverges ("6201pb01" vs
    # Rebrickable "6201pr0001") and for figs it's the minifig no ("sw0001a").
    # Two resolution paths so we price as many as possible:
    #   1. The id is a Rebrickable part in `parts`: use its primary BrickLink map.
    #   2. The id is itself a BrickLink item number in `bricklink_items` (the
    #      common case for printed parts that have no matching parts row): price
    #      by it directly. Pricing only needs the item_no, not a parts row.
    item_no: Optional[str] = None
    if part is not None:
        bl_id_row = conn.execute(
            "SELECT item_no FROM part_bricklink_ids WHERE part_num = ? "
            "ORDER BY is_primary DESC LIMIT 1",
            (part_num,),
        ).fetchone()
        if bl_id_row is not None:
            item_no = bl_id_row["item_no"]
    if item_no is None:
        direct = conn.execute(
            "SELECT item_no FROM bricklink_items WHERE item_no = ?", (part_num,)
        ).fetchone()
        if direct is not None:
            item_no = direct["item_no"]

    if part is None and item_no is None:
        return None

    metadata: dict[str, Any] = {
        "source": "local_db",
        "part_num": part["part_num"] if part is not None else part_num,
        "name": part["name"] if part is not None else None,
        "category": part["category"] if part is not None else None,
        "year_from": part["year_from"] if part is not None else None,
        "year_to": part["year_to"] if part is not None else None,
        "img_url": part["part_img_url"] if part is not None else None,
        "part_url": part["part_url"] if part is not None else None,
        "bricklink": None,
        "color_id": color_key,
        "price_currency": PRICE_CURRENCY,
        "price_color_specific": False,
        "price_updated_at": None,
        "moving_avg_price": None,
        "price": None,
        # When the exact printed item has no market data, these name the base
        # mold whose price we substituted (else None). The UI flags it as approx.
        "price_from_base_mold": None,
        "price_from_base_name": None,
    }

    if item_no is None:
        return metadata

    bl_item = conn.execute(
        "SELECT bi.item_no, bi.name, bi.weight, bi.dim_x_studs, bi.dim_y_studs, "
        "bi.year_released, bi.is_obsolete, bc.name AS category "
        "FROM bricklink_items bi LEFT JOIN bricklink_categories bc "
        "ON bc.id = bi.category_id WHERE bi.item_no = ?",
        (item_no,),
    ).fetchone()
    if bl_item is not None:
        metadata["bricklink"] = {
            "item_no": bl_item["item_no"],
            "name": bl_item["name"],
            "weight_g": bl_item["weight"],
            "dim_x_studs": bl_item["dim_x_studs"],
            "dim_y_studs": bl_item["dim_y_studs"],
            "year_released": bl_item["year_released"],
            "is_obsolete": bool(bl_item["is_obsolete"]),
            "category": bl_item["category"],
        }
        # No Rebrickable part row (printed-part id mismatch): fall back to the
        # BrickLink name/category so the piece still has a usable label.
        if metadata["name"] is None:
            metadata["name"] = bl_item["name"]
        if metadata["category"] is None:
            metadata["category"] = bl_item["category"]

    exact = _resolvePrice(conn, item_no, color_key)
    if exact is not None and exact["moving_avg"] is not None:
        chosen = exact
    else:
        # The exact (printed) item has no market data of its own. Fall back to
        # the base mold's price (e.g. 6201pb01 -> 6201) so the piece still gets a
        # number — flagged so the UI can mark it approximate.
        base = _baseMold(item_no)
        base_priced = _resolvePrice(conn, base, color_key) if base else None
        if base_priced is not None and base_priced["moving_avg"] is not None:
            chosen = base_priced
            metadata["price_from_base_mold"] = base
            base_row = conn.execute(
                "SELECT name FROM bricklink_items WHERE item_no = ?", (base,)
            ).fetchone()
            metadata["price_from_base_name"] = base_row["name"] if base_row else None
        else:
            chosen = exact  # may carry an all-empty block (renders as dashes) or None

    if chosen is not None:
        metadata["price"] = chosen["price"]
        # color-specificity only means something for the exact item, not a
        # substituted base-mold price.
        metadata["price_color_specific"] = (
            chosen["color_specific"] if metadata["price_from_base_mold"] is None else False
        )
        metadata["price_updated_at"] = chosen["updated_at"]
        metadata["moving_avg_price"] = chosen["moving_avg"]

    return metadata


def getLocalPieceMetadata(
    gc: GlobalConfig, part_num: Optional[str], color_id: Optional[str] = None
) -> Optional[dict[str, Any]]:
    if not part_num:
        return None
    color_key = _parseColorKey(color_id)
    cache_key = (part_num, color_key)
    with _cache_lock:
        if cache_key in _cache:
            return _cache[cache_key]

    conn = _getConn(gc)
    if conn is None:
        return None

    try:
        result = _query(conn, part_num, color_key)
    except Exception as exc:
        gc.logger.warn(f"piece metadata lookup failed for {part_num}: {exc}")
        return None

    with _cache_lock:
        _cache[cache_key] = result
    return result
