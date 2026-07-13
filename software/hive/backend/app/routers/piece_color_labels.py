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

from datetime import datetime, timedelta, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy import and_, exists, func
from sqlalchemy.orm import Session

from app.deps import get_current_user, get_db
from app.errors import APIError
from app.models.machine import Machine
from app.models.machine_channel_crop import MachineChannelCrop
from app.models.machine_piece import MachinePiece
from app.models.machine_piece_image import MachinePieceImage
from app.models.piece_color_label import PieceColorLabel
from app.models.piece_crop_link import PieceCropLink, PieceCropLinkMember
from app.models.piece_rejection import PieceRejection
from app.models.user import User
from app.services.channel_crop_lookup import find_possible_crops
from app.services.channel_crop_lookup_params import DEFAULT_PARAMS
from app.services.pixel_color import guess_piece_color
from app.services.profile_catalog import get_profile_catalog_service
from app.services.storage import serve_stored_file

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


def _labelable_query(db: Session):
    # A piece is labelable if it isn't a dead/spurious record and has a crop.
    return db.query(MachinePiece).filter(
        MachinePiece.dead.is_(False),
        _available_image_exists(),
    )


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


@router.get("/stats")
def label_stats(
    machine_id: UUID | None = Query(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    """Dashboard rollup: overall progress plus a histogram of how many distinct
    labelers have color-labeled each piece (drives the coverage chart). Scoped to
    one machine when machine_id is given, matching the grid's machine filter."""
    labelable_q = _labelable_query(db)
    if machine_id is not None:
        labelable_q = labelable_q.filter(MachinePiece.machine_id == machine_id)
    total_labelable = labelable_q.count()

    def _color_q():
        q = db.query(PieceColorLabel)
        return q.filter(PieceColorLabel.machine_id == machine_id) if machine_id is not None else q

    def _crop_q():
        q = db.query(PieceCropLink)
        return q.filter(PieceCropLink.machine_id == machine_id) if machine_id is not None else q

    labeled_by_me = _color_q().filter(PieceColorLabel.labeler_id == current_user.id).count()
    crop_links_by_me = _crop_q().filter(PieceCropLink.labeler_id == current_user.id).count()
    total_color_labels = _color_q().count()
    total_crop_links = _crop_q().count()

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
        "total_labels": int(total_color_labels),
        "total_color_labels": int(total_color_labels),
        "total_crop_links": int(total_crop_links),
        "color_labeled_pieces": int(color_labeled_pieces),
        "crop_linked_pieces": int(crop_linked_pieces),
        "labeler_histogram": {
            "0": labelers_0,
            "1": labelers_1,
            "2": labelers_2,
            "3+": labelers_3plus,
        },
    }


# Window (before/after the piece's arrival) in which a same-piece candidate crop
# could exist — mirrors the shared lookup params so ordering agrees with what the
# labeling view actually surfaces.
_CANDIDATE_WINDOW = timedelta(seconds=DEFAULT_PARAMS.lookback_window_s)
_CANDIDATE_SLOP = timedelta(seconds=DEFAULT_PARAMS.fwd_slop_s)


def _has_candidates_exists():
    """Correlated EXISTS: this piece's machine has at least one channel crop
    within its arrival window — i.e. the same-piece panel will have candidates.
    Cheap via the (machine_id, ts) index; arrival approximated by seen_at."""
    arrival = func.coalesce(MachinePiece.seen_at, MachinePiece.recorded_at)
    return exists().where(
        and_(
            MachineChannelCrop.machine_id == MachinePiece.machine_id,
            MachineChannelCrop.ts.isnot(None),
            MachineChannelCrop.ts >= arrival - _CANDIDATE_WINDOW,
            MachineChannelCrop.ts <= arrival + _CANDIDATE_SLOP,
        )
    )


_PIECE_SORTS = {
    "priority",
    "recent",
    "oldest",
    "least_color",
    "most_color",
    "least_crop",
    "most_crop",
    "needs_me",
}


@router.get("/pieces")
def list_pieces(
    sort: str = Query("priority"),
    limit: int = Query(60, ge=1, le=200),
    offset: int = Query(0, ge=0),
    machine_id: UUID | None = Query(None),
    with_candidates: bool = Query(False),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    """Sortable grid of labelable pieces with per-piece label/crop-link counts,
    for the dashboard. Sorts: priority (has same-piece candidates first, then
    fewest color labels — spreads effort where it's useful), recent, oldest,
    least/most_color, least/most_crop, needs_me (this user's unlabeled first).
    Optional machine_id filter and with_candidates (only pieces that have
    same-piece candidate crops)."""
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
    color_cnt = func.coalesce(color_cnt_sq.c.cnt, 0)
    crop_cnt = func.coalesce(crop_cnt_sq.c.cnt, 0)
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
    has_candidates = _has_candidates_exists()
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
        )
        .outerjoin(
            color_cnt_sq,
            and_(color_cnt_sq.c.mid == MachinePiece.machine_id, color_cnt_sq.c.puid == MachinePiece.piece_uuid),
        )
        .outerjoin(
            crop_cnt_sq,
            and_(crop_cnt_sq.c.mid == MachinePiece.machine_id, crop_cnt_sq.c.puid == MachinePiece.piece_uuid),
        )
        .filter(MachinePiece.dead.is_(False), _available_image_exists(), ~my_rejection)
    )
    if machine_id is not None:
        q = q.filter(MachinePiece.machine_id == machine_id)
    if with_candidates:
        q = q.filter(has_candidates)

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
    for p, ccnt, xcnt, mc, mx, has_c in rows:
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
                "my_color": bool(mc),
                "my_crop": bool(mx),
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
) -> dict:
    """Everything the single-piece labeling view needs: the piece, its crops, the
    pixel-average guess, and THIS user's saved color label (so revisiting a piece
    by URL restores what they'd set, rather than a fresh unlabeled view)."""
    piece = (
        db.query(MachinePiece)
        .filter(MachinePiece.machine_id == machine_id, MachinePiece.piece_uuid == piece_uuid)
        .first()
    )
    if piece is None:
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
    return {
        "machine_id": str(machine_id),
        "machine_name": machine_name,
        "piece_uuid": piece_uuid,
        "part": {"part_id": piece.part_id, "part_name": piece.part_name},
        "recorded_at": piece.recorded_at.isoformat() if piece.recorded_at else None,
        "seen_at": piece.seen_at.isoformat() if piece.seen_at else None,
        "pixel_guess": guess_piece_color(images),
        "images": [
            {"seq": im.seq, "source": im.source, "used": im.used, "score": im.score} for im in images
        ],
        "my_label": None if label is None else {"color_id": label.color_id, "notes": label.notes},
        "my_rejection": None if rejection is None else {"reasons": list(rejection.reasons or [])},
    }


