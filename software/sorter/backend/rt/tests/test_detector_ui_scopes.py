"""Tests for detector UI-scope mapping + default-slug helpers.

These helpers replace the legacy ``vision.detection_registry`` shim —
they live in ``rt.contracts.registry`` (single source of truth) and
``rt.perception.detector_metadata`` (run.json-backed shape for the
Svelte settings dropdown).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from rt.contracts.registry import (
    DETECTORS,
    StrategyRegistry,
    default_detector_slug_for_ui_scope,
    ui_scopes_for_detector,
)
from rt.perception import detector_metadata
from rt.perception.detectors import hive_onnx
from rt.perception.detectors.hive_onnx import discover_and_register_hive_detectors


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _write_run_json(dir_path: Path, payload: dict[str, Any]) -> None:
    dir_path.mkdir(parents=True, exist_ok=True)
    (dir_path / "run.json").write_text(json.dumps(payload))


def _write_onnx_artifact(dir_path: Path) -> Path:
    exports = dir_path / "exports"
    exports.mkdir(parents=True, exist_ok=True)
    path = exports / "best.onnx"
    path.write_bytes(b"\x00\x00")
    return path


@pytest.fixture
def fake_hive_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Populate a tmp_path with the 5 real hive model shapes and register them
    into a temporary registry.
    """
    specs = [
        ("hive-aaa", {
            "hive": {"model_id": "aaa", "variant_runtime": "onnx"},
            "model_family": "yolo",
            "name": "c-channel-yolo11n-320",
            "imgsz": 320,
            "scopes": ["c_channel"],
        }),
        ("hive-bbb", {
            "hive": {"model_id": "bbb", "variant_runtime": "onnx"},
            "model_family": "yolo",
            "name": "Carousel YOLO11n 320",
            "imgsz": 320,
            "scopes": ["carousel"],
        }),
        ("hive-ccc", {
            "hive": {"model_id": "ccc", "variant_runtime": "onnx"},
            "model_family": "yolo",
            "name": "Classification Chamber YOLO11n 320",
            "imgsz": 320,
            "scopes": ["classification_chamber"],
        }),
        ("hive-ddd", {
            "hive": {"model_id": "ddd", "variant_runtime": "onnx"},
            "model_family": "yolo",
            "name": "chamber-yolo11n-320",
            "imgsz": 320,
            "scopes": None,
        }),
        ("hive-eee", {
            "hive": {"model_id": "eee", "variant_runtime": "onnx"},
            "model_family": "nanodet",
            "name": "chamber-nanodet-1.5x-416",
            "imgsz": 416,
        }),
    ]
    for name, payload in specs:
        d = tmp_path / name
        _write_run_json(d, payload)
        _write_onnx_artifact(d)

    def fake_resolve(run_dir: Path, runtime: str) -> Path | None:
        artifact = run_dir / "exports" / "best.onnx"
        return artifact if artifact.exists() else None

    def fake_build(**kwargs: Any) -> Any:  # pragma: no cover - factory not called
        return object()

    monkeypatch.setattr(hive_onnx, "_resolve_model_artifact", fake_resolve)
    monkeypatch.setattr(hive_onnx, "_build_processor", fake_build)
    return tmp_path


@pytest.fixture
def hive_registry(fake_hive_dir: Path) -> StrategyRegistry[Any]:
    reg: StrategyRegistry[Any] = StrategyRegistry("detector")
    discover_and_register_hive_detectors(fake_hive_dir, registry=reg)
    return reg


# ---------------------------------------------------------------------------
# Registry-level metadata storage
# ---------------------------------------------------------------------------


def test_registry_stores_scopes_metadata_from_run_json(
    hive_registry: StrategyRegistry[Any],
) -> None:
    meta = hive_registry.metadata("hive:c-channel-yolo11n-320")
    assert meta["scopes"] == ("c_channel",)
    meta = hive_registry.metadata("hive:chamber-yolo11n-320")
    assert meta["scopes"] == ()
    meta = hive_registry.metadata("hive:chamber-nanodet-1.5x-416")
    assert meta["scopes"] == ()


