"""
Benchmark all local detection models against Gemini ground truth.

Picks N random samples that have Gemini distill labels, runs every registered
local detector on them, computes IoU-based similarity, and writes an HTML report.

Usage:
    uv run python scripts/benchmark_detector_models.py --num-samples 50
"""
from __future__ import annotations

import argparse
import base64
import json
import glob
import os
import random
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

import cv2
import numpy as np


BASE = Path(__file__).resolve().parent.parent
SESSION = "20260329-141728-9cf6b1f4"
META_DIR = BASE / "blob" / "classification_training" / SESSION / "metadata"
MODELS_DIR = BASE / "blob" / "local_detection_models"
RETEST_SCRIPT = BASE / "scripts" / "retest_local_detector_sample.py"


def iou(a: list[int], b: list[int]) -> float:
    x1 = max(a[0], b[0])
    y1 = max(a[1], b[1])
    x2 = min(a[2], b[2])
    y2 = min(a[3], b[3])
    inter = max(0, x2 - x1) * max(0, y2 - y1)
    area_a = max(0, a[2] - a[0]) * max(0, a[3] - a[1])
    area_b = max(0, b[2] - b[0]) * max(0, b[3] - b[1])
    union = area_a + area_b - inter
    return inter / union if union > 0 else 0.0


def bbox_match_score(gt_bboxes: list[list[int]], pred_bboxes: list[list[int]], iou_thresh: float = 0.3) -> dict:
    """Compute matching metrics between ground truth and predicted bboxes."""
    if not gt_bboxes and not pred_bboxes:
        return {"precision": 1.0, "recall": 1.0, "count_match": True, "avg_iou": 1.0, "count_diff": 0}
    if not gt_bboxes:
        return {"precision": 0.0, "recall": 1.0, "count_match": len(pred_bboxes) == 0, "avg_iou": 0.0, "count_diff": len(pred_bboxes)}
    if not pred_bboxes:
        return {"precision": 1.0, "recall": 0.0, "count_match": False, "avg_iou": 0.0, "count_diff": len(gt_bboxes)}

    matched_gt = set()
    matched_pred = set()
    ious = []

    for pi, pb in enumerate(pred_bboxes):
        best_iou = 0.0
        best_gi = -1
        for gi, gb in enumerate(gt_bboxes):
            if gi in matched_gt:
                continue
            v = iou(pb, gb)
            if v > best_iou:
                best_iou = v
                best_gi = gi
        if best_iou >= iou_thresh and best_gi >= 0:
            matched_gt.add(best_gi)
            matched_pred.add(pi)
            ious.append(best_iou)

    precision = len(matched_pred) / len(pred_bboxes) if pred_bboxes else 1.0
    recall = len(matched_gt) / len(gt_bboxes) if gt_bboxes else 1.0
    avg_iou = float(np.mean(ious)) if ious else 0.0

    return {
        "precision": precision,
        "recall": recall,
        "count_match": len(pred_bboxes) == len(gt_bboxes),
        "avg_iou": avg_iou,
        "count_diff": len(pred_bboxes) - len(gt_bboxes),
    }


def discover_models() -> list[dict]:
    models = []
    for rj_path in sorted(glob.glob(str(MODELS_DIR / "20260330-*" / "run.json"))):
        d = json.loads(open(rj_path).read())
        model_dir = os.path.dirname(rj_path)
        family = d.get("model_family", "?")
        runtime = d.get("runtime", "?")
        name = d.get("run_name", os.path.basename(model_dir))
        exports_dir = os.path.join(model_dir, "exports")

        # Always prefer ONNX for benchmarking (pyncnn not available locally)
        model_file = None
        onnx_path = os.path.join(exports_dir, "best.onnx")
        if os.path.exists(onnx_path):
            model_file = onnx_path
        else:
            for f in sorted(glob.glob(os.path.join(exports_dir, "*.onnx"))):
                model_file = f
                break

        if not model_file:
            continue

        # For benchmark, we always use ONNX runtime
        bench_runtime = "onnx"

        imgsz = d.get("inference", {}).get("imgsz") or d.get("train_args", {}).get("imgsz", 320)
        models.append({
            "name": name,
            "family": family,
            "runtime": bench_runtime,
            "original_runtime": runtime,
            "model_file": model_file,
            "imgsz": imgsz,
            "run_json": rj_path,
            "dir": model_dir,
        })
    return models


