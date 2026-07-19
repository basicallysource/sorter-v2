from __future__ import annotations

from typing import List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

router = APIRouter()


class IncidentSummaryRow(BaseModel):
    id: int
    kind: str
    source: Optional[str] = None
    source_kind: Optional[str] = None
    severity: Optional[str] = None
    scope: Optional[str] = None
    channel: Optional[str] = None
    role: Optional[str] = None
    channel_label: Optional[str] = None
    piece_uuid: Optional[str] = None
    track_id: Optional[int] = None
    reason: Optional[str] = None
    operator_message: Optional[str] = None
    status: str
    triggered_at: float
    resolved_at: Optional[float] = None
    resolved_by: Optional[str] = None
    duration_s: Optional[float] = None


class IncidentsListResponse(BaseModel):
    items: List[IncidentSummaryRow]
    next_cursor: Optional[str]
    total: int


class IncidentKindSummary(BaseModel):
    kind: str
    count: int
    avg_duration_s: Optional[float] = None
    operator_resolved: int = 0
    auto_resolved: int = 0


class IncidentDaySummary(BaseModel):
    date: str
    count: int


class IncidentChannelSummary(BaseModel):
    channel: str
    count: int


class IncidentsSummaryResponse(BaseModel):
    total: int
    active: int
    by_kind: List[IncidentKindSummary]
    by_day: List[IncidentDaySummary]
    by_channel: List[IncidentChannelSummary]


def _parseCursor(cursor: Optional[str]) -> Optional[int]:
    if cursor is None:
        return None
    try:
        return int(cursor)
    except ValueError:
        raise HTTPException(status_code=400, detail="invalid cursor")


@router.get("/api/incidents/summary", response_model=IncidentsSummaryResponse)
def getIncidentsSummary(
    date_from: Optional[float] = None,
    date_to: Optional[float] = None,
) -> IncidentsSummaryResponse:
    import incident_records

    return IncidentsSummaryResponse(
        **incident_records.incidentSummary(date_from=date_from, date_to=date_to)
    )


@router.get("/api/incidents", response_model=IncidentsListResponse)
def listIncidents(
    limit: int = 100,
    cursor: Optional[str] = None,
    kind: Optional[str] = None,
    status: Optional[str] = None,
    date_from: Optional[float] = None,
    date_to: Optional[float] = None,
) -> IncidentsListResponse:
    import incident_records

    result = incident_records.listIncidents(
        limit=limit,
        cursor=_parseCursor(cursor),
        kind=kind,
        status=status,
        date_from=date_from,
        date_to=date_to,
    )
    return IncidentsListResponse(
        items=[IncidentSummaryRow(**item) for item in result["items"]],
        next_cursor=result["next_cursor"],
        total=result["total"],
    )
