from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, String

from app.models import JSON_VARIANT, Base


class WorkerState(Base):
    """What the worker process and the web process tell each other, one row
    per name (``app.services.worker_state``):

    - ``published:<what>``: a background worker's latest answer that requests
      serve (the fleet's mass, the fleet records), so the web process never
      computes it and a restart of either never loses it.
    - ``heartbeat``: the worker process's report of itself and each of its
      workers, written every ``WORKER_HEARTBEAT_INTERVAL_S``. The admin pages
      read it in a web process, which has no workers of its own to ask.
    - ``request:<what>``: something an admin asked the worker process to do
      (run a pass now, start or stop a catalog sync). The worker takes the row
      and does it within a couple of seconds.
    """

    __tablename__ = "worker_state"

    name = Column(String(120), primary_key=True)
    payload = Column(JSON_VARIANT, nullable=False)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
