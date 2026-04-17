from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field


class ApiKeySummary(BaseModel):
    id: UUID
    name: str
    token_prefix: str
    scopes: list[str] | None = None
    created_at: datetime
    last_used_at: datetime | None = None
    revoked_at: datetime | None = None

    model_config = {"from_attributes": True}


class ApiKeyCreateRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=80)
    scopes: list[str] | None = None


class ApiKeyCreateResponse(BaseModel):
    summary: ApiKeySummary
    raw_token: str
