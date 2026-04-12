from __future__ import annotations

import argparse
import json
import os
import signal
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib import error as urllib_error
from urllib import request as urllib_request

from dotenv import load_dotenv


load_dotenv(Path(__file__).resolve().parents[2] / ".env")


DEFAULT_CONTROL_HOST = os.getenv("BACKEND_SUPERVISOR_HOST", "127.0.0.1")
DEFAULT_CONTROL_PORT = int(os.getenv("BACKEND_SUPERVISOR_PORT", "8001"))
DEFAULT_BACKEND_PORT = int(os.getenv("BACKEND_PORT", "8000"))
DEFAULT_HEALTH_INTERVAL_S = float(os.getenv("BACKEND_SUPERVISOR_HEALTH_INTERVAL_S", "2.0"))
DEFAULT_HEALTH_TIMEOUT_S = float(os.getenv("BACKEND_SUPERVISOR_HEALTH_TIMEOUT_S", "1.5"))
DEFAULT_RESTART_BACKOFF_S = float(os.getenv("BACKEND_SUPERVISOR_RESTART_BACKOFF_S", "1.0"))
DEFAULT_STOP_TIMEOUT_S = float(os.getenv("BACKEND_SUPERVISOR_STOP_TIMEOUT_S", "5.0"))


def _timestamp() -> float:
    return time.time()


