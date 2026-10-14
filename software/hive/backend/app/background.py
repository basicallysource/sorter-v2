"""Every background worker Hive runs, and the one place that starts them.

Which of them start in a process is its role's business (``app.roles``,
``agent-docs/process-roles.md``):

- ``worker`` and ``all``: every worker in ``workers()``. The parts catalog's
  own work differs: an ``all`` process holds the catalog and syncs it and
  publishes the default profiles itself, as it always did; the worker process
  never loads it, and runs that work in child processes instead
  (``catalog-tasks``, app.services.catalog_tasks).
- ``web``: none of them. A web process looks after itself only: the memory
  line in the log (each process reports its own memory) and loading the parts
  catalog it answers requests from, off the startup path.

A web process still shows the workers' state on the admin pages and asks them
for things ("walk the storage now"), so this module is also how it does both:
``worker_status`` and ``request_pass`` read the worker process's heartbeat and
leave it requests (``app.services.worker_state``) when the workers are not in
this process, and ``serve_requests`` is the worker process's side of that.
"""

from __future__ import annotations

import logging
import os
import socket
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable

from sqlalchemy.orm import Session

from app import roles
from app.config import settings
from app.services import swatch_jobs  # noqa: F401  (registers the swatch_find job kind)
from app.services import color_model_runs  # noqa: F401  (registers the color_model_run job kind)
from app.services import piece_warm  # noqa: F401  (registers the piece_warm job kind)
from app.services import worker_state
from app.services.condition_worker import get_condition_worker
from app.services.catalog_tasks import get_catalog_task_runner
from app.services.default_profiles import start_default_profiles_thread
from app.services.fleet_mass import get_fleet_mass_worker
from app.services.fleet_records import get_fleet_records_worker
from app.services.job_queue import get_job_worker
from app.services.labeling_queue import get_labeling_queue_worker
from app.services.machine_stats import get_machine_stats_worker
from app.services.periodic import PeriodicWorker
from app.services.profile_catalog import get_existing_profile_catalog_service, get_profile_catalog_service
from app.services.server_health import get_memory_log_worker, get_storage_stats_worker
from app.services.teacher_worker import get_teacher_worker

logger = logging.getLogger(__name__)

_STARTED_AT = datetime.now(timezone.utc).isoformat()

# The names the workers below go by (the periodic ones carry their own).
CATALOG_TASKS = "catalog-tasks"
CATALOG_AUTO_SYNC = "catalog-auto-sync"
TEACHER = "teacher-worker"
CONDITION = "condition-worker"
JOBS = "job-worker"
DEFAULT_PROFILES = "default-profiles"


@dataclass(frozen=True)
class Worker:
    name: str
    start: Callable[[], Any]
    stop: Callable[[], Any]
    status: Callable[[], dict[str, Any]]
    # Run a pass now instead of at the next tick, for the workers that can.
    wake: Callable[[], Any] | None = None


def _periodic(get: Callable[[], PeriodicWorker]) -> Worker:
    return Worker(
        get().name,
        start=lambda: get().start(),
        stop=lambda: get().stop(),
        status=lambda: get().status(),
        wake=lambda: get().wake(),
    )


# --------------------------------------------------------------- the catalog's own work
#
# In an all-in-one process: the auto-sync loop and the default profiles, on
# threads, against the catalog the process holds anyway. In the worker process:
# the catalog-tasks runner, which does both (and the syncs an admin asks for)
# in child processes, so the worker never holds the catalog.


def _catalog_auto_sync_enabled() -> bool:
    return settings.PROFILE_CATALOG_AUTO_SYNC_ENABLED


def _start_catalog_auto_sync() -> None:
    # Loads the catalog first, which takes a few seconds; only when it will sync.
    if _catalog_auto_sync_enabled():
        get_profile_catalog_service().start_auto_sync_loop()


def _stop_catalog_auto_sync() -> None:
    service = get_existing_profile_catalog_service()
    if service is not None:
        service.stop_auto_sync_loop()


