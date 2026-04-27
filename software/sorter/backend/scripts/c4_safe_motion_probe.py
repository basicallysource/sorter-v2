#!/usr/bin/env python3
"""Conservative live C4 carousel motion probe.

This script intentionally stays below the manual debug limits used for the
gear-driven C4 platter. It is for validating that small C4 moves start, stop,
and return to zero cleanly while the runtime stays paused.
"""

from __future__ import annotations

import argparse
import json
import time
from typing import Any
from urllib import parse, request


DEFAULT_BASE = "http://127.0.0.1:8000"
MAX_ABS_DEGREES = 36.0
MAX_SPEED = 250
MAX_ACCELERATION = 600


def _get_json(url: str, *, timeout: float = 10.0) -> dict[str, Any]:
    with request.urlopen(url, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def _post_json(
    url: str,
    *,
    params: dict[str, Any] | None = None,
    timeout: float = 10.0,
) -> dict[str, Any]:
    full_url = url
    if params:
        full_url = f"{url}?{parse.urlencode(params)}"
    req = request.Request(full_url, method="POST")
    with request.urlopen(req, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


class Probe:
    def __init__(self, base: str) -> None:
        self.base = base.rstrip("/")
        self.system_url = f"{self.base}/api/system/status"
        self.rt_url = f"{self.base}/api/rt/status"
        self.live_url = f"{self.base}/api/hardware-config/carousel/live"
        self.move_url = f"{self.base}/stepper/move-degrees"
        self.stop_all_url = f"{self.base}/stepper/stop-all"
        self.pause_url = f"{self.base}/api/rt/debug/pause"

    def pause_runtime(self) -> None:
        _post_json(self.pause_url)

    def stop_all(self) -> None:
        try:
            _post_json(self.stop_all_url)
        except Exception:
            pass

    def live(self) -> dict[str, Any]:
        return _get_json(self.live_url)

    def guard_ready(self) -> None:
        system = _get_json(self.system_url)
        if system.get("hardware_state") != "ready" or system.get("hardware_error"):
            raise RuntimeError(f"hardware not ready: {system}")
        rt = _get_json(self.rt_url)
        if not rt.get("paused"):
            raise RuntimeError("runtime must be paused before probing C4")
        live = self.live()
        if not live.get("live_available"):
            raise RuntimeError(f"carousel live status unavailable: {live}")
        if live.get("stepper_stopped") is not True:
            raise RuntimeError(f"carousel not stopped: {live}")

    def wait_stopped(self, *, timeout_s: float) -> dict[str, Any]:
        deadline = time.monotonic() + timeout_s
        last: dict[str, Any] = {}
        while time.monotonic() < deadline:
            last = self.live()
            if last.get("stepper_stopped") is True:
                return last
            time.sleep(0.05)
        self.stop_all()
        raise TimeoutError(f"carousel did not stop within {timeout_s:.1f}s: {last}")

    def move(
        self,
        *,
        degrees: float,
        speed: int,
        acceleration: int,
        timeout_s: float,
    ) -> dict[str, Any]:
        if abs(degrees) > MAX_ABS_DEGREES:
            raise ValueError(f"refusing degrees={degrees}; max is {MAX_ABS_DEGREES}")
        if speed > MAX_SPEED:
            raise ValueError(f"refusing speed={speed}; max is {MAX_SPEED}")
        if acceleration > MAX_ACCELERATION:
            raise ValueError(
                f"refusing acceleration={acceleration}; max is {MAX_ACCELERATION}"
            )
        self.guard_ready()
        before = self.live()
        started_at = time.monotonic()
        params = {
            "stepper": "carousel",
            "degrees": round(float(degrees), 6),
            "speed": int(speed),
            "min_speed": 16,
            "acceleration": int(acceleration),
        }
        _post_json(self.move_url, params=params)
        after = self.wait_stopped(timeout_s=timeout_s)
        duration_s = time.monotonic() - started_at
        return {
            "degrees": degrees,
            "duration_s": round(duration_s, 3),
            "before_deg": before.get("current_position_degrees"),
            "after_deg": after.get("current_position_degrees"),
            "before_microsteps": before.get("stepper_microsteps"),
            "after_microsteps": after.get("stepper_microsteps"),
        }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", default=DEFAULT_BASE)
    parser.add_argument("--cycles", type=int, default=3)
    parser.add_argument("--degrees", type=float, default=36.0)
    parser.add_argument("--speed", type=int, default=200)
    parser.add_argument("--acceleration", type=int, default=500)
    parser.add_argument("--timeout-s", type=float, default=25.0)
    parser.add_argument(
        "--single",
        action="store_true",
        help="Run exactly one relative move and do not auto-return.",
    )
    args = parser.parse_args()

    probe = Probe(args.base)
    probe.pause_runtime()
    probe.guard_ready()
    results: list[dict[str, Any]] = []
    try:
        if args.single:
            results.append(
                probe.move(
                    degrees=args.degrees,
                    speed=args.speed,
                    acceleration=args.acceleration,
                    timeout_s=args.timeout_s,
                )
            )
            print(
                json.dumps(
                    {"ok": True, "results": results, "final": probe.live()},
                    indent=2,
                )
            )
            return 0
        for _ in range(max(1, int(args.cycles))):
            results.append(
                probe.move(
                    degrees=args.degrees,
                    speed=args.speed,
                    acceleration=args.acceleration,
                    timeout_s=args.timeout_s,
                )
            )
            results.append(
                probe.move(
                    degrees=-args.degrees,
                    speed=args.speed,
                    acceleration=args.acceleration,
                    timeout_s=args.timeout_s,
                )
            )
    except Exception:
        probe.stop_all()
        raise
    print(json.dumps({"ok": True, "results": results, "final": probe.live()}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
