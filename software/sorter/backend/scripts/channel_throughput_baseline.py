#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from typing import Any

import requests

from channel_throughput_report import (
    BASE,
    OUT_ROOT,
    _load_runs,
    _write_index,
    _write_run,
)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run a timed throughput baseline and append it to the channel throughput report.")
    parser.add_argument("--backend-base", default=BASE)
    parser.add_argument("--out-root", default=str(OUT_ROOT))
    parser.add_argument("--duration-s", type=float, default=300.0)
    parser.add_argument("--sample-period-s", type=float, default=5.0)
    parser.add_argument("--title", default="Sorter Channel Throughput Report")
    parser.add_argument("--label", default="5 minute baseline")
    parser.add_argument("--strategy", default="baseline run")
    parser.add_argument("--changes", default="no tuning changes; capture baseline throughput")
    parser.add_argument("--note", default="")
    return parser.parse_args()


def _post(base_url: str, path: str) -> dict[str, Any]:
    response = requests.post(f"{base_url.rstrip('/')}{path}", timeout=20)
    response.raise_for_status()
    data = response.json()
    if not isinstance(data, dict):
        raise RuntimeError(f"{path} did not return a JSON object")
    return data


def _get(base_url: str, path: str) -> dict[str, Any]:
    response = requests.get(f"{base_url.rstrip('/')}{path}", timeout=20)
    response.raise_for_status()
    data = response.json()
    if not isinstance(data, dict):
        raise RuntimeError(f"{path} did not return a JSON object")
    return data


def _runtime_stats(base_url: str) -> dict[str, Any]:
    payload = _get(base_url, "/runtime-stats").get("payload")
    if not isinstance(payload, dict):
        raise RuntimeError("runtime-stats response did not contain a payload object")
    return payload


def _classification_debug(base_url: str) -> dict[str, Any] | None:
    try:
        return _get(base_url, "/api/classification-channel/debug")
    except Exception:
        return None


def _wait_for_ready(base_url: str, timeout_s: float = 240.0) -> None:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        status = _get(base_url, "/api/system/status")
        hardware_state = status.get("hardware_state")
        if hardware_state == "ready":
            return
        if hardware_state == "error":
            raise RuntimeError(f"Hardware entered error state: {status}")
        time.sleep(1.0)
    raise RuntimeError("Timed out waiting for hardware_state=ready")


def _wait_for_lifecycle(base_url: str, expected: str, timeout_s: float = 30.0) -> None:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        lifecycle_state = _runtime_stats(base_url).get("lifecycle_state")
        if lifecycle_state == expected:
            return
        time.sleep(0.25)
    raise RuntimeError(f"Timed out waiting for lifecycle_state={expected}")


def _ensure_ready(base_url: str) -> None:
    status = _get(base_url, "/api/system/status")
    hardware_state = status.get("hardware_state")
    if hardware_state == "ready":
        return
    if hardware_state == "standby":
        _post(base_url, "/api/system/start")
        _wait_for_ready(base_url)
        return
    if hardware_state == "homing":
        _wait_for_ready(base_url)
        return
    raise RuntimeError(f"Unsupported hardware state for baseline run: {status}")


def _ensure_paused(base_url: str) -> None:
    try:
        _post(base_url, "/pause")
    except Exception:
        pass
    deadline = time.monotonic() + 10.0
    while time.monotonic() < deadline:
        lifecycle_state = _runtime_stats(base_url).get("lifecycle_state")
        if lifecycle_state == "paused":
            return
        time.sleep(0.25)


def _num(value: Any) -> float | int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return value
    return None


def _delta(end_value: Any, start_value: Any) -> float | int | None:
    end_num = _num(end_value)
    start_num = _num(start_value)
    if end_num is None or start_num is None:
        return None
    return end_num - start_num


