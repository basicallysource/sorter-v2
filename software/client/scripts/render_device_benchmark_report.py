from __future__ import annotations

import argparse
import json
from collections import Counter
from html import escape
from pathlib import Path
from typing import Any

import cv2


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Render an HTML report from device benchmark result JSON files.")
    parser.add_argument("result_json", nargs="+", help="One or more benchmark result JSON files")
    parser.add_argument("--output", required=True, help="Where to write the HTML report")
    parser.add_argument("--title", default="Device Detector Benchmark Report")
    parser.add_argument("--image-dir", required=True, help="Directory holding the benchmark images")
    parser.add_argument("--manifest", required=True, help="Benchmark manifest with local reference boxes")
    parser.add_argument("--max-samples", type=int, default=12, help="How many sample comparison cards to render per result")
    return parser.parse_args()


def _load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text())


def _fmt_float(value: Any, digits: int = 3) -> str:
    if value is None:
        return "n/a"
    return f"{float(value):.{digits}f}"


def _fmt_pct(value: Any) -> str:
    if value is None:
        return "n/a"
    return f"{float(value) * 100:.1f}%"


def _confusion_rows(per_sample: list[dict[str, Any]]) -> list[tuple[str, int]]:
    counter: Counter[str] = Counter()
    for row in per_sample:
        if not row.get("ok"):
            counter["error -> error"] += 1
            continue
        gt = str(row.get("gt_decision", "unknown"))
        pred = str(row.get("pred_decision", "unknown"))
        counter[f"{gt} -> {pred}"] += 1
    return sorted(counter.items(), key=lambda item: (-item[1], item[0]))


def _load_manifest_index(path: Path) -> dict[str, dict[str, Any]]:
    payload = _load(path)
    samples = payload.get("samples")
    if not isinstance(samples, list):
        raise RuntimeError(f"Manifest is missing samples list: {path}")
    return {
        str(sample["image"]): sample
        for sample in samples
        if isinstance(sample, dict) and isinstance(sample.get("image"), str)
    }


def _normalized_to_xyxy(box: list[float], width: int, height: int) -> list[int]:
    x1 = int(round(max(0.0, min(1.0, float(box[0]))) * width))
    y1 = int(round(max(0.0, min(1.0, float(box[1]))) * height))
    x2 = int(round(max(0.0, min(1.0, float(box[2]))) * width))
    y2 = int(round(max(0.0, min(1.0, float(box[3]))) * height))
    return [x1, y1, x2, y2]


def _draw_overlay(
    image_path: Path,
    boxes: list[list[int]],
    *,
    title: str,
    color: tuple[int, int, int],
    label_prefix: str,
    scores: list[float] | None = None,
) -> Any:
    image = cv2.imread(str(image_path), cv2.IMREAD_COLOR)
    if image is None:
        raise RuntimeError(f"Could not read image: {image_path}")
    overlay = image.copy()
    for index, box in enumerate(boxes, start=1):
        x1, y1, x2, y2 = box
        cv2.rectangle(overlay, (x1, y1), (x2, y2), color, 2)
        label = f"{label_prefix} {index}"
        if scores is not None and index - 1 < len(scores):
            label = f"{label} {float(scores[index - 1]):.2f}"
        cv2.putText(
            overlay,
            label,
            (x1, max(22, y1 - 8)),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.55,
            color,
            2,
            lineType=cv2.LINE_AA,
        )
    cv2.putText(
        overlay,
        title,
        (16, 30),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.85,
        color,
        2,
        lineType=cv2.LINE_AA,
    )
    return overlay


