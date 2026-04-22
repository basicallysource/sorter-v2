from __future__ import annotations

import json
from html import escape
from pathlib import Path
from typing import Any

import cv2

from training.reports import benchmark as bench


TRAINING_ROOT = Path(__file__).resolve().parents[3]
REPORTS_OUT_DIR = TRAINING_ROOT / "reports_out"
BLOB_DIR = REPORTS_OUT_DIR
OUTPUT_PATH = REPORTS_OUT_DIR / "device_benchmarks" / "platform_matrix_report_20260406.html"

RUNS: list[dict[str, str]] = [
    {
        "key": "local_cpu",
        "label": "Local Mac Mini M4 · CPU (ONNX)",
        "short": "Mac CPU",
        "dir": "device_benchmarks/local_m4_cpu_20260406",
    },
    {
        "key": "local_coreml",
        "label": "Local Mac Mini M4 · CoreML",
        "short": "Mac CoreML",
        "dir": "device_benchmarks/local_m4_coreml_20260406",
    },
    {
        "key": "orangepi_cpu",
        "label": "Orange Pi 5 · CPU (ONNX)",
        "short": "Orange Pi CPU",
        "dir": "device_benchmarks/orangepi_cpu_onnx_20260406",
    },
    {
        "key": "orangepi_rknn",
        "label": "Orange Pi 5 · NPU (RKNN)",
        "short": "Orange Pi RKNN",
        "dir": "device_benchmarks/orangepi_npu_rknn_20260406",
    },
    {
        "key": "spencer_cpu",
        "label": "Spencer Pi 5 · CPU (ONNXRuntime 1.23.2)",
        "short": "Spencer Pi CPU",
        "dir": "device_benchmarks/pi5_aihat_cpu_ort123",
    },
    {
        "key": "spencer_hailo",
        "label": "Spencer Pi 5 · AI HAT (Hailo-8)",
        "short": "Spencer Pi Hailo",
        "dir": "device_benchmarks/spencer_pi5_hailo",
    },
]

COMPARES: dict[str, str] = {
    "local_coreml": "device_benchmarks/local_cpu_vs_coreml_20260406.json",
    "orangepi_cpu": "device_benchmarks/local_cpu_vs_orangepi_cpu_onnx_20260406.json",
    "orangepi_rknn": "device_benchmarks/local_cpu_vs_orangepi_npu_rknn_20260406.json",
    "spencer_cpu": "device_benchmarks/local_cpu_vs_spencer_pi_cpu_ort123_20260406.json",
    "spencer_hailo": "device_benchmarks/local_cpu_vs_spencer_pi_hailo_20260406.json",
}

RUNTIME_COLORS: dict[str, tuple[int, int, int]] = {
    "gt": (0, 180, 90),
    "local_cpu": (0, 114, 255),
    "local_coreml": (132, 56, 255),
    "orangepi_cpu": (209, 105, 0),
    "orangepi_rknn": (220, 38, 38),
    "spencer_cpu": (14, 116, 144),
    "spencer_hailo": (124, 58, 237),
}


def _load_result_set(relative_dir: str) -> dict[str, dict[str, Any]]:
    result_dir = (BLOB_DIR / relative_dir).resolve()
    result_paths = sorted(result_dir.glob("*.json"))
    return bench._result_map_from_paths(result_paths)


def _load_compare_map(relative_path: str) -> dict[str, dict[str, Any]]:
    payload = json.loads((BLOB_DIR / relative_path).read_text())
    return {
        str(item["model_id"]): item
        for item in payload.get("shared_models", [])
        if isinstance(item, dict) and isinstance(item.get("model_id"), str)
    }


def _fmt_float(value: Any, digits: int = 2) -> str:
    if value is None:
        return "n/a"
    return f"{float(value):.{digits}f}"


def _fmt_pct(value: Any) -> str:
    if value is None:
        return "n/a"
    return f"{float(value) * 100:.1f}%"


