import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

RECORDS_DIR = Path(__file__).parent.parent / "blob" / "records"


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
    classified = [p for p in pieces if p.get("classified_at")]

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

    for p in pieces:
        if p.get("distributed_at") and p.get("created_at"):
            creation_to_distributed.append(p["distributed_at"] - p["created_at"])
        if p.get("classified_at") and p.get("created_at"):
            classification_times.append(p["classified_at"] - p["created_at"])
        if p.get("distributed_at") and p.get("distributing_at"):
            distribution_times.append(p["distributed_at"] - p["distributing_at"])

    if creation_to_distributed:
        avg = sum(creation_to_distributed) / len(creation_to_distributed)
        print(f"  Avg total time (created->distributed): {avg:.2f}s")
    if classification_times:
        avg = sum(classification_times) / len(classification_times)
        print(f"  Avg classification time (created->classified): {avg:.2f}s")
    if distribution_times:
        avg = sum(distribution_times) / len(distribution_times)
        print(f"  Avg chute time (distributing->distributed): {avg:.2f}s")

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
