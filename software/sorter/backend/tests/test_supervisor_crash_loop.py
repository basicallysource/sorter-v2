import sys
import time
from pathlib import Path

from supervisor import BackendSupervisor


class _FakeProcess:
    pid = 12345
    returncode = 1

    def wait(self):
        return self.returncode

    def poll(self):
        return self.returncode


def _supervisor(fast_crash_window_s: float = 30.0) -> BackendSupervisor:
    return BackendSupervisor(
        command=["backend"],
        cwd=Path("."),
        environment={},
        restart_backoff_s=0.0,
        stop_timeout_s=0.01,
        fast_crash_window_s=fast_crash_window_s,
    )


def _crash_once(supervisor: BackendSupervisor, *, runtime_s: float) -> None:
    child = _FakeProcess()
    supervisor._process = child
    supervisor._process_started_at = time.time() - runtime_s
    supervisor._watch_process(child)


def test_three_fast_crashes_clear_bytecode_caches(monkeypatch):
    supervisor = _supervisor()
    restarted: list[int] = []
    cleared: list[int] = []
    monkeypatch.setattr(supervisor, "_start_backend", lambda: restarted.append(1))
    monkeypatch.setattr(supervisor, "_clear_bytecode_caches", lambda: cleared.append(1) or 2)

    _crash_once(supervisor, runtime_s=1.0)
    _crash_once(supervisor, runtime_s=1.0)
    assert cleared == []

    _crash_once(supervisor, runtime_s=1.0)
    assert cleared == [1]
    assert supervisor._consecutive_fast_crashes == 3
    assert len(restarted) == 3


def test_cache_cleared_once_per_streak(monkeypatch):
    supervisor = _supervisor()
    cleared: list[int] = []
    monkeypatch.setattr(supervisor, "_start_backend", lambda: None)
    monkeypatch.setattr(supervisor, "_clear_bytecode_caches", lambda: cleared.append(1) or 0)

    for _ in range(5):
        _crash_once(supervisor, runtime_s=1.0)

    assert cleared == [1]
    assert supervisor._consecutive_fast_crashes == 5


def test_slow_crash_resets_streak(monkeypatch):
    supervisor = _supervisor()
    cleared: list[int] = []
    monkeypatch.setattr(supervisor, "_start_backend", lambda: None)
    monkeypatch.setattr(supervisor, "_clear_bytecode_caches", lambda: cleared.append(1) or 0)

    _crash_once(supervisor, runtime_s=1.0)
    _crash_once(supervisor, runtime_s=1.0)
    _crash_once(supervisor, runtime_s=300.0)

    assert cleared == []
    assert supervisor._consecutive_fast_crashes == 0


def test_an_exit_for_a_requested_restart_is_not_a_crash(monkeypatch):
    supervisor = _supervisor()
    restarted: list[int] = []
    monkeypatch.setattr(supervisor, "_start_backend", lambda: restarted.append(1))
    supervisor._restart_requested = True

    _crash_once(supervisor, runtime_s=1.0)

    assert supervisor._consecutive_fast_crashes == 0
    assert restarted == []  # the restart worker starts the next backend


def test_real_crashing_subprocess_clears_cache(tmp_path):
    (tmp_path / "perception" / "__pycache__").mkdir(parents=True)
    supervisor = BackendSupervisor(
        command=[sys.executable, "-c", "import sys; sys.exit(1)"],
        cwd=tmp_path,
        environment={},
        restart_backoff_s=0.05,
        stop_timeout_s=0.01,
    )

    supervisor._start_backend()
    deadline = time.time() + 30.0
    while time.time() < deadline and (tmp_path / "perception" / "__pycache__").exists():
        time.sleep(0.05)
    supervisor.shutdown()

    assert supervisor._consecutive_fast_crashes >= 3
    assert not (tmp_path / "perception" / "__pycache__").exists()


def test_clear_bytecode_caches_skips_venv(tmp_path):
    backend = tmp_path / "backend"
    (backend / "perception" / "__pycache__").mkdir(parents=True)
    (backend / "perception" / "__pycache__" / "capture.cpython-312.pyc").write_bytes(b"garbage")
    (backend / ".venv" / "lib" / "__pycache__").mkdir(parents=True)
    cache_prefix = tmp_path / "pycache-prefix"
    (cache_prefix / "sub").mkdir(parents=True)
    supervisor = BackendSupervisor(
        command=["backend"],
        cwd=backend,
        environment={"PYTHONPYCACHEPREFIX": str(cache_prefix)},
        restart_backoff_s=0.0,
        stop_timeout_s=0.01,
    )

    cleared = supervisor._clear_bytecode_caches()

    assert cleared == 2
    assert not (backend / "perception" / "__pycache__").exists()
    assert not cache_prefix.exists()
    assert (backend / ".venv" / "lib" / "__pycache__").exists()
