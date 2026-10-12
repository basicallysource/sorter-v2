"""What the worker process and the web process tell each other.

Hive runs its background workers in a process of their own
(agent-docs/process-roles.md), so anything a request needs from them has to
go through the database. One small table, ``worker_state``, one row per name:

- ``published:<what>``: a worker's latest answer that requests serve.
  ``publish`` writes it on every pass, ``published`` reads it.
- ``heartbeat``: the worker process's report of itself and its workers.
  ``write_heartbeat`` / ``read_heartbeat``.
- ``request:<what>``: something asked of the worker process. ``ask`` leaves
  one (asking twice before it is taken is asking once), ``take_requests``
  removes and returns them all.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from fastapi.encoders import jsonable_encoder
from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from app.config import settings
from app.models.worker_state import WorkerState

HEARTBEAT = "heartbeat"
_PUBLISHED = "published:"
_REQUEST = "request:"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _aware(value: datetime) -> datetime:
    # sqlite (the tests) hands back naive datetimes.
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def _put(db: Session, name: str, payload: Any) -> None:
    insert = pg_insert if db.get_bind().dialect.name == "postgresql" else sqlite_insert
    stmt = insert(WorkerState).values(name=name, payload=jsonable_encoder(payload), updated_at=_now())
    stmt = stmt.on_conflict_do_update(
        index_elements=[WorkerState.name],
        set_={"payload": stmt.excluded.payload, "updated_at": stmt.excluded.updated_at},
    )
    db.execute(stmt)
    db.commit()


def _get(db: Session, name: str) -> WorkerState | None:
    return db.execute(select(WorkerState).where(WorkerState.name == name)).scalars().first()


# ---------------------------------------------------------------- published answers


def publish(db: Session, what: str, payload: dict[str, Any]) -> None:
    """Store a worker's latest answer for requests to serve. Commits."""
    _put(db, _PUBLISHED + what, payload)


def published(db: Session, what: str) -> dict[str, Any] | None:
    """The last answer published under ``what``, or None before the first."""
    row = _get(db, _PUBLISHED + what)
    return dict(row.payload) if row is not None else None


# ---------------------------------------------------------------- heartbeat


@dataclass(frozen=True)
class Heartbeat:
    payload: dict[str, Any]
    reported_at: datetime

    @property
    def age_s(self) -> float:
        return (_now() - self.reported_at).total_seconds()

    @property
    def fresh(self) -> bool:
        """Recent enough to believe: a few missed beats is a dead process."""
        return self.age_s <= max(60.0, 4 * settings.WORKER_HEARTBEAT_INTERVAL_S)


def write_heartbeat(db: Session, payload: dict[str, Any]) -> None:
    _put(db, HEARTBEAT, payload)


def read_heartbeat(db: Session) -> Heartbeat | None:
    row = _get(db, HEARTBEAT)
    if row is None:
        return None
    return Heartbeat(payload=dict(row.payload), reported_at=_aware(row.updated_at))


# ---------------------------------------------------------------- requests


def ask(db: Session, what: str, payload: dict[str, Any] | None = None) -> None:
    """Leave a request for the worker process. Commits."""
    _put(db, _REQUEST + what, payload or {})


def take_requests(db: Session) -> list[tuple[str, dict[str, Any]]]:
    """Remove every waiting request and return them, oldest first."""
    rows = db.execute(
        delete(WorkerState)
        .where(WorkerState.name.startswith(_REQUEST))
        .returning(WorkerState.name, WorkerState.payload, WorkerState.updated_at)
    ).all()
    db.commit()
    rows = sorted(rows, key=lambda r: _aware(r.updated_at))
    return [(r.name[len(_REQUEST):], dict(r.payload or {})) for r in rows]