def _row_map(result_payload: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        str(row["image"]): row
        for row in result_payload.get("per_sample", [])
        if isinstance(row, dict) and row.get("ok") and isinstance(row.get("image"), str)
    }


def _gt_boxes(manifest_sample: dict[str, Any], width: int, height: int) -> list[list[int]]:
    boxes: list[list[int]] = []
    normalized = manifest_sample.get("gt_boxes_normalized")
    if not isinstance(normalized, list):
        return boxes
    for box in normalized:
        if isinstance(box, list) and len(box) >= 4:
            boxes.append(bench._normalized_to_xyxy([float(value) for value in box[:4]], width, height))
    return boxes


def _pred_boxes(row: dict[str, Any]) -> list[list[int]]:
    boxes: list[list[int]] = []
    for box in row.get("candidate_bboxes", []):
        if isinstance(box, list) and len(box) >= 4:
            boxes.append([int(value) for value in box[:4]])
    return boxes


def _pred_scores(row: dict[str, Any]) -> list[float]:
    return [float(score) for score in row.get("scores", []) if isinstance(score, (int, float))]


def _select_showcase_images(
    model_id: str,
    results_by_run: dict[str, dict[str, dict[str, Any]]],
    compare_by_run: dict[str, dict[str, dict[str, Any]]],
    limit: int = 4,
) -> list[str]:
    selected: list[str] = []
    orange_compare = compare_by_run.get("orangepi_rknn", {}).get(model_id, {})
    for item in orange_compare.get("differing_images", []):
        image = item.get("image")
        if isinstance(image, str) and image not in selected:
            selected.append(image)
        if len(selected) >= max(0, limit - 1):
            break

    local_rows = results_by_run["local_cpu"][model_id]["rows"]
    for image, local_row in local_rows.items():
        same_everywhere = True
        for run in RUNS[1:]:
            other_row = results_by_run[run["key"]][model_id]["rows"].get(image)
            if other_row is None:
                same_everywhere = False
                break
            if (
                int(other_row.get("pred_count", -1)) != int(local_row.get("pred_count", -2))
                or str(other_row.get("pred_decision")) != str(local_row.get("pred_decision"))
            ):
                same_everywhere = False
                break
        if same_everywhere and image not in selected:
            selected.append(image)
            break

    for image in local_rows:
        if image not in selected:
            selected.append(image)
        if len(selected) >= limit:
            break
    return selected[:limit]


def _summary_rows_html(
    model_id: str,
    results_by_run: dict[str, dict[str, dict[str, Any]]],
    compare_by_run: dict[str, dict[str, dict[str, Any]]],
) -> str:
    rows: list[str] = []
    for run in RUNS:
        payload = results_by_run[run["key"]][model_id]["payload"]
        summary = payload["summary"]
        compare = compare_by_run.get(run["key"], {}).get(model_id)
        rows.append(
            "<tr>"
            f"<td>{escape(run['label'])}</td>"
            f"<td>{escape(str(summary.get('runtime', 'n/a')))}</td>"
            f"<td>{_fmt_float(summary.get('avg_latency_ms'))} ms</td>"
            f"<td>{_fmt_float(summary.get('avg_fps'))}</td>"
            f"<td>{_fmt_pct(compare.get('same_decision_rate') if compare else None)}</td>"
            f"<td>{_fmt_pct(compare.get('same_pred_count_rate') if compare else None)}</td>"
            f"<td>{_fmt_float(compare.get('top1_left_vs_right_mean_iou') if compare else None, 3)}</td>"
            "</tr>"
        )
    return "\n".join(rows)


