"""Minimal inference-runtime abstraction for the perception package.

Wraps the existing RKNN runtime in ``vision/ml/rknn.py`` so the
``InferenceWorker`` holds a direct, immutable runtime reference assigned
at construction time. No role-string dispatch, no shared dict, no first-
call build race.

Two concrete runtimes:
- ``RknnYoloRuntime`` — production path on RK3588. Wraps
  ``vision.ml.rknn.RknnYoloProcessor`` with a fixed core mask passed in
  at construction. Each ``InferenceWorker`` owns one and only one of
  these.
- ``StubRuntime`` — test path on the Mac. Returns whatever bboxes the
  test handed in. Used by ``test_no_camera_crossover.py`` and any other
  unit test that wants to exercise the worker without hardware.

The ``InferenceRuntime`` protocol is what the ``InferenceWorker`` reads
through. Keeping it narrow (one method: ``infer(bgr) -> list[Bbox]``)
means the worker has no opinion on which runtime it holds, and there is
no API surface that takes a runtime by string name.
"""

from __future__ import annotations

from typing import Iterable, Optional, Protocol, Sequence, Tuple

import numpy as np


Bbox = Tuple[int, int, int, int]


class InferenceRuntime(Protocol):
    def infer(
        self, bgr: np.ndarray, *, conf_threshold: Optional[float] = None
    ) -> Sequence[Bbox]:
        ...


class RknnYoloRuntime:
    """Thin adapter over ``vision.ml.rknn.RknnYoloProcessor``.

    The RKNN core mask is fixed at construction; this object will only
    ever run on that NPU core. There is no setter, no shared registry,
    no role lookup.
    """

    __slots__ = (
        "_processor", "_core_mask_name", "_model_path", "_imgsz",
        "_conf_threshold", "_iou_threshold",
    )

    def __init__(
        self,
        *,
        model_path,
        imgsz: int,
        core_mask_name: str,
        conf_threshold: float = 0.25,
        iou_threshold: float = 0.45,
    ) -> None:
        # Imported lazily so the perception package is importable on a
        # Mac dev box where rknnlite is unavailable. Only the production
        # entry point (PerceptionService.build on the Pi) reaches this.
        from vision.ml.rknn import RknnYoloProcessor

        self._core_mask_name = core_mask_name
        # Stashed for introspection (the perception-debug overlay stamps these).
        self._model_path = model_path
        self._imgsz = int(imgsz)
        self._conf_threshold = float(conf_threshold)
        self._iou_threshold = float(iou_threshold)
        self._processor = RknnYoloProcessor(
            model_path=model_path,
            imgsz=imgsz,
            conf_threshold=conf_threshold,
            iou_threshold=iou_threshold,
            core_mask_name=core_mask_name,
        )

    @property
    def core_mask_name(self) -> str:
        return self._core_mask_name

    @property
    def model_path(self):
        return self._model_path

    @property
    def imgsz(self) -> int:
        return self._imgsz

    @property
    def conf_threshold(self) -> float:
        return self._conf_threshold

    @property
    def iou_threshold(self) -> float:
        return self._iou_threshold

    def infer(
        self, bgr: np.ndarray, *, conf_threshold: Optional[float] = None
    ) -> Sequence[Bbox]:
        if conf_threshold is None:
            detections = self._processor.infer(bgr)
        else:
            detections = self._processor.infer(bgr, conf_threshold=conf_threshold)
        # ``Detection`` from vision.ml.base carries .bbox as a 4-tuple of ints.
        out: list[Bbox] = []
        for d in detections:
            b = d.bbox
            out.append((int(b[0]), int(b[1]), int(b[2]), int(b[3])))
        return out


class StubRuntime:
    """Test runtime: returns a fixed list of bboxes for any input.

    Used by perception's own unit tests so they don't need RKNN. Not part
    of any production code path.
    """

    __slots__ = ("_bboxes", "calls")

    def __init__(self, bboxes: Iterable[Bbox] = ()) -> None:
        self._bboxes: tuple[Bbox, ...] = tuple(bboxes)
        self.calls: int = 0

    def set_bboxes(self, bboxes: Iterable[Bbox]) -> None:
        self._bboxes = tuple(bboxes)

    def infer(
        self, bgr: np.ndarray, *, conf_threshold: Optional[float] = None
    ) -> Sequence[Bbox]:
        self.calls += 1
        return self._bboxes


