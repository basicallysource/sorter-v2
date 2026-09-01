"""Reviewer leaderboard endpoints.

Open to any authenticated user — the whole point is shared visibility
across the reviewing pool.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.deps import get_current_user, get_db
from app.errors import APIError
from app.models.user import User
from app.schemas.leaderboard import (
    AchievementEntry,
    LeaderboardEntry,
    LeaderboardResponse,
    ReviewerProfileResponse,
)
from app.services.leaderboard import (
    PERIOD_TO_HOURS,
    get_leaderboard,
    get_reviewer_profile,
)


router = APIRouter(prefix="/api/leaderboard", tags=["leaderboard"])


@router.get("", response_model=LeaderboardResponse)
def list_leaderboard(
    period: str = Query("7d", pattern="^(24h|7d|30d|all)$"),
    limit: int = Query(100, ge=1, le=500),
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    rows = get_leaderboard(db, period=period, limit=limit)
    return LeaderboardResponse(
        period=period,
        entries=[
            LeaderboardEntry(
                user_id=r.user_id,
                display_name=r.display_name,
                avatar_url=r.avatar_url,
                role=r.role,
                total_reviews=r.total_reviews,
                accepts=r.accepts,
                rejects=r.rejects,
                piece_color_labels=r.piece_color_labels,
                piece_crop_links=r.piece_crop_links,
                total_contributions=r.total_contributions,
                last_review_at=r.last_review_at,
            )
            for r in rows
        ],
    )


@router.get("/{user_id}", response_model=ReviewerProfileResponse)
def get_profile(
    user_id: UUID,
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    profile = get_reviewer_profile(db, user_id)
    if profile is None:
        raise APIError(404, "User not found", "USER_NOT_FOUND")
    return ReviewerProfileResponse(
        user_id=profile.user_id,
        display_name=profile.display_name,
        avatar_url=profile.avatar_url,
        role=profile.role,
        total_reviews=profile.total_reviews,
        accepts=profile.accepts,
        rejects=profile.rejects,
        piece_color_labels=profile.piece_color_labels,
        piece_crop_links=profile.piece_crop_links,
        total_contributions=profile.total_contributions,
        agreement_rate=profile.agreement_rate,
        machines_covered=profile.machines_covered,
        current_streak_days=profile.current_streak_days,
        longest_streak_days=profile.longest_streak_days,
        speed_record_24h=profile.speed_record_24h,
        first_review_at=profile.first_review_at,
        last_review_at=profile.last_review_at,
        daily_counts=profile.daily_counts,
        achievements=[AchievementEntry(**a) for a in profile.achievements],
    )
