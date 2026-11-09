"""The health of the computer the backend runs on, for the Computer settings
page: the latest reading, this process, the warnings open now, the thresholds,
and one point a minute for the hours asked for (computer_health.py)."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Query

import computer_health

router = APIRouter()


@router.get("/api/system/computer")
def get_computer_health(hours: float = Query(6.0, gt=0, le=computer_health.HISTORY_H)) -> dict[str, Any]:
    return computer_health.describe(hours)
