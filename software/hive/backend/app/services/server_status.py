"""What the admin Server page shows: how requests went in the last hour, this
process, the job queue, the background workers (wherever they run),
the database's health, the disk, memory and the stored files.

Everything here is cheap: the request numbers are in memory
(``app.middleware.request_timing``), the database figures come from
Postgres's own statistics views and catalog, the job counts from the jobs
table's indexes, and the stored-file totals from the cache the storage walk
keeps. The database part runs under a short statement timeout, so the page
cannot hold a connection for long however sick the database is. Each part
is read on its own: one that fails says so and the rest still show.
"""

from __future__ import annotations

import logging
import os
import shutil
import threading
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Callable

import anyio.from_thread
import anyio.to_thread
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app import background
from app.config import settings
from app.database import engine
from app.middleware.request_timing import request_stats
from app.models.job import Job
from app.services import job_queue
from app.services.redact import redact_secrets
from app.services.server_health import get_memory_stats, get_storage_stats

log = logging.getLogger(__name__)

STATEMENT_TIMEOUT_MS = 5000
_QUERY_CHARS = 500
_ROWS = 12


def server_status(db: Session) -> dict[str, Any]:
    return {
        "generated_at": _iso(datetime.now(timezone.utc)),
        "process": _part(_process),
        "requests": _part(request_stats.snapshot),
        "workers": _db_part(db, _workers),
        "jobs": _db_part(db, _jobs),
        "database": _db_part(db, _database),
        "disk": _part(_disks),
        "memory": _part(get_memory_stats),
        "storage": _db_part(db, get_storage_stats),
    }


def _part(read: Callable[[], Any], db: Session | None = None) -> Any:
    try:
        return read()
    except Exception as exc:
        log.exception("server page: a part could not be read")
        if db is not None:
            try:
                db.rollback()
            except Exception:
                log.exception("server page: could not roll back after a part failed")
        return {"error": f"{type(exc).__name__}: {exc}"[:300]}


def _db_part(db: Session, read: Callable[[Session], Any]) -> Any:
    def limited() -> Any:
        # SET LOCAL lasts until the transaction ends, so a part after one
        # that failed (and rolled back) sets it again.
        if db.get_bind().dialect.name == "postgresql":
            db.execute(text(f"SET LOCAL statement_timeout = {STATEMENT_TIMEOUT_MS}"))
        return read(db)

    return _part(limited, db=db)


def _iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.isoformat()


# ---------------------------------------------------------------- the process


def _process() -> dict[str, Any]:
    load = os.getloadavg() if hasattr(os, "getloadavg") else None
    return {
        "pid": os.getpid(),
        # Which background work this process runs, where processes are split.
        "role": os.environ.get("HIVE_ROLE") or None,
        "started_at": _iso(datetime.fromtimestamp(request_stats.started_at, timezone.utc)),
        "uptime_s": round(time.time() - request_stats.started_at),
        "threads": threading.active_count(),
        "cpus": os.cpu_count(),
        "load": [round(x, 2) for x in load] if load else None,
        "db_pool": _db_pool(),
        "threadpool": _threadpool(),
    }


def _db_pool() -> dict[str, Any]:
    """This process's database connections: how many requests and workers
    hold one now, of how many it may open."""
    pool = engine.pool
    size = pool.size() if hasattr(pool, "size") else None
    overflow = getattr(pool, "_max_overflow", None)
    return {
        "checked_out": pool.checkedout() if hasattr(pool, "checkedout") else None,
        "limit": size + overflow if isinstance(size, int) and isinstance(overflow, int) and overflow >= 0 else size,
    }


def _threadpool() -> dict[str, Any] | None:
    """The threads synchronous endpoints run on: how many are busy (this
    request's own among them) and how many requests wait for one."""

    def read() -> dict[str, Any]:
        stats = anyio.to_thread.current_default_thread_limiter().statistics()
        return {"busy": stats.borrowed_tokens, "size": int(stats.total_tokens), "waiting": stats.tasks_waiting}

    try:
        # Asked on the event loop, which owns the limiter.
        return anyio.from_thread.run_sync(read)
    except Exception:
        return None


# ---------------------------------------------------------------- the workers


# What the page calls each background worker (``app.background``).
_WORKER_LABELS = {
    "machine-stats-worker": "Machine stats",
    "fleet-mass-worker": "Fleet mass",
    "fleet-records-worker": "Fleet records",
    "labeling-queue-worker": "Labeling queue",
    "storage-stats-worker": "Storage walk",
    background.TEACHER: "Teacher",
    background.CONDITION: "Condition",
    background.JOBS: "Job queue",
    background.CATALOG_TASKS: "Catalog tasks",
    background.CATALOG_AUTO_SYNC: "Catalog auto-sync",
    background.DEFAULT_PROFILES: "Default profiles",
}


