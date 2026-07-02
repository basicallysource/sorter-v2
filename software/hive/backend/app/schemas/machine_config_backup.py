from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel


class ConfigBackupUpload(BaseModel):
    """Machine -> Hive: a full settings snapshot.

    ``payload`` is opaque to Hive — typically ``{"toml_text": str,
    "local_state": {...}}``. ``content_hash`` is computed by the sorter over the
    canonical payload so Hive can dedup without re-hashing.
    """

    content_hash: str
    payload: dict[str, Any]
    trigger: str = "config_change"


class ConfigBackupUploadResponse(BaseModel):
    ok: bool = True
    version: int
    content_hash: str
    # True when the hash matched the latest backup and no new version was stored.
    deduped: bool
    created_at: datetime


class ConfigBackupSummary(BaseModel):
    id: UUID
    version: int
    content_hash: str
    trigger: str
    created_at: datetime

    model_config = {"from_attributes": True}


class ConfigBackupDetail(ConfigBackupSummary):
    payload: dict[str, Any]

    model_config = {"from_attributes": True}
