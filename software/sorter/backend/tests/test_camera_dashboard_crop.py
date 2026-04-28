from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

_BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(_BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(_BACKEND_ROOT))

from server.services import camera_dashboard_crop as crop


def test_dashboard_crop_spec_scales_channel_polygon(
    monkeypatch,
) -> None:
    monkeypatch.setattr(crop, "public_aux_scope", lambda: "classification_channel")
    monkeypatch.setattr(
        crop,
        "get_channel_polygons",
        lambda: {
            "resolution": [100, 100],
            "polygons": {
                "second_channel": [[10, 20], [30, 20], [30, 40], [10, 40]],
            },
        },
    )

    spec = crop.dashboard_crop_spec("c_channel_2", frame_w=200, frame_h=100)

    assert spec is not None
    assert spec["kind"] == "bbox_masked"
    polygon = spec["polygons"][0]
    assert tuple(polygon[0]) == (20.0, 20.0)
    assert tuple(polygon[2]) == (60.0, 40.0)


def test_apply_dashboard_crop_uses_polygon_bbox() -> None:
    frame = np.ones((100, 200, 3), dtype=np.uint8)
    spec = {
        "kind": "bbox_masked",
        "polygons": [
            np.array([[20.0, 20.0], [60.0, 20.0], [60.0, 40.0], [20.0, 40.0]]),
        ],
    }

    cropped = crop.apply_dashboard_crop(frame, spec)

    assert cropped.shape == (20, 40, 3)
