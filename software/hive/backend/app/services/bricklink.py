from __future__ import annotations

import sqlite3
import time
from typing import Any, Sequence

import requests

# BLA is the only BrickLink API we hold a credential for (a single `api_key`
# query param — no OAuth consumer/token pair), so everything here goes through
# it. Docs are not public; the request/response shapes below were derived from
# the price sync that has been populating parts.db since 2026-06.
BLA_BASE_URL = "https://api.bricklink.com/api/affiliate/v1"
PRICE_GUIDE_BATCH_URL = f"{BLA_BASE_URL}/price_guide_batch"
PRICE_GUIDE_BATCH_SIZE = 500
PRICE_GUIDE_THROTTLE_SECONDS = 0.5
PRICE_GUIDE_RETRIES = 5


class BrickLinkError(RuntimeError):
    pass


def fetch_price_guide_batch(
    api_key: str,
    combos: Sequence[tuple[str, int, str]],
    currency_code: str = "USD",
    timeout: int = 30,
) -> list[dict[str, Any]]:
    """Price guide for up to PRICE_GUIDE_BATCH_SIZE (item_no, bl_color_id, type)
    combos in one POST. Returns the raw `data` entries, each shaped:

        {"item": {"no": "3623", "type": "PART"}, "color_id": 11,
         "inventory_new":  {"unit_quantity", "total_quantity", "min_price",
                            "max_price", "total_price", "total_qty_price"},
         "inventory_used": {...}, "ordered_new": {...}, "ordered_used": {...}}

    Combos it can't price (unknown item, item/color pair that doesn't exist) are
    dropped from the response rather than reported — a batch of 2 with one bogus
    item_no comes back with 1 entry and no error. Always key the response back by
    (item_no, color_id) instead of zipping it against the request.

    Beware the quantity fields: despite the names, `unit_quantity` is the number
    of individual pieces listed and `total_quantity` is the number of lots — the
    opposite of what BrickLink's storefront API documents. Confirmed against a
    live call (Plate 1x3 in Light Bluish Gray: unit_quantity 679255,
    total_quantity 3999; the reverse reading would mean 679k separate lots of one
    plate). The inventory lot count also saturates around 4000, so `*_quantity`
    on a common part is a sample ceiling, not a true total — rank by pieces."""
    if not api_key:
        raise BrickLinkError("BLA_API_KEY is not configured")
    if len(combos) > PRICE_GUIDE_BATCH_SIZE:
        raise BrickLinkError(f"batch of {len(combos)} exceeds {PRICE_GUIDE_BATCH_SIZE}")

    body = [
        {"color_id": color_id, "item": {"no": item_no, "type": item_type}}
        for item_no, color_id, item_type in combos
    ]
    last_exc: Exception | None = None
    for attempt in range(PRICE_GUIDE_RETRIES):
        try:
            resp = requests.post(
                PRICE_GUIDE_BATCH_URL,
                params={
                    "currency_code": currency_code,
                    "precision": "4",
                    "vat_type": "0",
                    "api_key": api_key,
                },
                json=body,
                timeout=timeout,
            )
            resp.raise_for_status()
            return resp.json().get("data", [])
        except requests.exceptions.RequestException as exc:
            last_exc = exc
            if attempt == PRICE_GUIDE_RETRIES - 1:
                break
            time.sleep(2**attempt)
    raise BrickLinkError(f"price_guide_batch failed: {last_exc}")


_live_cache: dict[tuple[str, int], tuple[float, dict[str, int]]] = {}
LIVE_CACHE_TTL_SECONDS = 6 * 3600
LIVE_CACHE_MAX_ENTRIES = 50_000


def _entry_quantities(entry: dict[str, Any]) -> dict[str, int]:
    new = entry.get("inventory_new") or {}
    used = entry.get("inventory_used") or {}
    qty_new = int(new.get("unit_quantity") or 0)
    qty_used = int(used.get("unit_quantity") or 0)
    return {
        "qty": qty_new + qty_used,
        "qty_new": qty_new,
        "qty_used": qty_used,
        "lots": int(new.get("total_quantity") or 0) + int(used.get("total_quantity") or 0),
    }


