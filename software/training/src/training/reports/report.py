import argparse
import ast
import json
import sys
import statistics
from datetime import datetime
from pathlib import Path

RECORDS_DIR = Path(__file__).parent.parent / "blob" / "records"


def loadRuntimeWaits() -> list[tuple[str, float | None]]:
    wait_values: list[tuple[str, float | None]] = []
    client_root = Path(__file__).resolve().parent.parent

    def readConstValue(path: Path, name: str) -> float | None:
        try:
            source = path.read_text()
            tree = ast.parse(source)
        except Exception:
            return None
        for node in tree.body:
            if not isinstance(node, ast.Assign):
                continue
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == name:
                    try:
                        value = ast.literal_eval(node.value)
                    except Exception:
                        return None
                    if isinstance(value, (int, float)):
                        return float(value)
                    return None
        return None

    wait_values.append(
        (
            "classification.detecting.WAIT_FOR_SETTLE_TO_TAKE_BASELINE_MS",
            readConstValue(client_root / "subsystems" / "classification" / "detecting.py", "WAIT_FOR_SETTLE_TO_TAKE_BASELINE_MS"),
        )
    )
    wait_values.append(
        (
            "classification.detecting.DEBOUNCE_MS",
            readConstValue(client_root / "subsystems" / "classification" / "detecting.py", "DEBOUNCE_MS"),
        )
    )
    wait_values.append(
        (
            "classification.rotating.PRE_ROTATE_DELAY_MS",
            readConstValue(client_root / "subsystems" / "classification" / "rotating.py", "PRE_ROTATE_DELAY_MS"),
        )
    )
    wait_values.append(
        (
            "classification.snapping.SETTLE_MS",
            readConstValue(client_root / "subsystems" / "classification" / "snapping.py", "SETTLE_MS"),
        )
    )
    wait_values.append(
        (
            "distribution.sending.CHUTE_SETTLE_MS",
            readConstValue(client_root / "subsystems" / "distribution" / "sending.py", "CHUTE_SETTLE_MS"),
        )
    )

    return wait_values


def loadRecord(path: Path) -> dict:
    with open(path, "r") as f:
        return json.load(f)


def getAllRecordPaths() -> list[Path]:
    if not RECORDS_DIR.exists():
        return []
    paths = sorted(RECORDS_DIR.glob("*.json"))
    return paths


def formatDuration(seconds: float) -> str:
    if seconds < 60:
        return f"{seconds:.1f}s"
    minutes = seconds / 60
    if minutes < 60:
        return f"{minutes:.1f}m"
    hours = minutes / 60
    return f"{hours:.1f}h"


def formatTimestamp(ts: float) -> str:
    return datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S")


def calcActiveSeconds(record: dict) -> float:
    total = 0.0
    for period in record.get("active_periods", []):
        total += period["end"] - period["start"]
    return total


def printTimingStats(label: str, values: list[float]) -> None:
    if not values:
        return
    values_sorted = sorted(values)
    avg = statistics.mean(values_sorted)
    med = statistics.median(values_sorted)
    p90 = values_sorted[int(len(values_sorted) * 0.9)]
    lo = values_sorted[0]
    hi = values_sorted[-1]
    print(f"  {label} (n={len(values)}):")
    print(f"    avg={avg:.2f}s  med={med:.2f}s  p90={p90:.2f}s  min={lo:.2f}s  max={hi:.2f}s")


