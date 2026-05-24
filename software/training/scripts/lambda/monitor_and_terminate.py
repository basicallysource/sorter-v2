"""Monitor a set of in-flight `train lambda run` jobs and terminate the Lambda
instance once every bundle has fully landed on local disk (default T7).

Designed to be launched via `nohup python monitor_and_terminate.py ... &` so it
survives the parent shell ending. It does NOT depend on Claude Code's task
harness or any external orchestrator — it polls the filesystem and the Lambda
REST API on a fixed interval.

Completion criteria for a single bundle dir on T7:
  - `<bundle>/<bundle>.rknn` exists and is non-empty
  - `<bundle>/run_metadata.json` exists  (written as the very last bundle file)
  - bundle dir has been stable (no size change) for `--stable-seconds` (default 60s)
    so we don't trigger mid-rsync

Termination:
  - Looks up the Lambda instance whose IP matches `--host-ip` via
    `GET https://cloud.lambdalabs.com/api/v1/instances`
  - Issues `POST .../instance-operations/terminate` with the matched instance id
  - Writes the API response to `--log-file` and exits

Safety:
  - `--dry-run` skips the actual terminate call (logs what it would do)
  - Refuses to terminate if any bundle still missing after `--max-wait-seconds`
    (default 8h) — leaves the box up for manual inspection
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from base64 import b64encode
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


LAMBDA_API_BASE = "https://cloud.lambdalabs.com/api/v1"


def _log(log_path: Path, msg: str) -> None:
    stamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
    line = f"[{stamp}] {msg}"
    print(line, flush=True)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("a") as fh:
        fh.write(line + "\n")


def _bundle_state(bundle_dir: Path) -> dict[str, Any]:
    if not bundle_dir.exists():
        return {"exists": False, "ready": False, "total_bytes": 0, "rknn_size": 0, "has_metadata": False}
    rknn_files = list(bundle_dir.glob("*.rknn"))
    rknn_size = max((f.stat().st_size for f in rknn_files), default=0)
    has_metadata = (bundle_dir / "run_metadata.json").exists()
    total = sum(f.stat().st_size for f in bundle_dir.rglob("*") if f.is_file())
    ready = rknn_size > 0 and has_metadata
    return {
        "exists": True,
        "ready": ready,
        "total_bytes": total,
        "rknn_size": rknn_size,
        "has_metadata": has_metadata,
    }


def _lambda_api(method: str, path: str, api_key: str, *, body: dict[str, Any] | None = None) -> tuple[int, dict[str, Any]]:
    url = f"{LAMBDA_API_BASE}{path}"
    headers = {
        "Authorization": "Basic " + b64encode(f"{api_key}:".encode()).decode(),
        "Content-Type": "application/json",
        "Accept": "application/json",
        # Lambda Cloud is fronted by Cloudflare which 403s the default urllib UA.
        "User-Agent": "curl/8.4.0",
    }
    data = json.dumps(body).encode() if body is not None else None
    req = Request(url, method=method, headers=headers, data=data)
    try:
        with urlopen(req, timeout=30) as resp:
            payload = json.loads(resp.read().decode())
            return resp.status, payload
    except HTTPError as exc:
        try:
            payload = json.loads(exc.read().decode())
        except Exception:
            payload = {"error": str(exc)}
        return exc.code, payload
    except URLError as exc:
        return -1, {"error": str(exc)}


def _find_instance_id(host_ip: str, api_key: str) -> str | None:
    status, payload = _lambda_api("GET", "/instances", api_key)
    if status != 200:
        return None
    for inst in payload.get("data", []):
        if inst.get("ip") == host_ip:
            return inst.get("id")
    return None


def _terminate_instance(instance_id: str, api_key: str) -> tuple[int, dict[str, Any]]:
    return _lambda_api(
        "POST",
        "/instance-operations/terminate",
        api_key,
        body={"instance_ids": [instance_id]},
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--bundle",
        action="append",
        required=True,
        help="Absolute path to a bundle dir on local disk (repeatable). All must be 'ready' before terminate.",
    )
    parser.add_argument("--host-ip", required=True, help="Public IP of the Lambda instance to terminate, e.g. 132.145.130.118")
    parser.add_argument("--lambda-api-key", required=True, help="Lambda Cloud API key (cloud.lambdalabs.com)")
    parser.add_argument("--log-file", required=True, help="Append-only log path for the monitor's own progress")
    parser.add_argument("--poll-seconds", type=int, default=60, help="Seconds between polls (default 60)")
    parser.add_argument(
        "--stable-seconds",
        type=int,
        default=120,
        help="A bundle must show no size change for this long before we trust it's done rsyncing (default 120s).",
    )
    parser.add_argument(
        "--max-wait-seconds",
        type=int,
        default=10 * 60 * 60,
        help="Refuse to terminate if not all bundles ready after this long (default 10h).",
    )
    parser.add_argument("--dry-run", action="store_true", help="Log what would happen, do not call Lambda API.")
    args = parser.parse_args()

    log_path = Path(args.log_file)
    bundles = [Path(b) for b in args.bundle]

    _log(log_path, f"monitor start: tracking {len(bundles)} bundles on host {args.host_ip}")
    for b in bundles:
        _log(log_path, f"  bundle: {b}")

    started_at = time.time()
    last_total: dict[str, int] = {str(b): -1 for b in bundles}
    stable_since: dict[str, float] = {str(b): 0.0 for b in bundles}

    while True:
        if time.time() - started_at > args.max_wait_seconds:
            _log(log_path, "TIMEOUT — refusing to terminate, leaving Lambda box running for inspection.")
            return 2

        states = {str(b): _bundle_state(b) for b in bundles}
        ready_count = 0
        now = time.time()
        for b in bundles:
            key = str(b)
            st = states[key]
            if st["total_bytes"] != last_total[key]:
                last_total[key] = st["total_bytes"]
                stable_since[key] = now
            stable_for = now - stable_since[key] if stable_since[key] > 0 else 0
            if st["ready"] and stable_for >= args.stable_seconds:
                ready_count += 1

        # Status line
        statuses = []
        for b in bundles:
            key = str(b)
            st = states[key]
            tag = "READY" if st["ready"] and (now - stable_since[key]) >= args.stable_seconds else (
                "rsyncing" if st["exists"] else "missing"
            )
            statuses.append(f"{Path(key).name}={tag}({st['total_bytes']//(1024*1024)}MB)")
        _log(log_path, f"poll: ready={ready_count}/{len(bundles)} | " + " | ".join(statuses))

        if ready_count == len(bundles):
            _log(log_path, "ALL BUNDLES READY — proceeding to terminate Lambda instance.")
            break

        time.sleep(args.poll_seconds)

    if args.dry_run:
        _log(log_path, "DRY RUN — skipping Lambda API call. Done.")
        return 0

    _log(log_path, f"Looking up Lambda instance ID for IP {args.host_ip} …")
    inst_id = _find_instance_id(args.host_ip, args.lambda_api_key)
    if not inst_id:
        _log(log_path, f"Could not find an active instance with IP {args.host_ip}. Listing all:")
        status, payload = _lambda_api("GET", "/instances", args.lambda_api_key)
        _log(log_path, f"  status={status} payload={json.dumps(payload)[:500]}")
        return 3
    _log(log_path, f"Found instance id={inst_id}. Issuing terminate …")
    status, payload = _terminate_instance(inst_id, args.lambda_api_key)
    _log(log_path, f"Terminate response: status={status} payload={json.dumps(payload)[:500]}")
    return 0 if status in (200, 202) else 4


if __name__ == "__main__":
    sys.exit(main())
