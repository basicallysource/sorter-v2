from __future__ import annotations

import atexit
import getpass
import hashlib
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import tempfile
import time
from typing import Any, TextIO

try:
    import fcntl
except ImportError:  # pragma: no cover - not expected on macOS/Linux dev hosts
    fcntl = None


APP_NAME = "lego-sorter-client-backend"
LOCK_RETRY_INTERVAL_S = 0.1
TERMINATE_GRACE_PERIOD_S = 5.0
FORCE_KILL_GRACE_PERIOD_S = 2.0


class ProcessGuardError(RuntimeError):
    pass


class BackendProcessGuard:
    def __init__(self, lock_path: Path, handle: TextIO, metadata: dict[str, Any]) -> None:
        self.lock_path = lock_path
        self._handle = handle
        self.metadata = metadata
        self._released = False
        atexit.register(self.release)

    def release(self) -> None:
        if self._released:
            return
        self._released = True

        try:
            self._handle.seek(0)
            self._handle.truncate()
            self._handle.flush()
            os.fsync(self._handle.fileno())
        except Exception:
            pass

        if fcntl is not None:
            try:
                fcntl.flock(self._handle.fileno(), fcntl.LOCK_UN)
            except Exception:
                pass

        try:
            self._handle.close()
        except Exception:
            pass


def acquire_backend_process_guard(
    *,
    script_path: Path,
    repo_root: Path,
    port: int | None = 8000,
    logger: Any | None = None,
    terminate_existing: bool = True,
    cleanup_port_conflicts: bool = True,
    lock_path: Path | None = None,
) -> BackendProcessGuard:
    if fcntl is None:
        raise ProcessGuardError("Backend process guard requires fcntl support on this platform.")

    resolved_script = script_path.resolve()
    resolved_repo = repo_root.resolve()
    resolved_lock_path = lock_path.resolve() if lock_path is not None else _default_lock_path(resolved_repo)
    metadata = _build_metadata(resolved_script, resolved_repo, port)

    resolved_lock_path.parent.mkdir(parents=True, exist_ok=True)
    handle = resolved_lock_path.open("a+", encoding="utf-8")

    try:
        _acquire_or_replace_lock(
            handle=handle,
            lock_path=resolved_lock_path,
            current_metadata=metadata,
            logger=logger,
            terminate_existing=terminate_existing,
        )
        guard = BackendProcessGuard(resolved_lock_path, handle, metadata)
    except Exception:
        handle.close()
        raise

    _log(logger, "info", "Acquired backend process guard at %s", resolved_lock_path)

    if cleanup_port_conflicts and port is not None:
        _cleanup_listening_conflicts(
            port=port,
            script_path=resolved_script,
            repo_root=resolved_repo,
            logger=logger,
        )

    return guard


def _default_lock_path(repo_root: Path) -> Path:
    repo_key = hashlib.sha1(str(repo_root).encode("utf-8")).hexdigest()[:12]
    return Path(tempfile.gettempdir()) / f"{APP_NAME}-{repo_key}.lock"


def _build_metadata(script_path: Path, repo_root: Path, port: int | None) -> dict[str, Any]:
    return {
        "app": APP_NAME,
        "pid": os.getpid(),
        "user": getpass.getuser(),
        "script_path": str(script_path),
        "repo_root": str(repo_root),
        "cwd": str(script_path.parent),
        "port": port,
        "started_at": time.time(),
    }


def _acquire_or_replace_lock(
    *,
    handle: TextIO,
    lock_path: Path,
    current_metadata: dict[str, Any],
    logger: Any | None,
    terminate_existing: bool,
) -> None:
    try:
        _try_lock(handle)
    except BlockingIOError:
        existing_metadata = _read_metadata(handle)
        if existing_metadata is None:
            raise ProcessGuardError(
                f"Backend lock at {lock_path} is already held, but its owner metadata could not be read safely."
            )

        if not terminate_existing:
            raise ProcessGuardError(_format_existing_process_message(lock_path, existing_metadata))

        if not _metadata_matches_current_repo(existing_metadata, current_metadata):
            raise ProcessGuardError(_format_existing_process_message(lock_path, existing_metadata))

        existing_pid = _safe_int(existing_metadata.get("pid"))
        if existing_pid is None or existing_pid <= 0 or existing_pid == os.getpid():
            raise ProcessGuardError(_format_existing_process_message(lock_path, existing_metadata))

        _log(
            logger,
            "warning",
            "Another backend instance for this repo is active (pid=%s). Requesting shutdown before continuing.",
            existing_pid,
        )
        _terminate_process(existing_pid, logger=logger)

        deadline = time.monotonic() + TERMINATE_GRACE_PERIOD_S + FORCE_KILL_GRACE_PERIOD_S
        while time.monotonic() < deadline:
            try:
                _try_lock(handle)
                break
            except BlockingIOError:
                time.sleep(LOCK_RETRY_INTERVAL_S)
        else:
            raise ProcessGuardError(
                f"Failed to take over backend lock at {lock_path} after stopping pid {existing_pid}."
            )

    _write_metadata(handle, current_metadata)


def _try_lock(handle: TextIO) -> None:
    assert fcntl is not None
    fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)


def _read_metadata(handle: TextIO) -> dict[str, Any] | None:
    try:
        handle.seek(0)
        raw = handle.read().strip()
    except Exception:
        return None

    if not raw:
        return None

    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return None

    if not isinstance(data, dict):
        return None
    return data


