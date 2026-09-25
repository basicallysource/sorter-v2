"""systemd stops the backend with SIGTERM. The supervisor has to exit on it,
taking the backend with it, instead of waiting out the unit's stop timeout."""

from __future__ import annotations

import json
import os
import signal
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def _backend_pid(port: int) -> int:
    deadline = time.time() + 20
    while True:
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/supervisor/status", timeout=1) as res:
                pid = json.load(res).get("backend_pid")
            if pid:
                return pid
        except OSError:
            pass
        if time.time() > deadline:
            raise TimeoutError("the supervisor never reported a running backend")
        time.sleep(0.1)


def test_sigterm_stops_the_supervisor_and_its_backend():
    port = _free_port()
    supervisor = subprocess.Popen(
        [sys.executable, "supervisor.py", "--control-port", str(port),
         "--health-url", "http://127.0.0.1:1/health", "--", "sleep", "60"],
        cwd=BACKEND_DIR,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        backend = _backend_pid(port)
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