def _concurrency_card(
    title: str,
    entries: list[dict[str, Any]],
    *,
    worker_counts: list[int],
) -> str:
    models = sorted({str(entry.get("model")) for entry in entries if str(entry.get("model")) != "mixed"})
    blocks: list[str] = [f"<section class=\"subcard\"><h3>{escape(title)}</h3>"]
    for model in models:
        blocks.append(f"<h4>{escape(model.title())}</h4>")
        blocks.append(
            "<table><thead><tr><th>Workers</th><th>Combined FPS</th><th>Mean Worker FPS</th><th>Mean Worker Latency</th></tr></thead><tbody>"
        )
        model_entries = [entry for entry in entries if entry.get("model") == model]
        entry_map = {int(entry.get("workers", 0)): entry for entry in model_entries}
        for workers in worker_counts:
            entry = entry_map.get(workers)
            blocks.append(
                "<tr>"
                f"<td>{workers}</td>"
                f"<td>{_fmt_float(entry.get('combined_fps') if entry else None)}</td>"
                f"<td>{_fmt_float(entry.get('mean_worker_fps') if entry else None)}</td>"
                f"<td>{_fmt_float(entry.get('mean_worker_latency_ms') if entry else None)} ms</td>"
                "</tr>"
            )
        blocks.append("</tbody></table>")
    blocks.append("</section>")
    return "\n".join(blocks)


def _render_overlay_tile(
    *,
    image_path: Path,
    boxes: list[list[int]],
    title: str,
    color: tuple[int, int, int],
    output_path: Path,
    scores: list[float] | None = None,
) -> str:
    overlay = bench._draw_overlay(
        image_path,
        boxes,
        title=title,
        color=color,
        label_prefix="Box",
        scores=scores,
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(output_path), overlay)
    return output_path.name