def _write_metadata(handle: TextIO, metadata: dict[str, Any]) -> None:
    handle.seek(0)
    handle.truncate()
    json.dump(metadata, handle)
    handle.flush()
    os.fsync(handle.fileno())


def _metadata_matches_current_repo(existing_metadata: dict[str, Any], current_metadata: dict[str, Any]) -> bool:
    return (
        existing_metadata.get("app") == APP_NAME
        and existing_metadata.get("repo_root") == current_metadata.get("repo_root")
        and existing_metadata.get("script_path") == current_metadata.get("script_path")
    )


def _terminate_process(pid: int, logger: Any | None) -> None:
    if not _send_signal(pid, signal.SIGTERM):
        return
    if _wait_for_process_exit(pid, TERMINATE_GRACE_PERIOD_S):
        return

    _log(logger, "warning", "Backend pid=%s did not exit after SIGTERM; escalating to SIGKILL.", pid)
    if not _send_signal(pid, signal.SIGKILL):
        return
    if _wait_for_process_exit(pid, FORCE_KILL_GRACE_PERIOD_S):
        return

    raise ProcessGuardError(f"Backend pid {pid} ignored termination signals.")


def _wait_for_process_exit(pid: int, timeout_s: float) -> bool:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if not _process_exists(pid):
            return True
        time.sleep(LOCK_RETRY_INTERVAL_S)
    return not _process_exists(pid)


def _process_exists(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True

    state = _read_process_state(pid)
    if state is not None and state.startswith("Z"):
        return False
    return True


def _send_signal(pid: int, sig: int) -> bool:
    try:
        os.kill(pid, sig)
    except ProcessLookupError:
        return False
    return True


def _cleanup_listening_conflicts(
    *,
    port: int,
    script_path: Path,
    repo_root: Path,
    logger: Any | None,
) -> None:
    listener_pids = _find_listening_pids(port)
    unresolved: list[str] = []

    for pid in listener_pids:
        if pid == os.getpid():
            continue

        process_info = _read_process_info(pid)
        if process_info is None:
            continue

        if process_info["user"] != getpass.getuser():
            unresolved.append(f"pid {pid} owned by {process_info['user']}")
            continue

        if not _process_matches_current_backend(
            pid=pid,
            command=process_info["command"],
            script_path=script_path,
            repo_root=repo_root,
        ):
            unresolved.append(f"pid {pid} listening on {port} with command: {process_info['command']}")
            continue

        _log(
            logger,
            "warning",
            "Port %s is already held by a stale backend process (pid=%s). Stopping it before startup.",
            port,
            pid,
        )
        _terminate_process(pid, logger=logger)

    if unresolved:
        raise ProcessGuardError(
            f"Backend startup aborted because port {port} is already in use: {'; '.join(unresolved)}"
        )


def _find_listening_pids(port: int) -> list[int]:
    if shutil.which("lsof") is None:
        return []

    result = subprocess.run(
        ["lsof", "-nP", "-t", f"-iTCP:{port}", "-sTCP:LISTEN"],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode not in (0, 1):
        return []

    pids: list[int] = []
    for line in result.stdout.splitlines():
        pid = _safe_int(line.strip())
        if pid is not None:
            pids.append(pid)
    return pids


def _read_process_info(pid: int) -> dict[str, str] | None:
    result = subprocess.run(
        ["ps", "-o", "user=", "-o", "command=", "-p", str(pid)],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        return None

    output = result.stdout.strip()
    if not output:
        return None

    parts = output.split(None, 1)
    if len(parts) != 2:
        return None

    return {"user": parts[0], "command": parts[1]}


def _read_process_state(pid: int) -> str | None:
    result = subprocess.run(
        ["ps", "-o", "stat=", "-p", str(pid)],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        return None

    state = result.stdout.strip()
    return state or None


def _read_process_cwd(pid: int) -> Path | None:
    if shutil.which("lsof") is None:
        return None

    result = subprocess.run(
        ["lsof", "-a", "-p", str(pid), "-d", "cwd", "-Fn"],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        return None

    for line in result.stdout.splitlines():
        if line.startswith("n"):
            try:
                return Path(line[1:]).resolve()
            except OSError:
                return None
    return None


def _process_matches_current_backend(
    *,
    pid: int,
    command: str,
    script_path: Path,
    repo_root: Path,
) -> bool:
    normalized_command = command.replace("\\", "/")
    normalized_script = str(script_path).replace("\\", "/")
    normalized_repo = str(repo_root).replace("\\", "/")

    if normalized_script in normalized_command:
        return True
    if normalized_repo in normalized_command and "main.py" in normalized_command:
        return True

    process_cwd = _read_process_cwd(pid)
    if process_cwd is None:
        return False

    resolved_client_dir = script_path.parent.resolve()
    return process_cwd == resolved_client_dir or process_cwd == repo_root.resolve()


def _format_existing_process_message(lock_path: Path, metadata: dict[str, Any]) -> str:
    pid = metadata.get("pid", "unknown")
    repo_root = metadata.get("repo_root", "unknown")
    return (
        f"Backend lock at {lock_path} is already held by pid {pid} for repo {repo_root}. "
        "Refusing to start a second backend instance."
    )


def _safe_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _log(logger: Any | None, level: str, msg: str, *args: Any) -> None:
    if logger is None:
        text = msg % args if args else msg
        print(f"[process_guard] {text}")
        return

    log_fn = getattr(logger, level, None)
    if callable(log_fn):
        log_fn(msg, *args)
        return

    text = msg % args if args else msg
    print(f"[process_guard] {text}")
