from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field


class LeaderboardEntry(BaseModel):
    user_id: UUID
    display_name: str | None = None
    avatar_url: str | None = None
    role: str
    total_reviews: int
    accepts: int
    rejects: int
    last_review_at: datetime | None = None


class LeaderboardResponse(BaseModel):
    period: str
    entries: list[LeaderboardEntry]


class AchievementEntry(BaseModel):
    slug: str
    name: str
    description: str
    icon: str
    tier: str
    earned: bool
    progress: str


class ReviewerProfileResponse(BaseModel):
    user_id: UUID
    display_name: str | None = None
    avatar_url: str | None = None
    role: str
    total_reviews: int
    accepts: int
    rejects: int
    agreement_rate: float | None = None  # 0..1
    machines_covered: int
    current_streak_days: int
    longest_streak_days: int
    speed_record_24h: int
    first_review_at: datetime | None = None
    last_review_at: datetime | None = None
    daily_counts: list[int] = Field(default_factory=list)
    achievements: list[AchievementEntry] = Field(default_factory=list)
