from __future__ import annotations

import pytest
from pydantic import ValidationError

from rt.config.loader import load_sorter_config_from_str
from rt.config.schema import SorterConfig


VALID_TOML = """
[[feeds]]
feed_id = "c2_feed"
camera_id = "cam_c2"
purpose = "c2_feed"
fps_target = 10.0

[feeds.zone]
kind = "polar"
params = { center_xy = [960, 540], r_inner = 180, r_outer = 260, theta_start_rad = 0.0, theta_end_rad = 6.28 }

[[pipelines]]
feed_id = "c2_feed"
detector = { key = "placeholder", params = { foo = 1 } }
tracker = { key = "polar", params = {} }
filters = []

[[runtimes]]
runtime_id = "c2"
feeds = ["c2_feed"]
downstream = "c3"
capacity_to_downstream = 1

[classification]
classifier = { key = "brickognize", params = { max_concurrent = 4 } }

[distribution]
rules_engine = { key = "lego_default", params = {} }
"""


INVALID_TOML = """
[[feeds]]
feed_id = "bad_feed"
camera_id = "cam_x"
purpose = "not_a_valid_purpose"
fps_target = 10.0

[feeds.zone]
kind = "rect"
params = { x = 0, y = 0, w = 10, h = 10 }

[classification]
classifier = { key = "brickognize" }

[distribution]
rules_engine = { key = "lego_default" }
"""


def test_valid_toml_loads_and_validates() -> None:
    cfg = load_sorter_config_from_str(VALID_TOML)

    assert isinstance(cfg, SorterConfig)
    assert len(cfg.feeds) == 1
    assert cfg.feeds[0].feed_id == "c2_feed"
    assert cfg.feeds[0].zone.kind == "polar"
    assert cfg.runtimes[0].runtime_id == "c2"
    assert cfg.classification.classifier["key"] == "brickognize"
    assert cfg.distribution.rules_engine["key"] == "lego_default"


def test_invalid_toml_raises_validation_error() -> None:
    with pytest.raises(ValidationError):
        load_sorter_config_from_str(INVALID_TOML)
