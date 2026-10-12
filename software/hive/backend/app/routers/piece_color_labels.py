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
from datetime import datetime, timezone
from uuid import UUID

import numpy as np
from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy import and_, case, exists, func
from sqlalchemy.orm import Session

from app.database import tune_for_aggregates
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
from app.models.machine_piece_prediction import MachinePiecePrediction
from app.models.machine_piece_rejection_reason import MachinePieceRejectionReason
from app.models.piece_color_label import PieceColorLabel
from app.models.piece_crop_ai_prediction import PieceCropAiPrediction
from app.models.piece_crop_link import PieceCropLink, PieceCropLinkMember
from app.models.piece_part_label import PiecePartLabel
from app.models.piece_rejection import PieceRejection
from app.models.user import User
from app.schemas.likely_colors import LikelyColorsResponse
from app.services import color_rank, likely_colors
from app.services.brickognize_feedback import submit_color_feedback, submit_part_feedback
from app.services.channel_crop_lookup import find_possible_crops
from app.services import review_queue
from app.services.review_queue import restrict_to_machines
from app.services.piece_color_guess import CropRef, color_guesses
from app.services.piece_link_scores import link_scores
from app.services.piece_crop_ai_matcher import (
    DEFAULT_MATCH_MODEL,
    AiMatchError,
    match_piece_crops,
    store_prediction,
)
from app.services.access_window import (
    _machine_owned_by,
    channel_crop_access_visible,
    is_unrestricted,
    piece_access_visible,
    piece_access_visible_by_key,
    scope_to_piece_access,
)
from app.services.pixel_color import _srgb_to_lab
from app.services.profile_catalog import get_profile_catalog_service
from app.services.rate_limit import rate_limit
from app.services.secrets import decrypt_secret
from app.services.storage import serve_stored_file
from app.services.storage_backend import get_backend

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/labeling", tags=["labeling"])

PIECE_IMAGE_CACHE_CONTROL = "public, max-age=31536000, immutable"


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
    """The BrickLink colors a piece can be labeled with."""
    return ColorsResponse(results=[ColorOut(**c) for c in likely_colors.labelable_palette()])


@router.get("/likely-colors", response_model=LikelyColorsResponse)
def labeling_likely_colors(
    part_id: str | None = Query(None, max_length=64),
    predictions: str | None = Query(None, max_length=400),
    limit: int = Query(likely_colors.DEFAULT_LIMIT, ge=1, le=likely_colors.DEFAULT_LIMIT),
    _user: User = Depends(get_current_user),
    _rl: None = Depends(rate_limit("labeling_list")),
) -> dict:
    """Every labelable color ranked for a piece: how near each is to the
    predictions (`predictions=<BrickLink color id>:<score>,...`, the machine's
    and Hive's own), times how likely the part exists in it on BrickLink, with
    the part's sale numbers per color. The same ranking machines get. Public
    catalog data, so no per-machine access gate."""
    return likely_colors.likely_colors(part_id or None, color_rank.parse_predictions(predictions), limit)