def _write_sample_assets(
    *,
    asset_dir: Path,
    image_dir: Path,
    manifest_index: dict[str, dict[str, Any]],
    per_sample: list[dict[str, Any]],
    limit: int,
) -> list[dict[str, Any]]:
    ranked = sorted(
        per_sample,
        key=lambda row: (
            row.get("gt_decision") == row.get("pred_decision"),
            abs(int(row.get("pred_count", 0)) - int(row.get("gt_count", 0))),
            float(row.get("latency_ms", 0.0)),
        ),
    )
    cards: list[dict[str, Any]] = []
    for row in ranked[:limit]:
        image_name = str(row.get("image", ""))
        if not image_name:
            continue
        image_path = image_dir / image_name
        if not image_path.exists():
            continue
        manifest_sample = manifest_index.get(image_name, {})
        source = cv2.imread(str(image_path), cv2.IMREAD_COLOR)
        if source is None:
            continue
        height, width = source.shape[:2]

        gt_boxes_normalized = manifest_sample.get("gt_boxes_normalized")
        gt_boxes = []
        if isinstance(gt_boxes_normalized, list):
            for box in gt_boxes_normalized:
                if isinstance(box, list) and len(box) >= 4:
                    gt_boxes.append(_normalized_to_xyxy([float(v) for v in box[:4]], width, height))

        pred_boxes = []
        if isinstance(row.get("candidate_bboxes"), list):
            pred_boxes = [
                [int(v) for v in box[:4]]
                for box in row["candidate_bboxes"]
                if isinstance(box, list) and len(box) >= 4
            ]
        pred_scores = [float(score) for score in row.get("scores", [])] if isinstance(row.get("scores"), list) else []

        stem = Path(image_name).stem
        pred_overlay_path = asset_dir / f"{stem}-pi-overlay.jpg"
        ref_overlay_path = asset_dir / f"{stem}-local-overlay.jpg"

        pred_overlay = _draw_overlay(
            image_path,
            pred_boxes,
            title="Pi prediction",
            color=(0, 114, 255),
            label_prefix="Pi",
            scores=pred_scores,
        )
        ref_overlay = _draw_overlay(
            image_path,
            gt_boxes,
            title="Local reference",
            color=(0, 180, 90),
            label_prefix="Ref",
        )
        pred_overlay_path.parent.mkdir(parents=True, exist_ok=True)
        cv2.imwrite(str(pred_overlay_path), pred_overlay)
        cv2.imwrite(str(ref_overlay_path), ref_overlay)

        cards.append(
            {
                "image": image_name,
                "pred_overlay": pred_overlay_path.name,
                "ref_overlay": ref_overlay_path.name,
                "gt_decision": row.get("gt_decision"),
                "pred_decision": row.get("pred_decision"),
                "gt_count": row.get("gt_count"),
                "pred_count": row.get("pred_count"),
                "latency_ms": row.get("latency_ms"),
                "fps": row.get("fps"),
            }
        )
    return cards


def _sample_table_rows(per_sample: list[dict[str, Any]], limit: int = 12) -> str:
    ranked = sorted(
        per_sample,
        key=lambda row: (
            row.get("gt_decision") == row.get("pred_decision"),
            float(row.get("latency_ms", 0.0)),
        ),
    )
    rows: list[str] = []
    for row in ranked[:limit]:
        rows.append(
            "<tr>"
            f"<td>{escape(str(row.get('image', 'unknown')))}</td>"
            f"<td>{escape(str(row.get('gt_decision', 'n/a')))}</td>"
            f"<td>{escape(str(row.get('pred_decision', 'n/a')))}</td>"
            f"<td>{escape(str(row.get('gt_count', 'n/a')))}</td>"
            f"<td>{escape(str(row.get('pred_count', 'n/a')))}</td>"
            f"<td>{_fmt_float(row.get('latency_ms'), 2)} ms</td>"
            f"<td>{_fmt_float(row.get('fps'), 2)}</td>"
            "</tr>"
        )
    return "\n".join(rows)


def _sample_cards_html(sample_cards: list[dict[str, Any]], assets_rel: str) -> str:
    blocks: list[str] = []
    for row in sample_cards:
        blocks.append(
            f"""
            <article class="sample-card">
              <div class="sample-head">
                <strong>{escape(str(row['image']))}</strong>
                <span>{escape(str(row['gt_decision']))} -> {escape(str(row['pred_decision']))}</span>
              </div>
              <div class="sample-meta">
                <span>GT count {escape(str(row['gt_count']))}</span>
                <span>Pred count {escape(str(row['pred_count']))}</span>
                <span>{_fmt_float(row['latency_ms'], 2)} ms</span>
                <span>{_fmt_float(row['fps'], 2)} FPS</span>
              </div>
              <div class="sample-images">
                <figure>
                  <img src="{assets_rel}/{escape(str(row['pred_overlay']))}" alt="Pi overlay for {escape(str(row['image']))}" />
                  <figcaption>Pi highlight</figcaption>
                </figure>
                <figure>
                  <img src="{assets_rel}/{escape(str(row['ref_overlay']))}" alt="Reference overlay for {escape(str(row['image']))}" />
                  <figcaption>Local reference boxes</figcaption>
                </figure>
              </div>
            </article>
            """
        )
    return "\n".join(blocks)