def _catalog_auto_sync_status() -> dict[str, Any]:
    # Never loads the catalog to answer: a status is not a reason to.
    service = get_existing_profile_catalog_service()
    return {
        "enabled": _catalog_auto_sync_enabled(),
        "running": bool(service is not None and service.auto_sync_loop_running),
    }


_default_profiles_thread: threading.Thread | None = None


def _start_default_profiles() -> None:
    global _default_profiles_thread
    # The tests make their own catalog; there is nothing to publish from it.
    if settings.ENVIRONMENT != "test":
        _default_profiles_thread = start_default_profiles_thread()


def _default_profiles_status() -> dict[str, Any]:
    thread = _default_profiles_thread
    return {"running": bool(thread is not None and thread.is_alive()), "started": thread is not None}


def _catalog_workers() -> tuple[list[Worker], list[Worker]]:
    """The catalog's workers: the ones that start first, and the ones last."""
    if roles.role() == "worker":
        runner = get_catalog_task_runner()
        return [Worker(CATALOG_TASKS, start=runner.start, stop=runner.stop, status=runner.status, wake=runner.wake)], []
    return (
        [Worker(CATALOG_AUTO_SYNC, start=_start_catalog_auto_sync, stop=_stop_catalog_auto_sync, status=_catalog_auto_sync_status)],
        [Worker(DEFAULT_PROFILES, start=_start_default_profiles, stop=lambda: None, status=_default_profiles_status)],
    )


def workers() -> list[Worker]:
    """The background workers, in the order they start."""
    first, last = _catalog_workers()
    return [
        *first,
        Worker(
            TEACHER,
            start=lambda: get_teacher_worker().start(),
            stop=lambda: get_teacher_worker().stop(),
            status=lambda: get_teacher_worker().status(),
            wake=lambda: get_teacher_worker().notify(),
        ),
        Worker(
            CONDITION,
            start=lambda: get_condition_worker().start(),
            stop=lambda: get_condition_worker().stop(),
            status=lambda: get_condition_worker().status(),
            wake=lambda: get_condition_worker().wake(),
        ),
        _periodic(get_machine_stats_worker),
        _periodic(get_fleet_mass_worker),
        _periodic(get_fleet_records_worker),
        _periodic(get_storage_stats_worker),
        _periodic(get_labeling_queue_worker),
        Worker(
            JOBS,
            start=lambda: get_job_worker().start(),  # stays off unless JOB_WORKER_ENABLED
            stop=lambda: get_job_worker().stop(),
            status=lambda: get_job_worker().status(),
            wake=lambda: get_job_worker().notify(),
        ),
        *last,
    ]


# --------------------------------------------------------------- the process's own upkeep


def _warm_catalog() -> None:
    """Load the catalog in the background, so the first requests after a start
    find it ready instead of each waiting seconds for it."""

    def run() -> None:
        try:
            get_profile_catalog_service()
        except Exception:
            logger.exception("catalog warm-up failed; the first request that needs it will load it")

    threading.Thread(target=run, name="catalog-warmup", daemon=True).start()


def _upkeep() -> list[Worker]:
    """What a process runs for itself, whatever its role."""
    memory_log = get_memory_log_worker()
    upkeep = [
        # Each process logs its own memory: the leak this watches was in the
        # process that answers requests, so it must not move to the worker.
        Worker(memory_log.name, start=memory_log.start, stop=memory_log.stop, status=memory_log.status),
    ]
    if roles.role() == "web":
        # An all-in-one process's default profiles load the catalog anyway, and
        # the worker process never loads it.
        upkeep.append(Worker("catalog-warmup", start=_warm_catalog, stop=lambda: None, status=lambda: {}))
    return upkeep


# --------------------------------------------------------------- starting and stopping

_started: list[Worker] = []
_lock = threading.Lock()


def start() -> list[str]:
    """Start what this process's role runs. Returns their names."""
    chosen = _upkeep() + (workers() if roles.runs_workers() else [])
    with _lock:
        for worker in chosen:
            worker.start()
            _started.append(worker)
    names = [w.name for w in chosen]
    logger.info("HIVE_ROLE=%s: started %s", roles.role(), ", ".join(names))
    return names


