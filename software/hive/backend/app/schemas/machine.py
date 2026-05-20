from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, field_validator


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


class MachineHeartbeat(BaseModel):
    hardware_info: dict | None = None
    local_ui_port: str | None = None


class MachineOwnerSummary(BaseModel):
    id: UUID
    display_name: str | None = None
    avatar_url: str | None = None


class MachineResponse(BaseModel):
    id: UUID
    owner_id: UUID
    token_prefix: str
    name: str
    description: str | None
    hardware_info: dict | None
    last_seen_ip: str | None
    local_ui_port: str | None
    last_seen_at: datetime | None
    is_active: bool
    created_at: datetime
    owner: MachineOwnerSummary | None = None

    model_config = {"from_attributes": True}

    @field_validator("owner", mode="before")
    @classmethod
    def _coerce_owner(cls, value: Any) -> Any:
        """Map the SQLAlchemy User loaded via Machine.owner into the summary shape.

        ``model_validate(machine)`` pulls every field by attribute, so ``machine.owner`` shows
        up as a User instance. Pydantic can't auto-fit that into MachineOwnerSummary; convert
        explicitly here so callers don't have to remember to strip or rebuild the field.
        """
        if value is None or isinstance(value, (MachineOwnerSummary, dict)):
            return value
        return {
            "id": getattr(value, "id", None),
            "display_name": getattr(value, "display_name", None),
            "avatar_url": getattr(value, "avatar_url", None),
        }


class MachineWithTokenResponse(MachineResponse):
    raw_token: str
