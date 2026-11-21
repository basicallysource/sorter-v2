"""GET /api/bins/layout reports each layer's size limit and the default it can go back to.

The Bins page switches a layer's size check off by saving a null limit and back
on by saving the default of the layer's bin count, so it needs both numbers.
"""

from __future__ import annotations

import pytest

from irl.bin_layout import BinLayoutConfig, LayerConfig
from server.routers import bins


def _layer(bin_count: int, limit: float | None) -> LayerConfig:
    return LayerConfig(
        sections=[["medium"] * (bin_count // 6) for _ in range(6)],
        enabled=True,
        max_dimension_mm=limit,
    )


@pytest.fixture
def layout(monkeypatch):
    config = BinLayoutConfig(layers=[_layer(18, 50.0), _layer(12, None)])
    monkeypatch.setattr(bins, "getBinLayout", lambda: config)
    monkeypatch.setattr(bins.machine_toml, "read", lambda: {})
    monkeypatch.setattr(
        bins,
        "_chute_settings_from_config",
        lambda cfg: {"first_bin_center": 0.0, "pillar_width_deg": 4.0},
    )
    monkeypatch.setattr(bins, "get_bin_categories", lambda: None)
    monkeypatch.setattr(bins, "_current_not_in_inventory", lambda: [])
    monkeypatch.setattr(bins.shared_state, "controller_ref", None)
    return config


def test_a_layer_with_a_limit_reports_it(layout) -> None:
    layers = bins.get_bins_layout()["layers"]

    assert layers[0]["max_dimension_mm"] == 50.0


def test_a_layer_with_the_check_off_reports_null(layout) -> None:
    layers = bins.get_bins_layout()["layers"]

    assert layers[1]["max_dimension_mm"] is None


def test_every_layer_reports_the_default_of_its_bin_count(layout) -> None:
    layers = bins.get_bins_layout()["layers"]

    assert layers[0]["max_dimension_default_mm"] == 50.0
    assert layers[1]["max_dimension_default_mm"] == 80.0
