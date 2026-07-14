from __future__ import annotations

import csv
import io
import time
from datetime import datetime
from enum import Enum
from typing import Any, Dict, Iterator, List, Optional

from fastapi import APIRouter, HTTPException
from fastapi.responses import Response, StreamingResponse
from pydantic import BaseModel

from defs.events import KnownObjectData
import server.shared_state as shared_state

router = APIRouter()

BACKEND_PROCESS_STARTED_AT = time.time()

_VALID_SORTS = ("recent", "oldest")


# A pending/classifying payload older than this process was started can never
# complete (the pipeline that owned it died with the previous process) — treat
# it as gone so the UI doesn't render a zombie "classifying…" card forever.
def _isStaleIncompleteKnownObject(payload: Optional[Dict[str, Any]]) -> bool:
    if payload is None:
        return False
    status = _statusValue(payload.get("classification_status"))
    if status not in {"pending", "classifying"}:
        return False
    updated_at = payload.get("updated_at")
    if not isinstance(updated_at, (int, float)):
        return False
    return float(updated_at) < BACKEND_PROCESS_STARTED_AT


def _statusValue(value: Any) -> Optional[str]:
    if isinstance(value, Enum):
        return str(value.value)
    if isinstance(value, str):
        return value
    return None


class BinRef(BaseModel):
    x: int
    y: int
    z: int


# The ONE piece shape: records list rows, the recent dropdown's REST fill, the
# CSV export, and the detail envelope all use it. Every data field is Optional —
# old rows predate several columns and a memory-origin piece may not have
# committed yet; a non-Optional field here would 500 the endpoint on legacy rows.
class PieceSummary(BaseModel):
    uuid: str
    run_id: Optional[str] = None
    seen_at: Optional[float] = None
    recorded_at: Optional[float] = None
    classification_status: Optional[str] = None
    part_id: Optional[str] = None
    part_name: Optional[str] = None
    color_id: Optional[str] = None
    color_name: Optional[str] = None
    category_id: Optional[str] = None
    confidence: Optional[float] = None
    bin: Optional[BinRef] = None
    dead: bool = False
    has_images: bool = False
    preview_url: Optional[str] = None
    est_value: Optional[float] = None
    # Brickognize-correction state. correctable is True only when a listing id
    # was captured for this piece (a prerequisite for submitting any correction).
    correctable: bool = False
    part_correct: Optional[bool] = None
    color_corrected_id: Optional[str] = None
    part_feedback_submitted: bool = False
    color_feedback_submitted: bool = False


class PiecesListResponse(BaseModel):
    items: List[PieceSummary]
    next_cursor: Optional[str]
    total: int


class PieceDetailResponse(BaseModel):
    origin: str
    summary: PieceSummary
    detail: Optional[Dict[str, Any]]
    detail_available: bool


class PiecesOverviewResponse(BaseModel):
    total_runs: int
    total_pieces: int
    classified_pieces: int
    distributed_pieces: int
    unique_parts: int
    unique_colors: int
    first_seen: Optional[float]
    last_seen: Optional[float]


class LifetimeDayItem(BaseModel):
    day: str
    seconds_powered: float
    seconds_sorted: float
    pieces_seen: int
    pieces_classified: int
    pieces_distributed: int


class LifetimeStatsResponse(BaseModel):
    seconds_sorted: float
    seconds_powered: float
    pieces_seen: int
    pieces_classified: int
    pieces_distributed: int
    overall_ppm: float
    best_hour_ppm: float
    active_days: int
    first_hour: Optional[float]
    last_hour: Optional[float]
    daily: List[LifetimeDayItem]


def _parseStatusFilter(status: Optional[str]) -> Optional[List[str]]:
    if status is None:
        return None
    values = [s.strip() for s in status.split(",") if s.strip()]
    return values or None


def _parseCursor(cursor: Optional[str]) -> Optional[int]:
    if cursor is None:
        return None
    try:
        return int(cursor)
    except ValueError:
        raise HTTPException(status_code=400, detail="invalid cursor")


