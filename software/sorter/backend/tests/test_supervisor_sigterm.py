"""systemd stops the backend with SIGTERM. The supervisor has to exit on it,
taking the backend with it, instead of waiting out the unit's stop timeout."""

from __future__ import annotations

import os
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def _backend_pid(pid_file: Path) -> int:
    deadline = time.time() + 20
    while not pid_file.exists() or not pid_file.read_text().strip():
        if time.time() > deadline:
            raise TimeoutError("the supervisor never started the backend")
        time.sleep(0.1)
    return int(pid_file.read_text())


def test_sigterm_stops_the_supervisor_and_its_backend(tmp_path):
    port = _free_port()
    pid_file = tmp_path / "backend.pid"
    supervisor = subprocess.Popen(
        [sys.executable, "supervisor.py", "--ui-port", str(port),
         "--", "sh", "-c", f"echo $$ > {pid_file}; exec sleep 60"],
        cwd=BACKEND_DIR,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        backend = _backend_pid(pid_file)
        supervisor.send_signal(signal.SIGTERM)
        supervisor.wait(timeout=10)
        try:
            os.kill(backend, 0)
            backend_alive = True
        except ProcessLookupError:
            backend_alive = False
        assert not backend_alive
    finally:
        if supervisor.poll() is None:
            supervisor.kill()