def _workers(db: Session) -> list[dict[str, Any]]:
    """Every background worker, wherever it runs: this process's own state when it
    runs them, else what the worker process last reported (``background.worker_status``),
    shown as not running once that report is too old to believe."""
    rows = []
    for worker in background.workers():
        s = background.worker_status(db, worker.name)
        rows.append(
            {
                "name": _WORKER_LABELS.get(worker.name, worker.name),
                "running": bool(s.get("running")),
                "last_run_at": s.get("last_run_at") or s.get("last_job_at"),
                "last_run_s": s.get("last_run_duration_s"),
                "last_error": s.get("last_error"),
                "every_s": s.get("interval_s") or s.get("poll_interval_s"),
                "runs": s.get("total_runs") if s.get("total_runs") is not None else s.get("processed"),
                "reported_at": s.get("reported_at"),
            }
        )
    return rows


# ---------------------------------------------------------------- the job queue


def _jobs(db: Session) -> dict[str, Any]:
    """The queue as the database has it, whichever process runs the jobs:
    each kind's counts, what finished and failed in the last hour, what is
    running now and by which worker, and the latest failures."""
    summary = job_queue.summary(db, failures=5)
    hour_ago = datetime.now(timezone.utc) - timedelta(hours=1)
    last_hour: dict[tuple[str, str], int] = {
        (kind, status): int(n)
        for kind, status, n in db.execute(
            select(Job.kind, Job.status, func.count())
            .where(Job.status.in_(("done", "failed")), Job.finished_at >= hour_ago)
            .group_by(Job.kind, Job.status)
        )
    }
    running = db.execute(
        select(Job.kind, Job.subject, Job.locked_by, Job.started_at)
        .where(Job.status == "running")
        .order_by(Job.started_at)
        .limit(_ROWS)
    ).all()
    last_done = db.execute(select(func.max(Job.finished_at)).where(Job.status == "done")).scalar()
    now = datetime.now(timezone.utc)
    return {
        "kinds": [
            {
                **kind,
                "done_last_hour": last_hour.get((kind["kind"], "done"), 0),
                "failed_last_hour": last_hour.get((kind["kind"], "failed"), 0),
            }
            for kind in summary["kinds"]
        ],
        "last_done_at": _iso(last_done),
        "running": [
            {
                "kind": kind,
                "subject": subject,
                # host:pid of the worker that holds it.
                "worker": ":".join((locked_by or "").split(":")[:2]) or None,
                "running_s": round((now - _aware(started)).total_seconds()) if started else None,
            }
            for kind, subject, locked_by, started in running
        ],
        "recent_failures": summary["recent_failures"],
        # The job worker as the process that runs it last reported (this one or the worker process).
        "worker": background.worker_status(db, background.JOBS),
    }


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)


# ---------------------------------------------------------------- the database


