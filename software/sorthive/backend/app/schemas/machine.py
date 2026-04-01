from datetime import datetime
from uuid import UUID

from pydantic import BaseModel


class MachineCreate(BaseModel):
    name: str
    description: str | None = None


class MachineRegister(BaseModel):
    """Self-registration: user credentials + machine info in one request."""
    email: str
    password: str
    machine_name: str
    machine_description: str | None = None


class MachineUpdate(BaseModel):
    name: str | None = None
    description: str | None = None


class MachineResponse(BaseModel):
    id: UUID
    owner_id: UUID
    token_prefix: str
    name: str
    description: str | None
    hardware_info: dict | None
    last_seen_at: datetime | None
    is_active: bool
    created_at: datetime

    model_config = {"from_attributes": True}


class MachineWithTokenResponse(MachineResponse):
    raw_token: str
