"""Rev04 perception perf smoke test.

Runs the live-machine pass gate from the rev04 plan
(``tasks/operation-30hz/rev04_2026-05-27.md``). Exits 0 only if every
metric in the pass-condition table is green.

Usage (from your Mac):

    /opt/homebrew/opt/python@3.11/libexec/bin/python \
      software/sorter/backend/scripts/rev04_perf_smoketest.py \
      --machine root-spencer-01

What it does, in order:
  1. Confirm tailscale shows the target machine online.
  2. Soft-restart the sorter-backend-dev process (supervisor endpoint —
     does NOT restart the systemd unit, per agent rules).
  3. POST /api/system/home — in no_power_development_mode this runs the
     safe-recovery path WITHOUT physical homing.
  4. Poll /api/system/status until ``hardware_state`` reaches a runnable
     state (``ready`` or ``initialized``), bail at 60 s.
  5. POST /resume.
  6. Sleep ``--steady-s`` seconds (default 60 s) of steady-state.
  7. GET /runtime-stats and apply the pass conditions.

It does NOT:
  - run ``systemctl restart sorter-backend-dev`` (Spencer explicitly
    forbids that without permission),
  - touch the prod ``sorter-backend.service`` ever,
  - modify any config files on the Pi.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from dataclasses import dataclass
from typing import Any, Optional


# --- pass conditions -------------------------------------------------------


@dataclass(frozen=True)
class PassCondition:
    label: str
    extract: Any           # function (stats_dict) -> float | None
    passes: Any            # function (value) -> bool
    why: str
    optional: bool = False # if True, missing == PASS (not all keys exist at
                           # all times — e.g. classification metrics only
                           # appear once C4 has fired)


def _perf_value(stats: dict, key: str, field: str = "p90_ms") -> Optional[float]:
    perf = stats.get("payload", {}).get("perf_ms", {}).get(key)
    if isinstance(perf, dict) and field in perf:
        try:
            return float(perf[field])
        except (TypeError, ValueError):
            return None
    return None


def _has_any_key(stats: dict, prefix: str) -> bool:
    perf = stats.get("payload", {}).get("perf_ms", {})
    counts = stats.get("payload", {}).get("counts", {})
    for key in list(perf.keys()) + list(counts.keys()):
        if key.startswith(prefix):
            return True
    return False


def _build_pass_conditions(steady_s: float) -> list[PassCondition]:
    # See rev04_2026-05-27.md "Performance pass conditions". The keys here
    # must match what perception/inference.py writes via observePerfMs.
    conds: list[PassCondition] = []

    for role in ("c_channel_2", "c_channel_3", "carousel"):
        conds.append(PassCondition(
            label=f"perception.{role}.cycle_ms.p90 < 35 ms (≥29 Hz/camera)",
            extract=(lambda s, r=role: _perf_value(s, f"perception.{r}.cycle_ms", "p90_ms")),
            passes=(lambda v: v is not None and v < 35.0),
            why="per-camera cycle ≥29 Hz",
        ))
        conds.append(PassCondition(
            label=f"perception.{role}.cycle_ms.med < 28 ms",
            extract=(lambda s, r=role: _perf_value(s, f"perception.{r}.cycle_ms", "med_ms")),
            passes=(lambda v: v is not None and v < 28.0),
            why="per-camera median cycle",
        ))
        conds.append(PassCondition(
            label=f"perception.{role}.source_id_assertion absent (== 0)",
            extract=(lambda s, r=role: 1 if _has_any_key(s, f"perception.{r}.source_id_assertion") else 0),
            passes=(lambda v: v == 0),
            why="cross-camera mixup architecturally impossible",
        ))

    conds.append(PassCondition(
        label="main.loop.interval_ms.p90 < 33 ms (≥30 Hz coordinator)",
        extract=(lambda s: _perf_value(s, "main.loop.interval_ms", "p90_ms")),
        passes=(lambda v: v is not None and v < 33.0),
        why="coordinator decision rate",
    ))
    conds.append(PassCondition(
        label="main.loop.interval_ms.med < 20 ms",
        extract=(lambda s: _perf_value(s, "main.loop.interval_ms", "med_ms")),
        passes=(lambda v: v is not None and v < 20.0),
        why="coordinator median tick",
    ))
    conds.append(PassCondition(
        label="coordinator.step.total_ms.p90 < 15 ms",
        extract=(lambda s: _perf_value(s, "coordinator.step.total_ms", "p90_ms")),
        passes=(lambda v: v is not None and v < 15.0),
        why="coordinator step budget",
    ))
    conds.append(PassCondition(
        label="coordinator.step.total_ms.max < 50 ms",
        extract=(lambda s: _perf_value(s, "coordinator.step.total_ms", "max_ms")),
        passes=(lambda v: v is not None and v < 50.0),
        why="coordinator step tail",
    ))

    # Anti-pattern keys: must NOT be present in Rev04.
    conds.append(PassCondition(
        label="no tracker.* keys present",
        extract=(lambda s: 1 if _has_any_key(s, "tracker.") else 0),
        passes=(lambda v: v == 0),
        why="SORT/handoff tracking is dead weight in this mode",
    ))
    conds.append(PassCondition(
        label="no producer.* keys present (Rev03 producers off)",
        extract=(lambda s: 1 if _has_any_key(s, "producer.") else 0),
        passes=(lambda v: v == 0),
        why="legacy Rev03 producers must be inactive",
    ))
    conds.append(PassCondition(
        label="no inference.by_thread.MainThread.* keys present",
        extract=(lambda s: 1 if _has_any_key(s, "inference.by_thread.MainThread") else 0),
        passes=(lambda v: v == 0),
        why="zero inference on coordinator thread",
    ))

    return conds


# --- SSH helpers -----------------------------------------------------------


def _run(cmd: list[str], *, timeout: float, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(
        cmd,
        timeout=timeout,
        check=check,
        capture_output=True,
        text=True,
    )


def _ssh(machine: str, remote_cmd: str, *, timeout: float) -> str:
    p = _run(
        ["ssh", machine, remote_cmd],
        timeout=timeout,
        check=False,
    )
    if p.returncode != 0:
        raise RuntimeError(
            f"ssh {machine} '{remote_cmd}' rc={p.returncode}\nstderr: {p.stderr}"
        )
    return p.stdout


def _ssh_curl_json(
    machine: str,
    url: str,
    *,
    method: str = "GET",
    origin: Optional[str] = None,
    timeout: float = 10.0,
) -> dict:
    headers = ""
    if origin:
        headers = f' -H "Origin: {origin}"'
    body = _ssh(
        machine,
        f"curl -sS -X {method}{headers} {url}",
        timeout=timeout,
    )
    return json.loads(body)


# --- runner ----------------------------------------------------------------


def _ssh_reachable(machine: str) -> bool:
    """Single fast SSH ping. The CLAUDE.md guidance: SSH fails fast when
    offline, so we just try it directly rather than grepping tailscale
    output (which uses tailnet-device hostnames, not the SSH alias)."""
    try:
        _ssh(machine, "true", timeout=5.0)
        return True
    except Exception:
        return False


def _soft_restart_backend(machine: str) -> None:
    _ssh(
        machine,
        'curl -sS -X POST http://127.0.0.1:8001/api/supervisor/restart '
        '-H "Origin: http://sorter.local:5173"',
        timeout=10.0,
    )


def _wait_ready(machine: str, *, timeout_s: float) -> dict:
    deadline = time.monotonic() + timeout_s
    last: dict = {}
    while time.monotonic() < deadline:
        try:
            last = _ssh_curl_json(
                machine, "http://127.0.0.1:8000/api/system/status", timeout=5.0
            )
            state = last.get("hardware_state")
            if state in ("ready", "initialized"):
                return last
        except Exception:
            pass
        time.sleep(1.0)
    raise TimeoutError(f"hardware did not reach ready/initialized in {timeout_s}s; last={last}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--machine", default="root-spencer-01")
    ap.add_argument("--steady-s", type=float, default=60.0)
    ap.add_argument("--skip-restart", action="store_true",
                    help="skip the supervisor soft-restart (use the already-running backend)")
    ap.add_argument("--skip-home", action="store_true",
                    help="skip /api/system/home (assume already initialized)")
    ap.add_argument("--skip-resume", action="store_true",
                    help="skip /resume (read stats from current lifecycle as-is)")
    args = ap.parse_args()

    machine: str = args.machine

    print(f"[smoke] target={machine}")
    if not _ssh_reachable(machine):
        print(f"[smoke] FAIL: {machine} not reachable over SSH", file=sys.stderr)
        return 2

    if not args.skip_restart:
        print("[smoke] soft-restarting sorter-backend-dev (supervisor endpoint)")
        try:
            _soft_restart_backend(machine)
        except Exception as exc:
            print(f"[smoke] FAIL: supervisor restart failed: {exc}", file=sys.stderr)
            return 2
        time.sleep(4.0)

    if not args.skip_home:
        print("[smoke] POST /api/system/home (no-power dev mode skips physical homing)")
        try:
            _ssh_curl_json(
                machine, "http://127.0.0.1:8000/api/system/home", method="POST", timeout=10.0
            )
        except Exception as exc:
            print(f"[smoke] FAIL: home request failed: {exc}", file=sys.stderr)
            return 2

    print("[smoke] waiting for hardware_state ready/initialized")
    try:
        _wait_ready(machine, timeout_s=60.0)
    except Exception as exc:
        print(f"[smoke] FAIL: {exc}", file=sys.stderr)
        return 2

    if not args.skip_resume:
        print("[smoke] POST /resume")
        try:
            _ssh_curl_json(
                machine, "http://127.0.0.1:8000/resume", method="POST", timeout=10.0
            )
        except Exception as exc:
            print(f"[smoke] FAIL: resume failed: {exc}", file=sys.stderr)
            return 2

    print(f"[smoke] steady-state sleep {args.steady_s:.1f}s")
    time.sleep(args.steady_s)

    print("[smoke] GET /runtime-stats")
    try:
        stats = _ssh_curl_json(
            machine, "http://127.0.0.1:8000/runtime-stats", timeout=15.0
        )
    except Exception as exc:
        print(f"[smoke] FAIL: runtime-stats fetch failed: {exc}", file=sys.stderr)
        return 2

    # --- apply pass conditions ----------------------------------------------
    conds = _build_pass_conditions(args.steady_s)
    all_pass = True
    for c in conds:
        try:
            v = c.extract(stats)
        except Exception as exc:
            v = None
            print(f"[smoke] WARN: extract failed for {c.label}: {exc}")
        ok = bool(c.passes(v))
        if not ok and c.optional:
            print(f"[smoke] OPT  {c.label}: value={v} (optional, skipping)")
            continue
        marker = "PASS" if ok else "FAIL"
        print(f"[smoke] {marker} {c.label}: value={v}")
        if not ok:
            all_pass = False

    print("\n[smoke] result:", "PASS" if all_pass else "FAIL")
    return 0 if all_pass else 1


if __name__ == "__main__":
    sys.exit(main())
