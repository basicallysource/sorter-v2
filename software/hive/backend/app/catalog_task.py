"""One piece of parts-catalog work, in a process of its own.

    python -m app.catalog_task default-profiles
    python -m app.catalog_task auto-sync
    python -m app.catalog_task sync <sets|categories|colors|parts|brickstore|prices|geometry>

The worker process never holds the parts catalog: it is ~390 MB in memory, and
the worker needs all of it only to sync it and to publish the default profiles
at its start. So the worker runs each of those as this, one at a time
(app.services.catalog_tasks): the child loads the catalog, does the one thing,
writes what an all-in-one process writes (parts.db; the default profiles in
Postgres), logs its peak memory and exits, and its memory goes back with it.
SIGTERM stops a sync the way the stop button on the catalog page does.

Exit status: 0 done (or stopped as asked), 1 failed (logged), 2 not a task.
"""

from __future__ import annotations

import logging
import signal
import sys
import threading
import time

from app.logging_config import configure_app_logging

logger = logging.getLogger("app.catalog_task")


def _peak_mb() -> int | None:
    try:
        with open("/proc/self/status") as f:
            for line in f:
                if line.startswith("VmHWM:"):
                    return int(line.split()[1]) // 1024
    except OSError:
        return None
    return None


def run(task: list[str]) -> int:
    from app.services import profile_catalog

    kind = task[0] if task else ""
    if kind not in ("default-profiles", "auto-sync", "sync") or (
        kind == "sync" and (len(task) != 2 or task[1] not in profile_catalog.PROFILE_CATALOG_SYNC_TYPES)
    ):
        logger.error("catalog task: not a task: %r", " ".join(task))
        return 2
    profile_catalog.allow_catalog_in_this_process()
    if kind == "default-profiles":
        from app.services.default_profiles import run_default_profiles

        return 0 if run_default_profiles() else 1

    service = profile_catalog.get_profile_catalog_service()
    # Nothing here reads the catalog while a sync reloads it at its end, so the
    # reload need not hold the old copy and the new one at once.
    service.parts_data.release_before_reload = True
    stopping = threading.Event()

    def _stop(signum: int, _frame: object) -> None:
        logger.info("catalog task: signal %d, stopping the sync", signum)
        stopping.set()
        service.stop_sync()

    signal.signal(signal.SIGTERM, _stop)
    plan = service.get_auto_sync_plan() if kind == "auto-sync" else [task[1]]
    if not plan:
        logger.info("catalog task: nothing to sync")
    for sync_type in plan:
        if stopping.is_set():
            break
        logger.info("catalog task: syncing %s", sync_type)
        if not service.start_sync(sync_type):
            logger.error("catalog task: the %s sync did not start: %s", sync_type, service.status().get("error"))
            return 1
        if not service.wait_for_sync():
            logger.error("catalog task: the %s sync failed: %s", sync_type, service.status().get("error"))
            return 1
    return 0


def main(argv: list[str] | None = None) -> int:
    configure_app_logging()
    task = list(sys.argv[1:] if argv is None else argv)
    started = time.monotonic()
    try:
        code = run(task)
    except Exception:
        logger.exception("catalog task %s failed", " ".join(task))
        code = 1
    logger.info(
        "catalog task %s: exit %d after %.0fs, peak %s MB",
        " ".join(task),
        code,
        time.monotonic() - started,
        _peak_mb(),
    )
    return code


if __name__ == "__main__":
    sys.exit(main())
