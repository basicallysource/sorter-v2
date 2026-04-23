from __future__ import annotations

import sys
from pathlib import Path

_BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(_BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(_BACKEND_ROOT))

from utils.polygon_resolution import saved_polygon_resolution


def test_saved_polygon_resolution_prefers_per_channel_arc_resolution() -> None:
    saved = {
        "resolution": [3840, 2160],
        "arc_params": {
            "second": {
                "resolution": [1280, 720],
            }
        },
    }

    assert saved_polygon_resolution(saved, channel_key="second") == (1280.0, 720.0)


def test_saved_polygon_resolution_prefers_quad_resolution_before_legacy_channels() -> None:
    saved = {
        "resolution": [3840, 2160],
        "quad_params": {
            "carousel": {
                "resolution": [1920, 1080],
            }
        },
        "channels": {
            "carousel": {
                "resolution": [640, 480],
            }
        },
    }

    assert saved_polygon_resolution(saved, channel_key="carousel") == (1920.0, 1080.0)


def test_saved_polygon_resolution_falls_back_to_top_level_resolution() -> None:
    saved = {
        "resolution": [2592, 1944],
        "arc_params": {},
    }

    assert saved_polygon_resolution(saved, channel_key="third") == (2592.0, 1944.0)


def test_saved_polygon_resolution_ignores_invalid_entries() -> None:
    saved = {
        "resolution": ["bad", None],
        "arc_params": {
            "second": {
                "resolution": [0, -1],
            }
        },
    }

    assert saved_polygon_resolution(saved, channel_key="second") == (1920.0, 1080.0)
