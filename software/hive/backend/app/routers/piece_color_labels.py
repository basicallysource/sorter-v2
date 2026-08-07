"""Human color-labeling of synced machine pieces.

A labeler views a piece's synced crop(s) and records the TRUE BrickLink color.
To speed labeling we suggest a pixel-average guess computed on the fly from the
crop pixels (see services.pixel_color) — a plain traditional estimate, not a
learned prediction — matched to the nearest BrickLink color. Nothing about the
suggestion is stored; a row is written only when a user provides a color, and
each user gets their own row (multiple independent labels per piece).

The palette comes from the parts.db catalog (BrickLink colors derived from the
Rebrickable `colors` external ids). Labels live in Postgres (piece_color_labels).
"""

from __future__ import annotations

import logging
import math
import time
from datetime import datetime, timedelta, timezone
from uuid import UUID

import numpy as np
from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy import String, and_, exists, false, func, or_
from sqlalchemy import column as sa_column
from sqlalchemy import table as sa_table
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Session

from app.deps import get_current_user, get_db, verify_csrf
from app.errors import APIError
from app.models.image_quality_label import (
    CROP_KIND_CHANNEL_CROP,
    CROP_KIND_PIECE_IMAGE,
    IMAGE_QUALITY_FLAG_FIELDS,
    ImageQualityLabel,
)
from app.models.machine import Machine
from app.models.machine_channel_crop import MachineChannelCrop
from app.models.machine_piece import MachinePiece
from app.models.machine_piece_image import MachinePieceImage
from app.models.machine_piece_rejection_reason import MachinePieceRejectionReason
from app.models.piece_color_label import PieceColorLabel
from app.models.piece_crop_ai_prediction import PieceCropAiPrediction
from app.models.piece_crop_link import PieceCropLink, PieceCropLinkMember
from app.models.piece_part_label import PiecePartLabel
from app.models.piece_rejection import PieceRejection
from app.models.user import User
from app.services.brickognize_feedback import submit_color_feedback, submit_part_feedback
from app.services.channel_crop_lookup import find_possible_crops
from app.services.color_predictor import predict as predict_piece_color
from app.services import link_predictor
from app.services.piece_crop_ai_matcher import (
    DEFAULT_MATCH_MODEL,
    AiMatchError,
    match_piece_crops,
    store_prediction,
)
from app.services.access_window import (
    _machine_owned_by,
    apply_piece_access,
    channel_crop_access_visible,
    is_unrestricted,
    piece_access_visible,
    piece_access_visible_by_key,
    scope_to_piece_access,
)
from app.services.pixel_color import _srgb_to_lab, guess_piece_color
from app.services.profile_catalog import get_profile_catalog_service
from app.services.rate_limit import rate_limit
from app.services.secrets import decrypt_secret
from app.services.storage import serve_stored_file

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/labeling", tags=["labeling"])

PIECE_IMAGE_CACHE_CONTROL = "public, max-age=31536000, immutable"


def _available_image_exists():
    """Correlated EXISTS: the piece has at least one synced crop still in
    storage (image_key set). Pieces whose crops were evicted before sync can't
    be color-labeled, so they're excluded from the queue."""
    return exists().where(
        and_(
            MachinePieceImage.machine_id == MachinePiece.machine_id,
            MachinePieceImage.piece_uuid == MachinePiece.piece_uuid,
            MachinePieceImage.image_key.isnot(None),
        )
    )


# Don't serve a piece until it's this old — the same-piece channel crops upload
# after the piece and take a while, so a too-fresh piece would show an incomplete
# candidate list.
_MIN_PIECE_AGE = timedelta(minutes=15)


def _old_enough():
    cutoff = datetime.now(timezone.utc) - _MIN_PIECE_AGE
    return func.coalesce(MachinePiece.seen_at, MachinePiece.recorded_at, MachinePiece.created_at) <= cutoff


def _labelable_query(db: Session):
    # A piece is labelable if it isn't a dead/spurious record, has a crop, and is
    # old enough for its channel crops to have synced.
    return db.query(MachinePiece).filter(
        MachinePiece.dead.is_(False),
        _available_image_exists(),
        _old_enough(),
    )


# The labelable-piece count is a full scan over machine_pieces with a
# per-row image EXISTS — by far the heaviest part of the stats rollup (it's
# the query that tipped Postgres over when /dev/shm ran out). It only changes
# as new pieces sync in, never from labeling activity, so a short TTL cache is
# safe and keeps every label-derived counter in the response live-accurate.
_LABELABLE_COUNT_TTL_S = 300.0
_labelable_count_cache: dict[tuple[object, str | None], tuple[float, int]] = {}


def _cached_labelable_count(db: Session, user: User, machine_id: UUID | None) -> int:
    key = (user.id, str(machine_id) if machine_id is not None else None)
    hit = _labelable_count_cache.get(key)
    now = time.monotonic()
    if hit is not None and now - hit[0] < _LABELABLE_COUNT_TTL_S:
        return hit[1]
    q = apply_piece_access(db, _labelable_query(db), user)
    if machine_id is not None:
        q = q.filter(MachinePiece.machine_id == machine_id)
    count = q.count()
    if len(_labelable_count_cache) > 512:
        for k in [k for k, (ts, _) in _labelable_count_cache.items() if now - ts >= _LABELABLE_COUNT_TTL_S]:
            _labelable_count_cache.pop(k, None)
    _labelable_count_cache[key] = (now, count)
    return count


class ColorOut(BaseModel):
    id: int
    name: str
    rgb: str | None = None
    is_trans: bool = False


class ColorsResponse(BaseModel):
    results: list[ColorOut]


@router.get("/colors", response_model=ColorsResponse)
def list_colors(
    _user: User = Depends(get_current_user),
) -> ColorsResponse:
    """The BrickLink color palette to label from."""
    colors = get_profile_catalog_service().list_bricklink_colors()
    return ColorsResponse(results=[ColorOut(**c) for c in colors])


class PartColorAvailabilityOut(BaseModel):
    color_id: int
    color_name: str
    rgb: str | None = None
    is_trans: bool = False
    qty: int
    qty_new: int
    qty_used: int
    lots: int
    share: float


class PartColorAvailabilityResponse(BaseModel):
    part_id: str
    item_no: str | None = None
    updated_at: str | None = None
    source: str = "cache"
    total_qty: int
    items: list[PartColorAvailabilityOut]


@router.get("/part/{part_id}/bricklink-colors", response_model=PartColorAvailabilityResponse)
def part_bricklink_colors(
    part_id: str,
    limit: int = Query(100, ge=1, le=250),
    _user: User = Depends(get_current_user),
    _rl: None = Depends(rate_limit("labeling_list")),
) -> PartColorAvailabilityResponse:
    """Every color this part is actually sold in on BrickLink, ranked by pieces
    for sale — the labeler's prior for what this mold even exists in. Priced live
    across the full palette; public catalog data, so no per-machine access gate."""
    result = get_profile_catalog_service().bricklink_part_colors(part_id, limit=limit)
    return PartColorAvailabilityResponse(
        part_id=result["part_id"],
        item_no=result["item_no"],
        updated_at=result["updated_at"],
        source=result.get("source", "cache"),
        total_qty=result["total_qty"],
        items=[PartColorAvailabilityOut(**it) for it in result["items"]],
    )