@router.get("/queue")
def label_queue(
    only_unlabeled: bool = Query(True),
    limit: int = Query(40, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    """Pieces to color-label, newest first.

    With only_unlabeled=true (default) the labeler's already-labeled pieces drop
    out, so the client just re-fetches from the top as it works — no cursor. Set
    only_unlabeled=false to browse the full set (use offset to page)."""
    query = _labelable_query(db)

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
    color_id: int
    notes: str | None = None


@router.post("")
def submit_label(
    payload: ColorLabelPayload,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    """Create or update the current user's color label for a piece."""
    valid_ids = {c["id"] for c in get_profile_catalog_service().list_bricklink_colors()}
    if payload.color_id not in valid_ids:
        raise APIError(400, f"Unknown BrickLink color id {payload.color_id}", "COLOR_ID_INVALID")

    piece = (
        db.query(MachinePiece.id)
        .filter(
            MachinePiece.machine_id == payload.machine_id,
            MachinePiece.piece_uuid == payload.piece_uuid,
        )
        .first()
    )
    if piece is None:
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
            color_id=payload.color_id,
            notes=payload.notes,
        )
        db.add(label)
        created = True
    else:
        label.color_id = payload.color_id
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
    _user: User = Depends(get_current_user),
) -> object:
    """Stream one synced crop. Any authenticated user may view it — color
    labeling is a community task over the whole synced fleet, not just the
    machine's owner (unlike the owner-gated /machines/... image route)."""
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


@router.get("/possible-crops/{machine_id}/{piece_uuid}")
def possible_crops(
    machine_id: UUID,
    piece_uuid: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    """Ranked "possibly the same piece" C2/C3 candidates for a classified piece,
    plus this labeler's saved selection (if any) so the UI can restore it."""
    result = find_possible_crops(db, machine_id, piece_uuid)
    result["my_link"] = _my_link_members(db, machine_id, piece_uuid, current_user.id)
    return result


@router.get("/channel-crops/{machine_id}/{local_id}/image")
def get_channel_crop_image(
    machine_id: UUID,
    local_id: int,
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
) -> object:
    """Stream one upstream-channel crop. Any authenticated user may view it —
    same-piece labeling is a community task over the synced fleet, like the color
    crops above (unlike the owner-gated /machines/... channel-crop route)."""
    crop = (
        db.query(MachineChannelCrop)
        .filter(
            MachineChannelCrop.machine_id == machine_id,
            MachineChannelCrop.local_id == local_id,
        )
        .first()
    )
    if crop is None or not crop.image_key:
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
    piece = (
        db.query(MachinePiece.id)
        .filter(
            MachinePiece.machine_id == payload.machine_id,
            MachinePiece.piece_uuid == payload.piece_uuid,
        )
        .first()
    )
    if piece is None:
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
# Flags the sample itself as unusable (as opposed to labeling color / same-piece).
# Rejected pieces drop out of the rejecter's queue (see list_pieces).

_REJECT_REASONS = {"no_piece", "multiple_pieces"}


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

    piece = (
        db.query(MachinePiece.id)
        .filter(MachinePiece.machine_id == payload.machine_id, MachinePiece.piece_uuid == payload.piece_uuid)
        .first()
    )
    if piece is None:
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