def _validateSort(sort: str) -> str:
    if sort not in _VALID_SORTS:
        raise HTTPException(status_code=400, detail=f"sort must be one of {_VALID_SORTS}")
    return sort


def _csvHeaders(filename: str) -> Dict[str, str]:
    return {"Content-Disposition": f'attachment; filename="{filename}"'}


# ---------------------------------------------------------------------------
# Literal paths MUST be declared before /api/pieces/{uuid} — a path param
# would otherwise swallow "overview", "export.csv", etc.
# ---------------------------------------------------------------------------


@router.get("/api/pieces/overview", response_model=PiecesOverviewResponse)
def getPiecesOverview() -> PiecesOverviewResponse:
    import piece_records

    return PiecesOverviewResponse(**piece_records.getOverview())


@router.get("/api/pieces/value")
def getPiecesValue() -> Dict[str, Any]:
    import piece_records

    gc = shared_state.gc_ref
    if gc is None:
        raise HTTPException(status_code=503, detail="not ready")
    return piece_records.getValueStats(gc)


@router.get("/api/pieces/lifetime", response_model=LifetimeStatsResponse)
def getPiecesLifetime(daily_days: int = 30) -> LifetimeStatsResponse:
    import lifetime_stats

    data = lifetime_stats.getOverview(daily_days=daily_days)
    return LifetimeStatsResponse(
        **{k: v for k, v in data.items() if k != "daily"},
        daily=[LifetimeDayItem(**d) for d in data["daily"]],
    )


@router.get("/api/pieces/lifetime/export.csv")
def exportLifetimeCsv() -> Response:
    import lifetime_stats

    data = lifetime_stats.getOverview(daily_days=365)
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(
        [
            "day",
            "seconds_powered",
            "seconds_sorted",
            "pieces_seen",
            "pieces_classified",
            "pieces_distributed",
        ]
    )
    for d in data["daily"]:
        writer.writerow(
            [
                d["day"],
                d["seconds_powered"],
                d["seconds_sorted"],
                d["pieces_seen"],
                d["pieces_classified"],
                d["pieces_distributed"],
            ]
        )
    filename = f"pieces-daily-{datetime.now().strftime('%Y%m%d-%H%M%S')}.csv"
    return Response(buf.getvalue(), media_type="text/csv", headers=_csvHeaders(filename))


@router.get("/api/pieces/aggregates")
def getPiecesAggregates(days: int = 365) -> Dict[str, Any]:
    import piece_records

    return piece_records.getAggregates(shared_state.gc_ref, days=days)


class ColorOption(BaseModel):
    id: int
    name: str
    rgb: Optional[str] = None
    is_trans: bool = False


class ColorsResponse(BaseModel):
    results: List[ColorOption]


@router.get("/api/pieces/colors", response_model=ColorsResponse)
def getPieceColors() -> ColorsResponse:
    # BrickLink color palette for the correction dropdown (searchable list of all
    # LEGO colors). Sourced from the local parts.db; empty when it's unavailable.
    import piece_metadata_db

    gc = shared_state.gc_ref
    if gc is None:
        return ColorsResponse(results=[])
    colors = piece_metadata_db.listBrickLinkColors(gc)
    return ColorsResponse(results=[ColorOption(**c) for c in colors])


_CSV_COLUMNS = [
    "uuid",
    "run_id",
    "seen_at",
    "recorded_at",
    "classification_status",
    "part_id",
    "part_name",
    "color_id",
    "color_name",
    "category_id",
    "confidence",
    "bin_x",
    "bin_y",
    "bin_z",
    "dead",
    "preview_url",
    "est_value",
]


def _isoTimestamp(ts: Any) -> str:
    if not isinstance(ts, (int, float)):
        return ""
    return datetime.fromtimestamp(float(ts)).isoformat()


