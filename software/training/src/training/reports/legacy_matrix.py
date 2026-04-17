from __future__ import annotations

import json
from html import escape
from pathlib import Path
from typing import Any


TRAINING_ROOT = Path(__file__).resolve().parents[3]
REPORTS_OUT_DIR = TRAINING_ROOT / "reports_out"
BLOB_DIR = REPORTS_OUT_DIR
OUTPUT_PATH = REPORTS_OUT_DIR / "device_benchmarks" / "legacy_parallel_matrix_report_20260406.html"


LEGACY_TABLES: dict[str, dict[str, Any]] = {
    "nanodet": {
        "title": "NanoDet-1.5x-416",
        "columns": ["M5 Pro CPU", "M4 Mini CPU", "CM5 ONNX", "CM5 NCNN", "CM5 NPU", "Pi 4 CPU"],
        "rows": {
            "1x": [130, 83, 20, 20, 40, 2],
            "2x": [191, 93, 16, 13, 75, 2],
            "3x": [242, 116, 20, 21, 102, 2],
        },
    },
    "yolo": {
        "title": "YOLO11s-320",
        "columns": ["M5 Pro CPU", "M5 Pro CoreML", "M4 Mini CPU", "M4 CoreML", "CM5 ONNX", "CM5 NCNN", "CM5 NPU", "Pi 4 CPU"],
        "rows": {
            "1x": [104, 440, 62, 370, 12, 19, 40, 1],
            "2x": [140, 766, 58, 581, 15, 29, 75, 1],
            "3x": [None, 876, None, 715, None, None, 98, None],
        },
    },
}


def _load_json(relative_path: str) -> dict[str, Any]:
    return json.loads((BLOB_DIR / relative_path).read_text())


def _entry_map(payload: dict[str, Any]) -> dict[tuple[str, int], dict[str, Any]]:
    mapping: dict[tuple[str, int], dict[str, Any]] = {}
    for entry in payload.get("entries", []):
        model = str(entry.get("model"))
        workers = int(entry.get("workers", 0))
        mapping[(model, workers)] = entry
    return mapping


def _compare_map(relative_path: str) -> dict[str, dict[str, Any]]:
    payload = _load_json(relative_path)
    return {
        str(item["model_id"]): item
        for item in payload.get("shared_models", [])
        if isinstance(item, dict) and isinstance(item.get("model_id"), str)
    }


def _fmt_cell(value: Any) -> str:
    if value is None:
        return "--"
    if isinstance(value, float):
        return str(int(round(value)))
    return escape(str(value))


def _fmt_pct(value: Any) -> str:
    if value is None:
        return "n/a"
    return f"{float(value) * 100:.0f}%"


def _fmt_iou(value: Any) -> str:
    if value is None:
        return "n/a"
    return f"{float(value):.3f}"


def _render_table(
    *,
    title: str,
    legacy_columns: list[str],
    legacy_rows: dict[str, list[Any]],
    cpu_entries: dict[tuple[str, int], dict[str, Any]],
    hailo_entries: dict[tuple[str, int], dict[str, Any]],
    model_key: str,
) -> str:
    headers = ["Instances", *legacy_columns, "Pi 5 CPU", "Pi 5 Hailo"]
    lines: list[str] = [
        f"<section class=\"matrix-block\"><h2>{escape(title)}</h2>",
        "<div class=\"table-wrap\"><table><thead><tr>",
        "".join(f"<th>{escape(header)}</th>" for header in headers),
        "</tr></thead><tbody>",
    ]
    for row_label, values in legacy_rows.items():
        workers = int(row_label.rstrip("x"))
        cpu_value = cpu_entries.get((model_key, workers), {}).get("combined_fps")
        hailo_value = hailo_entries.get((model_key, workers), {}).get("combined_fps")
        row_cells = [row_label, *values, cpu_value, hailo_value]
        lines.append("<tr>" + "".join(f"<td>{_fmt_cell(cell)}</td>" for cell in row_cells) + "</tr>")
    lines.append("</tbody></table></div></section>")
    return "\n".join(lines)


