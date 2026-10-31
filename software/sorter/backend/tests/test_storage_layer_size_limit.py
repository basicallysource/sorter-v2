"""Saving the storage layers keeps each layer's size limit unless the caller changes it.

The three UI callers of POST /api/hardware-config/storage-layers do not send
``max_dimension_mm``. It used to default to None and be saved as null, which
switches the per-layer size check off. A field that is left out now keeps the
saved limit; a field that is sent, null included, is taken as sent.
"""

from __future__ import annotations

import pytest

import bin_layout_store
from irl.bin_layout import BinLayoutConfig, LayerConfig
from server.routers import hardware
from server.routers.hardware import StorageLayerPayload, StorageLayerSettingsPayload


def _layer(bin_count: int, limit: float | None) -> LayerConfig:
    return LayerConfig(
        sections=[["medium"] * (bin_count // 6) for _ in range(6)],
        enabled=True,
        max_dimension_mm=limit,
    )


@pytest.fixture
def stored(monkeypatch):
    """The saved bin layout: 18 bins at 50 mm, 12 bins at 80 mm."""
    state = {"layout": BinLayoutConfig(layers=[_layer(18, 50.0), _layer(12, 80.0)])}
    monkeypatch.setattr(hardware, "getBinLayout", lambda: state["layout"])
    monkeypatch.setattr(
        hardware, "saveBinLayout", lambda config: state.__setitem__("layout", config)
    )
    monkeypatch.setattr(hardware, "_apply_live_storage_layer_enabled", lambda layers: False)
    monkeypatch.setattr(bin_layout_store, "get_servo_channel_calibration", lambda: {})
    return state


def _limits(state) -> list[float | None]:
    return [layer.max_dimension_mm for layer in state["layout"].layers]


def _save(*layers: StorageLayerPayload) -> None:
    hardware.save_storage_layer_hardware_config(StorageLayerSettingsPayload(layers=list(layers)))


def test_a_save_without_the_field_keeps_every_limit(stored) -> None:
    _save(
        StorageLayerPayload(bin_count=18, enabled=False),
        StorageLayerPayload(bin_count=12, enabled=True, max_pieces_per_bin=40),
    )

    assert _limits(stored) == [50.0, 80.0]
    assert stored["layout"].layers[0].enabled is False


def test_a_limit_that_was_already_off_stays_off(stored) -> None:
    stored["layout"].layers[1].max_dimension_mm = None

    _save(
        StorageLayerPayload(bin_count=18, enabled=True, max_pieces_per_bin=10),
        StorageLayerPayload(bin_count=12, enabled=True),
    )

    assert _limits(stored) == [50.0, None]


def test_a_sent_limit_is_saved(stored) -> None:
    _save(
        StorageLayerPayload(bin_count=18, max_dimension_mm=60),
        StorageLayerPayload(bin_count=12),
    )

    assert _limits(stored) == [60.0, 80.0]


def test_a_sent_null_switches_the_check_off(stored) -> None:
    _save(
        StorageLayerPayload(bin_count=18, max_dimension_mm=None),
        StorageLayerPayload(bin_count=12),
    )

    assert _limits(stored) == [None, 80.0]


def test_a_changed_bin_count_starts_from_the_default_of_the_new_count(stored) -> None:
    _save(
        StorageLayerPayload(bin_count=12),
        StorageLayerPayload(bin_count=12),
    )

    assert _limits(stored) == [80.0, 80.0]


def test_a_new_layer_starts_from_the_default_of_its_bin_count(stored) -> None:
    _save(
        StorageLayerPayload(bin_count=18),
        StorageLayerPayload(bin_count=12),
        StorageLayerPayload(bin_count=18),
    )

    assert _limits(stored) == [50.0, 80.0, 50.0]