class OnnxYoloRuntime:
    """ONNX inference runtime for non-RK3588 hosts (macOS dev, x86).

    Runs the bundled best.onnx export using onnxruntime-cpu.
    Input: BGR uint8 frame of any size (resized to imgsz×imgsz internally).
    Output: list of (x1, y1, x2, y2) integer bboxes.
    """

    __slots__ = ("_session", "_imgsz", "_conf_threshold", "_iou_threshold", "_model_path")

    def __init__(
        self,
        *,
        model_path,
        imgsz: int,
        conf_threshold: float = 0.25,
        iou_threshold: float = 0.45,
        # core_mask_name ignored on non-NPU hardware; accepted for API parity
        core_mask_name: str = "CPU",
    ) -> None:
        import onnxruntime as ort  # pip install onnxruntime

        self._model_path = model_path
        self._imgsz = int(imgsz)
        self._conf_threshold = float(conf_threshold)
        self._iou_threshold = float(iou_threshold)
        self._session = ort.InferenceSession(
            str(model_path),
            providers=["CPUExecutionProvider"],
        )

    @property
    def model_path(self):
        return self._model_path

    @property
    def imgsz(self) -> int:
        return self._imgsz

    @property
    def conf_threshold(self) -> float:
        return self._conf_threshold

    def infer(
        self, bgr: np.ndarray, *, conf_threshold: Optional[float] = None
    ) -> Sequence[Bbox]:
        import cv2

        conf = conf_threshold if conf_threshold is not None else self._conf_threshold
        img = cv2.resize(bgr, (self._imgsz, self._imgsz))
        rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
        inp = rgb.astype(np.float32) / 255.0
        inp = np.expand_dims(inp.transpose(2, 0, 1), 0)  # NCHW

        input_name = self._session.get_inputs()[0].name
        raw = self._session.run(None, {input_name: inp})[0]  # shape: (1, num_det, 6) or (1, 6, 8400)

        # YOLO11 ultralytics ONNX export: output shape (1, num_classes+4, 8400)
        # Transpose to (8400, num_classes+4) for row-by-row processing.
        preds = raw[0]
        if preds.shape[0] < preds.shape[1]:  # (6, 8400) → (8400, 6)
            preds = preds.T

        bboxes: list[Bbox] = []
        scale_x = bgr.shape[1] / self._imgsz
        scale_y = bgr.shape[0] / self._imgsz

        for row in preds:
            # YOLO format: cx, cy, w, h, [class scores...]
            cx, cy, w, h = row[0], row[1], row[2], row[3]
            scores = row[4:]
            score = float(scores.max())
            if score < conf:
                continue
            x1 = int((cx - w / 2) * scale_x)
            y1 = int((cy - h / 2) * scale_y)
            x2 = int((cx + w / 2) * scale_x)
            y2 = int((cy + h / 2) * scale_y)
            bboxes.append((x1, y1, x2, y2))

        # Simple NMS — filter overlapping detections
        return _nms(bboxes, self._iou_threshold)


def _nms(boxes: list[Bbox], iou_threshold: float) -> list[Bbox]:
    if not boxes:
        return []
    boxes_arr = np.array(boxes, dtype=np.float32)
    x1, y1, x2, y2 = boxes_arr[:, 0], boxes_arr[:, 1], boxes_arr[:, 2], boxes_arr[:, 3]
    areas = (x2 - x1) * (y2 - y1)
    order = areas.argsort()[::-1]
    keep = []
    while order.size:
        i = order[0]
        keep.append(i)
        xx1 = np.maximum(x1[i], x1[order[1:]])
        yy1 = np.maximum(y1[i], y1[order[1:]])
        xx2 = np.minimum(x2[i], x2[order[1:]])
        yy2 = np.minimum(y2[i], y2[order[1:]])
        inter = np.maximum(0.0, xx2 - xx1) * np.maximum(0.0, yy2 - yy1)
        iou = inter / (areas[i] + areas[order[1:]] - inter + 1e-6)
        order = order[np.where(iou <= iou_threshold)[0] + 1]
    return [boxes[i] for i in keep]
