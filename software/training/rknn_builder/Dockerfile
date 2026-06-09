# Pinned x86 toolchain that converts a YOLO best.pt into a working RK3588 RKNN.
#
# Why this exists / why fp16:
#   rknn-toolkit2's i8 path quantizes the fused YOLO output tensor *per-tensor*.
#   The box coordinates (0..imgsz) dominate that single scale, so the confidence
#   scores (0..1) fall below the quant resolution and collapse to exactly 0 ->
#   the NPU returns boxes but zero scores -> no detections. Building fp16
#   (do_quantization=False, which is what ultralytics' official RKNN export
#   does) keeps the scores intact. The sorter decodes the resulting
#   (1, 5, N) output via vision.ml.base.decode_yolo.
#
# rknn-toolkit2 is x86-only, so this runs under linux/amd64 (QEMU on Apple
# Silicon). onnx is pinned <1.19 because rknn-toolkit2 2.3.2 still imports the
# removed `onnx.mapping`.
FROM --platform=linux/amd64 python:3.11-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends libgl1 libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir \
        "rknn-toolkit2==2.3.2" \
        "onnx<1.19.0" \
        "ultralytics==8.4.38"

COPY build.py /build.py
WORKDIR /work
ENTRYPOINT ["python", "/build.py"]
