#!/usr/bin/env python3
"""Small live C4 sector probe.

Default mode is read-only: it checks lifecycle endpoints, reads C4 sector
occupancy, and asks the backend for a sector move plan with execute=false.
Use --execute together with --confirm-execute C4 to send the planned move.
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any
from urllib import error, parse, request


DEFAULT_BASE_URL = "http://localhost:8000"


class ProbeError(RuntimeError):
    pass


def _url(base_url: str, path: str, params: dict[str, Any] | None = None) -> str:
    base = base_url.rstrip("/")
    if not params:
        return f"{base}{path}"
    return f"{base}{path}?{parse.urlencode(params)}"


def _request_json(
    base_url: str,
    method: str,
    path: str,
    *,
    params: dict[str, Any] | None = None,
    timeout: float,
) -> dict[str, Any]:
    url = _url(base_url, path, params)
    req = request.Request(url, method=method)
    try:
        with request.urlopen(req, timeout=timeout) as response:
            raw = response.read().decode("utf-8")
    except error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        raise ProbeError(f"{method} {path} -> HTTP {exc.code}: {raw}") from exc
    except OSError as exc:
        raise ProbeError(f"{method} {path} failed: {exc}") from exc
    if not raw.strip():
        return {}
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ProbeError(f"{method} {path} returned non-JSON: {raw[:200]}") from exc
    return payload if isinstance(payload, dict) else {"value": payload}


def _print_section(title: str, payload: dict[str, Any]) -> None:
    print(f"\n## {title}")
    print(json.dumps(payload, indent=2, sort_keys=True))


def _status_summary(payload: dict[str, Any]) -> dict[str, Any]:
    keys = (
        "state",
        "hardware_state",
        "hardware_error",
        "sorter_state",
        "running",
        "blocked_reason",
        "mode",
        "camera_layout",
    )
    return {key: payload.get(key) for key in keys if key in payload}


def _auto_move_params_from_occupancy(
    occupancy: dict[str, Any],
    *,
    direction: str,
    execute: bool,
) -> dict[str, Any]:
    sectors = occupancy.get("sectors")
    if not isinstance(sectors, list):
        raise ProbeError("occupancy response has no sectors list")
    exit_sector = occupancy.get("exit_sector")
    if not isinstance(exit_sector, int):
        raise ProbeError("occupancy response has no exit_sector")

    occupied: list[dict[str, Any]] = []
    for sector in sectors:
        if not isinstance(sector, dict) or not sector.get("occupied"):
            continue
        sector_index = sector.get("sector_index")
        if not isinstance(sector_index, int):
            continue
        occupied.append(sector)

    if not occupied:
        raise ProbeError("occupancy response has no occupied sector to plan from")

    selected = next(
        (
            sector
            for sector in occupied
            if sector.get("sector_index") != exit_sector
        ),
        occupied[0],
    )
    from_sector = int(selected["sector_index"])
    return {
        "from_sector": from_sector,
        "to_sector": int(exit_sector),
        "direction": direction,
        "execute": "true" if execute else "false",
    }


def run_probe(args: argparse.Namespace) -> int:
    base_url = str(args.base_url)
    timeout = float(args.timeout)
    if args.execute and args.confirm_execute != "C4":
        raise ProbeError("--execute requires --confirm-execute C4")

    health = _request_json(base_url, "GET", "/health", timeout=timeout)
    _print_section("health", health)

    system_status = _request_json(base_url, "GET", "/api/system/status", timeout=timeout)
    _print_section("system_status", _status_summary(system_status) or system_status)

    try:
        rt_status = _request_json(base_url, "GET", "/api/rt/status", timeout=timeout)
    except ProbeError as exc:
        rt_status = {"ok": False, "error": str(exc)}
    _print_section("rt_status", _status_summary(rt_status) or rt_status)

    occupancy = _request_json(
        base_url,
        "POST",
        "/api/classification-channel/sector-occupancy",
        params={"force_detection": "true" if args.force_detection else "false"},
        timeout=timeout,
    )
    _print_section("c4_sector_occupancy", occupancy)

    if args.auto_plan:
        move_params = _auto_move_params_from_occupancy(
            occupancy,
            direction=str(args.direction),
            execute=bool(args.execute),
        )
        _print_section("c4_suggested_sector_move", move_params)
    else:
        move_params = {
            "from_sector": int(args.from_sector),
            "to_sector": int(args.to_sector),
            "direction": str(args.direction),
            "execute": "true" if args.execute else "false",
        }

    move_plan = _request_json(
        base_url,
        "POST",
        "/api/classification-channel/sector-move",
        params=move_params,
        timeout=timeout,
    )
    _print_section("c4_sector_move", move_plan)
    return 0


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Probe live C4 sector state and motion plan.")
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument("--timeout", type=float, default=5.0)
    parser.add_argument("--from-sector", type=int, default=0)
    parser.add_argument("--to-sector", type=int, default=1)
    parser.add_argument("--direction", choices=("shortest", "cw", "ccw"), default="shortest")
    parser.add_argument("--auto-plan", action="store_true")
    parser.add_argument("--force-detection", action="store_true")
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--confirm-execute", default="")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    try:
        return run_probe(args)
    except ProbeError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