def reportSingle(record: dict) -> None:
    run_id = record["run_id"]
    pieces = record["pieces"]
    total = len(pieces)
    started = record["started_at"]
    ended = record["ended_at"]
    wall_time = ended - started
    active_time = calcActiveSeconds(record)

    print(f"Run: {run_id}")
    print(f"  Started:  {formatTimestamp(started)}")
    print(f"  Ended:    {formatTimestamp(ended)}")
    print(f"  Wall time:   {formatDuration(wall_time)}")
    print(f"  Active time: {formatDuration(active_time)}")
    print(f"  Pieces: {total}")

    if total == 0:
        print("  No pieces to analyze.")
        return

    distributed = [p for p in pieces if p.get("distributed_at")]

    if len(distributed) >= 2:
        sorted_by_distributed = sorted(distributed, key=lambda p: p["distributed_at"])
        first = sorted_by_distributed[0]["distributed_at"]
        last = sorted_by_distributed[-1]["distributed_at"]
        span = last - first
        if span > 0:
            ppm = (len(distributed) - 1) / (span / 60.0)
            print(f"  Throughput: {ppm:.1f} pieces/min (distributed)")

    if active_time > 0 and len(distributed) > 0:
        ppm_active = len(distributed) / (active_time / 60.0)
        print(f"  Throughput (active): {ppm_active:.1f} pieces/min")

    creation_to_distributed = []
    classification_times = []
    distribution_times = []
    feeding_times = []
    find_to_rotate_times = []
    find_to_snap_done_times = []
    find_to_next_baseline_times = []
    find_to_next_ready_times = []
    rotate_only_times = []
    snapping_only_times = []
    chute_servo_target_to_positioned_times = []
    chute_servo_motion_only_times = []

    def appendDuration(out: list[float], start: float | None, end: float | None) -> None:
        if start is None or end is None:
            return
        if end >= start:
            out.append(end - start)

    for p in pieces:
        if p.get("distributed_at") and p.get("created_at"):
            creation_to_distributed.append(p["distributed_at"] - p["created_at"])
        if p.get("classified_at") and p.get("created_at"):
            classification_times.append(p["classified_at"] - p["created_at"])
        if p.get("distributed_at") and p.get("distributing_at"):
            distribution_times.append(p["distributed_at"] - p["distributing_at"])
        if p.get("feeding_started_at") and p.get("created_at"):
            feeding_times.append(p["created_at"] - p["feeding_started_at"])

        detect_confirmed_at = p.get("carousel_detected_confirmed_at") or p.get("created_at")
        appendDuration(find_to_rotate_times, detect_confirmed_at, p.get("carousel_rotated_at"))
        appendDuration(find_to_snap_done_times, detect_confirmed_at, p.get("carousel_snapping_completed_at"))
        appendDuration(find_to_next_baseline_times, detect_confirmed_at, p.get("carousel_next_baseline_captured_at"))
        appendDuration(find_to_next_ready_times, detect_confirmed_at, p.get("carousel_next_ready_at"))
        appendDuration(rotate_only_times, p.get("carousel_rotate_started_at"), p.get("carousel_rotated_at"))
        appendDuration(snapping_only_times, p.get("carousel_snapping_started_at"), p.get("carousel_snapping_completed_at"))
        appendDuration(
            chute_servo_target_to_positioned_times,
            p.get("distribution_target_selected_at"),
            p.get("distribution_positioned_at"),
        )
        appendDuration(
            chute_servo_motion_only_times,
            p.get("distribution_motion_started_at"),
            p.get("distribution_positioned_at"),
        )

    timing_sections = [
        ("Feed time (ready->landed)", feeding_times),
        ("Total time (created->distributed)", creation_to_distributed),
        ("Classification time (created->classified)", classification_times),
        ("Chute time (distributing->distributed)", distribution_times),
        ("Carousel: found->rotated", find_to_rotate_times),
        ("Carousel: found->snap done", find_to_snap_done_times),
        ("Carousel: found->next baseline captured", find_to_next_baseline_times),
        ("Carousel: found->next ready", find_to_next_ready_times),
        ("Carousel: rotate only", rotate_only_times),
        ("Carousel: snapping window (includes settle)", snapping_only_times),
        ("Distribution positioning: target selected->positioned", chute_servo_target_to_positioned_times),
        ("Distribution positioning: motion start->positioned", chute_servo_motion_only_times),
    ]
    for label, values in timing_sections:
        printTimingStats(label, values)

    waits = loadRuntimeWaits()
    if waits:
        print("  Constant waits currently configured:")
        for name, value in waits:
            if value is None:
                print(f"    {name}=<unavailable>")
            else:
                print(f"    {name}={value:.0f}ms")

    statuses: dict[str, int] = {}
    for p in pieces:
        s = p.get("classification_status", "unknown")
        statuses[s] = statuses.get(s, 0) + 1
    print(f"  Classification breakdown: {statuses}")

    categories: dict[str, int] = {}
    for p in pieces:
        cat = p.get("category_id") or "none"
        categories[cat] = categories.get(cat, 0) + 1
    top_cats = sorted(categories.items(), key=lambda x: -x[1])[:10]
    if top_cats:
        print(f"  Top categories: {dict(top_cats)}")

    runtime_stats = record.get("runtime_stats_final")
    if isinstance(runtime_stats, dict):
        feeder = runtime_stats.get("feeder", {})
        timings = runtime_stats.get("timings", {})
        ch2_to_ch1 = timings.get("ch2_clear_to_ch1_pulse_s", {})
        ch3_to_ch2 = timings.get("ch3_clear_to_ch2_pulse_s", {})
        held = timings.get("ch3_precise_held_s", {})
        print("  Feeder runtime stats (final snapshot):")
        if isinstance(ch2_to_ch1, dict) and ch2_to_ch1.get("n", 0) > 0:
            print(
                f"    ch2 clear->ch1 pulse: avg={ch2_to_ch1.get('avg_s', 0.0):.2f}s med={ch2_to_ch1.get('med_s', 0.0):.2f}s p90={ch2_to_ch1.get('p90_s', 0.0):.2f}s n={int(ch2_to_ch1.get('n', 0))}"
            )
        if isinstance(ch3_to_ch2, dict) and ch3_to_ch2.get("n", 0) > 0:
            print(
                f"    ch3 clear->ch2 pulse: avg={ch3_to_ch2.get('avg_s', 0.0):.2f}s med={ch3_to_ch2.get('med_s', 0.0):.2f}s p90={ch3_to_ch2.get('p90_s', 0.0):.2f}s n={int(ch3_to_ch2.get('n', 0))}"
            )
        if isinstance(held, dict) and held.get("n", 0) > 0:
            print(
                f"    ch3 precise held: avg={held.get('avg_s', 0.0):.2f}s med={held.get('med_s', 0.0):.2f}s p90={held.get('p90_s', 0.0):.2f}s n={int(held.get('n', 0))}"
            )
        if isinstance(feeder, dict):
            held_count = feeder.get("ch3_precise_held_count")
            if isinstance(held_count, int):
                print(f"    ch3 precise held count: {held_count}")


