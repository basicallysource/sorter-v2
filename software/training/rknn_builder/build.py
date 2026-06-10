"""In-container: convert a YOLO ``best.pt`` into a working fp16 RK3588 RKNN.

Runs ultralytics' official RKNN export, which (a) re-exports the model with the
end2end/NMS branch disabled so the detect head emits a plain ``(1, 5, N)``
tensor the sorter can decode, and (b) builds the RKNN with
``do_quantization=False`` (fp16) so the confidence scores survive. See the
Dockerfile header for why i8 is unusable for the fused YOLO output.
"""

from __future__ import annotations

import argparse
import shutil
from pathlib import Path

from ultralytics import YOLO


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pt", required=True, help="Source YOLO best.pt")
    ap.add_argument("--out", required=True, help="Destination .rknn path")
    ap.add_argument("--imgsz", type=int, default=320)
    ap.add_argument("--platform", default="rk3588")
    args = ap.parse_args()

    # ultralytics writes intermediates (onnx, _rknn_model/) next to the source
    # weights, so stage the .pt into the writable workdir first — the input mount
    # is read-only.
    work_pt = Path("/work") / Path(args.pt).name
    shutil.copy(args.pt, work_pt)

    result = YOLO(str(work_pt)).export(format="rknn", name=args.platform, imgsz=args.imgsz)

    result_path = Path(result)
    rknn = result_path if result_path.suffix == ".rknn" else next(result_path.glob("*.rknn"))
    shutil.copy(rknn, args.out)
    print(f"WROTE {args.out} ({rknn.stat().st_size} bytes)")


if __name__ == "__main__":
    main()
