#!/usr/bin/env python3
"""Watch active Vast.ai training runs and destroy finished instances.

The watcher polls remote instances over SSH. Once the tracked training process
is no longer running, it copies the log and results directory locally and then
destroys the instance to avoid unnecessary GPU costs.

Example:
  python scripts/watch_vastai_runs.py \
    --output-dir blob/vastai_results \
    --poll-seconds 120 \
    --run track_a 33834400 ssh3.vast.ai 34400 vastai_track_a.py /workspace/track_a.log \
    --run track_bc 33833544 ssh3.vast.ai 33544 vastai_track_bc.py /workspace/track_bc.log
"""
from __future__ import annotations

import argparse
import json
import re
import shlex
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path


@dataclass
class RunSpec:
    name: str
    contract: str
    ssh_host: str
    ssh_port: str
    process_pattern: str
    log_path: str


def run_command(args: list[str], *, check: bool = False) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, capture_output=True, text=True, check=check)


def ssh_command(spec: RunSpec, remote_cmd: str) -> subprocess.CompletedProcess[str]:
    return run_command(
        [
            "ssh",
            "-o",
            "StrictHostKeyChecking=no",
            "-o",
            "ConnectTimeout=20",
            "-p",
            spec.ssh_port,
            f"root@{spec.ssh_host}",
            remote_cmd,
        ]
    )


def scp_from_remote(spec: RunSpec, remote_path: str, local_path: Path) -> subprocess.CompletedProcess[str]:
    local_path.parent.mkdir(parents=True, exist_ok=True)
    return run_command(
        [
            "scp",
            "-P",
            spec.ssh_port,
            "-o",
            "StrictHostKeyChecking=no",
            f"root@{spec.ssh_host}:{remote_path}",
            str(local_path),
        ]
    )


def scp_tree_from_remote(spec: RunSpec, remote_path: str, local_path: Path) -> subprocess.CompletedProcess[str]:
    local_path.parent.mkdir(parents=True, exist_ok=True)
    return run_command(
        [
            "scp",
            "-P",
            spec.ssh_port,
            "-o",
            "StrictHostKeyChecking=no",
            "-r",
            f"root@{spec.ssh_host}:{remote_path}",
            str(local_path),
        ]
    )


def get_instance_info(contract: str) -> dict | None:
    result = run_command(["vastai", "show", "instance", contract, "--raw"])
    if result.returncode != 0 or not result.stdout.strip():
        return None
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError:
        return None


def _self_safe_grep_regex(pattern: str) -> str:
    escaped = re.escape(pattern)
    if not escaped:
        return escaped
    return f"[{escaped[0]}]{escaped[1:]}"


def process_running(spec: RunSpec) -> bool:
    regex = _self_safe_grep_regex(spec.process_pattern)
    remote_cmd = (
        "ps -eo args= | "
        f"grep -E {shlex.quote(regex)} | "
        "grep -v 'grep -E' || true"
    )
    result = ssh_command(spec, remote_cmd)
    return result.returncode == 0 and bool(result.stdout.strip())


def write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)


def collect_artifacts(spec: RunSpec, output_dir: Path) -> None:
    run_dir = output_dir / f"{spec.name}-{spec.contract}"
    run_dir.mkdir(parents=True, exist_ok=True)

    log_copy = scp_from_remote(spec, spec.log_path, run_dir / Path(spec.log_path).name)
    if log_copy.returncode != 0:
        write_text(run_dir / "log_copy_error.txt", log_copy.stderr or log_copy.stdout)

    results_copy = scp_tree_from_remote(spec, "/workspace/results", run_dir / "results")
    if results_copy.returncode != 0:
        write_text(run_dir / "results_copy_error.txt", results_copy.stderr or results_copy.stdout)

    remote_state = ssh_command(
        spec,
        "set -e; "
        "echo '=== ps ==='; pgrep -af python || true; "
        "echo '=== tail ==='; tail -n 200 "
        f"{shlex.quote(spec.log_path)} || true; "
        "echo '=== disk ==='; du -sh /workspace/results 2>/dev/null || true",
    )
    write_text(run_dir / "remote_state.txt", (remote_state.stdout or "") + (remote_state.stderr or ""))


def destroy_instance(contract: str, output_dir: Path, spec: RunSpec) -> None:
    result = run_command(["vastai", "destroy", "instance", contract, "--raw"])
    write_text(
        output_dir / f"{spec.name}-{spec.contract}" / "destroy_result.txt",
        (result.stdout or "") + (result.stderr or ""),
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--poll-seconds", type=int, default=120)
    parser.add_argument(
        "--run",
        action="append",
        nargs=6,
        metavar=("NAME", "CONTRACT", "SSH_HOST", "SSH_PORT", "PROCESS_PATTERN", "LOG_PATH"),
        required=True,
        help="Track one active Vast.ai run",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    output_dir = Path(args.output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    pending = [
        RunSpec(
            name=item[0],
            contract=item[1],
            ssh_host=item[2],
            ssh_port=item[3],
            process_pattern=item[4],
            log_path=item[5],
        )
        for item in args.run
    ]

    while pending:
        still_pending: list[RunSpec] = []
        for spec in pending:
            info = get_instance_info(spec.contract)
            run_dir = output_dir / f"{spec.name}-{spec.contract}"
            run_dir.mkdir(parents=True, exist_ok=True)
            if info is None:
                write_text(run_dir / "status.txt", "instance_missing\n")
                continue

            write_text(run_dir / "instance.json", json.dumps(info, indent=2))
            if process_running(spec):
                write_text(run_dir / "status.txt", "running\n")
                still_pending.append(spec)
                continue

            write_text(run_dir / "status.txt", "collecting\n")
            collect_artifacts(spec, output_dir)
            destroy_instance(spec.contract, output_dir, spec)
            write_text(run_dir / "status.txt", "destroyed\n")

        pending = still_pending
        if pending:
            time.sleep(args.poll_seconds)

    return 0


if __name__ == "__main__":
    sys.exit(main())
