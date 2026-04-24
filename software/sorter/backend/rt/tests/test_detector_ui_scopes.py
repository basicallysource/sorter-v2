"""Tests for detector scope metadata and UI-facing detector helpers."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from rt.contracts.registry import StrategyRegistry, default_detector_slug_for_ui_scope, ui_scopes_for_detector
from rt.perception import detector_metadata
from rt.perception.detectors import hive_onnx
from rt.perception.detectors.hive_onnx import discover_and_register_hive_detectors


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


def test_registry_stores_scopes_metadata_from_run_json(
    hive_registry: StrategyRegistry[Any],
) -> None:
    cases = {
        "hive:c-channel-yolo11n-320": ("c_channel",),
        "hive:chamber-yolo11n-320": (),
        "hive:chamber-nanodet-1.5x-416": (),
    }
    for slug, expected_scopes in cases.items():
        assert hive_registry.metadata(slug)["scopes"] == expected_scopes


@pytest.fixture
def real_hive_models() -> None:
    """Ensure the real Hive models from blob/ are registered globally."""
    models_dir = Path(__file__).resolve().parents[2] / "blob" / "hive_detection_models"
    if not models_dir.exists():
        pytest.skip("hive models not installed in this env")
    import rt.perception  # noqa: F401


def test_ui_scopes_for_detector(
    real_hive_models: None,
) -> None:
    cases = {
        "hive:c-channel-yolo11n-320": frozenset({"feeder", "classification_channel"}),
        "hive:carousel-yolo11n-320": frozenset({"carousel"}),
        "hive:classification-chamber-yolo11n-320": frozenset({"classification"}),
        "hive:chamber-yolo11n-320": frozenset(),
        "hive:chamber-nanodet-1.5x-416": frozenset(),
        "hive:does-not-exist": frozenset(),
    }
    for slug, expected in cases.items():
        assert ui_scopes_for_detector(slug) == expected


def test_default_detector_slug_for_ui_scope(
    real_hive_models: None,
) -> None:
    cases = {
        "feeder": "hive:c-channel-yolo11n-416",
        "classification_channel": "hive:c-channel-yolo11n-416",
        "carousel": "hive:carousel-yolo11n-320",
        "classification": "hive:classification-chamber-yolo11n-320",
        "": None,
        "bogus": None,
    }
    for scope, expected_slug in cases.items():
        assert default_detector_slug_for_ui_scope(scope) == expected_slug


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
    assert "hive:chamber-yolo11n-320" not in feeder_algos
    assert "hive:chamber-nanodet-1.5x-416" not in feeder_algos

    carousel_algos = {
        a.id for a in detector_metadata.detection_algorithms_for_scope("carousel")
    }
    assert carousel_algos == {"hive:carousel-yolo11n-320"}


def test_normalize_detection_algorithm(
    real_hive_models: None,
) -> None:
    cases = [
        ("feeder", "hive:c-channel-yolo11n-320", "hive:c-channel-yolo11n-320"),
        ("feeder", "hive:carousel-yolo11n-320", "hive:c-channel-yolo11n-416"),
        ("feeder", "bogus", "hive:c-channel-yolo11n-416"),
        ("feeder", None, "hive:c-channel-yolo11n-416"),
    ]
    for scope, selected, expected in cases:
        assert detector_metadata.normalize_detection_algorithm(scope, selected) == expected


def test_scope_supports_detection_algorithm(
    real_hive_models: None,
) -> None:
    cases = [
        ("feeder", "hive:c-channel-yolo11n-320", True),
        ("feeder", "hive:carousel-yolo11n-320", False),
        ("feeder", "hive:chamber-yolo11n-320", False),
        ("feeder", None, False),
    ]
    for scope, slug, expected in cases:
        assert detector_metadata.scope_supports_detection_algorithm(scope, slug) is expected


def test_options_shape_matches_frontend_contract(real_hive_models: None) -> None:
    options = detector_metadata.detection_algorithm_options("feeder")
    ids = {opt["id"] for opt in options}
    assert "hive:c-channel-yolo11n-320" in ids
    assert "hive:carousel-yolo11n-320" not in ids
    assert "hive:chamber-yolo11n-320" not in ids
    for opt in options:
        assert isinstance(opt["id"], str)
        assert isinstance(opt["label"], str)
        assert isinstance(opt["needs_baseline"], bool)
        assert "description" in opt
        assert "default" in opt
    defaults = [opt for opt in options if opt["default"]]
    assert len(defaults) == 1
    assert defaults[0]["id"] == "hive:c-channel-yolo11n-416"


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
