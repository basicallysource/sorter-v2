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