@router.get("/api/pieces/export.csv")
def exportPiecesCsv(
    status: Optional[str] = None,
    part_id: Optional[str] = None,
    color_id: Optional[str] = None,
    run_id: Optional[str] = None,
    dead: Optional[bool] = None,
    date_from: Optional[float] = None,
    date_to: Optional[float] = None,
    sort: str = "recent",
) -> StreamingResponse:
    import piece_records

    _validateSort(sort)
    status_values = _parseStatusFilter(status)
    gc = shared_state.gc_ref

    def generate() -> Iterator[str]:
        buf = io.StringIO()
        writer = csv.writer(buf)

        def drain() -> str:
            value = buf.getvalue()
            buf.seek(0)
            buf.truncate(0)
            return value

        writer.writerow(_CSV_COLUMNS)
        yield drain()
        for s in piece_records.iterPieceSummaries(
            gc,
            status=status_values,
            part_id=part_id,
            color_id=color_id,
            run_id=run_id,
            dead=dead,
            date_from=date_from,
            date_to=date_to,
            sort=sort,
        ):
            bin_ref = s.get("bin") or {}
            writer.writerow(
                [
                    s.get("uuid"),
                    s.get("run_id") or "",
                    _isoTimestamp(s.get("seen_at")),
                    _isoTimestamp(s.get("recorded_at")),
                    s.get("classification_status") or "",
                    s.get("part_id") or "",
                    s.get("part_name") or "",
                    s.get("color_id") or "",
                    s.get("color_name") or "",
                    s.get("category_id") or "",
                    s.get("confidence") if s.get("confidence") is not None else "",
                    bin_ref.get("x", ""),
                    bin_ref.get("y", ""),
                    bin_ref.get("z", ""),
                    1 if s.get("dead") else 0,
                    s.get("preview_url") or "",
                    s.get("est_value") if s.get("est_value") is not None else "",
                ]
            )
            yield drain()

    filename = f"pieces-{datetime.now().strftime('%Y%m%d-%H%M%S')}.csv"
    return StreamingResponse(
        generate(), media_type="text/csv", headers=_csvHeaders(filename)
    )


@router.get("/api/pieces", response_model=PiecesListResponse)
def listPieces(
    limit: int = 100,
    cursor: Optional[str] = None,
    status: Optional[str] = None,
    part_id: Optional[str] = None,
    color_id: Optional[str] = None,
    run_id: Optional[str] = None,
    dead: Optional[bool] = None,
    date_from: Optional[float] = None,
    date_to: Optional[float] = None,
    sort: str = "recent",
) -> PiecesListResponse:
    import piece_records

    _validateSort(sort)
    result = piece_records.listPieces(
        shared_state.gc_ref,
        limit=limit,
        cursor=_parseCursor(cursor),
        status=_parseStatusFilter(status),
        part_id=part_id,
        color_id=color_id,
        run_id=run_id,
        dead=dead,
        date_from=date_from,
        date_to=date_to,
        sort=sort,
    )
    return PiecesListResponse(
        items=[PieceSummary(**item) for item in result["items"]],
        next_cursor=result["next_cursor"],
        total=result["total"],
    )


class CorrectionRequest(BaseModel):
    # Fields present in the request body are applied; absent fields are left
    # unchanged (so the part check/x and the color dropdown can be saved
    # independently). part_correct null clears the piece back to unreviewed.
    part_correct: Optional[bool] = None
    color_corrected_id: Optional[str] = None
    # When true (default), any pending (verdict recorded, not yet submitted)
    # correction is sent to Brickognize now. The verdict is always recorded.
    submit: bool = True


class CorrectionResponse(BaseModel):
    summary: PieceSummary
    part_submitted: bool = False
    color_submitted: bool = False
    submit_error: Optional[str] = None


