from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


CLIENT_ROOT = Path(__file__).resolve().parents[1]
OUTPUT_ROOT = CLIENT_ROOT / "blob" / "local_detection_models"


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate a comparison report across multiple detector runs.")
    parser.add_argument(
        "run_dirs",
        nargs="*",
        help="Paths to run directories containing run.json. If omitted, scans --output-root for recent runs.",
    )
    parser.add_argument("--output-root", default=str(OUTPUT_ROOT))
    parser.add_argument("--latest", type=int, default=5, help="When auto-scanning, use the N most recent runs.")
    parser.add_argument("--output", default="", help="Output path for the report JSON. Defaults to stdout.")
    return parser.parse_args()


def _read_json(path: Path) -> dict[str, Any] | None:
    try:
        return json.loads(path.read_text())
    except Exception:
        return None


def _extract_metrics(run_dir: Path, run_data: dict[str, Any]) -> dict[str, Any]:
    model_family = run_data.get("model_family", "unknown")
    runtime = run_data.get("runtime", "unknown")
    run_name = run_data.get("run_name", run_dir.name)
    training = run_data.get("training") if isinstance(run_data.get("training"), dict) else {}
    train_args = run_data.get("train_args") if isinstance(run_data.get("train_args"), dict) else {}
    splits = run_data.get("splits") if isinstance(run_data.get("splits"), dict) else {}
    sample_count = run_data.get("sample_count", 0)

    imgsz = train_args.get("imgsz") or train_args.get("image_size") or "N/A"
    epochs = train_args.get("epochs", "N/A")

    # Extract validation metrics
    validation = training.get("validation") if isinstance(training.get("validation"), dict) else {}
    best_val = validation.get("best_validation_metrics") if isinstance(validation.get("best_validation_metrics"), dict) else {}
    mAP50 = best_val.get("mAP50")
    mAP50_95 = best_val.get("mAP50_95")
    precision = best_val.get("precision")
    recall = best_val.get("recall")

    # Extract benchmark test metrics
    benchmark = training.get("benchmark") if isinstance(training.get("benchmark"), dict) else {}
    test_metrics = benchmark.get("test_metrics") if isinstance(benchmark.get("test_metrics"), dict) else {}
    decision_match = test_metrics.get("decision_match_rate")
    exact_count_match = test_metrics.get("exact_count_match_rate")
    single_mean_iou = test_metrics.get("single_mean_iou")
    multi_detect = test_metrics.get("multi_detect_rate")
    avg_latency = test_metrics.get("avg_latency_ms")
    confidence = benchmark.get("selected_confidence_threshold") or test_metrics.get("confidence_threshold")

    # Count test samples
    test_split = splits.get("test") if isinstance(splits.get("test"), dict) else {}
    test_samples = test_split.get("samples") or test_metrics.get("samples", 0)

    return {
        "run_dir": str(run_dir),
        "run_name": run_name,
        "model_family": model_family,
        "runtime": runtime,
        "imgsz": imgsz,
        "epochs": epochs,
        "sample_count": sample_count,
        "test_samples": test_samples,
        "confidence_threshold": confidence,
        "mAP50": mAP50,
        "mAP50_95": mAP50_95,
        "precision": precision,
        "recall": recall,
        "decision_match_rate": decision_match,
        "exact_count_match_rate": exact_count_match,
        "single_mean_iou": single_mean_iou,
        "multi_detect_rate": multi_detect,
        "avg_latency_ms": avg_latency,
    }


def _format_pct(value: Any) -> str:
    if value is None:
        return "N/A"
    return f"{float(value) * 100:.1f}%"


def _format_float(value: Any, decimals: int = 3) -> str:
    if value is None:
        return "N/A"
    return f"{float(value):.{decimals}f}"


def _format_ms(value: Any) -> str:
    if value is None:
        return "N/A"
    return f"{float(value):.1f} ms"


