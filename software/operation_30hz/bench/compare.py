#!/usr/bin/env python3
"""Side-by-side compare two rev result JSONs."""
from __future__ import annotations

import json
import sys
from pathlib import Path


def load(p: str) -> dict:
    return json.loads(Path(p).read_text())


def fmt(v: dict | None, key: str = "avg_ms") -> str:
    if v is None:
        return "    -"
    return f"{v[key]:7.1f}"


def main() -> int:
    if len(sys.argv) < 3:
        print("usage: compare.py rev01.json rev02.json", file=sys.stderr)
        return 2
    a = load(sys.argv[1])
    b = load(sys.argv[2])

    print(f"A = {sys.argv[1]}  rev={a.get('rev')}  elapsed={a.get('elapsed_s'):.1f}s")
    print(f"B = {sys.argv[2]}  rev={b.get('rev')}  elapsed={b.get('elapsed_s'):.1f}s")
    print()

    sa, sb = a.get("series", {}), b.get("series", {})

    def row(label: str, k_a: str, k_b: str) -> None:
        va, vb = sa.get(k_a), sb.get(k_b)
        print(f"  {label:45s}  A avg={fmt(va)}ms  B avg={fmt(vb)}ms")

    print("=== decision loop ===")
    row("step time per tick",
        "coordinator.step.total_ms",
        "subsystem.feeder.step_ms")
    row("step interval (1/Hz)",
        "coordinator.step.interval_ms",
        "subsystem.feeder.interval_ms")
    row("frame -> decision latency",
        "frame_to_decision_ms",
        "frame_to_decision_feeder_ms")
    print()
    print("=== convert work (per role, GIL-sensitive) ===")
    for r in ("c_channel_2", "c_channel_3", "carousel"):
        row(f"feeder.{r}.convert_ms",
            f"coordinator.feeder.{r}.convert_ms",
            f"subsystem.feeder.{r}.convert_ms")
    print()
    print("=== inference per call ===")
    for r in ("c_channel_2", "c_channel_3", "carousel"):
        row(f"infer.{r}.ms", f"infer.{r}.ms", f"infer.{r}.ms")
    print()

    # Effective rates
    print("=== effective rates ===")
    ia = sa.get("coordinator.step.interval_ms")
    if ia and ia["avg_ms"] > 0:
        print(f"  A coordinator: {1000.0 / ia['avg_ms']:.1f} Hz")
    for sub in ("feeder", "classification", "distribution"):
        ib = sb.get(f"subsystem.{sub}.interval_ms")
        if ib and ib["avg_ms"] > 0:
            print(f"  B subsystem.{sub}: {1000.0 / ib['avg_ms']:.1f} Hz")

    print()
    print("=== which thread ran inference ===")
    ta = a.get("thread_counters", {})
    tb = b.get("thread_counters", {})
    for r in ("c_channel_2", "c_channel_3", "carousel"):
        k = f"infer.{r}.by_thread"
        print(f"  {r}:")
        print(f"    A: {dict(sorted(ta.get(k, {}).items(), key=lambda x: -x[1])[:6])}")
        print(f"    B: {dict(sorted(tb.get(k, {}).items(), key=lambda x: -x[1])[:6])}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