# ---------------------------------------------------------------------------
# ui_scopes_for_detector — uses global DETECTORS, so we test via the real
# registry populated by the real models dir (skip if no blobs).
# ---------------------------------------------------------------------------


@pytest.fixture
def real_hive_models() -> None:
    """Ensure the real Hive models from blob/ are registered globally."""
    models_dir = Path(__file__).resolve().parents[2] / "blob" / "hive_detection_models"
    if not models_dir.exists():
        pytest.skip("hive models not installed in this env")
    # Importing triggers discovery — idempotent.
    import rt.perception  # noqa: F401


def test_ui_scopes_c_channel_maps_to_feeder_and_classification_channel(
    real_hive_models: None,
) -> None:
    scopes = ui_scopes_for_detector("hive:c-channel-yolo11n-320")
    assert scopes == frozenset({"feeder", "classification_channel"})


def test_ui_scopes_carousel_maps_to_carousel_only(
    real_hive_models: None,
) -> None:
    scopes = ui_scopes_for_detector("hive:carousel-yolo11n-320")
    assert scopes == frozenset({"carousel"})


def test_ui_scopes_classification_chamber_maps_to_classification(
    real_hive_models: None,
) -> None:
    scopes = ui_scopes_for_detector("hive:classification-chamber-yolo11n-320")
    assert scopes == frozenset({"classification"})


def test_ui_scopes_none_scoped_model_is_filtered_out(
    real_hive_models: None,
) -> None:
    """chamber-yolo11n-320 and chamber-nanodet-1.5x-416 declare no scopes."""
    assert ui_scopes_for_detector("hive:chamber-yolo11n-320") == frozenset()
    assert ui_scopes_for_detector("hive:chamber-nanodet-1.5x-416") == frozenset()


def test_ui_scopes_unknown_detector_is_empty(real_hive_models: None) -> None:
    assert ui_scopes_for_detector("hive:does-not-exist") == frozenset()


# ---------------------------------------------------------------------------
# default_detector_slug_for_ui_scope
# ---------------------------------------------------------------------------


def test_default_for_feeder_is_c_channel(real_hive_models: None) -> None:
    assert (
        default_detector_slug_for_ui_scope("feeder")
        == "hive:c-channel-yolo11n-320"
    )


def test_default_for_classification_channel_is_c_channel(
    real_hive_models: None,
) -> None:
    assert (
        default_detector_slug_for_ui_scope("classification_channel")
        == "hive:c-channel-yolo11n-320"
    )


def test_default_for_carousel_is_carousel_yolo(real_hive_models: None) -> None:
    assert (
        default_detector_slug_for_ui_scope("carousel")
        == "hive:carousel-yolo11n-320"
    )


def test_default_for_classification_is_classification_chamber(
    real_hive_models: None,
) -> None:
    assert (
        default_detector_slug_for_ui_scope("classification")
        == "hive:classification-chamber-yolo11n-320"
    )


def test_default_for_empty_or_unknown_ui_scope_is_none(
    real_hive_models: None,
) -> None:
    assert default_detector_slug_for_ui_scope("") is None
    assert default_detector_slug_for_ui_scope("bogus") is None


# ---------------------------------------------------------------------------
# detector_metadata — the shim's API, now backed by rt
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _reset_metadata_cache() -> None:
    detector_metadata.invalidate_cache()
    yield
    detector_metadata.invalidate_cache()


def test_detection_algorithm_definition_returns_hive_shape(
    real_hive_models: None,
) -> None:
    definition = detector_metadata.detection_algorithm_definition(
        "hive:c-channel-yolo11n-320"
    )
    assert definition is not None
    assert definition.kind == "hive"
    assert definition.model_family == "yolo"
    assert definition.imgsz == 320
    assert definition.runtime in {"onnx", "ncnn"}
    assert definition.label  # non-empty
    assert "YOLO" in definition.description or "yolo" in definition.description.lower()
    assert definition.hive_metadata is not None
    assert definition.hive_metadata["slug"] == "c-channel-yolo11n-320"
    # Supported scopes come from run.json -> UI mapping.
    assert definition.supported_scopes == frozenset(
        {"feeder", "classification_channel"}
    )