def _generate_markdown(candidates: list[dict[str, Any]]) -> str:
    lines: list[str] = []
    lines.append("# Detector Candidate Comparison Report")
    lines.append("")
    lines.append(f"**Candidates evaluated:** {len(candidates)}")
    if candidates:
        lines.append(f"**Dataset samples:** {candidates[0].get('sample_count', 'N/A')}")
    lines.append("")

    # Main comparison table
    lines.append("## Test Set Results")
    lines.append("")
    lines.append("| Candidate | Family | ImgSz | Decision Match | Count Match | Single IoU | Multi Detect | Latency |")
    lines.append("|-----------|--------|-------|---------------|-------------|------------|--------------|---------|")
    for c in candidates:
        name = c["run_name"]
        if len(name) > 40:
            name = name[:37] + "..."
        lines.append(
            f"| {name} | {c['model_family']} | {c['imgsz']} | "
            f"{_format_pct(c['decision_match_rate'])} | {_format_pct(c['exact_count_match_rate'])} | "
            f"{_format_float(c['single_mean_iou'])} | {_format_pct(c['multi_detect_rate'])} | "
            f"{_format_ms(c['avg_latency_ms'])} |"
        )
    lines.append("")

    # YOLO-specific metrics
    yolo_candidates = [c for c in candidates if c.get("mAP50") is not None]
    if yolo_candidates:
        lines.append("## YOLO/EfficientDet Validation Metrics")
        lines.append("")
        lines.append("| Candidate | mAP50 | mAP50-95 | Precision | Recall |")
        lines.append("|-----------|-------|----------|-----------|--------|")
        for c in yolo_candidates:
            lines.append(
                f"| {c['run_name'][:40]} | {_format_pct(c['mAP50'])} | {_format_pct(c['mAP50_95'])} | "
                f"{_format_pct(c['precision'])} | {_format_pct(c['recall'])} |"
            )
        lines.append("")

    # Ranking
    ranked_decision = sorted(
        [c for c in candidates if c.get("decision_match_rate") is not None],
        key=lambda c: float(c["decision_match_rate"]),
        reverse=True,
    )
    if ranked_decision:
        lines.append("## Rankings")
        lines.append("")
        lines.append("### By Decision Match Rate (empty/single/multi classification)")
        for i, c in enumerate(ranked_decision, 1):
            lines.append(f"{i}. **{c['run_name'][:50]}** - {_format_pct(c['decision_match_rate'])}")
        lines.append("")

    ranked_latency = sorted(
        [c for c in candidates if c.get("avg_latency_ms") is not None],
        key=lambda c: float(c["avg_latency_ms"]),
    )
    if ranked_latency:
        lines.append("### By Inference Latency (fastest first)")
        for i, c in enumerate(ranked_latency, 1):
            lines.append(f"{i}. **{c['run_name'][:50]}** - {_format_ms(c['avg_latency_ms'])}")
        lines.append("")

    ranked_iou = sorted(
        [c for c in candidates if c.get("single_mean_iou") is not None],
        key=lambda c: float(c["single_mean_iou"]),
        reverse=True,
    )
    if ranked_iou:
        lines.append("### By Single-Piece Bounding Box IoU")
        for i, c in enumerate(ranked_iou, 1):
            lines.append(f"{i}. **{c['run_name'][:50]}** - {_format_float(c['single_mean_iou'])}")
        lines.append("")

    return "\n".join(lines)


def main() -> int:
    args = _parse_args()

    run_dirs: list[Path] = []
    if args.run_dirs:
        run_dirs = [Path(d).resolve() for d in args.run_dirs]
    else:
        output_root = Path(args.output_root).resolve()
        if output_root.exists():
            all_dirs = sorted(
                (d for d in output_root.iterdir() if d.is_dir() and (d / "run.json").exists()),
                key=lambda d: d.name,
                reverse=True,
            )
            run_dirs = all_dirs[: args.latest]

    if not run_dirs:
        raise SystemExit("No run directories found.")

    candidates: list[dict[str, Any]] = []
    for run_dir in run_dirs:
        run_json = run_dir / "run.json"
        run_data = _read_json(run_json)
        if run_data is None:
            print(f"Warning: could not read {run_json}, skipping.")
            continue
        candidates.append(_extract_metrics(run_dir, run_data))

    candidates.sort(key=lambda c: c.get("run_name", ""))

    report = {
        "candidates": candidates,
        "markdown": _generate_markdown(candidates),
    }

    if args.output:
        output_path = Path(args.output).resolve()
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(report, indent=2))
        print(f"Report written to {output_path}")
        md_path = output_path.with_suffix(".md")
        md_path.write_text(report["markdown"])
        print(f"Markdown report written to {md_path}")
    else:
        print(report["markdown"])
        print("\n---\nJSON:\n")
        print(json.dumps(report, indent=2))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