def _card(
    title: str,
    summary: dict[str, Any],
    system: dict[str, Any],
    per_sample: list[dict[str, Any]],
    sample_cards: list[dict[str, Any]],
    assets_rel: str,
) -> str:
    confusion = _confusion_rows(per_sample)
    confusion_html = "".join(
        f"<tr><td>{escape(label)}</td><td>{count}</td></tr>" for label, count in confusion
    )
    return f"""
    <section class="card">
      <h2>{escape(title)}</h2>
      <p class="muted">{escape(system.get('hostname', 'unknown'))} · {escape(system.get('machine', 'unknown'))} · {escape(system.get('release', 'unknown'))}</p>
      <div class="metrics">
        <div><span>Samples</span><strong>{summary.get('sample_count', 'n/a')}</strong></div>
        <div><span>Avg Latency</span><strong>{_fmt_float(summary.get('avg_latency_ms'), 2)} ms</strong></div>
        <div><span>P95</span><strong>{_fmt_float(summary.get('p95_latency_ms'), 2)} ms</strong></div>
        <div><span>FPS</span><strong>{_fmt_float(summary.get('avg_fps'), 2)}</strong></div>
        <div><span>Exact Count</span><strong>{_fmt_pct(summary.get('exact_count_match_rate'))}</strong></div>
        <div><span>Decision Match</span><strong>{_fmt_pct(summary.get('decision_match_rate'))}</strong></div>
        <div><span>Single IoU</span><strong>{_fmt_float(summary.get('single_mean_iou'), 3)}</strong></div>
        <div><span>Multi Detect</span><strong>{_fmt_pct(summary.get('multi_detect_rate'))}</strong></div>
      </div>
      <div class="columns">
        <div>
          <h3>Confusion</h3>
          <table>
            <thead><tr><th>Bucket</th><th>Count</th></tr></thead>
            <tbody>{confusion_html}</tbody>
          </table>
        </div>
        <div>
          <h3>Most Interesting Samples</h3>
          <table>
            <thead><tr><th>Image</th><th>GT</th><th>Pred</th><th>GT #</th><th>Pred #</th><th>Latency</th><th>FPS</th></tr></thead>
            <tbody>{_sample_table_rows(per_sample)}</tbody>
          </table>
        </div>
      </div>
      <div class="gallery">
        <h3>Pi Highlights vs Local Reference</h3>
        {_sample_cards_html(sample_cards, assets_rel)}
      </div>
    </section>
    """


