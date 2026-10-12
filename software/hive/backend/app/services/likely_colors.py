"""The colors a piece is likely to be, for people labeling on Hive and for the
machines' own review screens: one ranking (`color_rank.rank_colors`) over the
labelable palette, fed with the part's BrickLink sale data.

Sale data comes from `ProfileCatalogService.bricklink_part_colors`: the live
BrickLink price guide across the whole palette (cached in memory for hours, see
`bricklink.fetch_color_quantities`) when a key is configured, else the cached
price guide in parts.db. The colors the catalog lists the part in come from
`bricklink_item_colors`. Nothing here calls BrickLink outside those caches.
"""

from __future__ import annotations

from typing import Any, Sequence

from app.services import color_rank
from app.services.profile_catalog import get_profile_catalog_service

# How many colors a response carries unless asked for fewer or more. The whole
# palette is ~200; a review screen shows a dozen and searches the rest locally.
DEFAULT_LIMIT = 300


def is_labelable(color: dict[str, Any]) -> bool:
    """Whether a piece can truly be this color: the BrickLink palette less the
    placeholders (id 0 or below: "(Not Applicable)", "[Unknown]"), Modulex
    ("Mx ...", a separate brick system) and Fabuland (its own toy line)."""
    color_id = color.get("id")
    if not isinstance(color_id, int) or color_id <= 0:
        return False
    name = str(color.get("name") or "")
    return not (name.startswith("Mx ") or name.startswith("Fabuland") or name.startswith("["))


def labelable_palette() -> list[dict[str, Any]]:
    """The one palette people and machines label, rank and chart colors from."""
    return [c for c in get_profile_catalog_service().list_bricklink_colors() if is_labelable(c)]


def likely_colors(
    part_id: str | None,
    predictions: Sequence[tuple[int, float | None]],
    limit: int = DEFAULT_LIMIT,
) -> dict[str, Any]:
    """Every labelable color ranked for a piece of `part_id` (None when the
    piece was not identified) that was predicted to be `predictions`
    ((BrickLink color id, score 0..1 or None), best first or not)."""
    catalog = get_profile_catalog_service()
    full = catalog.list_bricklink_colors()
    palette = [c for c in full if is_labelable(c)]

    item_no: str | None = None
    source = "none"
    updated_at: str | None = None
    quantities: dict[int, dict[str, Any]] | None = None
    known_in: set[int] = set()
    if part_id:
        sale = catalog.bricklink_part_colors(part_id, limit=len(full) or 1)
        item_no = sale.get("item_no")
        if item_no:
            source = sale.get("source") or "cache"
            updated_at = sale.get("updated_at")
            quantities = {int(it["color_id"]): it for it in sale.get("items", [])}
            known_in = catalog.bricklink_known_colors(item_no)

    ranked = color_rank.rank_colors(
        palette,
        predictions,
        lookup={int(c["id"]): c for c in full},
        quantities=quantities,
        complete=source == "live",
        known_in=known_in,
    )
    return {
        "part_id": part_id,
        "item_no": item_no,
        # live: priced across the whole palette now; cache: the price guide
        # synced into parts.db (partial); none: no sale data for this part.
        "source": source,
        "updated_at": updated_at,
        "total_qty": sum(int(it.get("qty") or 0) for it in (quantities or {}).values()),
        "predictions": [{"color_id": color_id, "score": score} for color_id, score in predictions],
        "colors": ranked[: max(1, limit)],
    }
