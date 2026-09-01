from __future__ import annotations

import argparse
import json
import time
from dataclasses import asdict
from pathlib import Path

import cv2
import numpy as np

from detector import (
    DetectorParams,
    defaultAnnulusForMachine,
    detectSpokeAngle,
    drawDetection,
)


DEFAULT_IN = Path("/Volumes/T7/sorter-v2-c4-spoke-orientation/hive-images")
DEFAULT_OUT = Path("/Volumes/T7/sorter-v2-c4-spoke-orientation/site")


HTML_TEMPLATE = """<!doctype html>
<html><head>
<meta charset="utf-8">
<title>C4 spoke detector — iteration {iter_label}</title>
<style>
  body {{ font-family: -apple-system, sans-serif; margin: 0; padding: 24px;
         background: #111; color: #eee; }}
  h1, h2 {{ font-weight: 500; }}
  .machine {{ margin-bottom: 48px; }}
  .grid {{ display: grid; grid-template-columns: repeat(auto-fill, minmax(420px, 1fr));
           gap: 16px; }}
  .card {{ background: #1a1a1a; padding: 8px; border-radius: 6px; }}
  .card.fail {{ background: #3a0d0d; outline: 2px solid #ff3333; }}
  .card img {{ width: 100%; display: block; border-radius: 4px; }}
  .meta {{ font-size: 12px; color: #999; margin-top: 6px;
           font-family: ui-monospace, Menlo, monospace; }}
  .card.fail .meta {{ color: #ff8a8a; }}
  .summary {{ background: #1a1a1a; padding: 12px 16px; border-radius: 6px;
              margin-bottom: 24px; font-family: ui-monospace, Menlo, monospace;
              font-size: 13px; }}
  .summary .ok {{ color: #5fdb7b; }}
  .summary .bad {{ color: #ff5f5f; }}
</style>
</head><body>
<h1>C4 spoke-orientation detector — iteration <code>{iter_label}</code></h1>
<div class="summary">
  Generated: {generated_at} &middot; images: {n_images} &middot;
  <span class="ok">success: {n_success}</span> &middot;
  <span class="bad">fail: {n_fail}</span> &middot;
  mean inference time: {mean_ms:.1f} ms
  <br>Params: <code>{params_repr}</code>
</div>
{machine_sections}
</body></html>
"""


MACHINE_SECTION = """<div class="machine">
  <h2>{machine}</h2>
  <div class="grid">{cards}</div>
</div>"""


CARD = """<div class="card {fail_class}">
  <img src="{rel_path}" loading="lazy">
  <div class="meta">{filename}<br>{detail}</div>
</div>"""


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--in-dir", type=Path, default=DEFAULT_IN)
    p.add_argument("--out-dir", type=Path, default=DEFAULT_OUT)
    p.add_argument("--iter-label", type=str, default="iter001")
    p.add_argument("--max-side-px", type=int, default=1280,
                   help="Downscale overlays to this max edge for the site.")
    args = p.parse_args()

    args.out_dir.mkdir(parents=True, exist_ok=True)
    overlays_root = args.out_dir / "overlays" / args.iter_label
    overlays_root.mkdir(parents=True, exist_ok=True)

    params = DetectorParams()
    results: dict[str, list[dict]] = {}
    inference_ms: list[float] = []

    for machine_dir in sorted(p for p in args.in_dir.iterdir() if p.is_dir()):
        machine = machine_dir.name
        results[machine] = []
        for img_path in sorted(machine_dir.glob("*.jpg")):
            img = cv2.imread(str(img_path))
            if img is None:
                print(f"skip unreadable: {img_path}")
                continue
            annulus = defaultAnnulusForMachine(machine, img.shape[:2])
            t0 = time.perf_counter()
            res = detectSpokeAngle(img, annulus, params)
            dt_ms = (time.perf_counter() - t0) * 1000
            inference_ms.append(dt_ms)
            overlay = drawDetection(img, res.annulus_used, res)

            scale = 1.0
            mx = max(overlay.shape[:2])
            if mx > args.max_side_px:
                scale = args.max_side_px / mx
                overlay = cv2.resize(
                    overlay, (int(overlay.shape[1] * scale),
                              int(overlay.shape[0] * scale)),
                    interpolation=cv2.INTER_AREA,
                )

            sub = overlays_root / machine
            sub.mkdir(parents=True, exist_ok=True)
            out_path = sub / img_path.name
            cv2.imwrite(str(out_path), overlay,
                        [cv2.IMWRITE_JPEG_QUALITY, 85])
            rel = out_path.relative_to(args.out_dir).as_posix()
            results[machine].append({
                "filename": img_path.name,
                "rel_path": rel,
                "theta": res.angle_deg,
                "score": res.score,
                "success": res.success,
                "failure_reason": res.failure_reason,
                "prominence": res.prominence_ratio,
                "ms": dt_ms,
            })
            tag = "OK " if res.success else "FAIL"
            print(f"[{tag}] {machine}/{img_path.name}: theta={res.angle_deg:.3f} "
                  f"prom={res.prominence_ratio:.2f}x ({dt_ms:.1f} ms) "
                  f"{res.failure_reason}")

    sections = []
    n_total = 0
    n_success = 0
    n_fail = 0
    for machine, rows in results.items():
        cards_html = []
        for row in rows:
            if row["success"]:
                detail = (f"theta = {row['theta']:.3f}&deg; &middot; "
                          f"prom = {row['prominence']:.2f}x")
                fail_class = ""
                n_success += 1
            else:
                detail = (f"FAIL ({row['failure_reason']}) &middot; "
                          f"prom = {row['prominence']:.2f}x")
                fail_class = "fail"
                n_fail += 1
            cards_html.append(CARD.format(
                rel_path=row["rel_path"], filename=row["filename"],
                detail=detail, fail_class=fail_class,
            ))
        sections.append(MACHINE_SECTION.format(
            machine=machine, cards="\n".join(cards_html)))
        n_total += len(rows)

    html = HTML_TEMPLATE.format(
        iter_label=args.iter_label,
        generated_at=time.strftime("%Y-%m-%d %H:%M:%S"),
        n_images=n_total,
        n_success=n_success,
        n_fail=n_fail,
        mean_ms=(sum(inference_ms) / max(1, len(inference_ms))),
        params_repr=str(asdict(params)),
        machine_sections="\n".join(sections),
    )
    (args.out_dir / f"index_{args.iter_label}.html").write_text(html)
    (args.out_dir / "index.html").write_text(html)
    (args.out_dir / f"results_{args.iter_label}.json").write_text(
        json.dumps(results, indent=2)
    )
    print(f"\nwrote site -> {args.out_dir}/index.html ({n_total} images, "
          f"mean {sum(inference_ms)/max(1,len(inference_ms)):.1f} ms)")


if __name__ == "__main__":
    main()
