import sys
import time
from collections import deque
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
        backend_health_url="http://127.0.0.1:1/health",
        health_interval_s=999.0,
        health_timeout_s=0.01,
        restart_backoff_s=0.0,
        stop_timeout_s=0.01,
        fast_crash_window_s=fast_crash_window_s,
    )


def _crash_once(
    supervisor: BackendSupervisor,
    *,
    runtime_s: float,
    stderr_tail: deque[str] | None = None,
) -> None:
    child = _FakeProcess()
    supervisor._process = child
    supervisor._process_group_pid = child.pid
    supervisor._process_started_at = time.time() - runtime_s
    supervisor._watch_process(child, stderr_tail=stderr_tail)


def test_three_fast_crashes_clear_bytecode_caches(monkeypatch):
    supervisor = _supervisor()
    restarted: list[str] = []
    cleared: list[int] = []
    monkeypatch.setattr(
        supervisor, "_start_backend", lambda *, reason: restarted.append(reason)
    )
    monkeypatch.setattr(
        supervisor, "_clear_bytecode_caches", lambda: cleared.append(1) or 2
    )

    _crash_once(supervisor, runtime_s=1.0)
    _crash_once(supervisor, runtime_s=1.0)
    assert cleared == []
    assert supervisor.status()["crash_looping"] is False

    _crash_once(supervisor, runtime_s=1.0)
    assert cleared == [1]
    status = supervisor.status()
    assert status["crash_looping"] is True
    assert status["consecutive_fast_crashes"] == 3
    assert status["pycache_cleared_at"] is not None
    assert len(restarted) == 3


def test_cache_cleared_once_per_streak(monkeypatch):
    supervisor = _supervisor()
    cleared: list[int] = []
    monkeypatch.setattr(supervisor, "_start_backend", lambda *, reason: None)
    monkeypatch.setattr(
        supervisor, "_clear_bytecode_caches", lambda: cleared.append(1) or 0
    )

    for _ in range(5):
        _crash_once(supervisor, runtime_s=1.0)

    assert cleared == [1]
    assert supervisor.status()["consecutive_fast_crashes"] == 5


def test_slow_crash_resets_streak(monkeypatch):
    supervisor = _supervisor()
    cleared: list[int] = []
    monkeypatch.setattr(supervisor, "_start_backend", lambda *, reason: None)
    monkeypatch.setattr(
        supervisor, "_clear_bytecode_caches", lambda: cleared.append(1) or 0
    )

    _crash_once(supervisor, runtime_s=1.0)
    _crash_once(supervisor, runtime_s=1.0)
    _crash_once(supervisor, runtime_s=300.0)

    assert cleared == []
    assert supervisor.status()["consecutive_fast_crashes"] == 0


def test_crash_output_captured_in_status(monkeypatch):
    supervisor = _supervisor()
    monkeypatch.setattr(supervisor, "_start_backend", lambda *, reason: None)
    tail = deque(
        [
            "Traceback (most recent call last):\n",
            '  File "main.py", line 1, in <module>\n',
            "ValueError: could not convert string to float: ''\n",
        ]
    )

    _crash_once(supervisor, runtime_s=1.0, stderr_tail=tail)

    output = supervisor.status()["last_crash_output"]
    assert output is not None
    assert "ValueError: could not convert string to float" in output


def test_manual_stop_does_not_count_as_crash(monkeypatch):
    supervisor = _supervisor()
    monkeypatch.setattr(supervisor, "_start_backend", lambda *, reason: None)
    child = _FakeProcess()
    supervisor._process = child
    supervisor._process_group_pid = child.pid
    supervisor._process_started_at = time.time()
    supervisor._manual_stop_requested = True

    supervisor._watch_process(child)

    status = supervisor.status()
    assert status["consecutive_fast_crashes"] == 0
    assert status["last_crash_output"] is None


def test_real_crashing_subprocess_captures_stderr_and_clears_cache(tmp_path):
    (tmp_path / "perception" / "__pycache__").mkdir(parents=True)
    supervisor = BackendSupervisor(
        command=[
            sys.executable,
            "-c",
            "import sys; sys.stderr.write('ValueError: boom\\n'); sys.exit(1)",
        ],
        cwd=tmp_path,
        environment={},
        backend_health_url="http://127.0.0.1:1/health",
        health_interval_s=999.0,
        health_timeout_s=0.01,
        restart_backoff_s=0.05,
        stop_timeout_s=0.01,
    )

    supervisor._start_backend(reason="test")
    deadline = time.time() + 30.0
    while time.time() < deadline:
        if supervisor.status()["crash_looping"]:
            break
        time.sleep(0.05)
    supervisor.shutdown()

    status = supervisor.status()
    assert status["crash_looping"] is True
    assert status["last_crash_output"] is not None
    assert "ValueError: boom" in status["last_crash_output"]
    assert status["pycache_cleared_at"] is not None
    assert not (tmp_path / "perception" / "__pycache__").exists()


def test_clear_bytecode_caches_skips_venv(tmp_path):
    backend = tmp_path
    (backend / "perception" / "__pycache__").mkdir(parents=True)
    (backend / "perception" / "__pycache__" / "capture.cpython-312.pyc").write_bytes(
        b"garbage"
    )
    (backend / ".venv" / "lib" / "__pycache__").mkdir(parents=True)
    supervisor = BackendSupervisor(
        command=["backend"],
        cwd=backend,
        environment={},
        backend_health_url="http://127.0.0.1:1/health",
        health_interval_s=999.0,
        health_timeout_s=0.01,
        restart_backoff_s=0.0,
        stop_timeout_s=0.01,
    )

    cleared = supervisor._clear_bytecode_caches()

    assert cleared == 1
    assert not (backend / "perception" / "__pycache__").exists()
    assert (backend / ".venv" / "lib" / "__pycache__").exists()
