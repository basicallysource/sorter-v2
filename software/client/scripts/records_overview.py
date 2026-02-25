import argparse
import json
from datetime import datetime
from pathlib import Path
from statistics import mean, median


DEFAULT_RECORDS_PATH = Path(__file__).resolve().parents[1] / "blob" / "records.json"


def loadRecords(path: Path) -> dict:
    if not path.exists():
        return {"runs": {}}
    try:
        with open(path, "r") as f:
            data = json.load(f)
    except Exception:
        return {"runs": {}}
    if not isinstance(data, dict):
        return {"runs": {}}
    runs = data.get("runs")
    if not isinstance(runs, dict):
        data["runs"] = {}
    return data


def fmtSeconds(seconds: float | None) -> str:
    if seconds is None:
        return "-"
    if seconds < 1:
        return f"{seconds * 1000:.0f}ms"
    if seconds < 60:
        return f"{seconds:.2f}s"
    return f"{seconds / 60:.2f}m"


def fmtRatePpm(count: int, duration_s: float | None) -> str:
    if duration_s is None or duration_s <= 0:
        return "-"
    return f"{(count / duration_s) * 60.0:.2f}"


def statsSummary(values: list[float]) -> dict:
    if not values:
        return {}
    sorted_values = sorted(values)
    n = len(sorted_values)
    p95_idx = min(n - 1, max(0, int(round(0.95 * (n - 1)))))
    return {
        "count": n,
        "avg": mean(sorted_values),
        "median": median(sorted_values),
        "min": sorted_values[0],
        "max": sorted_values[-1],
        "p95": sorted_values[p95_idx],
    }


def percentileValue(values: list[float], p: float) -> float | None:
    if not values:
        return None
    sorted_values = sorted(values)
    idx = min(len(sorted_values) - 1, max(0, int(round(p * (len(sorted_values) - 1)))))
    return sorted_values[idx]


def printTimingLine(label: str, values: list[float]) -> None:
    summary = statsSummary(values)
    if not summary:
        print(f"  {label}: -")
        return
    print(
        f"  {label}: n={summary['count']} avg={fmtSeconds(summary['avg'])} "
        f"med={fmtSeconds(summary['median'])} p95={fmtSeconds(summary['p95'])} "
        f"min={fmtSeconds(summary['min'])} max={fmtSeconds(summary['max'])}"
    )