def _delta_channel_summary(start_snapshot: dict[str, Any], end_snapshot: dict[str, Any]) -> dict[str, Any]:
    start_channels = start_snapshot.get("channel_throughput")
    end_channels = end_snapshot.get("channel_throughput")
    if not isinstance(start_channels, dict) or not isinstance(end_channels, dict):
        return {}

    summary: dict[str, Any] = {}
    for channel_key in ("c_channel_2", "c_channel_3", "classification_channel"):
        start_channel = start_channels.get(channel_key)
        end_channel = end_channels.get(channel_key)
        if not isinstance(start_channel, dict) or not isinstance(end_channel, dict):
            continue
        exit_count = int(_delta(end_channel.get("exit_count"), start_channel.get("exit_count")) or 0)
        running_time_s = float(_delta(end_channel.get("running_time_s"), start_channel.get("running_time_s")) or 0.0)
        active_time_s = float(_delta(end_channel.get("active_time_s"), start_channel.get("active_time_s")) or 0.0)
        waiting_time_s = float(_delta(end_channel.get("waiting_time_s"), start_channel.get("waiting_time_s")) or 0.0)
        channel_summary: dict[str, Any] = {
            "exit_count": exit_count,
            "running_time_s": running_time_s,
            "active_time_s": active_time_s,
            "waiting_time_s": waiting_time_s,
            "overall_ppm": ((exit_count * 60.0) / running_time_s) if running_time_s > 0.0 and exit_count > 0 else None,
            "active_ppm": ((exit_count * 60.0) / active_time_s) if active_time_s > 0.0 and exit_count > 0 else None,
        }
        if channel_key == "classification_channel":
            start_outcomes = start_channel.get("outcomes")
            end_outcomes = end_channel.get("outcomes")
            outcome_summary: dict[str, Any] = {}
            if isinstance(start_outcomes, dict) and isinstance(end_outcomes, dict):
                for outcome_key in (
                    "classified_success",
                    "distributed_success",
                    "unknown",
                    "multi_drop_fail",
                    "not_found",
                ):
                    start_outcome = start_outcomes.get(outcome_key)
                    end_outcome = end_outcomes.get(outcome_key)
                    if not isinstance(start_outcome, dict) or not isinstance(end_outcome, dict):
                        continue
                    count = int(_delta(end_outcome.get("count"), start_outcome.get("count")) or 0)
                    outcome_summary[outcome_key] = {
                        "count": count,
                        "overall_ppm": ((count * 60.0) / running_time_s) if running_time_s > 0.0 and count > 0 else None,
                        "active_ppm": ((count * 60.0) / active_time_s) if active_time_s > 0.0 and count > 0 else None,
                    }
            channel_summary["outcomes"] = outcome_summary
        summary[channel_key] = channel_summary
    return summary


def _delta_counts(start_snapshot: dict[str, Any], end_snapshot: dict[str, Any]) -> dict[str, int]:
    start_counts = start_snapshot.get("counts")
    end_counts = end_snapshot.get("counts")
    if not isinstance(start_counts, dict) or not isinstance(end_counts, dict):
        return {}
    keys = (
        "pieces_seen",
        "classified",
        "unknown",
        "not_found",
        "multi_drop_fail",
        "distributed",
        "stage_created",
        "stage_distributing",
        "stage_distributed",
        "recognize_fired_total",
        "recognize_skipped_no_crops",
        "brickognize_empty_result",
        "brickognize_timeout_total",
    )
    return {
        key: int(_delta(end_counts.get(key), start_counts.get(key)) or 0)
        for key in keys
    }


def _sample_payload(base_url: str) -> dict[str, Any]:
    snapshot = _runtime_stats(base_url)
    classification_debug = _classification_debug(base_url)
    sample: dict[str, Any] = {
        "captured_at": time.time(),
        "lifecycle_state": snapshot.get("lifecycle_state"),
        "counts": snapshot.get("counts"),
        "channel_throughput": snapshot.get("channel_throughput"),
    }
    if isinstance(classification_debug, dict):
        sample["classification_debug"] = {
            "counts": classification_debug.get("counts"),
            "positions": classification_debug.get("positions"),
            "gates": classification_debug.get("gates"),
        }
    return sample


def main() -> int:
    args = _parse_args()
    base_url = str(args.backend_base)
    out_root = Path(args.out_root).expanduser().resolve()
    out_root.mkdir(parents=True, exist_ok=True)

    _ensure_ready(base_url)
    _ensure_paused(base_url)

    start_snapshot = _runtime_stats(base_url)
    start_debug = _classification_debug(base_url)
    started_at = time.time()

    _post(base_url, "/resume")
    _wait_for_lifecycle(base_url, "running")

    samples: list[dict[str, Any]] = []
    deadline = time.monotonic() + float(args.duration_s)
    while time.monotonic() < deadline:
        samples.append(_sample_payload(base_url))
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            break
        time.sleep(min(float(args.sample_period_s), remaining))

    try:
        _post(base_url, "/pause")
    except Exception:
        pass
    try:
        _wait_for_lifecycle(base_url, "paused")
    except RuntimeError as exc:
        print(f"warning: {exc}; continuing to save run data anyway", flush=True)

    ended_at = time.time()
    end_snapshot = _runtime_stats(base_url)
    end_debug = _classification_debug(base_url)

    summary = {
        "wall_duration_s": ended_at - started_at,
        "duration_requested_s": float(args.duration_s),
        "sample_period_s": float(args.sample_period_s),
        "sample_count": len(samples),
        "counts_delta": _delta_counts(start_snapshot, end_snapshot),
        "channel_throughput": _delta_channel_summary(start_snapshot, end_snapshot),
    }

    run_payload = {
        "captured_at": ended_at,
        "label": args.label,
        "strategy": args.strategy,
        "changes": args.changes,
        "note": args.note,
        "start_snapshot": start_snapshot,
        "start_classification_debug": start_debug,
        "end_snapshot": end_snapshot,
        "end_classification_debug": end_debug,
        "samples": samples,
        "summary": summary,
        "snapshot": end_snapshot,
    }

    _write_run(out_root, run_payload)
    runs = _load_runs(out_root)
    _write_index(out_root, args.title, runs)
    print(str(out_root / "index.html"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