def _ensurePieceRecorded(gc: Any, uuid: str) -> None:
    # A piece is correctable the instant it's classified (the live payload
    # carries the Brickognize listing), which is BEFORE it's written to
    # piece_records at distribution. If a correction lands in that window,
    # persist the piece straight from the in-memory KnownObject so the correction
    # has a row to attach to. recordPiece upserts, so the later distribution write
    # still fills in the bin.
    import piece_records

    if gc is None or getattr(gc, "runtime_stats", None) is None:
        return
    payload = gc.runtime_stats.lookupKnownObject(uuid)
    if payload is None:
        return
    status = payload.get("classification_status")
    if isinstance(status, Enum):
        status = status.value
    piece_records.recordPiece(
        {
            "uuid": uuid,
            "created_at": payload.get("created_at"),
            "distributed_at": payload.get("distributed_at"),
            "classification_status": status,
            "part_id": payload.get("part_id"),
            "part_name": payload.get("part_name"),
            "color_id": payload.get("color_id"),
            "color_name": payload.get("color_name"),
            "category_id": payload.get("category_id"),
            "confidence": payload.get("confidence"),
            "destination_bin": payload.get("destination_bin"),
            "dead": payload.get("dead"),
            "brickognize_preview_url": payload.get("brickognize_preview_url"),
            "brickognize_listing_id": payload.get("brickognize_listing_id"),
            "brickognize_item_rank": payload.get("brickognize_item_rank"),
            "brickognize_item_type": payload.get("brickognize_item_type"),
            "brickognize_color_rank": payload.get("brickognize_color_rank"),
        },
        run_id=getattr(gc, "run_id", None),
        machine_id=getattr(gc, "machine_id", None),
    )


@router.post("/api/pieces/{uuid}/correction", response_model=CorrectionResponse)
def submitPieceCorrection(uuid: str, body: CorrectionRequest) -> CorrectionResponse:
    import piece_records
    from classification.brickognize_feedback import (
        submitColorFeedback,
        submitPartFeedback,
    )

    gc = shared_state.gc_ref
    ctx = piece_records.getCorrectionContext(uuid)
    if ctx is None:
        # Not recorded yet — persist it from memory, then retry.
        _ensurePieceRecorded(gc, uuid)
        ctx = piece_records.getCorrectionContext(uuid)
    if ctx is None:
        raise HTTPException(status_code=404, detail="not found")

    fields = body.model_fields_set
    set_part = "part_correct" in fields
    set_color = "color_corrected_id" in fields
    if set_part or set_color:
        piece_records.setPieceCorrection(
            uuid,
            set_part=set_part,
            part_correct=body.part_correct,
            set_color=set_color,
            color_corrected_id=body.color_corrected_id,
        )
        ctx = piece_records.getCorrectionContext(uuid) or ctx

    part_submitted = False
    color_submitted = False
    submit_error: Optional[str] = None

    if body.submit:
        listing_id = ctx.get("brickognize_listing_id")
        # Part feedback: needs a listing, the applied item's rank, a part id, and
        # a recorded verdict that hasn't already been sent.
        if (
            listing_id
            and ctx.get("part_correct") is not None
            and not ctx.get("part_feedback_submitted")
            and ctx.get("brickognize_item_rank") is not None
            and ctx.get("part_id")
        ):
            try:
                submitPartFeedback(
                    listing_id=str(listing_id),
                    item_id=str(ctx["part_id"]),
                    item_rank=int(ctx["brickognize_item_rank"]),
                    item_type=ctx.get("brickognize_item_type"),
                    is_correct=bool(ctx["part_correct"]),
                )
                piece_records.markFeedbackSubmitted(uuid, part=True)
                part_submitted = True
            except Exception as e:
                submit_error = f"part: {e}"
                if gc is not None:
                    gc.logger.warning(f"Brickognize part feedback failed for {uuid}: {e}")
        # Color feedback: a corrected color equal to the prediction confirms it; a
        # different one rejects the prediction (Brickognize only accepts/rejects
        # its own ranked color, so it can't be told the actual true color).
        if (
            listing_id
            and ctx.get("color_corrected_id") is not None
            and not ctx.get("color_feedback_submitted")
            and ctx.get("brickognize_color_rank") is not None
            and ctx.get("color_id")
        ):
            try:
                is_correct = str(ctx["color_corrected_id"]) == str(ctx["color_id"])
                submitColorFeedback(
                    listing_id=str(listing_id),
                    color_id=str(ctx["color_id"]),
                    color_rank=int(ctx["brickognize_color_rank"]),
                    is_correct=is_correct,
                )
                piece_records.markFeedbackSubmitted(uuid, color=True)
                color_submitted = True
            except Exception as e:
                prev = submit_error + "; " if submit_error else ""
                submit_error = f"{prev}color: {e}"
                if gc is not None:
                    gc.logger.warning(f"Brickognize color feedback failed for {uuid}: {e}")

    summary = piece_records.getPieceSummaryByUuid(gc, uuid)
    if summary is None:
        raise HTTPException(status_code=404, detail="not found")
    return CorrectionResponse(
        summary=PieceSummary(**summary),
        part_submitted=part_submitted,
        color_submitted=color_submitted,
        submit_error=submit_error,
    )


