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

from datetime import datetime, timezone
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
from app.models.user import User
from app.services.channel_crop_lookup import find_possible_crops
from app.services.pixel_color import guess_piece_color
from app.services.profile_catalog import get_profile_catalog_service
from app.services.storage import serve_stored_file

router = APIRouter(prefix="/api/color-labels", tags=["color-labels"])

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
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, int]:
    total_labelable = _labelable_query(db).count()
    labeled_by_me = (
        db.query(func.count(PieceColorLabel.id))
        .filter(PieceColorLabel.labeler_id == current_user.id)
        .scalar()
        or 0
    )
    total_labels = db.query(func.count(PieceColorLabel.id)).scalar() or 0
    return {
        "total_labelable": total_labelable,
        "labeled_by_me": int(labeled_by_me),
        "total_labels": int(total_labels),
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