def _quality_rows_html(
    *,
    model_id: str,
    model_label: str,
    pi_cpu_compare: dict[str, Any] | None,
    hailo_compare: dict[str, Any] | None,
) -> str:
    rows: list[str] = []
    for runtime_label, compare in [
        ("Pi 5 CPU (ONNX)", pi_cpu_compare),
        ("Pi 5 Hailo-8", hailo_compare),
    ]:
        rows.append(
            "<tr>"
            f"<td>{escape(model_label)}</td>"
            f"<td>{escape(runtime_label)}</td>"
            f"<td>{_fmt_pct(compare.get('same_decision_rate') if compare else None)}</td>"
            f"<td>{_fmt_pct(compare.get('same_pred_count_rate') if compare else None)}</td>"
            f"<td>{_fmt_iou(compare.get('top1_left_vs_right_mean_iou') if compare else None)}</td>"
            "</tr>"
        )
    return "\n".join(rows)


def _detail_card(title: str, entry: dict[str, Any] | None) -> str:
    if not entry:
        return (
            f"<article class=\"detail-card\"><h3>{escape(title)}</h3>"
            "<p class=\"muted\">No measurement available.</p></article>"
        )
    worker_parts = []
    for worker in entry.get("workers_detail", []):
        worker_parts.append(
            f"{escape(str(worker.get('worker', '?')))}: "
            f"{float(worker.get('fps', 0.0)):.1f} FPS @ {float(worker.get('avg_latency_ms', 0.0)):.1f} ms"
        )
    return (
        f"<article class=\"detail-card\"><h3>{escape(title)}</h3>"
        f"<p><strong>Combined:</strong> {float(entry.get('combined_fps', 0.0)):.1f} FPS</p>"
        f"<p><strong>Mean worker:</strong> {float(entry.get('mean_worker_fps', 0.0)):.1f} FPS, "
        f"{float(entry.get('mean_worker_latency_ms', 0.0)):.1f} ms</p>"
        f"<p class=\"muted\">{'<br />'.join(worker_parts)}</p></article>"
    )