def _database(db: Session) -> dict[str, Any]:
    dialect = db.get_bind().dialect.name
    if dialect != "postgresql":
        return {"dialect": dialect}
    overall = db.execute(
        text(
            """
            SELECT pg_database_size(current_database()) AS size_bytes,
                   d.blks_hit, d.blks_read, d.temp_files, d.temp_bytes, d.deadlocks,
                   d.xact_commit, d.xact_rollback, d.stats_reset,
                   pg_postmaster_start_time() AS started_at,
                   current_setting('server_version') AS version,
                   current_setting('max_connections')::int AS max_connections,
                   current_setting('shared_buffers') AS shared_buffers
            FROM pg_stat_database d
            WHERE d.datname = current_database()
            """
        )
    ).mappings().one()
    hit, read = int(overall["blks_hit"] or 0), int(overall["blks_read"] or 0)
    connections = db.execute(
        text(
            """
            SELECT coalesce(state, 'unknown') AS state, count(*) AS n
            FROM pg_stat_activity
            WHERE backend_type = 'client backend' AND datname = current_database()
            GROUP BY 1
            ORDER BY 2 DESC
            """
        )
    ).all()
    all_clients = db.execute(
        text("SELECT count(*) FROM pg_stat_activity WHERE backend_type = 'client backend'")
    ).scalar()
    active = db.execute(
        text(
            """
            SELECT pid, state, application_name, client_addr::text AS client,
                   wait_event_type, wait_event,
                   extract(epoch FROM now() - query_start) AS query_s,
                   extract(epoch FROM now() - xact_start) AS transaction_s,
                   left(query, :chars) AS query
            FROM pg_stat_activity
            WHERE backend_type = 'client backend' AND datname = current_database()
              AND pid <> pg_backend_pid() AND state <> 'idle'
            ORDER BY xact_start NULLS LAST, query_start
            LIMIT 5
            """
        ),
        {"chars": _QUERY_CHARS},
    ).mappings().all()
    tables = db.execute(
        text(
            """
            SELECT c.relname AS name,
                   pg_total_relation_size(c.oid) AS total_bytes,
                   pg_indexes_size(c.oid) AS index_bytes,
                   greatest(c.reltuples, 0)::bigint AS rows,
                   s.n_dead_tup AS dead_rows,
                   s.seq_scan, s.seq_tup_read, s.idx_scan,
                   greatest(s.last_autovacuum, s.last_vacuum) AS last_vacuum
            FROM pg_class c
            JOIN pg_namespace n ON n.oid = c.relnamespace
            LEFT JOIN pg_stat_user_tables s ON s.relid = c.oid
            WHERE n.nspname = 'public' AND c.relkind IN ('r', 'm')
            ORDER BY pg_total_relation_size(c.oid) DESC
            LIMIT :rows
            """
        ),
        {"rows": _ROWS},
    ).mappings().all()
    indexes = db.execute(
        text(
            """
            SELECT s.indexrelname AS name, s.relname AS table_name,
                   pg_relation_size(s.indexrelid) AS bytes, s.idx_scan AS scans
            FROM pg_stat_user_indexes s
            ORDER BY pg_relation_size(s.indexrelid) DESC
            LIMIT :rows
            """
        ),
        {"rows": _ROWS},
    ).mappings().all()
    return {
        "dialect": dialect,
        "version": overall["version"],
        "size_bytes": int(overall["size_bytes"] or 0),
        "started_at": _iso(overall["started_at"]),
        "stats_since": _iso(overall["stats_reset"] or overall["started_at"]),
        "shared_buffers": overall["shared_buffers"],
        "cache_hit_ratio": round(hit / (hit + read), 4) if hit + read else None,
        "temp_files": int(overall["temp_files"] or 0),
        "temp_bytes": int(overall["temp_bytes"] or 0),
        "deadlocks": int(overall["deadlocks"] or 0),
        "commits": int(overall["xact_commit"] or 0),
        "rollbacks": int(overall["xact_rollback"] or 0),
        "connections": {
            "max": int(overall["max_connections"]),
            "all_databases": int(all_clients or 0),
            "by_state": [{"state": state, "count": int(n)} for state, n in connections],
        },
        "longest": [
            {
                "pid": r["pid"],
                "state": r["state"],
                "application": r["application_name"] or None,
                "client": r["client"],
                "waiting_on": f"{r['wait_event_type']}: {r['wait_event']}" if r["wait_event_type"] else None,
                "query_s": round(float(r["query_s"]), 1) if r["query_s"] is not None else None,
                "transaction_s": round(float(r["transaction_s"]), 1) if r["transaction_s"] is not None else None,
                "query": redact_secrets(r["query"] or ""),
            }
            for r in active
        ],
        "tables": [
            {
                "name": r["name"],
                "total_bytes": int(r["total_bytes"] or 0),
                "index_bytes": int(r["index_bytes"] or 0),
                "rows": int(r["rows"] or 0),
                "dead_rows": int(r["dead_rows"]) if r["dead_rows"] is not None else None,
                "seq_scans": int(r["seq_scan"]) if r["seq_scan"] is not None else None,
                "seq_rows_read": int(r["seq_tup_read"]) if r["seq_tup_read"] is not None else None,
                "index_scans": int(r["idx_scan"]) if r["idx_scan"] is not None else None,
                "last_vacuum": _iso(r["last_vacuum"]),
            }
            for r in tables
        ],
        "indexes": [
            {
                "name": r["name"],
                "table": r["table_name"],
                "bytes": int(r["bytes"] or 0),
                "scans": int(r["scans"] or 0),
            }
            for r in indexes
        ],
    }


# ---------------------------------------------------------------- the disk


def _disks() -> list[dict[str, Any]]:
    """Space on the filesystems this process writes to, as it sees them: in
    a container, its root is the host's disk that Docker keeps its data on."""
    paths = [("The backend's disk", "/")]
    if (settings.STORAGE_BACKEND or "local").strip().lower() == "local":
        paths.append(("Stored files", settings.UPLOAD_DIR))
    rows: list[dict[str, Any]] = []
    devices: set[int] = set()
    for label, path in paths:
        try:
            device = os.stat(path).st_dev
        except OSError:
            continue
        if device in devices:
            continue
        devices.add(device)
        usage = shutil.disk_usage(path)
        rows.append({"label": label, "path": path, "total_bytes": usage.total, "free_bytes": usage.free})
    return rows