def reportAggregate(records: list[dict]) -> None:
    total_pieces = 0
    total_active = 0.0
    total_distributed = 0
    all_throughputs: list[float] = []

    for record in records:
        pieces = record["pieces"]
        total_pieces += len(pieces)
        total_active += calcActiveSeconds(record)

        distributed = [p for p in pieces if p.get("distributed_at")]
        total_distributed += len(distributed)

        if len(distributed) >= 2:
            sorted_d = sorted(distributed, key=lambda p: p["distributed_at"])
            span = sorted_d[-1]["distributed_at"] - sorted_d[0]["distributed_at"]
            if span > 0:
                all_throughputs.append((len(distributed) - 1) / (span / 60.0))

    print(f"\n=== Aggregate ({len(records)} runs) ===")
    print(f"  Total pieces: {total_pieces}")
    print(f"  Total distributed: {total_distributed}")
    print(f"  Total active time: {formatDuration(total_active)}")

    if total_active > 0 and total_distributed > 0:
        print(f"  Overall throughput (active): {total_distributed / (total_active / 60.0):.1f} pieces/min")
    if all_throughputs:
        avg_tp = sum(all_throughputs) / len(all_throughputs)
        print(f"  Avg run throughput: {avg_tp:.1f} pieces/min")
        print(f"  Best run throughput: {max(all_throughputs):.1f} pieces/min")


def main() -> None:
    parser = argparse.ArgumentParser(description="Sort run report")
    parser.add_argument("--latest", action="store_true", help="show latest run only")
    parser.add_argument("--run-id", type=str, help="show specific run by id")
    parser.add_argument("--all", action="store_true", help="show all runs individually")
    parser.add_argument("file", nargs="?", help="path to a specific record file")
    args = parser.parse_args()

    if args.file:
        record = loadRecord(Path(args.file))
        reportSingle(record)
        return

    paths = getAllRecordPaths()
    if not paths:
        print(f"No records found in {RECORDS_DIR}")
        sys.exit(1)

    if args.run_id:
        matching = [p for p in paths if args.run_id in p.name]
        if not matching:
            print(f"No record found matching run id: {args.run_id}")
            sys.exit(1)
        record = loadRecord(matching[0])
        reportSingle(record)
        return

    if args.latest:
        record = loadRecord(paths[-1])
        reportSingle(record)
        return

    if args.all:
        records = [loadRecord(p) for p in paths]
        for record in records:
            reportSingle(record)
            print()
        reportAggregate(records)
        return

    records = [loadRecord(p) for p in paths]
    reportAggregate(records)
    print("\nLatest run:")
    reportSingle(records[-1])


if __name__ == "__main__":
    main()
