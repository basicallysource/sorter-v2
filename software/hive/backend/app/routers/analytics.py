from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.deps import get_current_user, get_db
from app.models.machine_daily_stats import MachineDailyStats
from app.models.user import User
from app.services import analytics

router = APIRouter(prefix="/api", tags=["analytics"])


@router.get("/analytics")
def get_analytics(
    machine_id: UUID | None = Query(None),
    owner_id: UUID | None = Query(None),
    scope: str | None = Query(None, pattern="^(mine|all)$"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Analytics over a set of machines, chosen by (in precedence order)
    machine_id, owner_id, or scope=mine|all. Authorization is enforced by
    resolve_machine_set; served from machine_daily_stats + live group-bys."""
    resolved = analytics.resolve_machine_set(
        db, current_user, machine_id=machine_id, owner_id=owner_id, scope=scope
    )
    # Cold-start: populate the daily table on the first request if the worker
    # hasn't run yet, so analytics isn't blank on a fresh deploy.
    if db.query(MachineDailyStats.machine_id).first() is None:
        try:
            analytics.refresh_daily_stats(db)
        except Exception:
            db.rollback()
    data = analytics.get_analytics(db, resolved["ids"])
    return {
        "scope": {
            "kind": resolved["kind"],
            "label": resolved["label"],
            "machine_count": len(resolved["ids"]),
        },
        **data,
    }
