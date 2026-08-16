"""Service-to-service reads of the parts catalog.

The sibling of `routers/public_stats.py`: same credential model, same
admin-owned unconstrained `hv_*` key, scope-gated the same way. Where that one
serves what the fleet has DONE, this serves what a part IS.

**Two scopes, because the halves carry different risk.** `parts:read` is
catalog fact — identity, category, the colors it exists in, physical size,
weight. `parts:prices` is market data, which is a licensed feed rather than a
fact about a brick, and is the half worth being able to withhold from a
consumer that gets the rest. A key with `parts:read` alone gets every part in
full with the price block absent; nothing 403s halfway through a batch.

**The batch endpoint is the one that matters.** A consumer doing arithmetic
over the fleet's parts — what does this all weigh, how big is the average
piece, which categories dominate — needs hundreds of parts per question, and
doing that one HTTP request at a time is slow enough that it does not get done.
`POST /parts/batch` takes up to MAX_BATCH ids and answers in one round trip and
one pass over sqlite.

The row shape comes from `profile_engine.db.pieceMetadata`, which the machines
already use, rather than a second assembler built beside it. One place resolves
a part id to a row, so a printed part or a minifig id behaves the same here as
it does on a sorter.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body, Depends, Query
from pydantic import BaseModel, Field

from app.deps import (
    API_KEY_SCOPE_PARTS_PRICES,
    API_KEY_SCOPE_PARTS_READ,
    optional_public_scope,
    require_public_scope,
)
from app.errors import APIError
from app.services.profile_catalog import get_profile_catalog_service

router = APIRouter(prefix="/api/public", tags=["public-catalog"])

require_parts_key = require_public_scope(API_KEY_SCOPE_PARTS_READ)
has_prices_scope = optional_public_scope(API_KEY_SCOPE_PARTS_PRICES)

# One request, one sqlite pass. Well above what a question about the fleet's
# part distribution needs (the distributions in /stats are fifteen deep) and
# low enough that a caller cannot ask for the whole catalog a page at a time
# and reassemble it. A consumer wanting bulk facts should say what it is
# actually computing; that is a conversation, not a limit to raise quietly.
MAX_BATCH = 250

# Everything price-shaped in a pieceMetadata row. Stripped as a set rather than
# by rebuilding the row field by field, so a new price field added upstream is
# excluded by DEFAULT instead of leaking until somebody notices. If you add a
# price field to pieceMetadata, add its name here in the same change.
_PRICE_FIELDS = frozenset(
    {
        "price",
        "moving_avg_price",
        "price_currency",
        "price_updated_at",
        "price_color_specific",
        "price_from_base_mold",
        "price_from_base_name",
    }
)


def _project(row: dict[str, Any] | None, *, with_prices: bool) -> dict[str, Any] | None:
    """One catalog row as this API serves it.

    Drops `source`, which pieceMetadata sets to the literal "hive" for the
    machine's benefit and which is noise here, and drops the price block unless
    the caller's key carries the scope for it.
    """
    if row is None:
        return None
    out = {k: v for k, v in row.items() if k != "source"}
    if not with_prices:
        out = {k: v for k, v in out.items() if k not in _PRICE_FIELDS}
    return out


@router.get("/parts/search", dependencies=[Depends(require_parts_key)])
def search_public_parts(
    q: str = Query(min_length=1, max_length=200),
    category_id: int | None = None,
    limit: int = Query(default=25, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
):
    """Find parts by name or number.

    The way in when the caller has words rather than ids — it does not know
    "3001", it knows "2x4 brick". Returns catalog summaries, not full rows;
    feed the part numbers to `/parts/batch` for the detail.
    """
    return get_profile_catalog_service().search_parts(
        query=q, cat_id=category_id, limit=limit, offset=offset
    )


@router.get("/parts/{part_num}", dependencies=[Depends(require_parts_key)])
def get_public_part(
    part_num: str,
    color_id: int | None = None,
    with_prices: bool = Depends(has_prices_scope),
):
    """One part in full: identity, category, years, size, weight, image.

    `part_num` may be a Rebrickable part number or a BrickLink item number —
    the machines predict in the latter for printed parts and minifigs, so both
    resolve here and the row that comes back names which is which.

    `color_id` selects the color-specific price where one exists, and is inert
    for a key without the price scope.
    """
    row = get_profile_catalog_service().piece_metadata(part_num, color_id)
    if row is None:
        raise APIError(404, f"No catalog entry for {part_num}", "PART_NOT_FOUND")
    return _project(row, with_prices=with_prices)


class BatchPartRef(BaseModel):
    part_num: str = Field(min_length=1, max_length=64)
    # Optional, and only meaningful for a caller that can see prices. A part is
    # the same shape and weight in every color.
    color_id: int | None = None


class BatchPartsRequest(BaseModel):
    parts: list[BatchPartRef] = Field(min_length=1, max_length=MAX_BATCH)


@router.post("/parts/batch", dependencies=[Depends(require_parts_key)])
def batch_public_parts(
    payload: BatchPartsRequest = Body(...),
    with_prices: bool = Depends(has_prices_scope),
):
    """Up to MAX_BATCH parts in one round trip.

    Answers in request order with one entry per requested id, and an id the
    catalog does not know comes back as `{"part_num": ..., "found": false}`
    rather than being dropped. A caller doing arithmetic over a list needs the
    answer to line up with what it asked; silently returning fewer rows than
    were requested is how a total ends up wrong and nobody can see why.

    Duplicate ids are resolved once and served to every position that asked.
    """
    catalog = get_profile_catalog_service()
    resolved: dict[tuple[str, int | None], dict[str, Any] | None] = {}
    out = []
    for ref in payload.parts:
        key = (ref.part_num, ref.color_id)
        if key not in resolved:
            resolved[key] = catalog.piece_metadata(ref.part_num, ref.color_id)
        row = _project(resolved[key], with_prices=with_prices)
        if row is None:
            out.append({"part_num": ref.part_num, "found": False})
        else:
            out.append({**row, "found": True})
    return {"parts": out, "count": len(out), "prices_included": with_prices}


@router.get("/colors", dependencies=[Depends(require_parts_key)])
def list_public_colors():
    """The BrickLink color palette: id, name, swatch hex, transparency.

    The id space `machine_pieces.color_id` and every distribution in `/stats`
    are expressed in, so a consumer joining a color count to a color name wants
    this list and not the Rebrickable one.
    """
    return {"colors": get_profile_catalog_service().list_bricklink_colors()}


@router.get("/categories", dependencies=[Depends(require_parts_key)])
def list_public_categories():
    """Rebrickable part categories, with how many parts each holds."""
    return {"categories": get_profile_catalog_service().admin_list_categories()}


@router.get("/parts/{part_num}/colors", dependencies=[Depends(require_parts_key)])
def public_part_colors(part_num: str, limit: int = Query(default=24, ge=1, le=100)):
    """Which colors this part is actually sold in, commonest first."""
    return get_profile_catalog_service().bricklink_part_colors(part_num, limit=limit)