@router.get("/stats")
def label_stats(
    machine_id: UUID | None = Query(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    _rl: None = Depends(rate_limit("labeling_list")),
) -> dict:
    """Dashboard rollup: overall progress plus a histogram of how many distinct
    labelers have color-labeled each piece (drives the coverage chart). Scoped to
    one machine when machine_id is given, matching the grid's machine filter, and
    to the caller's visibility window (so a member's dashboard reflects only their
    slice, not global fleet totals; admins see everything)."""
    total_labelable = _cached_labelable_count(db, current_user, machine_id)

    def _color_q():
        q = db.query(PieceColorLabel)
        if machine_id is not None:
            q = q.filter(PieceColorLabel.machine_id == machine_id)
        return scope_to_piece_access(db, q, current_user, PieceColorLabel.machine_id, PieceColorLabel.piece_uuid)

    def _crop_q():
        q = db.query(PieceCropLink)
        if machine_id is not None:
            q = q.filter(PieceCropLink.machine_id == machine_id)
        return scope_to_piece_access(db, q, current_user, PieceCropLink.machine_id, PieceCropLink.piece_uuid)

    def _part_q():
        q = db.query(PiecePartLabel)
        if machine_id is not None:
            q = q.filter(PiecePartLabel.machine_id == machine_id)
        return scope_to_piece_access(db, q, current_user, PiecePartLabel.machine_id, PiecePartLabel.piece_uuid)

    labeled_by_me = _color_q().filter(PieceColorLabel.labeler_id == current_user.id).count()
    crop_links_by_me = _crop_q().filter(PieceCropLink.labeler_id == current_user.id).count()
    part_labels_by_me = _part_q().filter(PiecePartLabel.labeler_id == current_user.id).count()
    total_color_labels = _color_q().count()
    total_crop_links = _crop_q().count()
    total_part_labels = _part_q().count()

    # Distinct pieces touched (one row per labeler per piece, so a grouped count).
    color_pieces_sq = (
        _color_q()
        .with_entities(PieceColorLabel.machine_id, PieceColorLabel.piece_uuid)
        .group_by(PieceColorLabel.machine_id, PieceColorLabel.piece_uuid)
        .subquery()
    )
    color_labeled_pieces = db.query(func.count()).select_from(color_pieces_sq).scalar() or 0
    crop_pieces_sq = (
        _crop_q()
        .with_entities(PieceCropLink.machine_id, PieceCropLink.piece_uuid)
        .group_by(PieceCropLink.machine_id, PieceCropLink.piece_uuid)
        .subquery()
    )
    crop_linked_pieces = db.query(func.count()).select_from(crop_pieces_sq).scalar() or 0
    part_pieces_sq = (
        _part_q()
        .with_entities(PiecePartLabel.machine_id, PiecePartLabel.piece_uuid)
        .group_by(PiecePartLabel.machine_id, PiecePartLabel.piece_uuid)
        .subquery()
    )
    part_labeled_pieces = db.query(func.count()).select_from(part_pieces_sq).scalar() or 0

    # Histogram: pieces by number of distinct color-labelers (1 / 2 / 3+).
    per_piece = (
        _color_q()
        .with_entities(func.count(PieceColorLabel.id).label("n"))
        .group_by(PieceColorLabel.machine_id, PieceColorLabel.piece_uuid)
        .subquery()
    )
    buckets = dict(
        db.query(
            func.least(per_piece.c.n, 3).label("bucket"),
            func.count().label("cnt"),
        )
        .group_by(func.least(per_piece.c.n, 3))
        .all()
    )
    labelers_1 = int(buckets.get(1, 0))
    labelers_2 = int(buckets.get(2, 0))
    labelers_3plus = int(buckets.get(3, 0))
    labelers_0 = max(0, total_labelable - color_labeled_pieces)

    return {
        "total_labelable": total_labelable,
        "labeled_by_me": int(labeled_by_me),
        "crop_links_by_me": int(crop_links_by_me),
        "part_labels_by_me": int(part_labels_by_me),
        "total_labels": int(total_color_labels),
        "total_color_labels": int(total_color_labels),
        "total_crop_links": int(total_crop_links),
        "total_part_labels": int(total_part_labels),
        "color_labeled_pieces": int(color_labeled_pieces),
        "crop_linked_pieces": int(crop_linked_pieces),
        "part_labeled_pieces": int(part_labeled_pieces),
        "labeler_histogram": {
            "0": labelers_0,
            "1": labelers_1,
            "2": labelers_2,
            "3+": labelers_3plus,
        },
    }


def _labelable_palette_colors() -> list[dict]:
    """The palette minus non-standard families the machine never meaningfully
    sorts: Modulex ("Mx …", a separate brick system), Fabuland (its own toy
    line), and id<=0 ("(Not Applicable)"/[Unknown]). Charting their coverage or
    hunting them as rare colors is just noise."""
    out = []
    for c in get_profile_catalog_service().list_bricklink_colors():
        cid = c.get("id")
        if not isinstance(cid, int) or cid <= 0:
            continue
        name = str(c.get("name", ""))
        if name.startswith("Mx ") or name.startswith("Fabuland"):
            continue
        out.append(c)
    return out


@router.get("/color-coverage")
def color_coverage(
    machine_id: UUID | None = Query(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    _rl: None = Depends(rate_limit("labeling_list")),
) -> dict:
    """Per-color coverage across the whole BrickLink palette: how many distinct
    pieces have been color-labeled as each color, scoped to the caller's
    visibility (admins see everything). Every palette color is returned, including
    the ones with zero labels — that's the point of the chart: it reveals which
    colors are well-covered and which are rare/missing in the labeled data."""
    scoped = scope_to_piece_access(
        db, db.query(PieceColorLabel), current_user, PieceColorLabel.machine_id, PieceColorLabel.piece_uuid
    ).filter(PieceColorLabel.color_id.isnot(None))  # exclude "I can't tell" answers
    if machine_id is not None:
        scoped = scoped.filter(PieceColorLabel.machine_id == machine_id)

    # Distinct (machine, piece) per color — a piece labeled by three people counts
    # once toward that color's coverage.
    per_piece = (
        scoped.with_entities(
            PieceColorLabel.color_id,
            PieceColorLabel.machine_id,
            PieceColorLabel.piece_uuid,
        )
        .group_by(PieceColorLabel.color_id, PieceColorLabel.machine_id, PieceColorLabel.piece_uuid)
        .subquery()
    )
    piece_counts = dict(
        db.query(per_piece.c.color_id, func.count()).group_by(per_piece.c.color_id).all()
    )
    label_counts = dict(
        scoped.with_entities(PieceColorLabel.color_id, func.count())
        .group_by(PieceColorLabel.color_id)
        .all()
    )

    palette = _labelable_palette_colors()
    colors = []
    covered = 0
    for c in palette:
        pieces = int(piece_counts.get(c["id"], 0))
        if pieces > 0:
            covered += 1
        colors.append(
            {
                "id": c["id"],
                "name": c["name"],
                "rgb": c.get("rgb"),
                "is_trans": bool(c.get("is_trans", False)),
                "pieces": pieces,
                "labels": int(label_counts.get(c["id"], 0)),
            }
        )
    return {
        "colors": colors,
        "total_colors": len(palette),
        "covered_colors": covered,
    }


# "Has same-piece candidates" — a channel crop exists within the piece's
# arrival window (DEFAULT_PARAMS lookback/slop). Computed live this was a
# correlated EXISTS that Postgres planned as a machine_id-only hash semi join
# (scanning each machine's whole crop set per piece, >100s); it's precomputed
# into the piece_has_candidates materialized view instead (a8c1d2e3f4a5
# migration, refreshed by CandidateMatviewWorker) and hash-joined here.
_piece_has_candidates = sa_table(
    "piece_has_candidates",
    sa_column("machine_id", PGUUID(as_uuid=True)),
    sa_column("piece_uuid", String),
)


_PIECE_SORTS = {
    "priority",
    "recent",
    "oldest",
    "least_color",
    "most_color",
    "least_crop",
    "most_crop",
    "least_part",
    "most_part",
    "rare_color",
    "unidentified",
    "needs_me",
}

# A color is "rare" (under-covered) if this many or fewer distinct pieces have
# been labeled with it. A predicted color counts as a rare-color *candidate* when
# it sits within this CIE-Lab distance of some rare color — the pixel/model may
# have landed on a nearby common color when the piece is actually the rare one.
_RARE_PIECE_THRESHOLD = 3
_RARE_LAB_NEAR = 22.0


def _rare_candidate_color_ids(db: Session, user: User, machine_id: UUID | None) -> set[str]:
    """BrickLink color ids (as stored on the piece — strings) that are worth
    surfacing when hunting rare colors: every under-covered color, plus any color
    close to one in Lab space. Pieces whose Brickognize color prediction is one of
    these are the ones most likely to actually be a rare color the model fumbled."""
    scoped = scope_to_piece_access(
        db, db.query(PieceColorLabel), user, PieceColorLabel.machine_id, PieceColorLabel.piece_uuid
    ).filter(PieceColorLabel.color_id.isnot(None))  # "I can't tell" answers aren't a color
    if machine_id is not None:
        scoped = scoped.filter(PieceColorLabel.machine_id == machine_id)
    per_piece = (
        scoped.with_entities(
            PieceColorLabel.color_id, PieceColorLabel.machine_id, PieceColorLabel.piece_uuid
        )
        .group_by(PieceColorLabel.color_id, PieceColorLabel.machine_id, PieceColorLabel.piece_uuid)
        .subquery()
    )
    piece_counts = dict(
        db.query(per_piece.c.color_id, func.count()).group_by(per_piece.c.color_id).all()
    )

    palette = [c for c in _labelable_palette_colors() if c.get("rgb")]
    rgbs = []
    ids = []
    for c in palette:
        h = str(c["rgb"]).replace("#", "")
        if len(h) < 6:
            continue
        try:
            rgbs.append([int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)])
        except ValueError:
            continue
        ids.append(c["id"])
    if not rgbs:
        return set()

    labs = _srgb_to_lab(np.array(rgbs, dtype=np.float64))
    rare_mask = np.array([int(piece_counts.get(cid, 0)) <= _RARE_PIECE_THRESHOLD for cid in ids])
    if not rare_mask.any():
        return set()
    rare_labs = labs[rare_mask]
    # Min Lab distance from each palette color to any rare color; keep those within
    # the near threshold (rare colors themselves are distance 0, so included).
    dists = np.linalg.norm(labs[:, None, :] - rare_labs[None, :, :], axis=2).min(axis=1)
    return {str(ids[i]) for i in range(len(ids)) if dists[i] <= _RARE_LAB_NEAR}


@router.get("/pieces")
def list_pieces(
    sort: str = Query("priority"),
    limit: int = Query(60, ge=1, le=200),
    offset: int = Query(0, ge=0),
    machine_id: UUID | None = Query(None),
    with_candidates: bool = Query(False),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    _rl: None = Depends(rate_limit("labeling_list")),
) -> dict:
    """Sortable grid of labelable pieces with per-piece label/crop-link/part-label
    counts, for the dashboard. Sorts: priority (has same-piece candidates first,
    then fewest color labels — spreads effort where it's useful), recent, oldest,
    least/most_color, least/most_crop, least/most_part, unidentified (pieces the
    machine couldn't name — the part-correction queue), needs_me (this user's
    unlabeled first). Optional machine_id filter and with_candidates (only pieces
    that have same-piece candidate crops)."""
    if sort not in _PIECE_SORTS:
        sort = "priority"

    color_cnt_sq = (
        db.query(
            PieceColorLabel.machine_id.label("mid"),
            PieceColorLabel.piece_uuid.label("puid"),
            func.count().label("cnt"),
        )
        .group_by(PieceColorLabel.machine_id, PieceColorLabel.piece_uuid)
        .subquery()
    )
    crop_cnt_sq = (
        db.query(
            PieceCropLink.machine_id.label("mid"),
            PieceCropLink.piece_uuid.label("puid"),
            func.count().label("cnt"),
        )
        .group_by(PieceCropLink.machine_id, PieceCropLink.piece_uuid)
        .subquery()
    )
    part_cnt_sq = (
        db.query(
            PiecePartLabel.machine_id.label("mid"),
            PiecePartLabel.piece_uuid.label("puid"),
            func.count().label("cnt"),
        )
        .group_by(PiecePartLabel.machine_id, PiecePartLabel.piece_uuid)
        .subquery()
    )
    color_cnt = func.coalesce(color_cnt_sq.c.cnt, 0)
    crop_cnt = func.coalesce(crop_cnt_sq.c.cnt, 0)
    part_cnt = func.coalesce(part_cnt_sq.c.cnt, 0)
    my_color = exists().where(
        and_(
            PieceColorLabel.machine_id == MachinePiece.machine_id,
            PieceColorLabel.piece_uuid == MachinePiece.piece_uuid,
            PieceColorLabel.labeler_id == current_user.id,
        )
    )
    my_crop = exists().where(
        and_(
            PieceCropLink.machine_id == MachinePiece.machine_id,
            PieceCropLink.piece_uuid == MachinePiece.piece_uuid,
            PieceCropLink.labeler_id == current_user.id,
        )
    )
    my_part = exists().where(
        and_(
            PiecePartLabel.machine_id == MachinePiece.machine_id,
            PiecePartLabel.piece_uuid == MachinePiece.piece_uuid,
            PiecePartLabel.labeler_id == current_user.id,
        )
    )
    # LEFT JOIN against the precomputed matview: one hash build, O(1) per piece —
    # both the with_candidates filter and the priority sort key come from it.
    has_candidates = _piece_has_candidates.c.machine_id.isnot(None)
    # A piece this user rejected is handled — drop it from their queue.
    my_rejection = exists().where(
        and_(
            PieceRejection.machine_id == MachinePiece.machine_id,
            PieceRejection.piece_uuid == MachinePiece.piece_uuid,
            PieceRejection.labeler_id == current_user.id,
        )
    )

    q = (
        db.query(
            MachinePiece,
            color_cnt.label("color_cnt"),
            crop_cnt.label("crop_cnt"),
            my_color.label("my_color"),
            my_crop.label("my_crop"),
            has_candidates.label("has_candidates"),
            part_cnt.label("part_cnt"),
            my_part.label("my_part"),
        )
        .outerjoin(
            color_cnt_sq,
            and_(color_cnt_sq.c.mid == MachinePiece.machine_id, color_cnt_sq.c.puid == MachinePiece.piece_uuid),
        )
        .outerjoin(
            crop_cnt_sq,
            and_(crop_cnt_sq.c.mid == MachinePiece.machine_id, crop_cnt_sq.c.puid == MachinePiece.piece_uuid),
        )
        .outerjoin(
            part_cnt_sq,
            and_(part_cnt_sq.c.mid == MachinePiece.machine_id, part_cnt_sq.c.puid == MachinePiece.piece_uuid),
        )
        .outerjoin(
            _piece_has_candidates,
            and_(
                _piece_has_candidates.c.machine_id == MachinePiece.machine_id,
                _piece_has_candidates.c.piece_uuid == MachinePiece.piece_uuid,
            ),
        )
        .filter(MachinePiece.dead.is_(False), _available_image_exists(), _old_enough(), ~my_rejection)
    )
    if machine_id is not None:
        q = q.filter(MachinePiece.machine_id == machine_id)
    if with_candidates:
        q = q.filter(has_candidates)
    q = apply_piece_access(db, q, current_user)

    if sort == "rare_color":
        # Only pieces whose predicted color is (near) an under-covered color.
        rare_ids = _rare_candidate_color_ids(db, current_user, machine_id)
        q = q.filter(MachinePiece.color_id.in_(rare_ids)) if rare_ids else q.filter(false())
    elif sort == "unidentified":
        # The part-correction queue: the machine never named these, so there's no
        # mold to confirm or reject — only a human can fill one in.
        q = q.filter(or_(MachinePiece.part_id.is_(None), MachinePiece.part_id == ""))

    recent_order = (MachinePiece.recorded_at.desc().nullslast(), MachinePiece.created_at.desc())
    if sort == "priority":
        # Candidates first, then the least-color-labeled — pushes effort to pieces
        # that are both useful (have crops to link) and under-labeled.
        q = q.order_by(has_candidates.desc(), color_cnt.asc(), *recent_order)
    elif sort == "recent":
        q = q.order_by(*recent_order)
    elif sort == "oldest":
        q = q.order_by(MachinePiece.recorded_at.asc().nullsfirst(), MachinePiece.created_at.asc())
    elif sort == "least_color":
        q = q.order_by(color_cnt.asc(), *recent_order)
    elif sort == "most_color":
        q = q.order_by(color_cnt.desc(), *recent_order)
    elif sort == "least_crop":
        q = q.order_by(crop_cnt.asc(), *recent_order)
    elif sort == "most_crop":
        q = q.order_by(crop_cnt.desc(), *recent_order)
    elif sort == "least_part":
        q = q.order_by(part_cnt.asc(), *recent_order)
    elif sort == "most_part":
        q = q.order_by(part_cnt.desc(), *recent_order)
    elif sort == "unidentified":
        # Already filtered to unidentified pieces; least-labeled first so the
        # queue drains rather than re-showing the same ones.
        q = q.order_by(part_cnt.asc(), *recent_order)
    elif sort == "rare_color":
        # Least-confident COLOR predictions first — those are the likeliest to be
        # the rare color the model missed. This deliberately reads
        # color_confidence, not confidence: the latter is the mold score, which
        # says nothing about how sure we were of the color. Pieces synced before
        # the two were split have no color score and sort last, since they carry
        # no color-rarity signal at all.
        q = q.order_by(MachinePiece.color_confidence.asc().nullslast(), *recent_order)
    elif sort == "needs_me":
        q = q.order_by(my_color.asc(), color_cnt.asc(), *recent_order)

    rows = q.offset(offset).limit(limit + 1).all()
    has_more = len(rows) > limit
    rows = rows[:limit]

    pieces = [r[0] for r in rows]
    machine_ids = {p.machine_id for p in pieces}
    machine_names = {
        mid: name
        for mid, name in db.query(Machine.id, Machine.name).filter(Machine.id.in_(machine_ids)).all()
    } if machine_ids else {}

    # Lowest available seq per piece → grid thumbnail.
    thumb_seq: dict[str, int] = {}
    piece_uuids = [p.piece_uuid for p in pieces]
    if piece_uuids:
        for mid, puid, seq in (
            db.query(MachinePieceImage.machine_id, MachinePieceImage.piece_uuid, func.min(MachinePieceImage.seq))
            .filter(
                MachinePieceImage.piece_uuid.in_(piece_uuids),
                MachinePieceImage.image_key.isnot(None),
            )
            .group_by(MachinePieceImage.machine_id, MachinePieceImage.piece_uuid)
            .all()
        ):
            if mid in machine_ids:
                thumb_seq[f"{mid}|{puid}"] = seq

    items = []
    for p, ccnt, xcnt, mc, mx, has_c, pcnt, mp in rows:
        items.append(
            {
                "machine_id": str(p.machine_id),
                "machine_name": machine_names.get(p.machine_id),
                "piece_uuid": p.piece_uuid,
                "part": {"part_id": p.part_id, "part_name": p.part_name},
                "recorded_at": p.recorded_at.isoformat() if p.recorded_at else None,
                "seen_at": p.seen_at.isoformat() if p.seen_at else None,
                "color_label_count": int(ccnt),
                "crop_link_count": int(xcnt),
                "part_label_count": int(pcnt),
                "my_color": bool(mc),
                "my_crop": bool(mx),
                "my_part": bool(mp),
                "has_candidates": bool(has_c),
                "thumb_seq": thumb_seq.get(f"{p.machine_id}|{p.piece_uuid}"),
            }
        )

    return {"items": items, "has_more": has_more, "offset": offset, "sort": sort}


@router.get("/piece/{machine_id}/{piece_uuid}")
def piece_detail(
    machine_id: UUID,
    piece_uuid: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    _rl: None = Depends(rate_limit("labeling_list")),
) -> dict:
    """Everything the single-piece labeling view needs: the piece, its crops, the
    pixel-average guess, and THIS user's saved color label (so revisiting a piece
    by URL restores what they'd set, rather than a fresh unlabeled view)."""
    piece = (
        db.query(MachinePiece)
        .filter(MachinePiece.machine_id == machine_id, MachinePiece.piece_uuid == piece_uuid)
        .first()
    )
    if piece is None or not piece_access_visible(db, current_user, piece):
        raise APIError(404, "Piece not found", "PIECE_NOT_FOUND")

    machine_name = db.query(Machine.name).filter(Machine.id == machine_id).scalar()
    images = (
        db.query(MachinePieceImage)
        .filter(
            MachinePieceImage.machine_id == machine_id,
            MachinePieceImage.piece_uuid == piece_uuid,
            MachinePieceImage.image_key.isnot(None),
        )
        .order_by(MachinePieceImage.seq.asc())
        .all()
    )
    label = (
        db.query(PieceColorLabel)
        .filter(
            PieceColorLabel.machine_id == machine_id,
            PieceColorLabel.piece_uuid == piece_uuid,
            PieceColorLabel.labeler_id == current_user.id,
        )
        .first()
    )
    rejection = (
        db.query(PieceRejection)
        .filter(
            PieceRejection.machine_id == machine_id,
            PieceRejection.piece_uuid == piece_uuid,
            PieceRejection.labeler_id == current_user.id,
        )
        .first()
    )
    part_label = (
        db.query(PiecePartLabel)
        .filter(
            PiecePartLabel.machine_id == machine_id,
            PiecePartLabel.piece_uuid == piece_uuid,
            PiecePartLabel.labeler_id == current_user.id,
        )
        .first()
    )
    operator_rejection_reasons = [
        r
        for (r,) in db.query(MachinePieceRejectionReason.reason)
        .filter(
            MachinePieceRejectionReason.machine_id == machine_id,
            MachinePieceRejectionReason.piece_uuid == piece_uuid,
        )
        .order_by(MachinePieceRejectionReason.reason)
        .all()
    ]
    # This user's per-image quality flags for these crops, keyed by seq.
    image_quality = {
        lbl.seq: lbl
        for lbl in db.query(ImageQualityLabel).filter(
            ImageQualityLabel.crop_kind == CROP_KIND_PIECE_IMAGE,
            ImageQualityLabel.machine_id == machine_id,
            ImageQualityLabel.piece_uuid == piece_uuid,
            ImageQualityLabel.labeler_id == current_user.id,
        )
    }
    return {
        "machine_id": str(machine_id),
        "machine_name": machine_name,
        "piece_uuid": piece_uuid,
        "part": {"part_id": piece.part_id, "part_name": piece.part_name},
        "recorded_at": piece.recorded_at.isoformat() if piece.recorded_at else None,
        "seen_at": piece.seen_at.isoformat() if piece.seen_at else None,
        "pixel_guess": guess_piece_color(images),
        # Learned prediction from the globally-active color model, if one is set.
        # None → the UI falls back to the pixel-average guess alone.
        "model_prediction": predict_piece_color(db, images),
        "images": [
            {
                "seq": im.seq,
                "source": im.source,
                "used": im.used,
                "score": im.score,
                **_image_quality_state(image_quality.get(im.seq)),
            }
            for im in images
        ],
        "my_label": None
        if label is None
        else {"color_id": label.color_id, "cant_tell": bool(label.cant_tell), "notes": label.notes},
        "my_rejection": None if rejection is None else {"reasons": list(rejection.reasons or [])},
        # This user's part correction, with the catalog entry resolved so the UI
        # can render the picked mold without a second round trip. part is None
        # for a cant_tell answer, or if the part later left the catalog.
        "my_part_label": None
        if part_label is None
        else {
            "part_num": part_label.part_num,
            "cant_tell": bool(part_label.cant_tell),
            "notes": part_label.notes,
            "part": get_profile_catalog_service().part_summary(part_label.part_num)
            if part_label.part_num
            else None,
        },
        # Brickognize's own predicted mold. Resolve against the catalog for the
        # image/category, but a catalog-mirror miss must not erase the fact that
        # Brickognize DID produce an answer — fall back to the bare id/name so
        # the picker still offers it as the incumbent to accept or replace, and
        # only shows "couldn't identify" when Brickognize truly gave nothing.
        "predicted_part": (
            get_profile_catalog_service().part_summary(piece.part_id)
            or {
                "part_num": piece.part_id,
                "name": piece.part_name,
                "part_cat_id": None,
                "category_name": None,
                "part_img_url": None,
            }
        )
        if piece.part_id
        else None,
        # Brickognize prediction + correction state. correctable is True only
        # when a listing id was captured (a prerequisite for submitting feedback).
        "prediction": {
            "color_id": piece.color_id,
            "color_name": piece.color_name,
        },
        "correction": {
            "correctable": piece.brickognize_listing_id is not None,
            "part_correct": piece.part_correct,
            "color_corrected_id": piece.color_corrected_id,
            "part_feedback_submitted": bool(piece.part_feedback_submitted),
            "color_feedback_submitted": bool(piece.color_feedback_submitted),
            # Capture issues the machine operator flagged (no_piece /
            # multiple_pieces / not_lego / blurry) — same vocabulary as
            # my_rejection.reasons, but this is the machine's own verdict, not a
            # labeler's.
            "rejection_reasons": operator_rejection_reasons,
        },
    }


class BrickognizeFeedbackPayload(BaseModel):
    # Fields present are applied and submitted; absent fields are left alone.
    # part_correct: True/False marks the part prediction right/wrong.
    # color_corrected_id: the picked true BrickLink color; if omitted, this
    # user's saved color label (piece_color_labels) is used as the true color.
    part_correct: bool | None = None
    color_corrected_id: int | None = None


@router.post("/piece/{machine_id}/{piece_uuid}/brickognize-feedback")
def submit_brickognize_feedback(
    machine_id: UUID,
    piece_uuid: str,
    payload: BrickognizeFeedbackPayload,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    """Send a piece's part and/or color correction back to Brickognize's feedback
    API and record that it was submitted. Gated on a captured listing id; each
    channel is sent at most once (the *_feedback_submitted flags). The verdict is
    written onto the piece regardless of whether the network call succeeds."""
    piece = (
        db.query(MachinePiece)
        .filter(MachinePiece.machine_id == machine_id, MachinePiece.piece_uuid == piece_uuid)
        .first()
    )
    if piece is None or not piece_access_visible(db, current_user, piece):
        raise APIError(404, "Piece not found", "PIECE_NOT_FOUND")
    if not piece.brickognize_listing_id:
        raise APIError(400, "Piece has no Brickognize listing to correct", "NOT_CORRECTABLE")

    part_submitted = False
    color_submitted = False
    submit_error: str | None = None

    # Part feedback: a recorded verdict, not yet sent, with the applied item rank.
    if payload.part_correct is not None:
        piece.part_correct = payload.part_correct
        if (
            not piece.part_feedback_submitted
            and piece.brickognize_item_rank is not None
            and piece.part_id
        ):
            try:
                submit_part_feedback(
                    listing_id=piece.brickognize_listing_id,
                    item_id=piece.part_id,
                    item_rank=piece.brickognize_item_rank,
                    item_type=piece.brickognize_item_type,
                    is_correct=bool(piece.part_correct),
                )
                piece.part_feedback_submitted = True
                part_submitted = True
            except Exception as exc:
                submit_error = f"part: {exc}"
                log.warning("Brickognize part feedback failed for %s: %s", piece_uuid, exc)

    # Color feedback: use the passed corrected color, else this user's saved true
    # color. Equal to the prediction confirms it; different rejects it.
    corrected = payload.color_corrected_id
    if corrected is None:
        my_label = (
            db.query(PieceColorLabel)
            .filter(
                PieceColorLabel.machine_id == machine_id,
                PieceColorLabel.piece_uuid == piece_uuid,
                PieceColorLabel.labeler_id == current_user.id,
            )
            .first()
        )
        corrected = my_label.color_id if my_label is not None else None
    if corrected is not None:
        piece.color_corrected_id = str(corrected)
        if (
            not piece.color_feedback_submitted
            and piece.brickognize_color_rank is not None
            and piece.color_id
        ):
            try:
                is_correct = str(corrected) == str(piece.color_id)
                submit_color_feedback(
                    listing_id=piece.brickognize_listing_id,
                    color_id=piece.color_id,
                    color_rank=piece.brickognize_color_rank,
                    is_correct=is_correct,
                )
                piece.color_feedback_submitted = True
                color_submitted = True
            except Exception as exc:
                prev = f"{submit_error}; " if submit_error else ""
                submit_error = f"{prev}color: {exc}"
                log.warning("Brickognize color feedback failed for %s: %s", piece_uuid, exc)

    piece.correction_updated_at = datetime.now(timezone.utc)
    db.commit()
    return {
        "ok": True,
        "part_submitted": part_submitted,
        "color_submitted": color_submitted,
        "submit_error": submit_error,
        "correction": {
            "correctable": True,
            "part_correct": piece.part_correct,
            "color_corrected_id": piece.color_corrected_id,
            "part_feedback_submitted": bool(piece.part_feedback_submitted),
            "color_feedback_submitted": bool(piece.color_feedback_submitted),
        },
    }


@router.get("/queue")
def label_queue(
    only_unlabeled: bool = Query(True),
    limit: int = Query(40, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    _rl: None = Depends(rate_limit("labeling_list")),
) -> dict:
    """Pieces to color-label, newest first.

    With only_unlabeled=true (default) the labeler's already-labeled pieces drop
    out, so the client just re-fetches from the top as it works — no cursor. Set
    only_unlabeled=false to browse the full set (use offset to page)."""
    query = apply_piece_access(db, _labelable_query(db), current_user)

    if only_unlabeled:
        my_label = exists().where(
            and_(
                PieceColorLabel.machine_id == MachinePiece.machine_id,
                PieceColorLabel.piece_uuid == MachinePiece.piece_uuid,
                PieceColorLabel.labeler_id == current_user.id,
            )
        )
        query = query.filter(~my_label)

    query = query.order_by(
        MachinePiece.recorded_at.desc().nullslast(),
        MachinePiece.created_at.desc(),
    )
    pieces = query.offset(offset).limit(limit + 1).all()
    has_more = len(pieces) > limit
    pieces = pieces[:limit]

    machine_ids = {p.machine_id for p in pieces}
    machine_names = {
        mid: name
        for mid, name in db.query(Machine.id, Machine.name).filter(Machine.id.in_(machine_ids)).all()
    } if machine_ids else {}

    # Available crops for the returned pieces, keyed by piece_uuid.
    images_by_piece: dict[str, list[MachinePieceImage]] = {}
    piece_uuids = [p.piece_uuid for p in pieces]
    if piece_uuids:
        rows = (
            db.query(MachinePieceImage)
            .filter(
                MachinePieceImage.piece_uuid.in_(piece_uuids),
                MachinePieceImage.image_key.isnot(None),
            )
            .order_by(MachinePieceImage.seq.asc())
            .all()
        )
        for im in rows:
            if im.machine_id in machine_ids:
                images_by_piece.setdefault(im.piece_uuid, []).append(im)

    # This user's existing labels for the returned pieces (present when
    # only_unlabeled=false, so the UI can show/edit them).
    my_labels: dict[tuple, PieceColorLabel] = {}
    if piece_uuids:
        label_rows = (
            db.query(PieceColorLabel)
            .filter(
                PieceColorLabel.labeler_id == current_user.id,
                PieceColorLabel.piece_uuid.in_(piece_uuids),
            )
            .all()
        )
        for lb in label_rows:
            my_labels[(lb.machine_id, lb.piece_uuid)] = lb

    items = []
    for p in pieces:
        lb = my_labels.get((p.machine_id, p.piece_uuid))
        piece_images = images_by_piece.get(p.piece_uuid, [])
        items.append(
            {
                "machine_id": str(p.machine_id),
                "machine_name": machine_names.get(p.machine_id),
                "piece_uuid": p.piece_uuid,
                "recorded_at": p.recorded_at.isoformat() if p.recorded_at else None,
                "seen_at": p.seen_at.isoformat() if p.seen_at else None,
                "part": {"part_id": p.part_id, "part_name": p.part_name},
                # Suggested color from a plain pixel average of the crops —
                # recomputed each request, never stored.
                "pixel_guess": guess_piece_color(piece_images),
                "images": [
                    {"seq": im.seq, "source": im.source, "used": im.used, "score": im.score}
                    for im in piece_images
                ],
                "my_label": None if lb is None else {"color_id": lb.color_id, "notes": lb.notes},
            }
        )

    return {"items": items, "has_more": has_more}


class ColorLabelPayload(BaseModel):
    machine_id: UUID
    piece_uuid: str = Field(min_length=1)
    # A concrete BrickLink color, OR cant_tell=True for "I can't tell" (an
    # indeterminate-color answer). Exactly one of the two must be provided.
    color_id: int | None = None
    cant_tell: bool = False
    notes: str | None = None


@router.post("")
def submit_label(
    payload: ColorLabelPayload,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    """Create or update the current user's color label for a piece — either a
    concrete BrickLink color or an "I can't tell" answer."""
    if payload.cant_tell:
        color_id = None
    else:
        if payload.color_id is None:
            raise APIError(400, "A color_id or cant_tell is required", "COLOR_REQUIRED")
        valid_ids = {c["id"] for c in get_profile_catalog_service().list_bricklink_colors()}
        if payload.color_id not in valid_ids:
            raise APIError(400, f"Unknown BrickLink color id {payload.color_id}", "COLOR_ID_INVALID")
        color_id = payload.color_id

    if not piece_access_visible_by_key(db, current_user, payload.machine_id, payload.piece_uuid):
        raise APIError(404, "Piece not found", "PIECE_NOT_FOUND")

    now = datetime.now(timezone.utc)
    label = (
        db.query(PieceColorLabel)
        .filter(
            PieceColorLabel.machine_id == payload.machine_id,
            PieceColorLabel.piece_uuid == payload.piece_uuid,
            PieceColorLabel.labeler_id == current_user.id,
        )
        .first()
    )
    if label is None:
        label = PieceColorLabel(
            machine_id=payload.machine_id,
            piece_uuid=payload.piece_uuid,
            labeler_id=current_user.id,
            color_id=color_id,
            cant_tell=payload.cant_tell,
            notes=payload.notes,
        )
        db.add(label)
        created = True
    else:
        label.color_id = color_id
        label.cant_tell = payload.cant_tell
        label.notes = payload.notes
        label.updated_at = now
        created = False
    db.commit()

    labeled_by_me = (
        db.query(func.count(PieceColorLabel.id))
        .filter(PieceColorLabel.labeler_id == current_user.id)
        .scalar()
        or 0
    )
    return {"ok": True, "created": created, "labeled_by_me": int(labeled_by_me)}


@router.delete("/{machine_id}/{piece_uuid}")
def delete_label(
    machine_id: UUID,
    piece_uuid: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    label = (
        db.query(PieceColorLabel)
        .filter(
            PieceColorLabel.machine_id == machine_id,
            PieceColorLabel.piece_uuid == piece_uuid,
            PieceColorLabel.labeler_id == current_user.id,
        )
        .first()
    )
    if label is None:
        raise APIError(404, "Label not found", "LABEL_NOT_FOUND")
    db.delete(label)
    db.commit()
    return {"ok": True}


@router.get("/pieces/{machine_id}/{piece_uuid}/images/{seq}")
def get_piece_image(
    machine_id: UUID,
    piece_uuid: str,
    seq: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    _rl: None = Depends(rate_limit("labeling_image")),
) -> object:
    """Stream one synced crop. Any authenticated user may view it — color
    labeling is a community task over the whole synced fleet, not just the
    machine's owner (unlike the owner-gated /machines/... image route) — but only
    within the caller's visibility window (admins unrestricted)."""
    if not piece_access_visible_by_key(db, current_user, machine_id, piece_uuid):
        raise APIError(404, "Image not found", "IMAGE_NOT_FOUND")
    image = (
        db.query(MachinePieceImage)
        .filter(
            MachinePieceImage.machine_id == machine_id,
            MachinePieceImage.piece_uuid == piece_uuid,
            MachinePieceImage.seq == seq,
        )
        .first()
    )
    if image is None or not image.image_key:
        raise APIError(404, "Image not found", "IMAGE_NOT_FOUND")
    return serve_stored_file(image.image_key, headers={"Cache-Control": PIECE_IMAGE_CACHE_CONTROL})


# --- Same-machine labeled reference set ---------------------------------------
#
# The reviewing view shows a column of OTHER already-labeled pieces from the same
# machine, so a labeler can calibrate: "this machine's dark tan looks like THIS,
# so the lighter one I'm looking at is probably plain tan." Only human-labeled
# pieces (ground truth), never model outputs. This intentionally reaches past a
# reviewer's normal visibility window — the exemplars are already vetted, and
# seeing the machine's full color range is the whole point — but stays gated:
# members still only see machines they own.


def _labeled_reference_visible(db: Session, user: User, machine_id: UUID, piece_uuid: str) -> bool:
    """Gate for a same-machine labeled reference piece/image. Admins and machine
    owners always. Reviewers may view any piece that actually carries a human
    color label (the deliberate window bypass — bounded to vetted exemplars)."""
    if is_unrestricted(user.role):
        return True
    if _machine_owned_by(db, machine_id, user):
        return True
    if user.role == "reviewer":
        return (
            db.query(PieceColorLabel.id)
            .filter(
                PieceColorLabel.machine_id == machine_id,
                PieceColorLabel.piece_uuid == piece_uuid,
                PieceColorLabel.color_id.isnot(None),
            )
            .first()
            is not None
        )
    return False


def _lab_hue_key(rgb_hex: str | None) -> tuple[int, float, float]:
    """Sort key that reads a color column as a gradient: near-neutral grays first
    (by lightness), then chromatic colors by hue angle. Keeps look-alike colors
    (tan / dark tan) adjacent so the eye can compare them."""
    if not rgb_hex:
        return (2, 0.0, 0.0)
    h = rgb_hex.replace("#", "")
    if len(h) < 6:
        return (2, 0.0, 0.0)
    try:
        rgb = np.array([int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)], dtype=np.float64)
    except ValueError:
        return (2, 0.0, 0.0)
    lab = _srgb_to_lab(rgb)
    L, a, b = float(lab[0]), float(lab[1]), float(lab[2])
    if math.hypot(a, b) < 8:
        return (0, L, 0.0)
    return (1, math.atan2(b, a), L)


@router.get("/machine/{machine_id}/labeled-pieces")
def machine_labeled_pieces(
    machine_id: UUID,
    anchor_piece: str = Query(..., min_length=1),
    exclude_piece: str | None = Query(None),
    limit: int = Query(200, ge=1, le=400),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    _rl: None = Depends(rate_limit("labeling_list")),
) -> dict:
    """Other human-labeled pieces on the same machine, one per piece (the
    most-agreed color), sorted into a hue gradient — the color-range reference
    column on the labeling view. Gated on access to the anchor piece being
    reviewed; the reference set itself ignores a reviewer's window on purpose."""
    if not piece_access_visible_by_key(db, current_user, machine_id, anchor_piece):
        raise APIError(404, "Piece not found", "PIECE_NOT_FOUND")

    rows = (
        db.query(PieceColorLabel.piece_uuid, PieceColorLabel.color_id, func.count().label("n"))
        .filter(
            PieceColorLabel.machine_id == machine_id,
            PieceColorLabel.color_id.isnot(None),
        )
        .group_by(PieceColorLabel.piece_uuid, PieceColorLabel.color_id)
        .all()
    )
    # Per piece, the color with the most labeler agreement (ties → lower id).
    best: dict[str, tuple[int, int]] = {}
    for puid, cid, n in rows:
        if exclude_piece and puid == exclude_piece:
            continue
        if cid is None:
            continue
        cur = best.get(puid)
        if cur is None or n > cur[0] or (n == cur[0] and cid < cur[1]):
            best[puid] = (int(n), int(cid))
    if not best:
        return {"items": [], "total": 0}

    piece_uuids = list(best.keys())
    thumb: dict[str, int] = dict(
        db.query(MachinePieceImage.piece_uuid, func.min(MachinePieceImage.seq))
        .filter(
            MachinePieceImage.machine_id == machine_id,
            MachinePieceImage.piece_uuid.in_(piece_uuids),
            MachinePieceImage.image_key.isnot(None),
        )
        .group_by(MachinePieceImage.piece_uuid)
        .all()
    )
    palette = {c["id"]: c for c in get_profile_catalog_service().list_bricklink_colors()}

    items = []
    for puid, (n, cid) in best.items():
        if puid not in thumb:
            continue  # no viewable crop — skip (nothing to show in the column)
        col = palette.get(cid)
        rgb = col.get("rgb") if col else None
        items.append(
            {
                "piece_uuid": puid,
                "thumb_seq": thumb[puid],
                "color_id": cid,
                "color_name": col["name"] if col else str(cid),
                "rgb": rgb,
                "is_trans": bool(col.get("is_trans", False)) if col else False,
                "label_count": n,
            }
        )
    total = len(items)
    items.sort(key=lambda it: _lab_hue_key(it["rgb"]))
    return {"items": items[:limit], "total": total}


@router.get("/machine/{machine_id}/labeled-pieces/{piece_uuid}/image")
def get_reference_image(
    machine_id: UUID,
    piece_uuid: str,
    seq: int = Query(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    _rl: None = Depends(rate_limit("labeling_image")),
) -> object:
    """Thumbnail for a same-machine labeled reference piece. Gated by
    ``_labeled_reference_visible`` — the reviewer window bypass, bounded to
    pieces that actually carry a human label."""
    if not _labeled_reference_visible(db, current_user, machine_id, piece_uuid):
        raise APIError(404, "Image not found", "IMAGE_NOT_FOUND")
    image = (
        db.query(MachinePieceImage)
        .filter(
            MachinePieceImage.machine_id == machine_id,
            MachinePieceImage.piece_uuid == piece_uuid,
            MachinePieceImage.seq == seq,
        )
        .first()
    )
    if image is None or not image.image_key:
        raise APIError(404, "Image not found", "IMAGE_NOT_FOUND")
    return serve_stored_file(image.image_key, headers={"Cache-Control": PIECE_IMAGE_CACHE_CONTROL})


# --- Same-piece-across-channels labeling -------------------------------------
#
# A second, independent labeling task layered on the same page: which upstream
# C2/C3 crops (machine_channel_crops) are the SAME physical piece as this
# classified piece. The time/angle heuristic (services.channel_crop_lookup,
# shared byte-for-byte with the sorter) proposes a ranked candidate set with a
# pre-selected prediction; the labeler keeps/drops/adds and accepts. Stored as
# piece_crop_links (+ members) — training data for a future tracking model,
# saved separately from the color label (accepting one does not touch the other).


def _my_link_members(db: Session, machine_id: UUID, piece_uuid: str, labeler_id: UUID) -> list[dict]:
    link = (
        db.query(PieceCropLink)
        .filter(
            PieceCropLink.machine_id == machine_id,
            PieceCropLink.piece_uuid == piece_uuid,
            PieceCropLink.labeler_id == labeler_id,
        )
        .first()
    )
    if link is None:
        return []
    members = db.query(PieceCropLinkMember).filter(PieceCropLinkMember.link_id == link.id).all()
    return [
        {"local_id": m.crop_local_id, "is_same": m.is_same, "was_predicted": m.was_predicted}
        for m in members
    ]


def _ai_prediction(db: Session, machine_id: UUID, piece_uuid: str) -> PieceCropAiPrediction | None:
    return (
        db.query(PieceCropAiPrediction)
        .filter(
            PieceCropAiPrediction.machine_id == machine_id,
            PieceCropAiPrediction.piece_uuid == piece_uuid,
        )
        .first()
    )


def _possible_crops_result(db: Session, machine_id: UUID, piece_uuid: str, labeler_id: UUID) -> dict:
    """The heuristic's time-window candidate set for a piece, annotated with this
    labeler's saved selection and whichever same-piece prediction is in force.

    Three prediction sources, in precedence order:
    - `ai`    — a stored vision-model (VLM) prediction exists for this piece (an
                explicit per-piece oracle run); `ai_same` per candidate.
    - `model` — a link matcher model is active; it scores every candidate crop
                (`model_score`) and its picks (`model_same`, score ≥ threshold)
                supersede the heuristic. Candidates are re-ranked by that score.
    - `heuristic` — neither; the time/angle `predicted` flag drives selection.

    Each candidate always keeps the heuristic's `predicted` flag untouched — it
    feeds the was_predicted training signal regardless of which source the UI
    pre-selects from."""
    result = find_possible_crops(db, machine_id, piece_uuid)
    result["my_link"] = _my_link_members(db, machine_id, piece_uuid, labeler_id)
    candidates = result.get("candidates", [])

    def _reset(c: dict) -> None:
        c["ai_same"] = None
        c["model_same"] = None
        c["model_score"] = None

    ai = _ai_prediction(db, machine_id, piece_uuid)
    model_pred = link_predictor.predict(db, machine_id, piece_uuid, candidates) if ai is None else None

    result["ai_model"] = None
    result["ai_reasoning"] = None
    result["link_model"] = None

    if ai is not None:
        same_ids = set(ai.same_local_ids or [])
        shown_ids = set(ai.candidate_local_ids or [])
        for c in candidates:
            _reset(c)
            c["ai_same"] = (c["local_id"] in same_ids) if c["local_id"] in shown_ids else None
        result["prediction_source"] = "ai"
        result["ai_model"] = ai.model
        result["ai_reasoning"] = ai.reasoning
    elif model_pred is not None:
        scores = model_pred["scores"]
        threshold = model_pred["threshold"]
        for c in candidates:
            _reset(c)
            s = scores.get(c["local_id"])
            c["model_score"] = round(s, 3) if s is not None else None
            c["model_same"] = (s >= threshold) if s is not None else None
        # re-rank by model score (scored crops first, best first); unscored keep order
        candidates.sort(key=lambda c: (c["model_score"] is not None, c["model_score"] or 0.0), reverse=True)
        result["prediction_source"] = "model"
        result["link_model"] = model_pred["model_name"]
    else:
        for c in candidates:
            _reset(c)
        result["prediction_source"] = "heuristic"

    # This labeler's per-image quality flags for the candidate crops, keyed by
    # local_id, so the star / not-good-enough marks persist on the grid.
    local_ids = [c["local_id"] for c in candidates]
    quality_labels = (
        {
            lbl.crop_local_id: lbl
            for lbl in db.query(ImageQualityLabel).filter(
                ImageQualityLabel.crop_kind == CROP_KIND_CHANNEL_CROP,
                ImageQualityLabel.machine_id == machine_id,
                ImageQualityLabel.crop_local_id.in_(local_ids),
                ImageQualityLabel.labeler_id == labeler_id,
            )
        }
        if local_ids
        else {}
    )
    for c in candidates:
        c.update(_image_quality_state(quality_labels.get(c["local_id"])))
    return result


@router.get("/possible-crops/{machine_id}/{piece_uuid}")
def possible_crops(
    machine_id: UUID,
    piece_uuid: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    _rl: None = Depends(rate_limit("labeling_list")),
) -> dict:
    """Ranked "possibly the same piece" C2/C3 candidates for a classified piece,
    plus this labeler's saved selection (if any) and any stored AI prediction."""
    if not piece_access_visible_by_key(db, current_user, machine_id, piece_uuid):
        raise APIError(404, "Piece not found", "PIECE_NOT_FOUND")
    return _possible_crops_result(db, machine_id, piece_uuid, current_user.id)


class AiPredictRequest(BaseModel):
    model: str | None = None


@router.post("/possible-crops/{machine_id}/{piece_uuid}/ai-predict")
def run_ai_predict(
    machine_id: UUID,
    piece_uuid: str,
    payload: AiPredictRequest | None = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    _csrf: None = Depends(verify_csrf),
) -> dict:
    """Run the vision model NOW to guess which candidate crops are the same piece,
    store it, and return the refreshed candidate set with the AI's picks applied.

    Open to admins and to any labeler who has added their own OpenRouter key
    (which pays for the call) — mirroring the sample teacher's key gating."""
    if not piece_access_visible_by_key(db, current_user, machine_id, piece_uuid):
        raise APIError(404, "Piece not found", "PIECE_NOT_FOUND")
    if current_user.role != "admin" and not current_user.openrouter_configured:
        raise APIError(
            403,
            "Add your OpenRouter API key on your profile to run AI predictions.",
            "OPENROUTER_KEY_MISSING",
        )
    api_key = decrypt_secret(current_user.openrouter_api_key_encrypted)
    if not api_key:
        raise APIError(
            400,
            "Set your OpenRouter API key on your profile to run AI predictions.",
            "OPENROUTER_KEY_MISSING",
        )

    model = (payload.model if payload else None) or DEFAULT_MATCH_MODEL
    try:
        result = match_piece_crops(db, machine_id, piece_uuid, api_key, model=model)
    except AiMatchError as exc:
        raise APIError(422, f"AI prediction could not run: {exc}", "AI_PREDICT_FAILED") from exc
    except Exception as exc:  # noqa: BLE001
        raise APIError(502, f"AI prediction failed: {exc}", "AI_PREDICT_ERROR") from exc

    store_prediction(db, machine_id, piece_uuid, result)
    db.commit()

    refreshed = _possible_crops_result(db, machine_id, piece_uuid, current_user.id)
    refreshed["ai_cost_usd"] = result.get("cost_usd")
    refreshed["ai_elapsed_ms"] = result.get("elapsed_ms")
    return refreshed


@router.get("/channel-crops/{machine_id}/{local_id}/image")
def get_channel_crop_image(
    machine_id: UUID,
    local_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    _rl: None = Depends(rate_limit("labeling_image")),
) -> object:
    """Stream one upstream-channel crop. Any authenticated user may view it —
    same-piece labeling is a community task over the synced fleet, like the color
    crops above (unlike the owner-gated /machines/... channel-crop route) — but
    only within the caller's visibility window (admins unrestricted). Channel
    crops are keyed by a guessable integer local_id, so this gate matters."""
    crop = (
        db.query(MachineChannelCrop)
        .filter(
            MachineChannelCrop.machine_id == machine_id,
            MachineChannelCrop.local_id == local_id,
        )
        .first()
    )
    if crop is None or not crop.image_key or not channel_crop_access_visible(db, current_user, crop):
        raise APIError(404, "Crop image not found", "CROP_IMAGE_NOT_FOUND")
    return serve_stored_file(crop.image_key, headers={"Cache-Control": PIECE_IMAGE_CACHE_CONTROL})


class CropLinkMemberIn(BaseModel):
    local_id: int
    is_same: bool
    was_predicted: bool = False


class CropLinkPayload(BaseModel):
    machine_id: UUID
    piece_uuid: str = Field(min_length=1)
    arrival_ts: float | None = None
    members: list[CropLinkMemberIn]


@router.post("/piece-crop-link")
def save_piece_crop_link(
    payload: CropLinkPayload,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    """Create or replace the current user's same-piece crop selection for a
    piece. Sent the full presented candidate set (each with the labeler's verdict
    and whether it was a prediction); replaces any prior members wholesale."""
    if not piece_access_visible_by_key(db, current_user, payload.machine_id, payload.piece_uuid):
        raise APIError(404, "Piece not found", "PIECE_NOT_FOUND")

    now = datetime.now(timezone.utc)
    link = (
        db.query(PieceCropLink)
        .filter(
            PieceCropLink.machine_id == payload.machine_id,
            PieceCropLink.piece_uuid == payload.piece_uuid,
            PieceCropLink.labeler_id == current_user.id,
        )
        .first()
    )
    if link is None:
        link = PieceCropLink(
            machine_id=payload.machine_id,
            piece_uuid=payload.piece_uuid,
            labeler_id=current_user.id,
            arrival_ts=payload.arrival_ts,
        )
        db.add(link)
        db.flush()
        created = True
    else:
        link.arrival_ts = payload.arrival_ts
        link.updated_at = now
        db.query(PieceCropLinkMember).filter(PieceCropLinkMember.link_id == link.id).delete()
        created = False

    # Dedup on local_id (last verdict wins) — the unique constraint would reject
    # a repeat, and the client shouldn't present the same crop twice anyway.
    seen: dict[int, CropLinkMemberIn] = {}
    for m in payload.members:
        seen[m.local_id] = m
    for m in seen.values():
        db.add(
            PieceCropLinkMember(
                link_id=link.id,
                crop_local_id=m.local_id,
                is_same=m.is_same,
                was_predicted=m.was_predicted,
            )
        )
    db.commit()

    same_count = sum(1 for m in seen.values() if m.is_same)
    return {"ok": True, "created": created, "same_count": same_count, "member_count": len(seen)}


@router.delete("/piece-crop-link/{machine_id}/{piece_uuid}")
def delete_piece_crop_link(
    machine_id: UUID,
    piece_uuid: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    link = (
        db.query(PieceCropLink)
        .filter(
            PieceCropLink.machine_id == machine_id,
            PieceCropLink.piece_uuid == piece_uuid,
            PieceCropLink.labeler_id == current_user.id,
        )
        .first()
    )
    if link is None:
        raise APIError(404, "Crop link not found", "CROP_LINK_NOT_FOUND")
    db.delete(link)
    db.commit()
    return {"ok": True}


# --- Reject a piece's bbox sample --------------------------------------------
#
# Flags an attribute of the sample itself (as opposed to labeling color /
# same-piece). Every code here currently counts as a reject, so a flagged piece
# drops out of the rejecter's queue (see list_pieces) — the sample data is kept,
# it's just handled. "assembly" (parts built into one unit) and "pieces_entangled"
# (separate parts stuck together) are reject reasons too. "blurry" is sorter-only
# and not offered in the Hive labeler UI, so it stays out of this set.
_REJECT_REASONS = {"no_piece", "multiple_pieces", "not_lego", "assembly", "pieces_entangled"}


class RejectionPayload(BaseModel):
    machine_id: UUID
    piece_uuid: str = Field(min_length=1)
    reasons: list[str] = Field(min_length=1)


@router.post("/piece-rejection")
def save_piece_rejection(
    payload: RejectionPayload,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    """Create or update this user's rejection of a piece's bbox sample, with one
    or more reason codes."""
    reasons = [r for r in dict.fromkeys(payload.reasons) if r in _REJECT_REASONS]
    if not reasons:
        raise APIError(400, "No valid rejection reasons", "REJECT_REASONS_INVALID")

    if not piece_access_visible_by_key(db, current_user, payload.machine_id, payload.piece_uuid):
        raise APIError(404, "Piece not found", "PIECE_NOT_FOUND")

    now = datetime.now(timezone.utc)
    rejection = (
        db.query(PieceRejection)
        .filter(
            PieceRejection.machine_id == payload.machine_id,
            PieceRejection.piece_uuid == payload.piece_uuid,
            PieceRejection.labeler_id == current_user.id,
        )
        .first()
    )
    if rejection is None:
        rejection = PieceRejection(
            machine_id=payload.machine_id,
            piece_uuid=payload.piece_uuid,
            labeler_id=current_user.id,
            reasons=reasons,
        )
        db.add(rejection)
        created = True
    else:
        rejection.reasons = reasons
        rejection.updated_at = now
        created = False
    db.commit()
    return {"ok": True, "created": created, "reasons": reasons}


@router.delete("/piece-rejection/{machine_id}/{piece_uuid}")
def delete_piece_rejection(
    machine_id: UUID,
    piece_uuid: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    rejection = (
        db.query(PieceRejection)
        .filter(
            PieceRejection.machine_id == machine_id,
            PieceRejection.piece_uuid == piece_uuid,
            PieceRejection.labeler_id == current_user.id,
        )
        .first()
    )
    if rejection is None:
        raise APIError(404, "Rejection not found", "REJECTION_NOT_FOUND")
    db.delete(rejection)
    db.commit()
    return {"ok": True}


# --- Per-image quality labels ------------------------------------------------
#
# A labeler's judgement of a single CROP (not the whole piece): a `high_quality`
# star and/or "not good enough for classification" reason flags. Recorded per
# (image, labeler) so the flags stay queryable columns for building image-quality
# training data. Covers both the piece's own crops (machine_piece_images, keyed
# by seq) and the same-piece channel candidates (machine_channel_crops, keyed by
# local_id) via crop_kind. Saved state is echoed back per-image in piece_detail
# and _possible_crops_result.


def _image_quality_state(label: "ImageQualityLabel | None") -> dict:
    """The per-image flags for a read response — all False when the crop is unmarked."""
    if label is None:
        return {f: False for f in IMAGE_QUALITY_FLAG_FIELDS}
    return {f: bool(getattr(label, f)) for f in IMAGE_QUALITY_FLAG_FIELDS}


class ImageQualityPayload(BaseModel):
    machine_id: UUID
    # 'piece_image' (needs piece_uuid + seq) or 'channel_crop' (needs crop_local_id).
    crop_kind: str
    piece_uuid: str | None = None
    seq: int | None = None
    crop_local_id: int | None = None
    high_quality: bool = False
    low_resolution: bool = False
    motion_blur: bool = False
    not_contained: bool = False
    no_piece_in_frame: bool = False
    other_bad: bool = False


@router.post("/image-quality")
def submit_image_quality(
    payload: ImageQualityPayload,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    """Upsert this user's quality flags for one crop. The client posts the whole
    flag set each time; when every flag is False the row is deleted, so an unmarked
    crop leaves nothing behind."""
    flags = {f: bool(getattr(payload, f)) for f in IMAGE_QUALITY_FLAG_FIELDS}

    if payload.crop_kind == CROP_KIND_PIECE_IMAGE:
        if not payload.piece_uuid or payload.seq is None:
            raise APIError(400, "piece_uuid and seq are required", "IMAGE_KEY_INVALID")
        if not piece_access_visible_by_key(db, current_user, payload.machine_id, payload.piece_uuid):
            raise APIError(404, "Piece not found", "PIECE_NOT_FOUND")
        key = and_(
            ImageQualityLabel.crop_kind == CROP_KIND_PIECE_IMAGE,
            ImageQualityLabel.machine_id == payload.machine_id,
            ImageQualityLabel.piece_uuid == payload.piece_uuid,
            ImageQualityLabel.seq == payload.seq,
            ImageQualityLabel.labeler_id == current_user.id,
        )
        key_cols = {"piece_uuid": payload.piece_uuid, "seq": payload.seq, "crop_local_id": None}
    elif payload.crop_kind == CROP_KIND_CHANNEL_CROP:
        if payload.crop_local_id is None:
            raise APIError(400, "crop_local_id is required", "IMAGE_KEY_INVALID")
        crop = (
            db.query(MachineChannelCrop)
            .filter(
                MachineChannelCrop.machine_id == payload.machine_id,
                MachineChannelCrop.local_id == payload.crop_local_id,
            )
            .first()
        )
        if crop is None or not channel_crop_access_visible(db, current_user, crop):
            raise APIError(404, "Crop not found", "CROP_NOT_FOUND")
        key = and_(
            ImageQualityLabel.crop_kind == CROP_KIND_CHANNEL_CROP,
            ImageQualityLabel.machine_id == payload.machine_id,
            ImageQualityLabel.crop_local_id == payload.crop_local_id,
            ImageQualityLabel.labeler_id == current_user.id,
        )
        key_cols = {"piece_uuid": None, "seq": None, "crop_local_id": payload.crop_local_id}
    else:
        raise APIError(400, f"Unknown crop_kind {payload.crop_kind}", "CROP_KIND_INVALID")

    label = db.query(ImageQualityLabel).filter(key).first()

    if not any(flags.values()):
        if label is not None:
            db.delete(label)
            db.commit()
            return {"ok": True, "deleted": True}
        return {"ok": True, "deleted": False}

    if label is None:
        label = ImageQualityLabel(
            machine_id=payload.machine_id,
            labeler_id=current_user.id,
            crop_kind=payload.crop_kind,
            **key_cols,
            **flags,
        )
        db.add(label)
        created = True
    else:
        for f, v in flags.items():
            setattr(label, f, v)
        label.updated_at = datetime.now(timezone.utc)
        created = False
    db.commit()
    return {"ok": True, "created": created}


# --- Correcting a piece's part (mold) ----------------------------------------
#
# The part sibling of the color label above. machine_pieces.part_correct could
# only record that Brickognize got the mold wrong; it had nowhere to say what the
# piece actually is, and a piece that came back unidentified (part_id NULL) had
# nothing to record at all. A labeler searches the parts catalog and picks the
# true mold; like color, each labeler gets their own row so several people can
# correct the same piece independently.
#
# Stored separately from the color label and the crop link — accepting one does
# not touch the others. Submitting the verdict on to Brickognize's feedback API
# stays the caller's move (POST .../brickognize-feedback), mirroring how the UI
# reports a color disagreement.


class PartLabelPayload(BaseModel):
    machine_id: UUID
    piece_uuid: str = Field(min_length=1)
    # A catalog part_num, OR cant_tell=True for "I can't identify this mold".
    # Exactly one of the two must be provided.
    part_num: str | None = None
    cant_tell: bool = False
    notes: str | None = None


@router.post("/piece-part-label")
def submit_part_label(
    payload: PartLabelPayload,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    """Create or update the current user's part correction for a piece — either a
    concrete catalog part or an "I can't tell" answer."""
    catalog = get_profile_catalog_service()
    part: dict | None = None
    if payload.cant_tell:
        part_num = None
    else:
        if not payload.part_num:
            raise APIError(400, "A part_num or cant_tell is required", "PART_REQUIRED")
        part = catalog.part_summary(payload.part_num)
        if part is None:
            raise APIError(400, f"Unknown part {payload.part_num}", "PART_NUM_INVALID")
        part_num = part["part_num"]

    if not piece_access_visible_by_key(db, current_user, payload.machine_id, payload.piece_uuid):
        raise APIError(404, "Piece not found", "PIECE_NOT_FOUND")

    # Snapshot what the machine had predicted, so the label still reads as
    # "human disagreed with X" if the piece is later re-synced.
    predicted_part_num = (
        db.query(MachinePiece.part_id)
        .filter(
            MachinePiece.machine_id == payload.machine_id,
            MachinePiece.piece_uuid == payload.piece_uuid,
        )
        .scalar()
    )

    now = datetime.now(timezone.utc)
    label = (
        db.query(PiecePartLabel)
        .filter(
            PiecePartLabel.machine_id == payload.machine_id,
            PiecePartLabel.piece_uuid == payload.piece_uuid,
            PiecePartLabel.labeler_id == current_user.id,
        )
        .first()
    )
    if label is None:
        label = PiecePartLabel(
            machine_id=payload.machine_id,
            piece_uuid=payload.piece_uuid,
            labeler_id=current_user.id,
            part_num=part_num,
            cant_tell=payload.cant_tell,
            predicted_part_num=predicted_part_num,
            notes=payload.notes,
        )
        db.add(label)
        created = True
    else:
        label.part_num = part_num
        label.cant_tell = payload.cant_tell
        label.predicted_part_num = predicted_part_num
        label.notes = payload.notes
        label.updated_at = now
        created = False
    db.commit()

    part_labeled_by_me = (
        db.query(func.count(PiecePartLabel.id))
        .filter(PiecePartLabel.labeler_id == current_user.id)
        .scalar()
        or 0
    )
    return {
        "ok": True,
        "created": created,
        "part": part,
        "part_labeled_by_me": int(part_labeled_by_me),
    }


@router.delete("/piece-part-label/{machine_id}/{piece_uuid}")
def delete_part_label(
    machine_id: UUID,
    piece_uuid: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    label = (
        db.query(PiecePartLabel)
        .filter(
            PiecePartLabel.machine_id == machine_id,
            PiecePartLabel.piece_uuid == piece_uuid,
            PiecePartLabel.labeler_id == current_user.id,
        )
        .first()
    )
    if label is None:
        raise APIError(404, "Part label not found", "PART_LABEL_NOT_FOUND")
    db.delete(label)
    db.commit()
    return {"ok": True}