class BackendSupervisor:
    def __init__(
        self,
        *,
        command: list[str],
        cwd: Path,
        environment: dict[str, str],
        backend_health_url: str,
        health_interval_s: float,
        health_timeout_s: float,
        restart_backoff_s: float,
        stop_timeout_s: float,
    ) -> None:
        self._command = list(command)
        self._cwd = cwd
        self._environment = dict(environment)
        self._backend_health_url = backend_health_url
        self._health_interval_s = health_interval_s
        self._health_timeout_s = health_timeout_s
        self._restart_backoff_s = restart_backoff_s
        self._stop_timeout_s = stop_timeout_s

        self._lock = threading.RLock()
        self._shutdown = threading.Event()
        self._restart_requested = False
        self._process: subprocess.Popen[bytes] | None = None
        self._process_group_pid: int | None = None
        self._process_started_at: float | None = None
        self._last_exit_code: int | None = None
        self._last_exit_at: float | None = None
        self._last_exit_reason: str | None = None
        self._last_health_error: str | None = None
        self._last_health_ok_at: float | None = None
        self._health_failures = 0
        self._state = "stopped"

        self._health_thread = threading.Thread(target=self._health_loop, daemon=True)

    def start(self) -> None:
        self._start_backend(reason="initial start")
        self._health_thread.start()

    def shutdown(self) -> None:
        self._shutdown.set()
        self._stop_backend(reason="supervisor shutdown")

    def status(self) -> dict[str, Any]:
        with self._lock:
            process = self._process
            running = process is not None and process.poll() is None
            return {
                "ok": True,
                "supervisor_state": self._state,
                "backend_running": running,
                "backend_pid": process.pid if running and process is not None else None,
                "backend_started_at": self._process_started_at,
                "backend_health_url": self._backend_health_url,
                "backend_healthy": self._last_health_error is None and self._last_health_ok_at is not None,
                "last_health_ok_at": self._last_health_ok_at,
                "last_health_error": self._last_health_error,
                "consecutive_health_failures": self._health_failures,
                "last_exit_code": self._last_exit_code,
                "last_exit_at": self._last_exit_at,
                "last_exit_reason": self._last_exit_reason,
                "restart_requested": self._restart_requested,
                "command": list(self._command),
            }

    def request_restart(self, *, reason: str) -> bool:
        with self._lock:
            if self._restart_requested:
                return False
            self._restart_requested = True
            self._state = "restarting"

        threading.Thread(
            target=self._restart_worker,
            kwargs={"reason": reason},
            daemon=True,
        ).start()
        return True

    def _restart_worker(self, *, reason: str) -> None:
        try:
            self._stop_backend(reason=reason)
            if self._shutdown.is_set():
                return
            time.sleep(self._restart_backoff_s)
            self._start_backend(reason=reason)
        finally:
            with self._lock:
                self._restart_requested = False

    def _health_loop(self) -> None:
        while not self._shutdown.wait(self._health_interval_s):
            with self._lock:
                process = self._process
                running = process is not None and process.poll() is None
            if not running:
                continue

            try:
                with urllib_request.urlopen(
                    self._backend_health_url,
                    timeout=self._health_timeout_s,
                ) as response:
                    if response.status < 200 or response.status >= 300:
                        raise RuntimeError(f"health returned {response.status}")
                with self._lock:
                    self._last_health_ok_at = _timestamp()
                    self._last_health_error = None
                    self._health_failures = 0
            except Exception as exc:
                with self._lock:
                    self._last_health_error = str(exc)
                    self._health_failures += 1

    def _start_backend(self, *, reason: str) -> None:
        with self._lock:
            process = self._process
            if process is not None and process.poll() is None:
                return

            child = subprocess.Popen(
                self._command,
                cwd=str(self._cwd),
                env=self._environment,
                start_new_session=True,
            )
            self._process = child
            self._process_group_pid = child.pid
            self._process_started_at = _timestamp()
            self._last_exit_code = None
            self._last_exit_at = None
            self._last_exit_reason = reason
            self._last_health_error = None
            self._health_failures = 0
            self._state = "running"

        threading.Thread(
            target=self._watch_process,
            args=(child,),
            daemon=True,
        ).start()

    def _watch_process(self, child: subprocess.Popen[bytes]) -> None:
        return_code = child.wait()
        with self._lock:
            if self._process is not child:
                return
            self._process = None
            self._process_group_pid = None
            self._last_exit_code = return_code
            self._last_exit_at = _timestamp()
            if self._shutdown.is_set():
                self._state = "stopped"
                if self._last_exit_reason is None:
                    self._last_exit_reason = "supervisor shutdown"
                return
            if self._restart_requested:
                self._state = "restarting"
                return
            self._state = "crashed"
            self._last_exit_reason = "backend exited unexpectedly"

        time.sleep(self._restart_backoff_s)
        if not self._shutdown.is_set():
            self._start_backend(reason="auto restart after crash")

    def _stop_backend(self, *, reason: str) -> None:
        with self._lock:
            process = self._process
            pgid = self._process_group_pid
            if process is None or process.poll() is not None or pgid is None:
                self._process = None
                self._process_group_pid = None
                self._last_exit_reason = reason
                self._state = "stopped" if self._shutdown.is_set() else "restarting"
                return
            self._last_exit_reason = reason

        try:
            os.killpg(pgid, signal.SIGTERM)
        except ProcessLookupError:
            pass

        deadline = time.time() + self._stop_timeout_s
        while time.time() < deadline:
            if process.poll() is not None:
                break
            time.sleep(0.1)

        if process.poll() is None:
            try:
                os.killpg(pgid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            deadline = time.time() + 2.0
            while time.time() < deadline:
                if process.poll() is not None:
                    break
                time.sleep(0.05)

        with self._lock:
            if self._process is process and process.poll() is not None:
                self._process = None
                self._process_group_pid = None
                self._last_exit_code = process.returncode
                self._last_exit_at = _timestamp()
                self._state = "stopped" if self._shutdown.is_set() else "restarting"


def _handler_factory(supervisor: BackendSupervisor):
    class SupervisorHandler(BaseHTTPRequestHandler):
        def do_OPTIONS(self) -> None:
            self._send_json(204, {"ok": True})

        def do_GET(self) -> None:
            if self.path == "/health":
                self._send_json(200, {"status": "ok"})
                return
            if self.path == "/api/supervisor/status":
                self._send_json(200, supervisor.status())
                return
            self._send_json(404, {"ok": False, "message": "Not found"})

        def do_POST(self) -> None:
            if self.path == "/api/supervisor/restart":
                accepted = supervisor.request_restart(reason="hard restart requested")
                self._send_json(
                    202,
                    {
                        "ok": True,
                        "accepted": accepted,
                        "message": "Hard restart requested.",
                    },
                )
                return
            if self.path == "/api/supervisor/start":
                supervisor._start_backend(reason="manual start requested")
                self._send_json(200, {"ok": True, "message": "Backend start requested."})
                return
            if self.path == "/api/supervisor/stop":
                supervisor._stop_backend(reason="manual stop requested")
                self._send_json(200, {"ok": True, "message": "Backend stop requested."})
                return
            self._send_json(404, {"ok": False, "message": "Not found"})

        def log_message(self, format: str, *args: Any) -> None:
            message = format % args
            print(f"[supervisor] {self.address_string()} {message}", flush=True)

        def _send_json(self, status: int, payload: dict[str, Any]) -> None:
            body = json.dumps(payload).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Access-Control-Allow-Methods", "GET,POST,OPTIONS")
            self.send_header("Access-Control-Allow-Headers", "Content-Type")
            self.end_headers()
            if status != 204:
                self.wfile.write(body)

    return SupervisorHandler


def _default_backend_command(script_dir: Path) -> list[str]:
    return [sys.executable, str(script_dir / "main.py")]


def _parse_args() -> argparse.Namespace:
    script_dir = Path(__file__).resolve().parent
    parser = argparse.ArgumentParser(description="Supervisor for the sorter backend.")
    parser.add_argument("--host", default=DEFAULT_CONTROL_HOST)
    parser.add_argument("--control-port", type=int, default=DEFAULT_CONTROL_PORT)
    parser.add_argument("--backend-port", type=int, default=DEFAULT_BACKEND_PORT)
    parser.add_argument(
        "--health-url",
        default=None,
        help="Backend health URL to probe. Defaults to http://127.0.0.1:<backend-port>/health",
    )
    parser.add_argument(
        "--health-interval",
        type=float,
        default=DEFAULT_HEALTH_INTERVAL_S,
    )
    parser.add_argument(
        "--health-timeout",
        type=float,
        default=DEFAULT_HEALTH_TIMEOUT_S,
    )
    parser.add_argument(
        "--restart-backoff",
        type=float,
        default=DEFAULT_RESTART_BACKOFF_S,
    )
    parser.add_argument(
        "--stop-timeout",
        type=float,
        default=DEFAULT_STOP_TIMEOUT_S,
    )
    parser.add_argument(
        "backend_command",
        nargs=argparse.REMAINDER,
        help="Optional backend command after '--'. Defaults to running main.py with the current Python.",
    )
    args = parser.parse_args()

    default_command = _default_backend_command(script_dir)
    command = list(args.backend_command)
    if command and command[0] == "--":
        command = command[1:]
    args.backend_command = command or default_command
    if args.health_url is None:
        args.health_url = f"http://127.0.0.1:{args.backend_port}/health"
    return args


def main() -> None:
    args = _parse_args()
    script_dir = Path(__file__).resolve().parent
    supervisor = BackendSupervisor(
        command=list(args.backend_command),
        cwd=script_dir,
        environment=os.environ.copy(),
        backend_health_url=str(args.health_url),
        health_interval_s=float(args.health_interval),
        health_timeout_s=float(args.health_timeout),
        restart_backoff_s=float(args.restart_backoff),
        stop_timeout_s=float(args.stop_timeout),
    )
    supervisor.start()

    server = ThreadingHTTPServer((str(args.host), int(args.control_port)), _handler_factory(supervisor))

    def _shutdown(*_args: Any) -> None:
        server.shutdown()

    signal.signal(signal.SIGINT, _shutdown)
    signal.signal(signal.SIGTERM, _shutdown)

    print(
        f"[supervisor] control=http://{args.host}:{args.control_port} "
        f"backend_health={args.health_url} command={' '.join(args.backend_command)}",
        flush=True,
    )

    try:
        server.serve_forever()
    finally:
        supervisor.shutdown()
        server.server_close()


if __name__ == "__main__":
    main()
