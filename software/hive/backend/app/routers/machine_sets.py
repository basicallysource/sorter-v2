"""Which LEGO sets a machine's lot could be built from.

One endpoint, for a sorter's dashboard: it posts a lot's inventory and gets
back the sets the lot plausibly holds, or none. The matching, its thresholds
and what they were measured on are in ``app.services.set_match`` and
agent-docs/set-match.md.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from app.deps import get_current_machine
from app.errors import APIError
from app.models.machine import Machine
from app.services import set_match

router = APIRouter(prefix="/api/machine/sets", tags=["machine-sets"])

# A lot's distinct part + colors. A sorted lot of 40,000 pieces has under
# 10,000; this leaves room and still bounds a request.
MAX_INVENTORY_LINES = 50_000
# How long a request waits for the index when this process has not built it
# yet (its first use after a start). The build takes longer than a sorter's
# client should wait, so past this the answer is a 503 to ask again.
INDEX_WAIT_S = 8.0
INDEX_RETRY_AFTER_S = 15


class InventoryLine(BaseModel):
    # BrickLink ids, as a sorter records a piece. A color the sorter did not
    # name (None) counts toward the part's pieces in other colors only.
    part_id: str = Field(min_length=1, max_length=64)
    color_id: int | str | None = None
    quantity: int = Field(default=1, ge=1, le=1_000_000)


class SetMatchRequest(BaseModel):
    inventory: list[InventoryLine] = Field(max_length=MAX_INVENTORY_LINES)
    # How many sets to return, likeliest first, and how many missing lines to
    # list for each.
    limit: int = Field(default=set_match.DEFAULT_LIMIT, ge=1, le=100)
    missing_limit: int = Field(default=set_match.DEFAULT_MISSING_LIMIT, ge=0, le=500)
    # Each piece counts for one set: a set is matched against what the sets
    # before it left. Off, every set is matched against the whole inventory.
    exclusive: bool = True
    # What a set must reach to be returned at all (agent-docs/set-match.md).
    min_set_pieces: int = Field(default=set_match.DEFAULT_MIN_SET_PIECES, ge=1)
    min_distinctive_lines: int = Field(default=set_match.DEFAULT_MIN_DISTINCTIVE_LINES, ge=1)
    min_evidence: float = Field(default=set_match.DEFAULT_MIN_EVIDENCE, ge=0)
    min_distinctive_share: float = Field(default=set_match.DEFAULT_MIN_DISTINCTIVE_SHARE, ge=0, le=1)
    min_share: float = Field(default=set_match.DEFAULT_MIN_SHARE, ge=0, le=1)
    # Which lines are distinctive: those the lot had at most this chance of
    # holding.
    distinctive_chance: float = Field(default=set_match.DEFAULT_DISTINCTIVE_CHANCE, gt=0, le=1)


@router.post("/match")
def match_sets(payload: SetMatchRequest, _machine: Machine = Depends(get_current_machine)):
    """The sets this inventory could be (partly) built from, likeliest first.

    ``sets`` is empty when no set reaches the thresholds: common bricks alone
    never make a match. Each set comes with how many of its required pieces
    the inventory covers (its part in its own color), how much of what is
    unusual about it is there, and its missing lines, the most unusual first.
    """
    index = set_match.get_set_match_service().index(wait_s=INDEX_WAIT_S)
    if index is None:
        raise APIError(
            503,
            "The set index is being built. Ask again shortly.",
            "SET_INDEX_BUILDING",
            {"retry_after_s": INDEX_RETRY_AFTER_S},
        )
    return set_match.match_sets(
        index,
        [line.model_dump() for line in payload.inventory],
        thresholds=set_match.Thresholds(
            min_set_pieces=payload.min_set_pieces,
            min_distinctive_lines=payload.min_distinctive_lines,
            min_evidence=payload.min_evidence,
            min_distinctive_share=payload.min_distinctive_share,
            min_share=payload.min_share,
            distinctive_chance=payload.distinctive_chance,
        ),
        exclusive=payload.exclusive,
        limit=payload.limit,
        missing_limit=payload.missing_limit,
    )
