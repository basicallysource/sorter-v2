from __future__ import annotations
import os
import platform
import threading
import time
from pathlib import Path
from typing import TYPE_CHECKING, Optional, Union

if TYPE_CHECKING:
    from global_config import GlobalConfig

DEFAULT_MAX_LOG_BYTES = 1 * 1024 ** 3

# Deleting several multi-GB run logs off the SD card at once can saturate disk
# I/O and stall the camera / hardware hot loops. The prune therefore runs on a
# detached daemon thread, drops itself to idle I/O + CPU priority, and paces
# each unlink so it can never starve the live session of disk bandwidth.
_DELETE_PACING_S = 0.1

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


def _pruneOldLogsBlocking(gc: "GlobalConfig", log_dir: Path, current_log: Optional[Path], max_bytes: int) -> None:
    _deprioritizeCurrentThread()

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
        time.sleep(_DELETE_PACING_S)

    if deleted:
        gc.logger.info(
            f"log prune: removed {deleted} old session log(s), "
            f"freed {freed / 1024 ** 2:.0f} MiB (cap {max_bytes / 1024 ** 2:.0f} MiB)"
        )


def pruneOldLogsAsync(gc: "GlobalConfig", log_dir: Union[str, Path], current_log: Optional[Union[str, Path]]) -> None:
    max_bytes = getattr(gc, "max_log_bytes", DEFAULT_MAX_LOG_BYTES)
    if not max_bytes or max_bytes <= 0:
        return
    thread = threading.Thread(
        target=_pruneOldLogsBlocking,
        args=(gc, Path(log_dir), Path(current_log) if current_log is not None else None, int(max_bytes)),
        name="log-pruner",
        daemon=True,
    )
    thread.start()