def fetch_color_quantities(
    api_key: str,
    item_no: str,
    color_ids: Sequence[int],
    item_type: str = "PART",
    now: float | None = None,
) -> dict[int, dict[str, int]]:
    """Live pieces-for-sale for specific colors of one item, TTL-cached in memory.

    The cached price guide in parts.db can't answer this: it only holds the combos
    BrickStore's import happened to know about (~1.5 colors per item, skewed to
    pre-2004 catalog colors), so the modern color a labeler is deciding between is
    usually absent — 2877 in Dark Bluish Gray and 3069 in Reddish Brown are both
    missing from it while the API reports 387k and 366k pieces for sale."""
    now = time.time() if now is None else now
    out: dict[int, dict[str, int]] = {}
    stale: list[int] = []
    for color_id in color_ids:
        hit = _live_cache.get((item_no, color_id))
        if hit and now - hit[0] < LIVE_CACHE_TTL_SECONDS:
            out[color_id] = hit[1]
        else:
            stale.append(color_id)

    for start in range(0, len(stale), PRICE_GUIDE_BATCH_SIZE):
        chunk = stale[start:start + PRICE_GUIDE_BATCH_SIZE]
        entries = fetch_price_guide_batch(api_key, [(item_no, cid, item_type) for cid in chunk])
        priced = {
            int(e["color_id"]): _entry_quantities(e)
            for e in entries
            if e.get("item", {}).get("no") == item_no and e.get("color_id") is not None
        }
        # Colors the API declined to price aren't sold in that color — cache the
        # zero too, or every page view re-asks for the same known-empty combos.
        for color_id in chunk:
            quantities = priced.get(color_id, {"qty": 0, "qty_new": 0, "qty_used": 0, "lots": 0})
            _live_cache[(item_no, color_id)] = (now, quantities)
            out[color_id] = quantities

    if len(_live_cache) > LIVE_CACHE_MAX_ENTRIES:
        for key in [k for k, (at, _) in _live_cache.items() if now - at >= LIVE_CACHE_TTL_SECONDS]:
            del _live_cache[key]
        # Still oversized means heavy live traffic inside one TTL window; drop the
        # oldest half rather than let a long-lived process grow without bound.
        if len(_live_cache) > LIVE_CACHE_MAX_ENTRIES:
            oldest = sorted(_live_cache, key=lambda k: _live_cache[k][0])
            for key in oldest[: len(_live_cache) // 2]:
                del _live_cache[key]
    return out


def resolve_item_no(conn: sqlite3.Connection, part_id: str) -> str | None:
    """Machine piece part_ids come from Brickognize, which speaks BrickLink item
    numbers — so a direct hit is the common case. The part_num fallbacks cover
    pieces whose id came from a Rebrickable-numbered source instead."""
    row = conn.execute("SELECT item_no FROM bricklink_items WHERE item_no = ?", (part_id,)).fetchone()
    if row:
        return str(row[0])
    row = conn.execute(
        "SELECT item_no FROM part_bricklink_ids WHERE part_num = ? ORDER BY is_primary DESC LIMIT 1",
        (part_id,),
    ).fetchone()
    if row:
        return str(row[0])
    row = conn.execute("SELECT item_no FROM bricklink_items WHERE part_num = ? LIMIT 1", (part_id,)).fetchone()
    return str(row[0]) if row else None


def part_color_availability(conn: sqlite3.Connection, part_id: str, limit: int = 24) -> dict[str, Any]:
    """Which colors this part is actually stocked in on BrickLink, ranked by how
    many pieces are for sale. Reads the cached price guide in parts.db
    rather than calling the API — the whole catalog is already synced there, and
    a labeling page cannot wait on a network round trip per piece.

    `inv_*_lots` / `inv_*_qty` in price_guides are stored under the API's own
    (inverted) field names, so the pieces-for-sale count lives in the `_lots`
    column. See fetch_price_guide_batch."""
    item_no = resolve_item_no(conn, part_id)
    if item_no is None:
        return {"part_id": part_id, "item_no": None, "updated_at": None, "total_qty": 0, "items": []}

    rows = conn.execute(
        "SELECT bl_color_id, inv_new_lots, inv_new_qty, inv_used_lots, inv_used_qty, updated_at "
        "FROM price_guides WHERE item_no = ?",
        (item_no,),
    ).fetchall()

    items: list[dict[str, Any]] = []
    updated_at: str | None = None
    for bl_color_id, new_qty, new_lots, used_qty, used_lots, row_updated_at in rows:
        qty = int(new_qty or 0) + int(used_qty or 0)
        if qty <= 0:
            continue  # not stocked in this color right now — nothing to calibrate against
        items.append(
            {
                "color_id": int(bl_color_id),
                "qty": qty,
                "qty_new": int(new_qty or 0),
                "qty_used": int(used_qty or 0),
                "lots": int(new_lots or 0) + int(used_lots or 0),
            }
        )
        if updated_at is None or (row_updated_at and row_updated_at > updated_at):
            updated_at = row_updated_at

    items.sort(key=lambda it: it["qty"], reverse=True)
    total_qty = sum(it["qty"] for it in items)
    for it in items:
        it["share"] = (it["qty"] / total_qty) if total_qty else 0.0

    return {
        "part_id": part_id,
        "item_no": item_no,
        "updated_at": updated_at,
        "total_qty": total_qty,
        "items": items[:limit],
    }
