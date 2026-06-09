# RKNN builder (RK3588 / Orange Pi 5)

Converts a YOLO `best.pt` into a **working fp16 RKNN** for the RK3588 NPU.

```bash
./build.sh runs/<run>/weights/best.pt out/model.rknn 320
```

## Why fp16 and not i8

rknn-toolkit2's int8 path quantizes the fused YOLO output tensor **per-tensor**.
The box coordinates (`0..imgsz`) dominate that single scale, so the confidence
scores (`0..1`) fall below the quant step and collapse to **exactly 0** — the
NPU returns boxes but zero scores, so nothing is ever detected. This silently
broke every i8 model (Aqua, Bronze, Cherry).

fp16 (`rknn.build(do_quantization=False)`, which ultralytics' official RKNN
export uses) keeps the scores intact. Cost on RK3588 is ~1.7× the i8 latency per
stream, but with per-core fanout (one stream per NPU core) a yolo26s-320 still
reaches ~108 FPS aggregate — well above the camera rate.

If you later need the i8 throughput *with* correct scores, the proper route is a
true **head-stripped** export (raw conv logits — box-reg and cls are both
logits, so they quantize together cleanly — with DFL/sigmoid/NMS on the CPU via
`vision.ml.base.decode_yolo_head_stripped`). That is a larger change; fp16 is
the clean, correct default today.

## Output format

ultralytics disables the end2end/NMS branch for RKNN, so the model emits a
`(1, 5, N)` tensor (`[x, y, w, h, score]` per anchor, single class). The sorter
decodes it with `vision.ml.base.decode_yolo` (the `len(outputs) != 3` branch in
`RknnYoloProcessor.infer`).

## Notes

- rknn-toolkit2 is x86-only; on Apple Silicon the container runs under QEMU. The
  image is built once and cached.
- `onnx` is pinned `<1.19` because rknn-toolkit2 2.3.2 imports the removed
  `onnx.mapping`.