def test_detection_algorithm_definition_unknown_returns_none(
    real_hive_models: None,
) -> None:
    assert detector_metadata.detection_algorithm_definition(None) is None
    assert detector_metadata.detection_algorithm_definition("nope") is None


def test_detection_algorithms_for_scope_filters_by_ui_scope(
    real_hive_models: None,
) -> None:
    feeder_algos = {
        a.id for a in detector_metadata.detection_algorithms_for_scope("feeder")
    }
    assert "hive:c-channel-yolo11n-320" in feeder_algos
    # None-scoped legacy models must NOT surface on any UI scope.
    assert "hive:chamber-yolo11n-320" not in feeder_algos
    assert "hive:chamber-nanodet-1.5x-416" not in feeder_algos

    carousel_algos = {
        a.id for a in detector_metadata.detection_algorithms_for_scope("carousel")
    }
    assert carousel_algos == {"hive:carousel-yolo11n-320"}


def test_normalize_returns_input_when_valid_for_scope(
    real_hive_models: None,
) -> None:
    assert (
        detector_metadata.normalize_detection_algorithm(
            "feeder", "hive:c-channel-yolo11n-320"
        )
        == "hive:c-channel-yolo11n-320"
    )


def test_normalize_returns_default_when_input_not_in_scope(
    real_hive_models: None,
) -> None:
    # carousel model on feeder scope is invalid → default.
    assert (
        detector_metadata.normalize_detection_algorithm(
            "feeder", "hive:carousel-yolo11n-320"
        )
        == "hive:c-channel-yolo11n-320"
    )


def test_normalize_returns_default_for_bogus_value(
    real_hive_models: None,
) -> None:
    assert (
        detector_metadata.normalize_detection_algorithm("feeder", "bogus")
        == "hive:c-channel-yolo11n-320"
    )
    assert (
        detector_metadata.normalize_detection_algorithm("feeder", None)
        == "hive:c-channel-yolo11n-320"
    )


def test_scope_supports_detection_algorithm(real_hive_models: None) -> None:
    assert detector_metadata.scope_supports_detection_algorithm(
        "feeder", "hive:c-channel-yolo11n-320"
    )
    assert not detector_metadata.scope_supports_detection_algorithm(
        "feeder", "hive:carousel-yolo11n-320"
    )
    # None-scoped model accepted nowhere.
    assert not detector_metadata.scope_supports_detection_algorithm(
        "feeder", "hive:chamber-yolo11n-320"
    )
    assert not detector_metadata.scope_supports_detection_algorithm("feeder", None)


def test_options_shape_matches_frontend_contract(real_hive_models: None) -> None:
    options = detector_metadata.detection_algorithm_options("feeder")
    ids = {opt["id"] for opt in options}
    assert "hive:c-channel-yolo11n-320" in ids
    assert "hive:carousel-yolo11n-320" not in ids  # different UI scope
    assert "hive:chamber-yolo11n-320" not in ids  # filtered (scopes=None)
    for opt in options:
        assert isinstance(opt["id"], str)
        assert isinstance(opt["label"], str)
        assert isinstance(opt["needs_baseline"], bool)
        assert "description" in opt
        assert "default" in opt
    defaults = [opt for opt in options if opt["default"]]
    assert len(defaults) == 1
    assert defaults[0]["id"] == "hive:c-channel-yolo11n-320"


def test_invalidate_cache_reloads(
    real_hive_models: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Prime
    first = detector_metadata.all_detection_algorithms()
    assert first

    detector_metadata.invalidate_cache()
    calls: list[int] = []
    original = detector_metadata._index_hive_run_metadata

    def _tracking_index() -> dict[str, dict[str, object]]:
        calls.append(1)
        return original()

    monkeypatch.setattr(detector_metadata, "_index_hive_run_metadata", _tracking_index)

    second = detector_metadata.all_detection_algorithms()
    third = detector_metadata.all_detection_algorithms()

    assert len(calls) == 1, "Should re-read metadata exactly once after invalidate"
    assert {a.id for a in second} == {a.id for a in third}