def stop() -> None:
    with _lock:
        started = list(reversed(_started))
        _started.clear()
    for worker in started:
        try:
            worker.stop()
        except Exception:
            logger.exception("%s: stop failed", worker.name)


def _find(name: str) -> Worker | None:
    return next((w for w in workers() if w.name == name), None)


# --------------------------------------------------------------- across processes


def worker_status(db: Session, name: str) -> dict[str, Any]:
    """A background worker's state, wherever it runs: its own in a process that
    runs the workers, else what the worker process last reported. ``running``
    is false when that report is too old to believe."""
    worker = _find(name)
    local = worker.status() if worker is not None else {}
    if roles.runs_workers():
        return local
    beat = worker_state.read_heartbeat(db)
    reported = ((beat.payload.get("workers") or {}).get(name) if beat else None) or {}
    status = {**local, **reported}
    status["running"] = bool(reported.get("running")) and beat is not None and beat.fresh
    status["reported_at"] = beat.reported_at.isoformat() if beat else None
    return status


def request_pass(db: Session, name: str) -> None:
    """Have a worker run a pass now rather than at its next tick."""
    if roles.runs_workers():
        worker = _find(name)
        if worker is not None and worker.wake is not None:
            worker.wake()
        return
    worker_state.ask(db, f"wake:{name}")


# The catalog syncs run where the workers run. A process that runs them uses
# its own catalog service; a web process reads what the worker process last
# reported and leaves it these requests.


def reported_catalog_status(db: Session) -> dict[str, Any] | None:
    """The catalog sync state as the worker process last reported it, or None
    when it has not reported lately."""
    beat = worker_state.read_heartbeat(db)
    if beat is None or not beat.fresh:
        return None
    return beat.payload.get("catalog")


def ask_catalog_sync(db: Session, sync_type: str) -> None:
    worker_state.ask(db, f"catalog-sync:{sync_type}")


def ask_catalog_stop(db: Session) -> None:
    worker_state.ask(db, "catalog-stop")


# --------------------------------------------------------------- the worker process's side


def heartbeat_payload() -> dict[str, Any]:
    return {
        "process": {
            "role": roles.role(),
            "host": socket.gethostname(),
            "pid": os.getpid(),
            "started_at": _STARTED_AT,
        },
        "workers": {w.name: _safe_status(w) for w in workers()},
        "catalog": _catalog_status(),
    }


def _catalog_status() -> dict[str, Any] | None:
    """The catalog page's status, as the process that syncs the catalog sees it."""
    try:
        if roles.role() == "worker":
            return get_catalog_task_runner().catalog_status()
        catalog = get_existing_profile_catalog_service()
        return catalog.status() if catalog is not None else None
    except FileNotFoundError:
        return None  # no parts.db yet: a new install, before its first sync
    except Exception:
        logger.exception("could not read the catalog's status for the heartbeat")
        return None


def _safe_status(worker: Worker) -> dict[str, Any]:
    try:
        return worker.status()
    except Exception as exc:  # one broken status must not cost the whole report
        return {"running": False, "status_error": str(exc)[:300]}


def serve_requests(db: Session) -> list[str]:
    """Do what the web process asked for since the last look. Returns what was done."""
    done = []
    for what, _payload in worker_state.take_requests(db):
        kind, _, arg = what.partition(":")
        try:
            if kind == "wake":
                worker = _find(arg)
                if worker is None or worker.wake is None:
                    logger.warning("request to wake %r, which has no pass to run", arg)
                    continue
                worker.wake()
            elif kind == "catalog-sync":
                get_catalog_task_runner().request("sync", arg)
            elif kind == "catalog-stop":
                get_catalog_task_runner().request_stop()
            else:
                logger.warning("unknown request %r from the web process", what)
                continue
        except Exception:
            logger.exception("request %r failed", what)
            continue
        done.append(what)
    return done