def main() -> int:
    args = _parse_args()
    image_dir = Path(args.image_dir).resolve()
    manifest_index = _load_manifest_index(Path(args.manifest).resolve())
    output_path = Path(args.output).resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    assets_dir = output_path.parent / f"{output_path.stem}_assets"
    assets_dir.mkdir(parents=True, exist_ok=True)
    assets_rel = assets_dir.name

    cards: list[str] = []
    for raw_path in args.result_json:
        path = Path(raw_path).resolve()
        payload = _load(path)
        summary = payload.get("summary") if isinstance(payload.get("summary"), dict) else {}
        system = payload.get("system") if isinstance(payload.get("system"), dict) else {}
        per_sample = payload.get("per_sample") if isinstance(payload.get("per_sample"), list) else []
        sample_cards = _write_sample_assets(
            asset_dir=assets_dir / path.stem,
            image_dir=image_dir,
            manifest_index=manifest_index,
            per_sample=per_sample,
            limit=args.max_samples,
        )
        title = f"{path.stem} · {summary.get('runtime', 'runtime')} · threads={summary.get('threads', 'n/a')}"
        cards.append(_card(title, summary, system, per_sample, sample_cards, f"{assets_rel}/{path.stem}"))

    html = f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>{escape(args.title)}</title>
  <style>
    :root {{
      color-scheme: light;
      --bg: #f5f1e8;
      --panel: #fffdf8;
      --ink: #1f1c18;
      --muted: #6b655d;
      --line: #d9d0c5;
      --accent: #0f766e;
      --accent-soft: #d8f0ec;
    }}
    body {{
      margin: 0;
      font-family: "IBM Plex Sans", "Avenir Next", sans-serif;
      background: linear-gradient(180deg, #f2ece0 0%, #f8f5ee 100%);
      color: var(--ink);
    }}
    main {{
      max-width: 1360px;
      margin: 0 auto;
      padding: 32px 24px 48px;
    }}
    h1 {{
      margin: 0 0 10px;
      font-size: 2rem;
    }}
    h3 {{
      margin-top: 24px;
      margin-bottom: 10px;
    }}
    .intro {{
      margin: 0 0 24px;
      color: var(--muted);
    }}
    .card {{
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 18px;
      padding: 22px;
      box-shadow: 0 18px 40px rgba(44, 32, 20, 0.06);
      margin-bottom: 24px;
    }}
    .muted {{
      color: var(--muted);
      margin-top: -6px;
    }}
    .metrics {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
      gap: 12px;
      margin: 20px 0 24px;
    }}
    .metrics div {{
      background: var(--accent-soft);
      border-radius: 14px;
      padding: 12px 14px;
      display: flex;
      flex-direction: column;
      gap: 4px;
    }}
    .metrics span {{
      color: var(--muted);
      font-size: 0.82rem;
    }}
    .metrics strong {{
      font-size: 1.05rem;
    }}
    .columns {{
      display: grid;
      grid-template-columns: 260px 1fr;
      gap: 18px;
    }}
    table {{
      width: 100%;
      border-collapse: collapse;
      font-size: 0.92rem;
    }}
    th, td {{
      text-align: left;
      padding: 8px 10px;
      border-bottom: 1px solid var(--line);
      vertical-align: top;
    }}
    th {{
      font-size: 0.8rem;
      text-transform: uppercase;
      letter-spacing: 0.04em;
      color: var(--muted);
    }}
    .gallery {{
      margin-top: 28px;
    }}
    .sample-card {{
      border-top: 1px solid var(--line);
      padding-top: 18px;
      margin-top: 18px;
    }}
    .sample-head {{
      display: flex;
      justify-content: space-between;
      gap: 16px;
      align-items: baseline;
      margin-bottom: 6px;
    }}
    .sample-head span {{
      color: var(--muted);
      font-size: 0.92rem;
    }}
    .sample-meta {{
      display: flex;
      flex-wrap: wrap;
      gap: 10px;
      color: var(--muted);
      font-size: 0.88rem;
      margin-bottom: 12px;
    }}
    .sample-images {{
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 14px;
    }}
    figure {{
      margin: 0;
      background: #f7f3ec;
      border: 1px solid var(--line);
      border-radius: 14px;
      overflow: hidden;
    }}
    figure img {{
      display: block;
      width: 100%;
      height: auto;
      background: #fff;
    }}
    figcaption {{
      padding: 10px 12px;
      font-size: 0.9rem;
      color: var(--muted);
      border-top: 1px solid var(--line);
    }}
    @media (max-width: 980px) {{
      .columns {{
        grid-template-columns: 1fr;
      }}
      .sample-images {{
        grid-template-columns: 1fr;
      }}
      .sample-head {{
        flex-direction: column;
        align-items: flex-start;
      }}
    }}
  </style>
</head>
<body>
  <main>
    <h1>{escape(args.title)}</h1>
    <p class="intro">Classification-chamber benchmark results collected on the Raspberry Pi using the NanoDet NCNN runtime path, with Pi-predicted overlays compared against the local reference boxes.</p>
    {''.join(cards)}
  </main>
</body>
</html>
"""

    output_path.write_text(html)
    print(output_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