def _summaryFromMemory(gc: Any, payload: Dict[str, Any]) -> PieceSummary:
    # HOT PATH: RecentObjects polls this per active piece every 600ms during
    # sorting. Everything here must come from the in-memory payload / process
    # state — zero sqlite. est_value uses the dict-hit-only price peek; a cache
    # miss stays null rather than touching parts.db.
    from piece_records import peekCachedPrice

    part_id = payload.get("part_id")
    color_id = payload.get("color_id")
    est_value: Optional[float] = None
    if isinstance(part_id, str):
        _, est_value = peekCachedPrice(
            part_id, color_id if isinstance(color_id, str) else None
        )
    dest = payload.get("destination_bin")
    bin_ref = None
    if isinstance(dest, (list, tuple)) and len(dest) == 3:
        bin_ref = BinRef(x=int(dest[0]), y=int(dest[1]), z=int(dest[2]))
    return PieceSummary(
        uuid=str(payload.get("uuid")),
        run_id=getattr(gc, "run_id", None),
        seen_at=payload.get("created_at"),
        recorded_at=payload.get("distributed_at"),
        classification_status=_statusValue(payload.get("classification_status")),
        part_id=part_id,
        part_name=payload.get("part_name"),
        color_id=color_id,
        color_name=payload.get("color_name"),
        category_id=payload.get("category_id"),
        confidence=payload.get("confidence"),
        bin=bin_ref,
        dead=bool(payload.get("dead")),
        has_images=bool(payload.get("recognition_image_set")),
        preview_url=payload.get("brickognize_preview_url"),
        est_value=est_value,
        # A freshly classified piece can be corrected the moment it appears in
        # the recent list — the correction state itself lives only in the DB, so
        # it defaults to unreviewed here.
        correctable=payload.get("brickognize_listing_id") is not None,
    )


@router.get("/api/pieces/{uuid}", response_model=PieceDetailResponse)
def getPiece(uuid: str) -> PieceDetailResponse:
    import piece_image_store
    import piece_records

    gc = shared_state.gc_ref
    if gc is not None and getattr(gc, "runtime_stats", None) is not None:
        payload = gc.runtime_stats.lookupKnownObject(uuid)
        if payload is not None and not _isStaleIncompleteKnownObject(payload):
            try:
                detail = KnownObjectData.model_validate(payload).model_dump()
            except Exception:
                detail = None
            if detail is not None:
                return PieceDetailResponse(
                    origin="memory",
                    summary=_summaryFromMemory(gc, payload),
                    detail=detail,
                    detail_available=True,
                )

    summary = piece_records.getPieceSummaryByUuid(gc, uuid)
    if summary is None:
        # No memory entry and no durable record — but the piece may still have
        # crops on disk (image writes and record commits are independent paths).
        if not piece_image_store.listPieceImages(uuid):
            raise HTTPException(status_code=404, detail="not found")
        summary = {"uuid": uuid, "has_images": True}
    return PieceDetailResponse(
        origin="disk",
        summary=PieceSummary(**summary),
        detail=None,
        detail_available=False,
    )
