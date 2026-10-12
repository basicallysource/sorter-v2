"""Which part of Hive this process is: ``HIVE_ROLE`` (app.config).

One image runs as two processes in production: ``web`` answers requests and
``worker`` runs every background worker (``python -m app.worker``). ``all`` is
both in one process, for a dev server and the tests. The reasons and the
details are in ``agent-docs/process-roles.md``.
"""

from __future__ import annotations

from app.config import settings


def role() -> str:
    return settings.HIVE_ROLE


def runs_workers() -> bool:
    """This process runs the background workers (and owns the catalog syncs)."""
    return settings.HIVE_ROLE in ("all", "worker")


def serves_requests() -> bool:
    """This process answers HTTP requests."""
    return settings.HIVE_ROLE in ("all", "web")
