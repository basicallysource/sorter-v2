from __future__ import annotations

import sqlite3
import time
from typing import Any, Sequence

import requests

# The affiliate API is the only BrickLink API we hold a credential for (a single
# `api_key` query param — no OAuth consumer/token pair), so everything here goes
# through it. Docs are not public; the request/response shapes below were derived
# from the price sync that has been populating parts.db since 2026-06.
AFFILIATE_BASE_URL = "https://api.bricklink.com/api/affiliate/v1"
PRICE_GUIDE_BATCH_URL = f"{AFFILIATE_BASE_URL}/price_guide_batch"
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

    Beware the quantity fields: despite the names, `unit_quantity` is the number
    of individual pieces listed and `total_quantity` is the number of lots — the
    opposite of what BrickLink's storefront API documents. Confirmed against a
    live call (Plate 1x3 in Light Bluish Gray: unit_quantity 679255,
    total_quantity 3999; the reverse reading would mean 679k separate lots of one
    plate). The inventory lot count also saturates around 4000, so `*_quantity`
    on a common part is a sample ceiling, not a true total — rank by pieces."""
    if not api_key:
        raise BrickLinkError("BL_AFFILIATE_API_KEY is not configured")
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
    many pieces are for sale. Reads the cached affiliate price guide in parts.db
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