def main() -> int:
    bundle_dir = (BLOB_DIR / "device_benchmarks" / "chamber_zone_pair_bundle").resolve()
    manifest_index = bench._load_manifest_index(bundle_dir)
    image_dir = bundle_dir / "images"

    results_by_run: dict[str, dict[str, dict[str, Any]]] = {}
    for run in RUNS:
        result_map = _load_result_set(run["dir"])
        results_by_run[run["key"]] = {
            model_id: {
                "payload": payload,
                "rows": _row_map(payload),
            }
            for model_id, payload in result_map.items()
        }

    compare_by_run = {key: _load_compare_map(path) for key, path in COMPARES.items()}
    orange_parallel = json.loads((BLOB_DIR / "device_benchmarks" / "concurrency" / "orangepi_parallel_npu_20260406.json").read_text())
    hailo_parallel = json.loads((BLOB_DIR / "device_benchmarks" / "concurrency" / "hailo_parallel_20260406.json").read_text())

    asset_dir = OUTPUT_PATH.parent / f"{OUTPUT_PATH.stem}_assets"
    asset_dir.mkdir(parents=True, exist_ok=True)
    asset_rel = asset_dir.name

    model_sections: list[str] = []
    shared_model_ids = sorted(results_by_run["local_cpu"].keys())
    for model_id in shared_model_ids:
        model_label = results_by_run["local_cpu"][model_id]["payload"]["summary"]["model_label"]
        showcase_images = _select_showcase_images(model_id, results_by_run, compare_by_run, limit=4)
        sample_blocks: list[str] = []
        for image_name in showcase_images:
            image_path = image_dir / image_name
            source = cv2.imread(str(image_path), cv2.IMREAD_COLOR)
            if source is None:
                continue
            height, width = source.shape[:2]
            manifest_sample = manifest_index[image_name]
            tiles: list[str] = []

            gt_output = asset_dir / model_id / Path(image_name).stem / "gt.jpg"
            gt_name = _render_overlay_tile(
                image_path=image_path,
                boxes=_gt_boxes(manifest_sample, width, height),
                title="Reference Boxes",
                color=RUNTIME_COLORS["gt"],
                output_path=gt_output,
            )
            tiles.append(
                f"""
                <figure>
                  <img src="{asset_rel}/{escape(str((gt_output.relative_to(asset_dir)).as_posix()))}" alt="Reference overlay for {escape(image_name)}" />
                  <figcaption>Reference</figcaption>
                </figure>
                """
            )

            for run in RUNS:
                row = results_by_run[run["key"]][model_id]["rows"][image_name]
                output_path = asset_dir / model_id / Path(image_name).stem / f"{run['key']}.jpg"
                output_name = _render_overlay_tile(
                    image_path=image_path,
                    boxes=_pred_boxes(row),
                    title=f"{run['short']} · {int(row.get('pred_count', 0))} boxes",
                    color=RUNTIME_COLORS[run["key"]],
                    output_path=output_path,
                    scores=_pred_scores(row),
                )
                tiles.append(
                    f"""
                    <figure>
                      <img src="{asset_rel}/{escape(str((output_path.relative_to(asset_dir)).as_posix()))}" alt="{escape(run['label'])} overlay for {escape(image_name)}" />
                      <figcaption>{escape(run['short'])} · {escape(str(row.get('pred_decision')))} · {_fmt_float(row.get('latency_ms'))} ms</figcaption>
                    </figure>
                    """
                )

            sample_blocks.append(
                f"""
                <article class="sample-card">
                  <div class="sample-head">
                    <strong>{escape(image_name)}</strong>
                    <span>GT: {escape(str(manifest_sample.get('decision')))} · {escape(str(manifest_sample.get('detection_count')))} boxes</span>
                  </div>
                  <div class="tile-grid">
                    {''.join(tiles)}
                  </div>
                </article>
                """
            )

        model_sections.append(
            f"""
            <section class="card">
              <h2>{escape(model_label)}</h2>
              <p class="muted">Single-run comparison against the same 50-image chamber-zone bundle.</p>
              <table class="summary-table">
                <thead>
                  <tr>
                    <th>Run</th>
                    <th>Runtime</th>
                    <th>Avg Latency</th>
                    <th>Avg FPS</th>
                    <th>Decision Match vs Mac CPU</th>
                    <th>Pred Count Match vs Mac CPU</th>
                    <th>Top-1 IoU vs Mac CPU</th>
                  </tr>
                </thead>
                <tbody>
                  {_summary_rows_html(model_id, results_by_run, compare_by_run)}
                </tbody>
              </table>
              <div class="sample-group">
                <h3>Overlay Comparison</h3>
                <p class="muted">Three disagreement-heavy samples plus one consensus sample.</p>
                {''.join(sample_blocks)}
              </div>
            </section>
            """
        )

    html = f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Detector Platform Report · 2026-04-06</title>
  <style>
    :root {{
      color-scheme: light;
      --bg: #efe7da;
      --panel: #fffdf9;
      --ink: #211d18;
      --muted: #655d55;
      --line: #d9cdbf;
      --accent: #9a3412;
      --accent-soft: #f5ded3;
      --good: #166534;
      --warn: #92400e;
      --bad: #b91c1c;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      font-family: "IBM Plex Sans", "Avenir Next", sans-serif;
      color: var(--ink);
      background:
        radial-gradient(circle at top left, rgba(154, 52, 18, 0.08), transparent 28%),
        linear-gradient(180deg, #f3ece2 0%, #faf7f1 100%);
    }}
    main {{
      max-width: 1500px;
      margin: 0 auto;
      padding: 28px 22px 56px;
    }}
    h1 {{ margin: 0 0 10px; font-size: 2.2rem; }}
    h2 {{ margin: 0 0 10px; font-size: 1.55rem; }}
    h3 {{ margin: 24px 0 10px; font-size: 1.05rem; }}
    h4 {{ margin: 20px 0 10px; font-size: 1rem; }}
    p {{ line-height: 1.5; }}
    .intro {{
      max-width: 980px;
      color: var(--muted);
      margin-bottom: 24px;
    }}
    .note-grid {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(240px, 1fr));
      gap: 12px;
      margin: 18px 0 28px;
    }}
    .note {{
      background: var(--accent-soft);
      border: 1px solid rgba(154, 52, 18, 0.15);
      border-radius: 16px;
      padding: 14px 16px;
      color: var(--muted);
    }}
    .card, .subcard {{
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 20px;
      padding: 20px;
      box-shadow: 0 14px 38px rgba(46, 30, 15, 0.06);
      margin-bottom: 22px;
    }}
    .muted {{ color: var(--muted); }}
    .parallel-grid {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(380px, 1fr));
      gap: 16px;
      margin-bottom: 24px;
    }}
    table {{
      width: 100%;
      border-collapse: collapse;
      font-size: 0.93rem;
    }}
    th, td {{
      text-align: left;
      padding: 9px 10px;
      border-bottom: 1px solid var(--line);
      vertical-align: top;
    }}
    th {{
      color: var(--muted);
      font-size: 0.82rem;
      text-transform: uppercase;
      letter-spacing: 0.04em;
    }}
    .summary-table {{ margin-top: 14px; }}
    .sample-group {{ margin-top: 22px; }}
    .sample-card {{
      border-top: 1px solid var(--line);
      padding-top: 18px;
      margin-top: 18px;
    }}
    .sample-head {{
      display: flex;
      justify-content: space-between;
      gap: 12px;
      align-items: baseline;
      margin-bottom: 10px;
    }}
    .sample-head span {{ color: var(--muted); font-size: 0.92rem; }}
    .tile-grid {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
      gap: 12px;
    }}
    figure {{
      margin: 0;
      background: #f8f3eb;
      border: 1px solid var(--line);
      border-radius: 14px;
      overflow: hidden;
    }}
    img {{
      display: block;
      width: 100%;
      height: auto;
      background: #fff;
    }}
    figcaption {{
      padding: 10px 12px;
      border-top: 1px solid var(--line);
      color: var(--muted);
      font-size: 0.88rem;
    }}
    code {{
      font-family: "IBM Plex Mono", "SFMono-Regular", monospace;
      background: rgba(33, 29, 24, 0.05);
      padding: 0 0.3em;
      border-radius: 0.25em;
    }}
    @media (max-width: 900px) {{
      .sample-head {{
        flex-direction: column;
        align-items: flex-start;
      }}
    }}
  </style>
