"""Lightweight status broadcast for a Lambda pipeline run.

Spins up a stdlib HTTP server on localhost that serves a single-page UI which
polls `/state` for live step + log updates. Designed for one viewer (the
local dev machine driving the CLI); no auth, no SSE — just a JSON poll loop.

Usage:

    with PipelineStatus(open_browser=True) as status:
        with status.step("Pull samples"):
            run_remote("...", status=status)
        with status.step("Build dataset"):
            ...

Each `step` block transitions the named step to running, captures any
`status.log_line(...)` calls into a bounded ring buffer, and marks it
done/failed depending on whether the body raised.
"""

from __future__ import annotations

import contextlib
import json
import threading
import time
import webbrowser
from collections import deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Iterator


MAX_LOG_LINES_PER_STEP = 80


_INDEX_HTML = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Lambda pipeline</title>
<style>
  :root { color-scheme: dark; }
  body { font: 13px/1.4 ui-monospace, monospace; background: #0d1117; color: #c9d1d9; margin: 0; padding: 24px; }
  h1 { font-size: 14px; margin: 0 0 4px; color: #58a6ff; }
  .sub { color: #8b949e; margin-bottom: 18px; }
  .step { border-left: 3px solid #30363d; padding: 8px 12px; margin: 4px 0; background: #161b22; border-radius: 0 4px 4px 0; }
  .step.running { border-left-color: #d29922; }
  .step.done    { border-left-color: #3fb950; }
  .step.failed  { border-left-color: #f85149; }
  .step.pending { opacity: 0.55; }
  .row { display: flex; justify-content: space-between; align-items: baseline; gap: 16px; }
  .name { font-weight: 600; }
  .meta { color: #8b949e; font-size: 12px; white-space: nowrap; }
  .tag { display: inline-block; padding: 1px 6px; border-radius: 999px; font-size: 11px; margin-right: 6px; }
  .tag.running { background: #4d3500; color: #f0c674; }
  .tag.done    { background: #033a16; color: #56d364; }
  .tag.failed  { background: #5a0e15; color: #ff7b72; }
  .tag.pending { background: #21262d; color: #8b949e; }
  pre.log { margin: 6px 0 0; padding: 8px 10px; background: #010409; color: #8b949e; border-radius: 4px;
            font: 12px/1.35 ui-monospace, monospace; max-height: 220px; overflow: auto; white-space: pre-wrap; }
  .meta.error { color: #f85149; }
  .overall { padding: 8px 12px; background: #21262d; border-radius: 4px; margin-bottom: 16px; }
  .overall.failed { background: #5a0e15; color: #ffd6d3; }
  .overall.done { background: #033a16; color: #b3f0c4; }
</style>
</head>
<body>
  <h1 id="title">Lambda pipeline</h1>
  <div class="sub" id="sub">Waiting for first update…</div>
  <div id="overall" class="overall">…</div>
  <div id="steps"></div>
<script>
function fmtElapsed(ms) {
  if (ms == null) return "";
  let s = Math.floor(ms / 1000);
  if (s < 60) return s + "s";
  const m = Math.floor(s / 60);
  s = s % 60;
  if (m < 60) return m + "m" + s.toString().padStart(2, "0") + "s";
  const h = Math.floor(m / 60);
  return h + "h" + (m % 60).toString().padStart(2, "0") + "m";
}

function render(state) {
  const sub = state.bundle_name ? `${state.bundle_name} → ${state.host || ""}` : "(no run config)";
  document.getElementById("sub").textContent = sub;
  document.title = `${state.overall || "?"} · ${state.bundle_name || "Lambda"}`;

  const overall = document.getElementById("overall");
  overall.className = "overall " + (state.overall || "");
  const startedAgo = state.started_at ? fmtElapsed(Date.now() - state.started_at * 1000) : "—";
  overall.textContent = `status: ${state.overall || "?"}  ·  elapsed: ${startedAgo}` +
    (state.error ? `  ·  error: ${state.error}` : "");

  const steps = state.steps || [];
  const container = document.getElementById("steps");
  container.innerHTML = "";
  for (const s of steps) {
    const div = document.createElement("div");
    div.className = "step " + s.status;
    const meta = [];
    if (s.started_at) {
      const elapsedMs = ((s.finished_at || (Date.now()/1000)) - s.started_at) * 1000;
      meta.push(fmtElapsed(elapsedMs));
    }
    if (s.error) meta.push(`<span class="meta error">${s.error.slice(0,140)}</span>`);
    div.innerHTML = `
      <div class="row">
        <div><span class="tag ${s.status}">${s.status}</span><span class="name">${s.name}</span></div>
        <div class="meta">${meta.join("  ·  ")}</div>
      </div>` + (s.tail && s.tail.length ? `<pre class="log">${s.tail.map(l => l.replace(/[<>&]/g, c=>({'<':'&lt;','>':'&gt;','&':'&amp;'}[c]))).join("\\n")}</pre>` : "");
    container.appendChild(div);
  }
}

async function poll() {
  try {
    const r = await fetch("/state", {cache: "no-store"});
    if (r.ok) render(await r.json());
  } catch (e) { /* ignore */ }
  setTimeout(poll, 500);
}
poll();
</script>
</body>
</html>
"""


class PipelineStatus:
    def __init__(self, *, host: str = "127.0.0.1", port: int = 0, open_browser: bool = True) -> None:
        self._lock = threading.Lock()
        self._state: dict = {
            "bundle_name": None,
            "host": None,
            "overall": "starting",
            "started_at": time.time(),
            "error": None,
            "steps": [],
        }
        self._current_step: dict | None = None
        self._server = ThreadingHTTPServer((host, port), self._make_handler())
        self.port = self._server.server_address[1]
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._open_browser = open_browser
        self.url = f"http://{host}:{self.port}/"

    def __enter__(self) -> "PipelineStatus":
        self._thread.start()
        print(f"[status] live UI at {self.url}")
        if self._open_browser:
            try:
                webbrowser.open(self.url)
            except Exception:
                pass
        return self

    def __exit__(self, exc_type, exc_val, _tb) -> None:
        with self._lock:
            if self._state["overall"] not in {"done", "failed"}:
                if exc_type is not None:
                    self._state["overall"] = "failed"
                    self._state["error"] = f"{exc_type.__name__}: {exc_val}"
                else:
                    self._state["overall"] = "done"
        # Keep server alive briefly so the user can see the final state.
        time.sleep(0.6)
        self._server.shutdown()

    # -- run-config metadata ----------------------------------------------
    def configure(self, *, bundle_name: str, host: str) -> None:
        with self._lock:
            self._state["bundle_name"] = bundle_name
            self._state["host"] = host
            self._state["overall"] = "running"

    # -- step lifecycle ---------------------------------------------------
    @contextlib.contextmanager
    def step(self, name: str) -> Iterator[None]:
        s = self._start_step(name)
        try:
            yield
            self._finish_step(s, success=True)
        except BaseException as exc:
            self._finish_step(s, success=False, error=f"{type(exc).__name__}: {exc}")
            raise

    def _start_step(self, name: str) -> dict:
        with self._lock:
            step = {
                "name": name,
                "status": "running",
                "started_at": time.time(),
                "finished_at": None,
                "error": None,
                "tail": deque(maxlen=MAX_LOG_LINES_PER_STEP),
            }
            self._state["steps"].append(step)
            self._current_step = step
            return step

    def _finish_step(self, step: dict, *, success: bool, error: str | None = None) -> None:
        with self._lock:
            step["finished_at"] = time.time()
            step["status"] = "done" if success else "failed"
            if error:
                step["error"] = error
                self._state["overall"] = "failed"
                self._state["error"] = error
            if self._current_step is step:
                self._current_step = None

    # -- live log capture --------------------------------------------------
    def log_line(self, line: str) -> None:
        line = line.rstrip()
        if not line:
            return
        with self._lock:
            if self._current_step is None:
                return
            self._current_step["tail"].append(line)

    # -- HTTP handlers -----------------------------------------------------
    def _snapshot(self) -> dict:
        with self._lock:
            return {
                **self._state,
                "steps": [
                    {**s, "tail": list(s["tail"])} for s in self._state["steps"]
                ],
            }

    def _make_handler(self):
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_args, **_kwargs) -> None:
                pass  # silence default access logs

            def _send(self, code: int, body: bytes, content_type: str) -> None:
                self.send_response(code)
                self.send_header("Content-Type", content_type)
                self.send_header("Cache-Control", "no-store")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_GET(self) -> None:
                if self.path == "/" or self.path.startswith("/?"):
                    self._send(200, _INDEX_HTML.encode("utf-8"), "text/html; charset=utf-8")
                elif self.path == "/state":
                    body = json.dumps(outer._snapshot(), default=list).encode("utf-8")
                    self._send(200, body, "application/json")
                else:
                    self._send(404, b"not found", "text/plain")

        return Handler
