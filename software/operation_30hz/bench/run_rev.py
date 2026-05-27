#!/usr/bin/env python3
"""Driver for an operation-30hz revision benchmark.

Usage:
  python3 bench/run_rev.py rev01 --duration 20
  python3 bench/run_rev.py rev02 --duration 20
"""
from __future__ import annotations

import argparse
import logging
import os
import signal
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from common.config import from_env
from common.metrics import Metrics


def _build_rev(label: str, cfg, metrics):
    if label == "rev01":
        from rev01.main import Rev01
        return Rev01(cfg, metrics)
    if label == "rev02":
        from rev02.main import Rev02
        return Rev02(cfg, metrics)
    raise SystemExit(f"unknown rev: {label}")


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("rev", choices=["rev01", "rev02"])
    p.add_argument("--duration", type=float, default=20.0,
                   help="Seconds to run (default 20)")
    p.add_argument("--workload", type=int, default=1,
                   help="Subsystem-work multiplier per step (1 = light, 30 = approx live)")
    args = p.parse_args()

    logging.basicConfig(
        level=logging.WARNING,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    results_dir = Path(__file__).parent.parent / "results"
    results_dir.mkdir(parents=True, exist_ok=True)
    cfg = from_env(args.rev, args.duration, results_dir, workload_x=args.workload)

    print(f"[{args.rev}] starting (duration={args.duration}s, workload={args.workload}x, port={cfg.preview_port})")
    print(f"[{args.rev}] model: {cfg.model_path}")
    print(f"[{args.rev}] cameras: {[(c.name, c.device, c.core_mask) for c in cfg.cameras]}")

    metrics = Metrics()
    rev = _build_rev(args.rev, cfg, metrics)
    rev.start()

    # Run the bench for `duration`, then snapshot and exit.
    deadline = time.perf_counter() + args.duration
    try:
        while time.perf_counter() < deadline:
            time.sleep(1.0)
            print(f"[{args.rev}] +{int(time.perf_counter() - (deadline - args.duration))}s ...")
    except KeyboardInterrupt:
        pass

    print(f"[{args.rev}] stopping ...")
    rev.stop()
    snap = metrics.snapshot()
    snap["rev"] = args.rev
    snap["config"] = {
        "duration_s": cfg.duration_s,
        "width": cfg.width, "height": cfg.height, "fps_target": cfg.fps_target,
        "preview_port": cfg.preview_port, "bus_command_ms": cfg.bus_command_ms,
        "model": str(cfg.model_path),
        "cameras": [(c.name, c.device, c.core_mask) for c in cfg.cameras],
    }
    import json
    cfg.output_path.write_text(json.dumps(snap, indent=2, default=str))
    print(f"[{args.rev}] wrote {cfg.output_path}")
    _print_summary(args.rev, snap)
    return 0


def _print_summary(label: str, snap: dict) -> None:
    s = snap.get("series", {})
    print()
    print(f"=== {label} summary ===")

    def show(name: str) -> None:
        v = s.get(name)
        if v is None:
            print(f"  {name}: (no samples)")
            return
        print(f"  {name}: count={v['count']:6d}  avg={v['avg_ms']:8.2f}ms  "
              f"p50={v['p50_ms']:8.2f}  p90={v['p90_ms']:8.2f}  max={v['max_ms']:8.2f}")

    # Cross-rev metrics
    if label == "rev01":
        show("coordinator.step.total_ms")
        show("coordinator.step.interval_ms")
        show("coordinator.feeder_ms")
        show("coordinator.classification_ms")
        for r in ("c_channel_2", "c_channel_3", "carousel"):
            show(f"coordinator.feeder.{r}.convert_ms")
        show("frame_to_decision_ms")
    else:
        for sub in ("feeder", "classification", "distribution"):
            show(f"subsystem.{sub}.step_ms")
            show(f"subsystem.{sub}.interval_ms")
        show("frame_to_decision_feeder_ms")
        show("frame_to_decision_classification_ms")

    for r in ("c_channel_2", "c_channel_3", "carousel"):
        show(f"infer.{r}.ms")
    print()
    # Effective Hz
    if label == "rev01":
        iv = s.get("coordinator.step.interval_ms")
        if iv and iv["avg_ms"] > 0:
            print(f"  coordinator effective rate: {1000.0 / iv['avg_ms']:.1f} Hz")
    else:
        for sub in ("feeder", "classification", "distribution"):
            iv = s.get(f"subsystem.{sub}.interval_ms")
            if iv and iv["avg_ms"] > 0:
                print(f"  subsystem.{sub} effective rate: {1000.0 / iv['avg_ms']:.1f} Hz")
    print()
    print("  thread counters:")
    for name, by_thread in snap.get("thread_counters", {}).items():
        items = ", ".join(f"{t}={c}" for t, c in sorted(by_thread.items(), key=lambda x: -x[1])[:6])
        print(f"    {name}: {items}")


if __name__ == "__main__":
    raise SystemExit(main())
