#!/usr/bin/env python3
"""Keep retrying pending Vast.ai NCNN training models until they succeed."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess
import sys
import time

from vastai_orchestrate_training import RUNS_DIR, TRACK_SPECS

SCRIPT_DIR = Path(__file__).resolve().parent
DEFAULT_MODEL_IDS = ("B1", "B2", "B3", "D1", "D2", "E1", "F1")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model-ids", nargs="+", default=list(DEFAULT_MODEL_IDS))
    parser.add_argument("--image-profile", default="pytorch-cu121-compat")
    parser.add_argument("--hardware-profile", default="stable_3090")
    parser.add_argument("--retry-delay-seconds", type=int, default=30)
    parser.add_argument("--watcher-poll-seconds", type=int, default=30)
    parser.add_argument("--running-timeout-seconds", type=int, default=600)
    parser.add_argument("--label-prefix", default="matrix-rest-ncnn-supervised")
    parser.add_argument("--state-path", default=None)
    return parser.parse_args()


def write_state(state_path: Path | None, payload: dict[str, object]) -> None:
    if state_path is None:
        return
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(json.dumps(payload, indent=2))


def model_to_track(model_id: str) -> str:
    normalized = model_id.strip().upper()
    for track_name, track in TRACK_SPECS.items():
        if any(model.model_id == normalized for model in track.models):
            return track_name
    raise KeyError(f"Unknown model ID: {model_id}")


def group_by_track(model_ids: list[str]) -> dict[str, list[str]]:
    grouped: dict[str, list[str]] = {}
    for model_id in model_ids:
        track_name = model_to_track(model_id)
        grouped.setdefault(track_name, []).append(model_id)
    return grouped


def latest_run_dir(label: str) -> Path | None:
    candidates: list[tuple[float, Path]] = []
    for run_dir in RUNS_DIR.iterdir():
        if not run_dir.is_dir():
            continue
        manifest_path = run_dir / "run.json"
        if not manifest_path.exists():
            continue
        try:
            payload = json.loads(manifest_path.read_text())
        except json.JSONDecodeError:
            continue
        if payload.get("label") != label:
            continue
        candidates.append((manifest_path.stat().st_mtime, run_dir))
    if not candidates:
        return None
    candidates.sort()
    return candidates[-1][1]


def wait_for_watcher(run_dir: Path, poll_seconds: int) -> dict[str, object]:
    manifest_path = run_dir / "run.json"
    while True:
        payload = json.loads(manifest_path.read_text())
        watcher = payload.get("watcher")
        if isinstance(watcher, dict):
            watcher_pid = watcher.get("pid")
            if isinstance(watcher_pid, int):
                while True:
                    proc = subprocess.run(
                        ["ps", "-p", str(watcher_pid), "-o", "pid="],
                        capture_output=True,
                        text=True,
                    )
                    if proc.returncode != 0 or not proc.stdout.strip():
                        return payload
                    time.sleep(poll_seconds)
        time.sleep(2)


def run_results_for_track(run_dir: Path, track_name: str) -> dict[str, object]:
    results_root = run_dir / "results"
    if not results_root.exists():
        return {}
    for candidate in sorted(results_root.glob(f"{track_name}-*/results/{track_name}_results.json")):
        try:
            return json.loads(candidate.read_text())
        except json.JSONDecodeError:
            continue
    return {}


def model_succeeded(payload: dict[str, object]) -> bool:
    return payload.get("train_returncode") == 0 and bool(payload.get("ncnn_exported"))


def launch_track(
    *,
    track_name: str,
    model_ids: list[str],
    label: str,
    image_profile: str,
    hardware_profile: str,
    poll_seconds: int,
    running_timeout_seconds: int,
) -> tuple[int, Path | None]:
    cmd = [
        sys.executable,
        str(SCRIPT_DIR / "vastai_orchestrate_training.py"),
        "--tracks",
        track_name,
        "--model-ids",
        *model_ids,
        "--label",
        label,
        "--image-profile",
        image_profile,
        "--hardware-profile",
        hardware_profile,
        "--poll-seconds",
        str(poll_seconds),
        "--running-timeout-seconds",
        str(running_timeout_seconds),
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.stdout.strip():
        print(proc.stdout, flush=True)
    if proc.stderr.strip():
        print(proc.stderr, file=sys.stderr, flush=True)
    return proc.returncode, latest_run_dir(label)


def main() -> int:
    args = parse_args()
    pending = sorted({model_id.strip().upper() for model_id in args.model_ids if model_id.strip()})
    state_path = Path(args.state_path).resolve() if args.state_path else None

    attempt = 1
    while pending:
        grouped = group_by_track(pending)
        progress_this_round = False
        for track_name, track_model_ids in grouped.items():
            label = f"{args.label_prefix}-{track_name}-attempt{attempt:02d}"
            write_state(
                state_path,
                {
                    "status": "launching",
                    "attempt": attempt,
                    "track": track_name,
                    "pending_model_ids": pending,
                    "active_model_ids": track_model_ids,
                    "label": label,
                },
            )

            rc, run_dir = launch_track(
                track_name=track_name,
                model_ids=track_model_ids,
                label=label,
                image_profile=args.image_profile,
                hardware_profile=args.hardware_profile,
                poll_seconds=args.watcher_poll_seconds,
                running_timeout_seconds=args.running_timeout_seconds,
            )

            if rc != 0 or run_dir is None:
                write_state(
                    state_path,
                    {
                        "status": "launch_failed",
                        "attempt": attempt,
                        "track": track_name,
                        "pending_model_ids": pending,
                        "active_model_ids": track_model_ids,
                        "label": label,
                        "returncode": rc,
                    },
                )
                time.sleep(args.retry_delay_seconds)
                continue

            write_state(
                state_path,
                {
                    "status": "watching",
                    "attempt": attempt,
                    "track": track_name,
                    "pending_model_ids": pending,
                    "active_model_ids": track_model_ids,
                    "label": label,
                    "run_dir": str(run_dir),
                },
            )

            wait_for_watcher(run_dir, args.watcher_poll_seconds)
            results = run_results_for_track(run_dir, track_name)
            succeeded = sorted(
                model_id
                for model_id in track_model_ids
                if isinstance(results.get(model_id), dict) and model_succeeded(results[model_id])
            )
            if succeeded:
                progress_this_round = True
                pending = [model_id for model_id in pending if model_id not in set(succeeded)]

            write_state(
                state_path,
                {
                    "status": "track_finished",
                    "attempt": attempt,
                    "track": track_name,
                    "pending_model_ids": pending,
                    "active_model_ids": track_model_ids,
                    "succeeded_model_ids": succeeded,
                    "label": label,
                    "run_dir": str(run_dir),
                    "results": results,
                },
            )

        if pending:
            if not progress_this_round:
                print(
                    f"No model finished successfully in attempt {attempt}; retrying pending set after "
                    f"{args.retry_delay_seconds}s: {', '.join(pending)}",
                    flush=True,
                )
            attempt += 1
            time.sleep(args.retry_delay_seconds)

    write_state(
        state_path,
        {
            "status": "complete",
            "attempt": attempt,
            "pending_model_ids": [],
            "completed_model_ids": sorted({model_id.strip().upper() for model_id in args.model_ids if model_id.strip()}),
        },
    )
    print("All requested NCNN models completed successfully.", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