def main() -> int:
    pi_cpu_parallel = _load_json("device_benchmarks/concurrency/spencer_pi_cpu_parallel_20260406.json")
    hailo_parallel = _load_json("device_benchmarks/concurrency/hailo_parallel_20260406.json")
    pi_cpu_entries = _entry_map(pi_cpu_parallel)
    hailo_entries = _entry_map(hailo_parallel)

    pi_cpu_compare = _compare_map("device_benchmarks/local_cpu_vs_spencer_pi_cpu_ort123_20260406.json")
    hailo_compare = _compare_map("device_benchmarks/local_cpu_vs_spencer_pi_hailo_20260406.json")

    model_meta = {
        "nanodet": {
            "id": "20260331-zone-classification-chamber-nanodet",
            "label": "NanoDet-1.5x-416",
        },
        "yolo": {
            "id": "20260331-zone-classification-chamber-yolo11s",
            "label": "YOLO11s-320",
        },
    }

    quality_rows = []
    for model_key, meta in model_meta.items():
        model_id = meta["id"]
        quality_rows.append(
            _quality_rows_html(
                model_id=model_id,
                model_label=str(meta["label"]),
                pi_cpu_compare=pi_cpu_compare.get(model_id),
                hailo_compare=hailo_compare.get(model_id),
            )
        )

    nanodet_cpu_1x = pi_cpu_entries.get(("nanodet", 1))
    nanodet_hailo_1x = hailo_entries.get(("nanodet", 1))
    yolo_cpu_1x = pi_cpu_entries.get(("yolo", 1))
    yolo_hailo_1x = hailo_entries.get(("yolo", 1))

    html = f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Legacy Parallel Matrix + Pi 5 Update</title>
  <style>
    :root {{
      color-scheme: dark;
      --bg: #2d3038;
      --panel: #32363f;
      --panel-2: #262a31;
      --line: rgba(255,255,255,0.68);
      --text: #f4f4f1;
      --muted: #c8c8c1;
      --accent: #f1efe7;
      --green: #c9f9cd;
      --amber: #ffe1a8;
      --red: #ffb3b3;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      font-family: "IBM Plex Mono", "SFMono-Regular", Menlo, monospace;
      background: radial-gradient(circle at top left, rgba(255,255,255,0.05), transparent 24%), var(--bg);
      color: var(--text);
    }}
    main {{
      max-width: 1500px;
      margin: 0 auto;
      padding: 28px 20px 48px;
    }}
    h1, h2, h3 {{
      margin: 0 0 12px;
      font-weight: 600;
    }}
    h1 {{ font-size: 2rem; }}
    h2 {{ font-size: 1.55rem; margin-top: 28px; }}
    h3 {{ font-size: 1rem; }}
    p {{
      line-height: 1.55;
      color: var(--muted);
      margin: 0 0 12px;
    }}
    .lede {{
      max-width: 1080px;
      margin-bottom: 20px;
    }}
    .note-grid, .detail-grid {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(260px, 1fr));
      gap: 14px;
      margin: 18px 0 24px;
    }}
    .note, .detail-card {{
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 12px;
      padding: 14px 16px;
    }}
    .table-wrap {{
      overflow-x: auto;
      border: 1px solid var(--line);
      border-radius: 12px;
      background: var(--panel);
    }}
    table {{
      width: 100%;
      border-collapse: collapse;
    }}
    th, td {{
      border-right: 1px solid var(--line);
      border-bottom: 1px solid var(--line);
      padding: 12px 16px;
      white-space: nowrap;
    }}
    th:last-child, td:last-child {{ border-right: 0; }}
    tr:last-child td {{ border-bottom: 0; }}
    th {{
      text-align: left;
      color: var(--accent);
      font-size: 1.02rem;
      font-weight: 500;
      background: var(--panel-2);
    }}
    td {{
      font-size: 1.95rem;
      line-height: 1.1;
      color: var(--text);
    }}
    td:first-child, th:first-child {{
      font-size: 1.25rem;
      min-width: 110px;
    }}
    .matrix-block + .matrix-block {{
      margin-top: 30px;
    }}
    .subtle {{
      font-size: 0.95rem;
      color: var(--muted);
    }}
    .quality table td {{
      font-size: 1rem;
      white-space: normal;
    }}
    .quality table th {{
      font-size: 0.95rem;
    }}
    .tag {{
      display: inline-block;
      padding: 0.18rem 0.48rem;
      border-radius: 999px;
      border: 1px solid var(--line);
      font-size: 0.85rem;
      margin-right: 0.4rem;
      color: var(--accent);
    }}
    .strong {{ color: var(--green); }}
    .warn {{ color: var(--amber); }}
    .bad {{ color: var(--red); }}
  </style>