@router.get("/stats")
def label_stats(
    machine_id: list[UUID] | None = Query(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    _rl: None = Depends(rate_limit("labeling_list")),
) -> dict:
    """Dashboard rollup: overall progress plus a histogram of how many distinct
    labelers have color-labeled each piece (drives the coverage chart). Scoped to
    one machine when machine_id is given, matching the grid's machine filter, and
    to the caller's visibility window (so a member's dashboard reflects only their
    slice, not global fleet totals; admins see everything). machine_id may be
    given several times, for several machines."""
    tune_for_aggregates(db)
    # Kept per machine by the labeling-queue worker; this only sums.
    total_labelable = review_queue.piece_count(db, current_user, machine_id)

    def _color_q():
        q = restrict_to_machines(db.query(PieceColorLabel), PieceColorLabel.machine_id, machine_id)
        return scope_to_piece_access(db, q, current_user, PieceColorLabel.machine_id, PieceColorLabel.piece_uuid)

    def _crop_q():
        q = restrict_to_machines(db.query(PieceCropLink), PieceCropLink.machine_id, machine_id)
        return scope_to_piece_access(db, q, current_user, PieceCropLink.machine_id, PieceCropLink.piece_uuid)

    def _part_q():
        q = restrict_to_machines(db.query(PiecePartLabel), PiecePartLabel.machine_id, machine_id)
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
    bucket = case((per_piece.c.n > 3, 3), else_=per_piece.c.n)
    buckets = dict(db.query(bucket.label("bucket"), func.count().label("cnt")).group_by(bucket).all())
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


@router.get("/color-coverage")
def color_coverage(
    machine_id: list[UUID] | None = Query(None),
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
    scoped = restrict_to_machines(scoped, PieceColorLabel.machine_id, machine_id)

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

    palette = likely_colors.labelable_palette()
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


# A color is "rare" (under-covered) if this many or fewer distinct pieces have
# been labeled with it. A predicted color counts as a rare-color *candidate* when
# it sits within this CIE-Lab distance of some rare color — the pixel/model may
# have landed on a nearby common color when the piece is actually the rare one.
_RARE_PIECE_THRESHOLD = 3
_RARE_LAB_NEAR = 22.0


def _rare_candidate_color_ids(db: Session, user: User, machine_ids: list[UUID] | None) -> set[str]:
    """BrickLink color ids (as stored on the piece — strings) that are worth
    surfacing when hunting rare colors: every under-covered color, plus any color
    close to one in Lab space. Pieces whose Brickognize color prediction is one of
    these are the ones most likely to actually be a rare color the model fumbled."""
    scoped = scope_to_piece_access(
        db, db.query(PieceColorLabel), user, PieceColorLabel.machine_id, PieceColorLabel.piece_uuid
    ).filter(PieceColorLabel.color_id.isnot(None))  # "I can't tell" answers aren't a color
    scoped = restrict_to_machines(scoped, PieceColorLabel.machine_id, machine_ids)
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

    palette = [c for c in likely_colors.labelable_palette() if c.get("rgb")]
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
    cursor: str | None = Query(None),
    machine_id: list[UUID] | None = Query(None),
    with_candidates: bool = Query(False),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    _rl: None = Depends(rate_limit("labeling_list")),
) -> dict:
    """One page of labelable pieces, with per-piece label/crop-link/part-label
    counts, for the labeling grid. Sorts: priority (has same-piece candidates
    first, then fewest color labels — spreads effort where it's useful), recent,
    oldest, least/most_color, least/most_crop, least/most_part, rare_color,
    unidentified (pieces the machine couldn't name — the part-correction queue),
    needs_me (this user's unlabeled first). machine_id (one or several) keeps
    only those machines' pieces; with_candidates only pieces that have same-piece
    candidate crops.

    Pages by keyset: pass the previous page's next_cursor to get the one after
    it (null at the end). Served from the labeling queue through
    services.review_queue, so every page costs the same."""
    if sort not in review_queue.PIECE_SORTS:
        sort = "priority"
    tune_for_aggregates(db)
    rare_ids = _rare_candidate_color_ids(db, current_user, machine_id) if sort == "rare_color" else None
    rows, next_cursor = review_queue.piece_page(
        db,
        current_user,
        sort=sort,
        limit=limit,
        cursor=cursor,
        machine_ids=machine_id,
        with_candidates=with_candidates,
        rare_color_ids=rare_ids,
    )
    return {
        "items": review_queue.piece_cards(db, current_user, rows),
        "has_more": next_cursor is not None,
        "next_cursor": next_cursor,
        "sort": sort,
    }


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
    machine_predictions = (
        db.query(MachinePiecePrediction)
        .filter(
            MachinePiecePrediction.machine_id == machine_id,
            MachinePiecePrediction.piece_uuid == piece_uuid,
        )
        .order_by(MachinePiecePrediction.kind, MachinePiecePrediction.request, MachinePiecePrediction.rank)
        .all()
    )
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
    backend = get_backend()
    # Last of the reads: when the guesses are not stored yet this commits and
    # reads the crops from storage.
    pixel_guess, model_prediction = color_guesses(
        db,
        machine_id,
        piece_uuid,
        [CropRef(im.seq, im.image_key, bool(im.used), im.channel) for im in images],
    )
    return {
        "machine_id": str(machine_id),
        "machine_name": machine_name,
        "piece_uuid": piece_uuid,
        "part": {"part_id": piece.part_id, "part_name": piece.part_name},
        "recorded_at": piece.recorded_at.isoformat() if piece.recorded_at else None,
        "seen_at": piece.seen_at.isoformat() if piece.seen_at else None,
        "pixel_guess": pixel_guess,
        # Learned prediction from the globally-active color model, if one is set.
        # None → the UI falls back to the pixel-average guess alone.
        "model_prediction": model_prediction,
        "images": [
            {
                "seq": im.seq,
                "url": backend.presigned_get_url(im.image_key),
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
            "color_confidence": piece.color_confidence,
        },
        # Every ranked part and colour answer the machine got for the piece
        # (each request's, applied or not), ordered by kind, request, rank.
        "machine_predictions": [
            {
                "request": p.request,
                "provider": p.provider,
                "model": p.model,
                "kind": p.kind,
                "rank": p.rank,
                "value_id": p.value_id,
                "value_name": p.value_name,
                "score": p.score,
                "applied": bool(p.applied),
            }
            for p in machine_predictions
        ],
        "correction": {
            **_my_brickognize_correction(db, piece, part_label, label),
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


def _part_feedback_sent(db: Session, piece: MachinePiece) -> bool:
    """Brickognize already has a part verdict on this piece: the machine's
    operator sent one, or a Hive labeler did."""
    if piece.part_feedback_submitted:
        return True
    return db.query(
        exists().where(
            PiecePartLabel.machine_id == piece.machine_id,
            PiecePartLabel.piece_uuid == piece.piece_uuid,
            PiecePartLabel.brickognize_feedback_at.isnot(None),
        )
    ).scalar()


def _color_feedback_sent(db: Session, piece: MachinePiece) -> bool:
    if piece.color_feedback_submitted:
        return True
    return db.query(
        exists().where(
            PieceColorLabel.machine_id == piece.machine_id,
            PieceColorLabel.piece_uuid == piece.piece_uuid,
            PieceColorLabel.brickognize_feedback_at.isnot(None),
        )
    ).scalar()


def _my_brickognize_correction(
    db: Session,
    piece: MachinePiece,
    part_label: PiecePartLabel | None,
    color_label: PieceColorLabel | None,
) -> dict:
    """The Brickognize card's state for one labeler: their own verdict (from
    their label rows, never the machine operator's columns) and whether
    Brickognize already has a verdict on the piece from anyone, so it is sent
    at most once."""
    part_correct = None
    if part_label is not None:
        if part_label.part_correct is not None:
            part_correct = bool(part_label.part_correct)
        elif part_label.part_num is not None and piece.part_id is not None:
            part_correct = part_label.part_num == piece.part_id
    return {
        "correctable": piece.brickognize_listing_id is not None,
        "part_correct": part_correct,
        "color_corrected_id": (
            str(color_label.color_id) if color_label is not None and color_label.color_id is not None else None
        ),
        "part_feedback_submitted": _part_feedback_sent(db, piece),
        "color_feedback_submitted": _color_feedback_sent(db, piece),
    }


@router.post("/piece/{machine_id}/{piece_uuid}/brickognize-feedback")
def submit_brickognize_feedback(
    machine_id: UUID,
    piece_uuid: str,
    payload: BrickognizeFeedbackPayload,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    """Record this labeler's part and/or color verdict on a piece and send it on
    to Brickognize's feedback API. Gated on a captured listing id; each channel
    goes to Brickognize at most once per piece, from the machine or from Hive.

    The verdict is the labeler's own, on their label rows: a part answer on
    their piece_part_labels row (part_correct; "right" also names the machine's
    part as theirs), a color on their piece_color_labels row; brickognize_
    feedback_at on that row records the send. machine_pieces' verdict columns
    belong to the machine operator and are never written here. The verdict is
    saved whether or not the network call succeeds."""
    piece = (
        db.query(MachinePiece)
        .filter(MachinePiece.machine_id == machine_id, MachinePiece.piece_uuid == piece_uuid)
        .first()
    )
    if piece is None or not piece_access_visible(db, current_user, piece):
        raise APIError(404, "Piece not found", "PIECE_NOT_FOUND")
    if not piece.brickognize_listing_id:
        raise APIError(400, "Piece has no Brickognize listing to correct", "NOT_CORRECTABLE")

    now = datetime.now(timezone.utc)
    part_submitted = False
    color_submitted = False
    submit_error: str | None = None

    def my_row(model):
        return (
            db.query(model)
            .filter(model.machine_id == machine_id, model.piece_uuid == piece_uuid, model.labeler_id == current_user.id)
            .first()
        )

    part_label = my_row(PiecePartLabel)
    if payload.part_correct is not None:
        if part_label is None:
            part_label = PiecePartLabel(
                machine_id=machine_id,
                piece_uuid=piece_uuid,
                labeler_id=current_user.id,
                part_num=piece.part_id if payload.part_correct else None,
                cant_tell=False,
                predicted_part_num=piece.part_id,
            )
            db.add(part_label)
        elif payload.part_correct:
            part_label.part_num = piece.part_id
            part_label.cant_tell = False
        elif part_label.part_num is not None and part_label.part_num == piece.part_id:
            part_label.part_num = None
        part_label.part_correct = payload.part_correct
        part_label.updated_at = now
        if (
            not _part_feedback_sent(db, piece)
            and piece.brickognize_item_rank is not None
            and piece.part_id
        ):
            try:
                submit_part_feedback(
                    listing_id=piece.brickognize_listing_id,
                    item_id=piece.part_id,
                    item_rank=piece.brickognize_item_rank,
                    item_type=piece.brickognize_item_type,
                    is_correct=bool(payload.part_correct),
                )
                part_label.brickognize_feedback_at = now
                part_submitted = True
            except Exception as exc:
                submit_error = f"part: {exc}"
                log.warning("Brickognize part feedback failed for %s: %s", piece_uuid, exc)

    # Color: the passed true color, else this user's saved one. Equal to the
    # prediction confirms it; different rejects it.
    color_label = my_row(PieceColorLabel)
    corrected = payload.color_corrected_id
    if corrected is None and color_label is not None:
        corrected = color_label.color_id
    if corrected is not None:
        if color_label is None:
            color_label = PieceColorLabel(
                machine_id=machine_id,
                piece_uuid=piece_uuid,
                labeler_id=current_user.id,
                color_id=corrected,
                cant_tell=False,
            )
            db.add(color_label)
        if (
            not _color_feedback_sent(db, piece)
            and piece.brickognize_color_rank is not None
            and piece.color_id
        ):
            try:
                submit_color_feedback(
                    listing_id=piece.brickognize_listing_id,
                    color_id=piece.color_id,
                    color_rank=piece.brickognize_color_rank,
                    is_correct=str(corrected) == str(piece.color_id),
                )
                color_label.brickognize_feedback_at = now
                color_submitted = True
            except Exception as exc:
                prev = f"{submit_error}; " if submit_error else ""
                submit_error = f"{prev}color: {exc}"
                log.warning("Brickognize color feedback failed for %s: %s", piece_uuid, exc)

    db.flush()
    correction = _my_brickognize_correction(db, piece, part_label, color_label)
    db.commit()
    return {
        "ok": True,
        "part_submitted": part_submitted,
        "color_submitted": color_submitted,
        "submit_error": submit_error,
        "correction": correction,
    }


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
        valid_ids = {c["id"] for c in likely_colors.labelable_palette()}
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
    # Lowest available seq per piece, with its key for a direct storage URL.
    thumb: dict[str, tuple[int, str]] = {}
    for puid, seq, key in (
        db.query(MachinePieceImage.piece_uuid, MachinePieceImage.seq, MachinePieceImage.image_key)
        .filter(
            MachinePieceImage.machine_id == machine_id,
            MachinePieceImage.piece_uuid.in_(piece_uuids),
            MachinePieceImage.image_key.isnot(None),
        )
        .order_by(MachinePieceImage.seq.asc())
    ):
        thumb.setdefault(puid, (seq, key))
    palette = {c["id"]: c for c in get_profile_catalog_service().list_bricklink_colors()}
    backend = get_backend()

    items = []
    for puid, (n, cid) in best.items():
        if puid not in thumb:
            continue  # no viewable crop — skip (nothing to show in the column)
        col = palette.get(cid)
        rgb = col.get("rgb") if col else None
        items.append(
            {
                "piece_uuid": puid,
                "thumb_seq": thumb[puid][0],
                "thumb_url": backend.presigned_get_url(thumb[puid][1]),
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
                (`model_score`) and its picks (`model_same`, score at or above
                `link_threshold`, the model's published threshold) supersede the
                heuristic. Candidates are re-ranked by that score. Scores are
                kept per piece and model (services.piece_link_scores).
    - `heuristic` — neither; the time/angle `predicted` flag drives selection.

    Each candidate always keeps the heuristic's `predicted` flag untouched — it
    feeds the was_predicted training signal regardless of which source the UI
    pre-selects from."""
    result = find_possible_crops(db, machine_id, piece_uuid)
    result["my_link"] = _my_link_members(db, machine_id, piece_uuid, labeler_id)
    candidates = result.get("candidates", [])

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
    backend = get_backend()
    for c in candidates:
        c.update(_image_quality_state(quality_labels.get(c["local_id"])))
        c["ai_same"] = None
        c["model_same"] = None
        c["model_score"] = None
        c["thumb_url"] = backend.presigned_get_url(c["image_key"]) if c["image_key"] else None

    result["ai_model"] = None
    result["ai_reasoning"] = None
    result["link_model"] = None
    result["link_threshold"] = None
    result["prediction_source"] = "heuristic"

    ai = _ai_prediction(db, machine_id, piece_uuid)
    if ai is not None:
        same_ids = set(ai.same_local_ids or [])
        shown_ids = set(ai.candidate_local_ids or [])
        for c in candidates:
            c["ai_same"] = (c["local_id"] in same_ids) if c["local_id"] in shown_ids else None
        result["prediction_source"] = "ai"
        result["ai_model"] = ai.model
        result["ai_reasoning"] = ai.reasoning
    else:
        # Last, because scoring a piece for the first time commits and then
        # reads its crops from storage.
        model_pred = link_scores(db, machine_id, piece_uuid, candidates)
        if model_pred is not None:
            scores = model_pred["scores"]
            threshold = model_pred["threshold"]
            for c in candidates:
                s = scores.get(c["local_id"])
                c["model_score"] = round(s, 3) if s is not None else None
                c["model_same"] = (s >= threshold) if s is not None else None
            # re-rank by model score (scored crops first, best first); unscored keep order
            candidates.sort(key=lambda c: (c["model_score"] is not None, c["model_score"] or 0.0), reverse=True)
            result["prediction_source"] = "model"
            result["link_model"] = model_pred["model_name"]
            result["link_threshold"] = threshold

    for c in candidates:
        c.pop("image_key", None)
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