def pick_samples(n: int, seed: int = 42) -> list[dict]:
    rng = random.Random(seed)
    files = glob.glob(str(META_DIR / "*.json"))
    eligible = []
    for f in files:
        try:
            d = json.loads(open(f).read())
        except Exception:
            continue
        dr = d.get("distill_result")
        if d.get("detection_algorithm") == "gemini_sam" and dr and dr.get("result_json"):
            rj = dr["result_json"]
            if os.path.exists(rj):
                eligible.append(d)
    rng.shuffle(eligible)
    return eligible[:n]


def load_gemini_gt(sample: dict) -> list[list[int]]:
    rj = sample["distill_result"]["result_json"]
    d = json.loads(open(rj).read())
    bboxes = []
    for det in d.get("detections", []):
        bb = det.get("bbox")
        if bb and len(bb) == 4:
            bboxes.append([int(v) for v in bb])
    return bboxes


def run_model_on_sample(model: dict, sample: dict, output_dir: Path) -> dict:
    sample_id = sample["sample_id"]
    model_name = model["name"].replace(" ", "_").replace("/", "_")
    image_path = sample["input_image"]

    result_json = output_dir / f"{sample_id}__{model_name}.json"
    overlay_image = output_dir / f"{sample_id}__{model_name}.jpg"

    cmd = [
        sys.executable, str(RETEST_SCRIPT),
        "--input", image_path,
        "--model", model["model_file"],
        "--result-json", str(result_json),
        "--overlay-image", str(overlay_image),
        "--imgsz", str(model["imgsz"]),
        "--conf", "0.25",
    ]

    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        if result_json.exists():
            return json.loads(result_json.read_text())
        else:
            return {"ok": False, "error": proc.stderr[:500] if proc.stderr else "no output"}
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": "timeout"}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def img_to_base64(path: str, max_width: int = 300) -> str:
    if not os.path.exists(path):
        return ""
    img = cv2.imread(path)
    if img is None:
        return ""
    h, w = img.shape[:2]
    if w > max_width:
        scale = max_width / w
        img = cv2.resize(img, (max_width, int(h * scale)))
    _, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 75])
    return "data:image/jpeg;base64," + base64.b64encode(buf).decode()