def minuteBuckets(event_times: list[float], start_time_s: float, end_time_s: float) -> list[dict]:
    if end_time_s < start_time_s:
        return []
    total_minutes = int((end_time_s - start_time_s) // 60) + 1
    buckets = [
        {
            "minute_index": i,
            "start_s": start_time_s + i * 60.0,
            "end_s": start_time_s + (i + 1) * 60.0,
            "count": 0,
        }
        for i in range(total_minutes)
    ]
    for ts in event_times:
        if ts < start_time_s:
            idx = 0
        else:
            idx = int((ts - start_time_s) // 60)
        if idx < 0:
            idx = 0
        if idx >= total_minutes:
            idx = total_minutes - 1
        buckets[idx]["count"] += 1
    return buckets


def minuteRateSummary(event_times: list[float], start_time_s: float | None, end_time_s: float | None) -> dict:
    if not event_times or start_time_s is None or end_time_s is None:
        return {}

    buckets = minuteBuckets(event_times, start_time_s, end_time_s)
    if not buckets:
        return {}

    counts_all = [b["count"] for b in buckets]
    counts_nonzero = [b["count"] for b in buckets if b["count"] > 0]

    fastest_bucket = max(buckets, key=lambda b: b["count"])
    slowest_bucket = min(buckets, key=lambda b: b["count"])

    slowest_nonzero_bucket = None
    nonzero_buckets = [b for b in buckets if b["count"] > 0]
    if nonzero_buckets:
        slowest_nonzero_bucket = min(nonzero_buckets, key=lambda b: b["count"])

    return {
        "bucket_count": len(buckets),
        "idle_minutes": sum(1 for c in counts_all if c == 0),
        "all_minutes": statsSummary(counts_all),
        "active_minutes": statsSummary(counts_nonzero),
        "all_minutes_p10": percentileValue(counts_all, 0.10),
        "all_minutes_p90": percentileValue(counts_all, 0.90),
        "active_minutes_p10": percentileValue(counts_nonzero, 0.10),
        "active_minutes_p90": percentileValue(counts_nonzero, 0.90),
        "fastest_bucket": fastest_bucket,
        "slowest_bucket": slowest_bucket,
        "slowest_nonzero_bucket": slowest_nonzero_bucket,
    }


def printMinuteRateLine(label: str, rate_summary: dict) -> None:
    if not rate_summary:
        print(f"  {label}: -")
        return

    all_minutes = rate_summary.get("all_minutes", {})
    active_minutes = rate_summary.get("active_minutes", {})
    fastest_bucket = rate_summary["fastest_bucket"]
    slowest_bucket = rate_summary["slowest_bucket"]
    slowest_nonzero_bucket = rate_summary["slowest_nonzero_bucket"]

    print(
        f"  {label}: buckets={rate_summary['bucket_count']} "
        f"idle_minutes={rate_summary['idle_minutes']}"
    )

    if all_minutes:
        print(
            f"    all minutes: avg={all_minutes['avg']:.2f} med={all_minutes['median']:.2f} "
            f"p10={rate_summary['all_minutes_p10']:.2f} p90={rate_summary['all_minutes_p90']:.2f} "
            f"p95={all_minutes['p95']:.2f} min={all_minutes['min']:.2f} max={all_minutes['max']:.2f}"
        )
    else:
        print("    all minutes: -")

    if active_minutes:
        print(
            f"    active minutes (>0): avg={active_minutes['avg']:.2f} med={active_minutes['median']:.2f} "
            f"p10={rate_summary['active_minutes_p10']:.2f} p90={rate_summary['active_minutes_p90']:.2f} "
            f"p95={active_minutes['p95']:.2f} min={active_minutes['min']:.2f} max={active_minutes['max']:.2f}"
        )
    else:
        print("    active minutes (>0): -")

    print(
        f"    fastest minute: m{fastest_bucket['minute_index']} count={fastest_bucket['count']}"
    )
    print(
        f"    slowest minute: m{slowest_bucket['minute_index']} count={slowest_bucket['count']}"
    )
    if slowest_nonzero_bucket is not None:
        print(
            f"    slowest active minute: m{slowest_nonzero_bucket['minute_index']} "
            f"count={slowest_nonzero_bucket['count']}"
        )


def getRunSortKey(run_id: str, run_record: dict) -> tuple:
    started_at = run_record.get("started_at")
    updated_at = run_record.get("updated_at")
    return (
        started_at if isinstance(started_at, (int, float)) else -1,
        updated_at if isinstance(updated_at, (int, float)) else -1,
        run_id,
    )


def selectRuns(runs: dict, run_id: str | None, latest: bool) -> list[tuple[str, dict]]:
    run_items = [(k, v) for k, v in runs.items() if isinstance(v, dict)]
    run_items.sort(key=lambda item: getRunSortKey(item[0], item[1]))

    if run_id is not None:
        if run_id not in runs or not isinstance(runs[run_id], dict):
            return []
        return [(run_id, runs[run_id])]

    if latest:
        return [run_items[-1]] if run_items else []

    return run_items


def summarizeRun(run_id: str, run_record: dict) -> dict:
    known_objects = run_record.get("known_objects", {})
    if not isinstance(known_objects, dict):
        known_objects = {}

    object_records = [v for v in known_objects.values() if isinstance(v, dict)]

    created_times = []
    updated_times = []
    classified_complete_times = []
    classified_success_times = []
    category_assigned_times = []
    distributed_times = []

    created_to_classify_complete_s = []
    created_to_classify_success_s = []
    created_to_category_s = []
    created_to_distributed_s = []
    classify_complete_to_distributed_s = []
    category_to_distributed_s = []

    classified_success_count = 0
    classified_failure_count = 0
    classified_unknown_count = 0
    classified_not_found_count = 0
    classification_done_count = 0
    category_assigned_count = 0
    distributed_count = 0

    for obj in object_records:
        created_at = obj.get("created_at")
        updated_at = obj.get("updated_at")
        classification_completed_at = obj.get("classification_completed_at")
        classified_at = obj.get("classified_at")
        category_assigned_at = obj.get("category_assigned_at")
        distributed_at = obj.get("distributed_at")
        classification_successful = obj.get("classification_successful")

        if isinstance(created_at, (int, float)):
            created_times.append(created_at)
        if isinstance(updated_at, (int, float)):
            updated_times.append(updated_at)
        if isinstance(classification_completed_at, (int, float)):
            classified_complete_times.append(classification_completed_at)
            classification_done_count += 1
        if isinstance(classified_at, (int, float)):
            classified_success_times.append(classified_at)
        if isinstance(category_assigned_at, (int, float)):
            category_assigned_times.append(category_assigned_at)
            category_assigned_count += 1
        if isinstance(distributed_at, (int, float)):
            distributed_times.append(distributed_at)
            distributed_count += 1

        if classification_successful is True:
            classified_success_count += 1
        elif classification_successful is False:
            classified_failure_count += 1

        cls_status = obj.get("classification_status")
        if cls_status == "unknown":
            classified_unknown_count += 1
        elif cls_status == "not_found":
            classified_not_found_count += 1

        if isinstance(created_at, (int, float)) and isinstance(
            classification_completed_at, (int, float)
        ):
            created_to_classify_complete_s.append(classification_completed_at - created_at)
        if isinstance(created_at, (int, float)) and isinstance(classified_at, (int, float)):
            created_to_classify_success_s.append(classified_at - created_at)
        if isinstance(created_at, (int, float)) and isinstance(
            category_assigned_at, (int, float)
        ):
            created_to_category_s.append(category_assigned_at - created_at)
        if isinstance(created_at, (int, float)) and isinstance(distributed_at, (int, float)):
            created_to_distributed_s.append(distributed_at - created_at)
        if isinstance(classification_completed_at, (int, float)) and isinstance(
            distributed_at, (int, float)
        ):
            classify_complete_to_distributed_s.append(
                distributed_at - classification_completed_at
            )
        if isinstance(category_assigned_at, (int, float)) and isinstance(
            distributed_at, (int, float)
        ):
            category_to_distributed_s.append(distributed_at - category_assigned_at)

    run_started_at = run_record.get("started_at")
    run_updated_at = run_record.get("updated_at")

    timeline_candidates = []
    for timestamp in created_times:
        timeline_candidates.append(timestamp)
    if isinstance(run_started_at, (int, float)):
        timeline_candidates.append(run_started_at)
    run_start_s = min(timeline_candidates) if timeline_candidates else None

    end_candidates = []
    for timestamp in updated_times + distributed_times + classified_complete_times:
        end_candidates.append(timestamp)
    if isinstance(run_updated_at, (int, float)):
        end_candidates.append(run_updated_at)
    run_end_s = max(end_candidates) if end_candidates else None

    active_duration_s = None
    if (
        isinstance(run_start_s, (int, float))
        and isinstance(run_end_s, (int, float))
        and run_end_s >= run_start_s
    ):
        active_duration_s = run_end_s - run_start_s

    distributed_window_s = None
    if len(distributed_times) >= 2:
        distributed_window_s = max(distributed_times) - min(distributed_times)

    return {
        "run_id": run_id,
        "objects_total": len(object_records),
        "classification_done_count": classification_done_count,
        "classified_success_count": classified_success_count,
        "classified_failure_count": classified_failure_count,
        "classified_unknown_count": classified_unknown_count,
        "classified_not_found_count": classified_not_found_count,
        "category_assigned_count": category_assigned_count,
        "distributed_count": distributed_count,
        "run_start_s": run_start_s,
        "run_end_s": run_end_s,
        "active_duration_s": active_duration_s,
        "distributed_window_s": distributed_window_s,
        "created_times": created_times,
        "classified_complete_times": classified_complete_times,
        "classified_success_times": classified_success_times,
        "category_assigned_times": category_assigned_times,
        "distributed_times": distributed_times,
        "created_to_classify_complete_s": created_to_classify_complete_s,
        "created_to_classify_success_s": created_to_classify_success_s,
        "created_to_category_s": created_to_category_s,
        "created_to_distributed_s": created_to_distributed_s,
        "classify_complete_to_distributed_s": classify_complete_to_distributed_s,
        "category_to_distributed_s": category_to_distributed_s,
        "distributed_ppm_1m": minuteRateSummary(distributed_times, run_start_s, run_end_s),
        "created_ppm_1m": minuteRateSummary(created_times, run_start_s, run_end_s),
        "classification_done_ppm_1m": minuteRateSummary(
            classified_complete_times, run_start_s, run_end_s
        ),
    }


def fmtTimestamp(ts: float | None) -> str:
    if ts is None:
        return "-"
    return datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S")


def fmtDuration(seconds: float | None) -> str:
    if seconds is None:
        return "-"
    if seconds < 60:
        return f"{seconds:.0f}s"
    m = int(seconds // 60)
    s = int(seconds % 60)
    if m < 60:
        return f"{m}m {s}s"
    h = m // 60
    m = m % 60
    return f"{h}h {m}m {s}s"


def successRate(success: int, total: int) -> str:
    if total == 0:
        return "-"
    return f"{success / total * 100:.0f}%"


def printRunSummary(summary: dict) -> None:
    run_id = summary["run_id"]
    total = summary["objects_total"]
    distributed = summary["distributed_count"]
    success = summary["classified_success_count"]
    fail = summary["classified_failure_count"]
    classify_done = summary["classification_done_count"]
    cat_assigned = summary["category_assigned_count"]
    duration = summary["active_duration_s"]
    start = summary["run_start_s"]
    end = summary["run_end_s"]

    print(f"{'=' * 60}")
    print(f"  Run: {run_id}")
    print(f"  Started: {fmtTimestamp(start)}   Ended: {fmtTimestamp(end)}")
    print(f"  Duration: {fmtDuration(duration)}")
    print(f"{'=' * 60}")

    print(f"\n  Pieces")
    print(f"    detected: {total}   distributed: {distributed}   in-flight: {total - distributed}")
    unknown = summary.get("classified_unknown_count", 0)
    not_found = summary.get("classified_not_found_count", 0)
    print(
        f"    classified: {classify_done} ({successRate(success, classify_done)} success)"
        f"   success: {success}   fail: {fail}"
    )
    print(f"    unknown: {unknown}   not found: {not_found}")
    print(f"    category assigned: {cat_assigned}")

    print(f"\n  Throughput")
    dist_ppm = fmtRatePpm(distributed, duration)
    created_ppm = fmtRatePpm(total, duration)
    dist_window_ppm = fmtRatePpm(distributed, summary["distributed_window_s"])
    print(f"    overall:  {dist_ppm} distributed/min   {created_ppm} detected/min")
    print(f"    distribution window: {dist_window_ppm} distributed/min")

    dist_rate = summary.get("distributed_ppm_1m", {})
    if dist_rate:
        active = dist_rate.get("active_minutes", {})
        if active:
            print(
                f"    per-minute (active): avg={active['avg']:.1f} med={active['median']:.1f} "
                f"best={active['max']:.0f} worst={active['min']:.0f}"
            )
        print(f"    idle minutes: {dist_rate.get('idle_minutes', 0)} / {dist_rate.get('bucket_count', 0)}")

    print(f"\n  Latencies")
    printTimingLine(
        "detect -> classify done",
        summary["created_to_classify_complete_s"],
    )
    printTimingLine(
        "detect -> classify success",
        summary["created_to_classify_success_s"],
    )
    printTimingLine("detect -> category assigned", summary["created_to_category_s"])
    printTimingLine("detect -> distributed", summary["created_to_distributed_s"])
    printTimingLine(
        "classify done -> distributed",
        summary["classify_complete_to_distributed_s"],
    )
    printTimingLine("category -> distributed", summary["category_to_distributed_s"])

    print(f"\n  Minute-by-Minute Detail")
    printMinuteRateLine("distributed/min", summary["distributed_ppm_1m"])
    printMinuteRateLine("detected/min", summary["created_ppm_1m"])
    printMinuteRateLine(
        "classified/min",
        summary["classification_done_ppm_1m"],
    )


def combineSummaries(summaries: list[dict]) -> dict:
    if not summaries:
        return {}

    combined = {
        "run_id": "ALL_SELECTED",
        "objects_total": 0,
        "classification_done_count": 0,
        "classified_success_count": 0,
        "classified_failure_count": 0,
        "classified_unknown_count": 0,
        "classified_not_found_count": 0,
        "category_assigned_count": 0,
        "distributed_count": 0,
        "run_start_s": None,
        "run_end_s": None,
        "active_duration_s": 0.0,
        "distributed_window_s": None,
        "created_to_classify_complete_s": [],
        "created_to_classify_success_s": [],
        "created_to_category_s": [],
        "created_to_distributed_s": [],
        "classify_complete_to_distributed_s": [],
        "category_to_distributed_s": [],
        "distributed_ppm_1m": {},
        "created_ppm_1m": {},
        "classification_done_ppm_1m": {},
    }

    all_distributed_times = []

    for summary in summaries:
        combined["objects_total"] += summary["objects_total"]
        combined["classification_done_count"] += summary["classification_done_count"]
        combined["classified_success_count"] += summary["classified_success_count"]
        combined["classified_failure_count"] += summary["classified_failure_count"]
        combined["classified_unknown_count"] += summary.get("classified_unknown_count", 0)
        combined["classified_not_found_count"] += summary.get("classified_not_found_count", 0)
        combined["category_assigned_count"] += summary["category_assigned_count"]
        combined["distributed_count"] += summary["distributed_count"]

        if summary["active_duration_s"] is not None:
            combined["active_duration_s"] += summary["active_duration_s"]

        s_start = summary.get("run_start_s")
        s_end = summary.get("run_end_s")
        if isinstance(s_start, (int, float)):
            if combined["run_start_s"] is None or s_start < combined["run_start_s"]:
                combined["run_start_s"] = s_start
        if isinstance(s_end, (int, float)):
            if combined["run_end_s"] is None or s_end > combined["run_end_s"]:
                combined["run_end_s"] = s_end

        for key in (
            "created_to_classify_complete_s",
            "created_to_classify_success_s",
            "created_to_category_s",
            "created_to_distributed_s",
            "classify_complete_to_distributed_s",
            "category_to_distributed_s",
        ):
            combined[key].extend(summary[key])

        all_distributed_times.extend(summary["distributed_times"])

    if len(all_distributed_times) >= 2:
        combined["distributed_window_s"] = max(all_distributed_times) - min(all_distributed_times)

    return combined


def printRunList(runs: dict, n: int) -> None:
    run_items = [(k, v) for k, v in runs.items() if isinstance(v, dict)]
    # sort by started_at descending to get most recent
    run_items.sort(key=lambda item: getRunSortKey(item[0], item[1]), reverse=True)
    run_items = run_items[:n]

    summaries = [summarizeRun(rid, rec) for rid, rec in run_items]
    # sort by duration descending
    summaries.sort(key=lambda s: s["active_duration_s"] or 0, reverse=True)

    # header
    print(f"{'#':<4} {'duration':<10} {'pieces':<8} {'dist':<6} {'ppm':<8} {'success':<9} {'started':<20} {'run_id'}")
    print("-" * 100)

    for i, s in enumerate(summaries, 1):
        dur = fmtDuration(s["active_duration_s"])
        ppm = fmtRatePpm(s["distributed_count"], s["active_duration_s"])
        started = fmtTimestamp(s["run_start_s"])
        total = s["objects_total"]
        distributed = s["distributed_count"]
        classify_done = s["classification_done_count"]
        success = s["classified_success_count"]
        srate = successRate(success, classify_done) if classify_done else "-"
        print(f"{i:<4} {dur:<10} {total:<8} {distributed:<6} {ppm:<8} {srate:<9} {started:<20} {s['run_id']}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--path", default=str(DEFAULT_RECORDS_PATH))
    parser.add_argument("--run-id", default=None)
    parser.add_argument("--latest", action="store_true")
    parser.add_argument("--list", type=int, default=None, nargs="?", const=0, metavar="N",
                        help="list the N most recent runs sorted by duration (all if N omitted)")
    parser.add_argument("--no-per-run", action="store_true")
    args = parser.parse_args()

    records_path = Path(args.path)
    data = loadRecords(records_path)
    runs = data.get("runs", {})

    if not isinstance(runs, dict) or not runs:
        print(f"No runs found in {records_path}")
        return

    if args.list is not None:
        printRunList(runs, args.list or len(runs))
        return

    selected_runs = selectRuns(runs, args.run_id, args.latest)
    if not selected_runs:
        if args.run_id:
            print(f"Run not found: {args.run_id}")
        else:
            print(f"No runs found in {records_path}")
        return

    summaries = [summarizeRun(run_id, run_record) for run_id, run_record in selected_runs]

    print(f"Records file: {records_path}")
    print(f"Selected runs: {len(summaries)}")

    if not args.no_per_run:
        for summary in summaries:
            print("")
            printRunSummary(summary)

    if len(summaries) > 1:
        combined = combineSummaries(summaries)
        print("")
        print("Aggregate")
        printRunSummary(combined)


if __name__ == "__main__":
    main()
