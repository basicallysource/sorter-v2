"""Runs the backend (main.py) and restarts it when it exits, and serves the
UI's static build, so the page loads even while the backend restarts."""

from __future__ import annotations

import argparse
import html
import ipaddress
import json
import mimetypes
import os
import posixpath
import shutil
import signal
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlsplit

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[2] / ".env")

DEFAULT_UI_PORT = 80
DEFAULT_RESTART_BACKOFF_S = float(os.getenv("BACKEND_SUPERVISOR_RESTART_BACKOFF_S", "0.2"))
DEFAULT_STOP_TIMEOUT_S = float(os.getenv("BACKEND_SUPERVISOR_STOP_TIMEOUT_S", "5.0"))
DEFAULT_FAST_CRASH_WINDOW_S = float(os.getenv("BACKEND_SUPERVISOR_FAST_CRASH_WINDOW_S", "30.0"))
CACHE_CLEAR_CRASH_THRESHOLD = 3

UI_BUILD_DIR = Path(__file__).resolve().parents[1] / "frontend" / "build"
RESTART_PATH = "/api/supervisor/restart"
# Built files under here have a content hash in their names: a new build
# gets new names, so browsers may keep these for good.
IMMUTABLE_PREFIX = "/_app/immutable/"
PRECOMPRESSED = (("br", ".br"), ("gzip", ".gz"))
# Python's own table, the same on every machine, whatever /etc/mime.types says.
CONTENT_TYPES = mimetypes.MimeTypes()
CONTENT_TYPES.add_type("font/woff2", ".woff2")