def generate_html(samples: list[dict], models: list[dict], results: dict, gemini_gt: dict, output_dir: Path) -> str:
    """Generate the full HTML benchmark report."""

    # Compute per-model aggregate stats
    model_stats = {}
    for model in models:
        mn = model["name"]
        model_stats[mn] = {
            "precisions": [], "recalls": [], "avg_ious": [],
            "count_matches": 0, "total": 0,
            "inference_ms": [], "found_count": 0,
        }

    for sample in samples:
        sid = sample["sample_id"]
        gt_bboxes = gemini_gt[sid]
        for model in models:
            mn = model["name"]
            r = results.get((sid, mn))
            if not r or not r.get("ok"):
                continue
            pred_bboxes = r.get("candidate_bboxes", [])
            ms = bbox_match_score(gt_bboxes, pred_bboxes)
            stats = model_stats[mn]
            stats["precisions"].append(ms["precision"])
            stats["recalls"].append(ms["recall"])
            stats["avg_ious"].append(ms["avg_iou"])
            stats["count_matches"] += int(ms["count_match"])
            stats["total"] += 1
            stats["found_count"] += int(r.get("found", False))
            if r.get("inference_ms"):
                stats["inference_ms"].append(r["inference_ms"])

    # Build summary table
    summary_rows = []
    for model in models:
        mn = model["name"]
        s = model_stats[mn]
        if s["total"] == 0:
            continue
        avg_prec = np.mean(s["precisions"]) * 100
        avg_recall = np.mean(s["recalls"]) * 100
        avg_iou = np.mean(s["avg_ious"]) * 100
        count_acc = s["count_matches"] / s["total"] * 100
        det_rate = s["found_count"] / s["total"] * 100
        avg_ms = np.mean(s["inference_ms"]) if s["inference_ms"] else 0
        avg_fps = 1000.0 / avg_ms if avg_ms > 0 else 0
        f1 = 2 * avg_prec * avg_recall / (avg_prec + avg_recall) if (avg_prec + avg_recall) > 0 else 0

        summary_rows.append({
            "name": mn,
            "family": model["family"],
            "runtime": model["runtime"],
            "original_runtime": model.get("original_runtime", model["runtime"]),
            "imgsz": model["imgsz"],
            "precision": avg_prec,
            "recall": avg_recall,
            "f1": f1,
            "avg_iou": avg_iou,
            "count_acc": count_acc,
            "det_rate": det_rate,
            "avg_ms": avg_ms,
            "fps": avg_fps,
            "total": s["total"],
        })

    summary_rows.sort(key=lambda r: r["f1"], reverse=True)

    # Build HTML
    html_parts = []
    html_parts.append("""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Detector Benchmark Report</title>
<style>
* { box-sizing: border-box; margin: 0; padding: 0; }
body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background: #0d1117; color: #c9d1d9; padding: 20px; }
h1 { color: #58a6ff; margin-bottom: 8px; }
h2 { color: #58a6ff; margin: 24px 0 12px; }
.subtitle { color: #8b949e; margin-bottom: 20px; }
table { border-collapse: collapse; width: 100%; margin-bottom: 24px; }
th, td { padding: 8px 12px; text-align: left; border: 1px solid #30363d; }
th { background: #161b22; color: #58a6ff; font-weight: 600; position: sticky; top: 0; }
tr:hover { background: #161b22; }
.good { color: #3fb950; }
.ok { color: #d29922; }
.bad { color: #f85149; }
.metric { font-weight: 600; }
.grid-container { overflow-x: auto; }
.grid-table { border-collapse: collapse; }
.grid-table th, .grid-table td { padding: 4px; border: 1px solid #30363d; text-align: center; vertical-align: top; }
.grid-table th { background: #161b22; font-size: 11px; min-width: 160px; max-width: 200px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.grid-table td img { display: block; border-radius: 4px; }
.grid-table .row-header { text-align: left; font-size: 11px; min-width: 100px; background: #161b22; }
.cell-info { font-size: 10px; color: #8b949e; margin-top: 2px; }
.badge { display: inline-block; padding: 2px 6px; border-radius: 3px; font-size: 11px; font-weight: 600; }
.badge-ncnn { background: #1f6feb33; color: #58a6ff; }
.badge-onnx { background: #3fb95033; color: #3fb950; }
.legend { background: #161b22; padding: 12px; border-radius: 6px; margin-bottom: 20px; font-size: 13px; }
.legend span { margin-right: 16px; }
</style>
</head>
<body>
<h1>Detector Benchmark Report</h1>
<p class="subtitle">""")

    html_parts.append(f"{len(samples)} samples &times; {len(models)} models &mdash; Ground truth: Gemini SAM distillation</p>")

    # Legend
    html_parts.append("""
<div class="legend">
  <strong>Metrics vs Gemini:</strong>
  <span class="good">■ &ge;80%</span>
  <span class="ok">■ 50-80%</span>
  <span class="bad">■ &lt;50%</span>
  &nbsp;|&nbsp;
  <span>Precision = correct pred / total pred</span>
  <span>Recall = matched GT / total GT</span>
  <span>Count Acc = exact bbox count match rate</span>
</div>
""")

    # Summary table
    html_parts.append("<h2>Model Summary</h2>")
    html_parts.append("""<table>
<tr>
  <th>#</th><th>Model</th><th>Type</th><th>ImgSz</th>
  <th>Precision</th><th>Recall</th><th>F1</th><th>Avg IoU</th>
  <th>Count Acc</th><th>Det Rate</th><th>Avg ms</th><th>FPS</th>
</tr>""")

    def color_class(v):
        if v >= 80:
            return "good"
        elif v >= 50:
            return "ok"
        return "bad"

    for i, row in enumerate(summary_rows, 1):
        orig_rt = row.get("original_runtime", row["runtime"])
        rt_badge = f'<span class="badge badge-{orig_rt}">{orig_rt}</span>'
        html_parts.append(f"""<tr>
  <td>{i}</td>
  <td><strong>{row['name']}</strong></td>
  <td>{row['family']} {rt_badge}</td>
  <td>{row['imgsz']}</td>
  <td class="metric {color_class(row['precision'])}">{row['precision']:.1f}%</td>
  <td class="metric {color_class(row['recall'])}">{row['recall']:.1f}%</td>
  <td class="metric {color_class(row['f1'])}">{row['f1']:.1f}%</td>
  <td class="metric {color_class(row['avg_iou'])}">{row['avg_iou']:.1f}%</td>
  <td class="metric {color_class(row['count_acc'])}">{row['count_acc']:.1f}%</td>
  <td class="metric {color_class(row['det_rate'])}">{row['det_rate']:.1f}%</td>
  <td>{row['avg_ms']:.1f}</td>
  <td>{row['fps']:.1f}</td>
</tr>""")

    html_parts.append("</table>")

    # Visual grid
    html_parts.append("<h2>Visual Comparison Grid</h2>")
    html_parts.append('<div class="grid-container"><table class="grid-table">')

    # Header row
    html_parts.append("<tr><th>Sample</th><th>Gemini GT</th>")
    for model in models:
        label = model["name"][:25]
        html_parts.append(f"<th>{label}<br><small>{model['runtime']} {model['imgsz']}</small></th>")
    html_parts.append("</tr>")

    # One row per sample
    for sample in samples:
        sid = sample["sample_id"]
        gt_bboxes = gemini_gt[sid]

        # Gemini overlay
        gemini_overlay = sample.get("distill_result", {}).get("overlay_image", "")
        gemini_b64 = img_to_base64(gemini_overlay) if gemini_overlay else ""

        html_parts.append(f'<tr><td class="row-header">{sid[:20]}<br><small>{len(gt_bboxes)} pieces</small></td>')
        if gemini_b64:
            html_parts.append(f'<td><img src="{gemini_b64}" width="150"></td>')
        else:
            html_parts.append("<td>-</td>")

        for model in models:
            mn = model["name"]
            r = results.get((sid, mn))
            if not r or not r.get("ok"):
                html_parts.append('<td><small class="bad">error</small></td>')
                continue

            overlay_path = r.get("overlay_image", "")
            b64 = img_to_base64(overlay_path) if overlay_path else ""
            pred_bboxes = r.get("candidate_bboxes", [])
            ms = bbox_match_score(gt_bboxes, pred_bboxes)
            iou_pct = ms["avg_iou"] * 100
            inf_ms = r.get("inference_ms", 0)

            if b64:
                html_parts.append(f'<td><img src="{b64}" width="150">')
            else:
                html_parts.append("<td>")

            count_color = "good" if ms["count_match"] else ("ok" if abs(ms["count_diff"]) <= 1 else "bad")
            html_parts.append(f'<div class="cell-info">'
                              f'<span class="{color_class(iou_pct)}">IoU:{iou_pct:.0f}%</span> '
                              f'<span class="{count_color}">n={len(pred_bboxes)}</span> '
                              f'{inf_ms:.0f}ms</div></td>')

        html_parts.append("</tr>")

    html_parts.append("</table></div>")
    html_parts.append("</body></html>")

    return "\n".join(html_parts)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--num-samples", type=int, default=50)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()

    print(f"Discovering models...")
    models = discover_models()
    print(f"Found {len(models)} usable models")
    for m in models:
        print(f"  {m['family']}/{m['runtime']} {m['imgsz']}px  {m['name']}")

    print(f"\nPicking {args.num_samples} random Gemini samples...")
    samples = pick_samples(args.num_samples, seed=args.seed)
    print(f"Selected {len(samples)} samples")

    # Load Gemini ground truth
    gemini_gt = {}
    for s in samples:
        gemini_gt[s["sample_id"]] = load_gemini_gt(s)

    # Create output dir
    output_dir = BASE / "blob" / "benchmark_reports" / f"benchmark-{int(time.time())}"
    output_dir.mkdir(parents=True, exist_ok=True)
    overlays_dir = output_dir / "overlays"
    overlays_dir.mkdir(exist_ok=True)

    # Run all models on all samples
    results = {}
    total = len(samples) * len(models)
    done = 0
    for si, sample in enumerate(samples):
        sid = sample["sample_id"]
        for mi, model in enumerate(models):
            mn = model["name"]
            done += 1
            print(f"  [{done}/{total}] {sid[:16]}.. × {mn[:30]}", end="", flush=True)
            r = run_model_on_sample(model, sample, overlays_dir)
            results[(sid, mn)] = r
            status = "ok" if r.get("ok") else "FAIL"
            ms = r.get("inference_ms", 0)
            n = r.get("bbox_count", 0)
            print(f"  → {status} {n} boxes {ms:.0f}ms")

    # Generate HTML
    print("\nGenerating HTML report...")
    html = generate_html(samples, models, results, gemini_gt, output_dir)
    report_path = output_dir / "report.html"
    report_path.write_text(html)
    print(f"\nReport saved to: {report_path}")

    # Also save raw data
    raw_data = {
        "samples": [s["sample_id"] for s in samples],
        "models": [{"name": m["name"], "family": m["family"], "runtime": m["runtime"], "imgsz": m["imgsz"]} for m in models],
        "results": {f"{sid}__{mn}": r for (sid, mn), r in results.items()},
    }
    (output_dir / "benchmark_data.json").write_text(json.dumps(raw_data, indent=2, default=str))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
