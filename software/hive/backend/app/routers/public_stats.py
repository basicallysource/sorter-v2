"""Service-to-service aggregate stats.

A single shared-secret endpoint that exposes the same aggregate analytics an admin
sees on the all-machines page (totals + daily time-series + distributions across
every non-archived machine). Meant for other basically services (e.g. the public
website) to pull headline numbers without a user session — regular Hive users
cannot reach these aggregate stats through the normal analytics API.

Auth is a static key in `settings.PUBLIC_STATS_API_KEY`, presented as either
`Authorization: Bearer <key>` or an `X-Stats-Key: <key>` header.
"""

import hmac

from fastapi import APIRouter, Depends, Header, HTTPException
from sqlalchemy.orm import Session

from app.config import settings
from app.deps import get_db
from app.models.machine import Machine
from app.models.machine_daily_stats import MachineDailyStats
from app.services import analytics

router = APIRouter(prefix="/api/public", tags=["public-stats"])


def require_stats_key(
    authorization: str | None = Header(default=None),
    x_stats_key: str | None = Header(default=None),
) -> None:
    configured = (settings.PUBLIC_STATS_API_KEY or "").strip()
    if not configured:
        raise HTTPException(status_code=503, detail="Public stats API is not configured")
    presented = x_stats_key
    if not presented and authorization and authorization.startswith("Bearer "):
        presented = authorization[7:]
    if not presented or not hmac.compare_digest(presented.strip(), configured):
        raise HTTPException(status_code=401, detail="Invalid stats API key")


@router.get("/stats", dependencies=[Depends(require_stats_key)])
def get_public_stats(db: Session = Depends(get_db)):
    """Aggregate analytics across every non-archived machine — the same block the
    admin all-machines dashboard renders, minus any per-owner PII."""
    ids = [mid for (mid,) in db.query(Machine.id).filter(Machine.archived_at.is_(None)).all()]
    # Cold-start: populate the daily table on the first request if the worker
    # hasn't run yet, so stats aren't blank on a fresh deploy.
    if db.query(MachineDailyStats.machine_id).first() is None:
        try:
            analytics.refresh_daily_stats(db)
        except Exception:
            db.rollback()
    data = analytics.get_analytics(db, ids)
    return {
        "scope": {"kind": "all", "label": "All machines", "machine_count": len(ids)},
        **data,
    }