</head>
<body>
  <main>
    <h1>Detector Platform Comparison Report</h1>
    <p class="intro">Generated on April 6, 2026 from the shared 50-image chamber-zone benchmark bundle. The local Mac CPU run is used as the quality reference. Orange Pi CPU and Spencer Pi CPU reproduce that reference exactly on this bundle; the main quality differences show up on the Orange Pi RKNN path and, to a smaller extent, the Spencer Pi Hailo path.</p>

    <div class="note-grid">
      <div class="note"><strong>Mac CoreML:</strong> Measured through the ONNX Runtime <code>CoreMLExecutionProvider</code>, not through a separately exported <code>.mlpackage</code>.</div>
      <div class="note"><strong>Orange Pi RKNN:</strong> Uses the pre-existing RKNN artifacts found on <code>/root/bench/models</code>. The RKNN compiler was not installed on the device, so those files were not regenerated from the current chamber-zone ONNX exports during this run.</div>
      <div class="note"><strong>Spencer Pi Hailo:</strong> Uses the freshly compiled Hailo-8 <code>HEF</code> files produced from our chamber-zone YOLO11s and NanoDet exports.</div>
      <div class="note"><strong>Hailo parallelism:</strong> Multi-process scaling was measured with a direct shared-service Python worker because the installed <code>hailortcli benchmark</code> fails under <code>--multi-process-service</code> on this stack.</div>
    </div>

    <section class="card">
      <h2>NPU Parallelism</h2>
      <p class="muted">Orange Pi scales by distributing work across three physical RK3588 NPU cores. The Hailo AI HAT can multiplex multiple jobs, but total throughput stays roughly flat and is sliced across workers.</p>
      <div class="parallel-grid">
        {_concurrency_card("Orange Pi 5 · RKNN NPU", orange_parallel["entries"], worker_counts=[1, 3])}
        {_concurrency_card("Spencer Pi 5 · Hailo-8", hailo_parallel["entries"], worker_counts=[1, 2, 3])}
      </div>
    </section>

    {''.join(model_sections)}
  </main>
</body>
</html>
"""

    OUTPUT_PATH.write_text(html)
    print(OUTPUT_PATH)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