class BackendSupervisor:
    """Runs the backend, restarts it when it exits, and restarts it on request.
    The backend inherits the supervisor's stdout and stderr (the journal)."""

    def __init__(
        self,
        *,
        command: list[str],
        cwd: Path,
        environment: dict[str, str],
        restart_backoff_s: float,
        stop_timeout_s: float,
        fast_crash_window_s: float = DEFAULT_FAST_CRASH_WINDOW_S,
    ) -> None:
        self._command = list(command)
        self._cwd = cwd
        self._environment = dict(environment)
        self._restart_backoff_s = restart_backoff_s
        self._stop_timeout_s = stop_timeout_s
        self._fast_crash_window_s = fast_crash_window_s
        self._lock = threading.RLock()
        self._shutdown = threading.Event()
        self._restart_requested = False
        # Started with start_new_session, so its pid is also its process group.
        self._process: subprocess.Popen[bytes] | None = None
        self._process_started_at: float | None = None
        self._consecutive_fast_crashes = 0
        self._cache_cleared_for_streak = False

    def start(self) -> None:
        self._start_backend()

    def shutdown(self) -> None:
        self._shutdown.set()
        self._stop_backend()

    def request_restart(self) -> bool:
        with self._lock:
            if self._restart_requested:
                return False
            self._restart_requested = True
        threading.Thread(target=self._restart_worker, daemon=True).start()
        return True

    def _restart_worker(self) -> None:
        try:
            self._stop_backend()
            if self._shutdown.is_set():
                return
            time.sleep(self._restart_backoff_s)
            self._start_backend()
        finally:
            with self._lock:
                self._restart_requested = False

    def _start_backend(self) -> None:
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
            self._process_started_at = time.time()
        threading.Thread(target=self._watch_process, args=(child,), daemon=True).start()

    def _clear_bytecode_caches(self) -> int:
        cleared = 0
        cache_prefix = self._environment.get("PYTHONPYCACHEPREFIX")
        if cache_prefix and Path(cache_prefix).is_dir():
            try:
                shutil.rmtree(cache_prefix)
                cleared += 1
            except OSError:
                pass
        for root, dirs, _files in os.walk(self._cwd):
            dirs[:] = [d for d in dirs if d not in (".venv", "node_modules", ".git")]
            if "__pycache__" in dirs:
                dirs.remove("__pycache__")
                try:
                    shutil.rmtree(Path(root) / "__pycache__")
                    cleared += 1
                except OSError:
                    pass
        return cleared

    def _watch_process(self, child: subprocess.Popen[bytes]) -> None:
        child.wait()
        with self._lock:
            if self._process is not child:
                return
            started_at = self._process_started_at
            self._process = None
            if self._shutdown.is_set() or self._restart_requested:
                return
            if started_at is not None and time.time() - started_at < self._fast_crash_window_s:
                self._consecutive_fast_crashes += 1
            else:
                self._consecutive_fast_crashes = 0
                self._cache_cleared_for_streak = False
            clear_cache = (
                self._consecutive_fast_crashes >= CACHE_CLEAR_CRASH_THRESHOLD
                and not self._cache_cleared_for_streak
            )
            if clear_cache:
                self._cache_cleared_for_streak = True

        if clear_cache:
            # A corrupt .pyc never self-heals: Python trusts the cache header while the
            # body is garbage, so the backend crash-loops forever. Clearing the caches
            # once per streak is free and lets the next start recompile from source.
            cleared = self._clear_bytecode_caches()
            print(
                f"[supervisor] crash loop detected ({self._consecutive_fast_crashes} fast exits); "
                f"cleared {cleared} __pycache__ dirs before restarting",
                flush=True,
            )

        time.sleep(self._restart_backoff_s)
        if not self._shutdown.is_set():
            self._start_backend()

    def _stop_backend(self) -> None:
        with self._lock:
            process = self._process
        if process is None or process.poll() is not None:
            return

        try:
            os.killpg(process.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        try:
            process.wait(timeout=self._stop_timeout_s)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            try:
                process.wait(timeout=2.0)
            except subprocess.TimeoutExpired:
                pass


def _file_in(root: Path, url_path: str) -> Path | None:
    """The file under root that url_path names; None for a directory, a
    missing file, or anything outside root ('..' or a symlink out)."""
    try:
        file = (root / url_path.lstrip("/")).resolve()
        return file if file.is_relative_to(root.resolve()) and file.is_file() else None
    except (OSError, ValueError):
        return None


def _names_this_machine(host: str) -> bool:
    """Whether a Host header names this machine the way people reach it: an IP
    address, localhost, a bare or mDNS (.local) name, or a Tailscale name. A
    public domain means DNS rebinding: another site's page, reaching this
    machine under that site's own name, where Origin matches Host."""
    name = urlsplit(f"//{host}").hostname or ""
    try:
        ipaddress.ip_address(name)
        return True
    except ValueError:
        return name == "localhost" or "." not in name or name.endswith((".local", ".ts.net"))


def _ui_handler(supervisor: BackendSupervisor, build_dir: Path) -> type[BaseHTTPRequestHandler]:
    not_built = (
        "<!doctype html><meta charset=utf-8><title>Sorter UI not built</title>"
        "<p>The Sorter UI is not built on this machine yet. Build it, then reload this page:</p>"
        f"<pre>cd {html.escape(str(build_dir.parent))} &amp;&amp; "
        "pnpm install --frozen-lockfile &amp;&amp; pnpm build</pre>"
    ).encode()

    class UIHandler(BaseHTTPRequestHandler):
        # Keep-alive: a page load's files share a few connections instead of
        # opening one each. An idle connection is dropped after the timeout.
        protocol_version = "HTTP/1.1"
        timeout = 60

        def do_GET(self) -> None:
            self._serve(body=True)

        def do_HEAD(self) -> None:
            self._serve(body=False)

        def _serve(self, body: bool) -> None:
            shell = build_dir / "index.html"
            if not shell.is_file():
                self._send(503, not_built, {"Content-Type": "text/html; charset=utf-8"}, body)
                return
            path = posixpath.normpath(unquote(self.path.split("?", 1)[0].split("#", 1)[0]))
            file = _file_in(build_dir, path)
            if file is None and path.startswith("/_app/"):
                # A missing script or stylesheet must fail, not become the page.
                self._send(404, b"Not found\n", {"Content-Type": "text/plain"}, body)
                return
            # Any other path is a page of the app, which the shell renders.
            file = file or shell
            headers = {
                "Content-Type": CONTENT_TYPES.guess_type(file.name)[0] or "application/octet-stream",
                "Vary": "Accept-Encoding",
            }
            if path.startswith(IMMUTABLE_PREFIX):
                headers["Cache-Control"] = "public, max-age=31536000, immutable"
            accepted = {part.split(";")[0].strip().lower() for part in self.headers.get("Accept-Encoding", "").split(",")}
            for encoding, suffix in PRECOMPRESSED:
                compressed = file.with_name(file.name + suffix)
                if encoding in accepted and compressed.is_file():
                    file, headers["Content-Encoding"] = compressed, encoding
                    break
            try:
                content = file.read_bytes()
            except OSError:  # a build replacing it right now
                self._send(404, b"Not found\n", {"Content-Type": "text/plain"}, body)
                return
            self._send(200, content, headers, body)

        def do_POST(self) -> None:
            if self.path != RESTART_PATH:
                self._send_json(404, {"ok": False, "message": "Not found"})
                return
            # Another site's page can post here too, but its browser names that
            # site in Origin: only the UI served from here may restart.
            origin = urlsplit(self.headers.get("Origin") or "").netloc.lower()
            host = (self.headers.get("Host") or "").lower()
            if not origin or origin != host or not _names_this_machine(host):
                self._send_json(403, {"ok": False, "message": "Origin must match Host, and name this machine."})
                return
            print(f"[supervisor] restart requested by {self.client_address[0]}", flush=True)
            accepted = supervisor.request_restart()
            self._send_json(202, {"ok": True, "accepted": accepted, "message": "Hard restart requested."})

        def log_request(self, code: int | str = "-", size: int | str = "-") -> None:
            return  # not a journal line per file; errors are still logged

        def log_error(self, format: str, *args: Any) -> None:
            if not format.startswith("Request timed out"):  # an idle kept-alive connection closing
                super().log_error(format, *args)

        def _send_json(self, status: int, payload: dict[str, Any]) -> None:
            self._send(status, json.dumps(payload).encode(), {"Content-Type": "application/json"})

        def _send(self, status: int, content: bytes, headers: dict[str, str], body: bool = True) -> None:
            # Everything but the hashed files is checked on every load, so a
            # new build shows on the next one.
            headers.setdefault("Cache-Control", "no-cache")
            self.send_response(status)
            for name, value in headers.items():
                self.send_header(name, value)
            self.send_header("Content-Length", str(len(content)))
            self.end_headers()
            if body:
                self.wfile.write(content)

    return UIHandler


class _UIServer(ThreadingHTTPServer):
    # A page load opens dozens of connections at once. The default backlog of
    # 5 drops some, and a dropped connection waits a second to try again.
    request_queue_size = 128


def _bind_ui(port: int, handler: type[BaseHTTPRequestHandler]) -> ThreadingHTTPServer:
    """The UI's server on every interface, once it has the port, however long
    that takes: on SorterOS's first boot the progress page keeps port 80
    until the backend answers, then lets it go."""
    waiting = False
    while True:
        try:
            return _UIServer(("0.0.0.0", port), handler)
        except OSError as exc:
            if not waiting:
                print(f"[supervisor] cannot serve the UI on port {port} yet ({exc}); trying every second", flush=True)
                waiting = True
            time.sleep(1)


def _serve_ui(supervisor: BackendSupervisor, port: int) -> None:
    server = _bind_ui(port, _ui_handler(supervisor, UI_BUILD_DIR))
    print(f"[supervisor] serving the UI from {UI_BUILD_DIR} on port {port}", flush=True)
    server.serve_forever()


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Supervisor for the sorter backend.")
    parser.add_argument("--ui-port", type=int, default=DEFAULT_UI_PORT,
                        help="Port to serve the UI's build on (all interfaces); 0 serves no UI.")
    parser.add_argument("--restart-backoff", type=float, default=DEFAULT_RESTART_BACKOFF_S)
    parser.add_argument("--stop-timeout", type=float, default=DEFAULT_STOP_TIMEOUT_S)
    parser.add_argument("backend_command", nargs=argparse.REMAINDER,
                        help="Optional backend command after '--'. Defaults to running main.py with the current Python.")
    args = parser.parse_args()
    command = args.backend_command[1:] if args.backend_command[:1] == ["--"] else args.backend_command
    args.backend_command = command or [sys.executable, str(Path(__file__).resolve().parent / "main.py")]
    return args


def main() -> None:
    args = _parse_args()
    environment = os.environ.copy()
    if args.ui_port:
        # Where the UI is, for the backend: its heartbeat reports it, and its
        # origin check lets that page call the API.
        environment["SORTER_SUPERVISOR_UI_PORT"] = str(args.ui_port)
    supervisor = BackendSupervisor(
        command=args.backend_command,
        cwd=Path(__file__).resolve().parent,
        environment=environment,
        restart_backoff_s=args.restart_backoff,
        stop_timeout_s=args.stop_timeout,
    )
    stop = threading.Event()
    signal.signal(signal.SIGINT, lambda *_: stop.set())
    signal.signal(signal.SIGTERM, lambda *_: stop.set())

    print(f"[supervisor] command={' '.join(args.backend_command)}", flush=True)
    supervisor.start()
    if args.ui_port:
        threading.Thread(target=_serve_ui, args=(supervisor, args.ui_port), daemon=True).start()
    stop.wait()
    # Stop the backend before exiting, so it never outlives the supervisor.
    supervisor.shutdown()


if __name__ == "__main__":
    main()