</head>
<body>
  <main>
    <h1>Maximum Real FPS by Platform (sustained, parallel)</h1>
    <p class="lede">This report keeps the old benchmark-matrix style from the historic screenshot and extends it with fresh <span class="tag">Pi 5 CPU</span> and <span class="tag">Pi 5 Hailo</span> measurements from April 6, 2026. The old columns were transcribed from the prior screenshot rather than rerun in this session. The new Pi 5 columns were measured directly on Spencer's Raspberry Pi 5 AI HAT box.</p>

    <div class="note-grid">
      <div class="note"><strong>Legacy CM5 columns:</strong> carried over from the earlier screenshot as-is. They reflect the earlier Orange Pi CM5 / RK3588 test setup.</div>
      <div class="note"><strong>Pi 5 CPU columns:</strong> new sustained ONNX CPU runs at <code>1x / 2x / 3x</code> parallel workers on the Raspberry Pi 5.</div>
      <div class="note"><strong>Pi 5 Hailo columns:</strong> new shared-service Hailo-8 measurements at <code>1x / 2x / 3x</code> concurrent jobs on the Raspberry Pi 5 AI HAT.</div>
      <div class="note"><strong>Reading the matrix:</strong> all values are shown as combined FPS and rounded to whole numbers to stay visually compatible with the original table style.</div>
    </div>

    {_render_table(
        title=LEGACY_TABLES["nanodet"]["title"],
        legacy_columns=LEGACY_TABLES["nanodet"]["columns"],
        legacy_rows=LEGACY_TABLES["nanodet"]["rows"],
        cpu_entries=pi_cpu_entries,
        hailo_entries=hailo_entries,
        model_key="nanodet",
    )}

    {_render_table(
        title=LEGACY_TABLES["yolo"]["title"],
        legacy_columns=LEGACY_TABLES["yolo"]["columns"],
        legacy_rows=LEGACY_TABLES["yolo"]["rows"],
        cpu_entries=pi_cpu_entries,
        hailo_entries=hailo_entries,
        model_key="yolo",
    )}

    <section class="note-grid" style="margin-top: 28px;">
      <div class="note"><strong>Pi 5 CPU takeaway:</strong> the Raspberry Pi 5 CPU saturates immediately. It lands around <span class="strong">{float(nanodet_cpu_1x.get('combined_fps', 0.0)):.1f} FPS</span> for NanoDet and <span class="strong">{float(yolo_cpu_1x.get('combined_fps', 0.0)):.1f} FPS</span> for YOLO at 1x, then loses total throughput when split across 2-3 jobs.</div>
      <div class="note"><strong>Pi 5 Hailo takeaway:</strong> Hailo stays near a fixed throughput ceiling: about <span class="strong">{float(nanodet_hailo_1x.get('combined_fps', 0.0)):.1f} FPS</span> NanoDet and <span class="strong">{float(yolo_hailo_1x.get('combined_fps', 0.0)):.1f} FPS</span> YOLO at 1x, with extra workers time-slicing that budget instead of increasing it much.</div>
      <div class="note"><strong>Against the old CM5 NPU:</strong> Orange Pi CM5 scaled linearly because it spread work across three physical RK3588 NPU cores. Hailo behaves differently: one fast accelerator, strong single-stream speed, but not the same multi-core scaling shape.</div>
      <div class="note"><strong>Recommendation:</strong> use <span class="strong">Pi 5 Hailo + NanoDet</span> for the best blend of speed and output fidelity. Use <span class="warn">Pi 5 CPU</span> as a correctness fallback, not as the target throughput path.</div>
    </section>

    <section class="quality">
      <h2>Quality Context vs Local Mac CPU Reference</h2>
      <p class="subtle">The matrix above is throughput-only. This table adds the most important quality check: how closely the Raspberry Pi 5 runs match the local Mac CPU reference on the shared 50-image chamber-zone bundle.</p>
      <div class="table-wrap">
        <table>
          <thead>
            <tr>
              <th>Model</th>
              <th>Runtime</th>
              <th>Decision Match</th>
              <th>Pred Count Match</th>
              <th>Top-1 IoU</th>
            </tr>
          </thead>
          <tbody>
            {''.join(quality_rows)}
          </tbody>
        </table>
      </div>
    </section>

    <section>
      <h2>New Pi 5 Measurement Details</h2>
      <p class="subtle">Exact worker-level values behind the rounded matrix cells for the new Raspberry Pi 5 columns.</p>
      <div class="detail-grid">
        {_detail_card("NanoDet · Pi 5 CPU · 1x", pi_cpu_entries.get(("nanodet", 1)))}
        {_detail_card("NanoDet · Pi 5 Hailo · 3x", hailo_entries.get(("nanodet", 3)))}
        {_detail_card("YOLO11s · Pi 5 CPU · 1x", pi_cpu_entries.get(("yolo", 1)))}
        {_detail_card("YOLO11s · Pi 5 Hailo · 3x", hailo_entries.get(("yolo", 3)))}
      </div>
    </section>
  </main>
</body>
</html>
"""

    OUTPUT_PATH.write_text(html)
    print(OUTPUT_PATH)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
