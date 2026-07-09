from __future__ import annotations
import os
import platform
import threading
import time
from pathlib import Path
from typing import TYPE_CHECKING, Optional, Union

if TYPE_CHECKING:
    from global_config import GlobalConfig

# Single background pruning system for everything that grows unbounded on the
# machine: the software/logs/ run logs, plus a one-time drain of the legacy
# per-second metric snapshot tables that used to bloat local_state.sqlite
# (metric writes now go to local_metrics.sqlite, which does its own retention).
# One daemon thread runs every _PRUNE_INTERVAL_S, drops itself to idle I/O +
# CPU priority and paces its deletes so a multi-GB cleanup can never choke the
# camera / hardware hot loops.

DEFAULT_MAX_LOG_BYTES = 1 * 1024 ** 3

_PRUNE_INTERVAL_S = 3600
_LOG_DELETE_PACING_S = 0.1
_DB_DELETE_BATCH = 5000
_DB_DELETE_PACING_S = 0.05

# Arch-specific __NR_ioprio_set — glibc ships no wrapper for it, so we go
# straight through syscall(). Numbers differ per ABI; the Orange Pi is aarch64.
_IOPRIO_SET_SYSCALL = {
    "x86_64": 251,
    "aarch64": 30,
    "armv7l": 289,
    "armv6l": 289,
    "i686": 289,
}
_IOPRIO_CLASS_IDLE = 3
_IOPRIO_CLASS_SHIFT = 13
_IOPRIO_WHO_PROCESS = 1


def _deprioritizeCurrentThread() -> None:
    try:
        os.nice(19)
    except Exception:
        pass
    syscall_nr = _IOPRIO_SET_SYSCALL.get(platform.machine())
    if syscall_nr is None:
        return
    try:
        import ctypes

        libc = ctypes.CDLL("libc.so.6", use_errno=True)
        tid = threading.get_native_id()
        prio = _IOPRIO_CLASS_IDLE << _IOPRIO_CLASS_SHIFT
        libc.syscall(syscall_nr, _IOPRIO_WHO_PROCESS, tid, prio)
    except Exception:
        pass


def _pruneLogs(gc: "GlobalConfig", log_dir: Path, current_log: Optional[Path], max_bytes: int) -> None:
    if not max_bytes or max_bytes <= 0:
        return

    entries: list[tuple[float, int, Path]] = []
    try:
        for path in log_dir.glob("*.log"):
            if path == current_log:
                continue
            try:
                st = path.stat()
            except OSError:
                continue
            entries.append((st.st_mtime, st.st_size, path))
    except OSError:
        return

    # current_log is None when file dumping is off — nothing live to protect,
    # so we just trim the leftover .log files down to the cap.
    current_size = 0
    if current_log is not None:
        try:
            current_size = current_log.stat().st_size
        except OSError:
            current_size = 0

    # The live session is always kept; we only ever remove whole prior .log
    # files, oldest-first, until everything fits under the cap. Never truncate —
    # a partial file would be a partial session, which we explicitly avoid.
    entries.sort(key=lambda e: e[0])
    total = current_size + sum(size for _, size, _ in entries)
    if total <= max_bytes:
        return

    freed = 0
    deleted = 0
    for _, size, path in entries:
        if total <= max_bytes:
            break
        try:
            path.unlink()
        except OSError:
            continue
        total -= size
        freed += size
        deleted += 1
        time.sleep(_LOG_DELETE_PACING_S)

    if deleted:
        gc.logger.info(
            f"log prune: removed {deleted} old session log(s), "
            f"freed {freed / 1024 ** 2:.0f} MiB (cap {max_bytes / 1024 ** 2:.0f} MiB)"
        )


def _drainLegacyMetricTables(gc: "GlobalConfig") -> None:
    from local_state import drain_legacy_metric_snapshot_tables

    deleted = drain_legacy_metric_snapshot_tables(
        batch_size=_DB_DELETE_BATCH, pacing_s=_DB_DELETE_PACING_S
    )
    total = sum(deleted.values())
    if total:
        detail = ", ".join(f"{name}={count}" for name, count in deleted.items() if count)
        gc.logger.info(
            f"legacy metrics drain: removed {total} snapshot row(s) and dropped emptied table(s) ({detail})"
        )


def _run(
    gc: "GlobalConfig",
    log_dir: Path,
    current_log: Optional[Path],
    max_bytes: int,
) -> None:
    _deprioritizeCurrentThread()
    while True:
        try:
            _pruneLogs(gc, log_dir, current_log, max_bytes)
        except Exception as exc:
            try:
                gc.logger.error(f"log prune failed: {exc}")
            except Exception:
                pass
        try:
            _drainLegacyMetricTables(gc)
        except Exception as exc:
            try:
                gc.logger.error(f"legacy metrics drain failed: {exc}")
            except Exception:
                pass
        time.sleep(_PRUNE_INTERVAL_S)


def runPruningAsync(gc: "GlobalConfig", log_dir: Union[str, Path], current_log: Optional[Union[str, Path]]) -> None:
    max_bytes = int(getattr(gc, "max_log_bytes", DEFAULT_MAX_LOG_BYTES) or 0)
    thread = threading.Thread(
        target=_run,
        args=(
            gc,
            Path(log_dir),
            Path(current_log) if current_log is not None else None,
            max_bytes,
        ),
        name="pruner",
        daemon=True,
    )
    thread.start()
