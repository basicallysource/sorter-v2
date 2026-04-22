"""Tests for the rt-bridging shim in ``vision/detection_registry.py``.

The shim reads ``rt.contracts.registry.DETECTORS`` + the Hive ``run.json``
blobs at ``backend/blob/hive_detection_models/`` to expose the legacy
detection-algorithm API used by ``server/routers/detection.py`` and the
Svelte settings dropdown.
"""

from __future__ import annotations

import sys
from pathlib import Path

# Backend root -> sys.path so ``vision.detection_registry`` imports when
# pytest is run from any cwd.
_BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(_BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(_BACKEND_ROOT))

import pytest  # noqa: E402

from vision import detection_registry  # noqa: E402


EXPECTED_HIVE_KEYS = {
    "hive:c-channel-yolo11n-320",
    "hive:carousel-yolo11n-320",
    "hive:chamber-nanodet-1.5x-416",
    "hive:chamber-yolo11n-320",
    "hive:classification-chamber-yolo11n-320",
}


@pytest.fixture(autouse=True)
def _reset_cache() -> None:
    """Ensure each test starts from a clean shim cache."""
    detection_registry.invalidate_registry()
    yield
    detection_registry.invalidate_registry()


def test_all_detection_algorithms_returns_5_hive_models() -> None:
    algos = detection_registry.all_detection_algorithms()
    ids = {algo.id for algo in algos}
    assert EXPECTED_HIVE_KEYS.issubset(ids), (
        f"Expected all 5 Hive detectors; got {sorted(ids)}"
    )
    # Only Hive detectors live in the registry right now.
    assert len(algos) >= 5


def test_default_is_c_channel_yolo_for_every_scope() -> None:
    for scope in ("feeder", "carousel", "classification"):
        assert (
            detection_registry.default_detection_algorithm(scope)
            == "hive:c-channel-yolo11n-320"
        )


def test_normalize_returns_input_when_valid() -> None:
    assert (
        detection_registry.normalize_detection_algorithm(
            "feeder", "hive:carousel-yolo11n-320"
        )
        == "hive:carousel-yolo11n-320"
    )


def test_normalize_returns_default_when_invalid() -> None:
    assert (
        detection_registry.normalize_detection_algorithm("feeder", "bogus")
        == "hive:c-channel-yolo11n-320"
    )


def test_normalize_returns_default_for_none() -> None:
    assert (
        detection_registry.normalize_detection_algorithm("feeder", None)
        == "hive:c-channel-yolo11n-320"
    )


def test_detection_algorithm_definition_returns_metadata() -> None:
    definition = detection_registry.detection_algorithm_definition(
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


def test_detection_algorithm_definition_unknown_returns_none() -> None:
    assert detection_registry.detection_algorithm_definition(None) is None
    assert detection_registry.detection_algorithm_definition("nope") is None


def test_scope_supports_detection_algorithm_accepts_all_hive_for_all_scopes() -> None:
    for scope in ("feeder", "carousel", "classification"):
        for key in EXPECTED_HIVE_KEYS:
            assert detection_registry.scope_supports_detection_algorithm(scope, key), (
                f"{key} should be accepted on {scope}"
            )
    assert not detection_registry.scope_supports_detection_algorithm("feeder", "nope")
    assert not detection_registry.scope_supports_detection_algorithm("feeder", None)


def test_options_includes_all_hive_models_with_frontend_shape() -> None:
    options = detection_registry.detection_algorithm_options("feeder")
    ids = {opt["id"] for opt in options}
    assert EXPECTED_HIVE_KEYS.issubset(ids)
    # The Svelte dropdown filters on these fields — every option must have them.
    for opt in options:
        assert isinstance(opt["id"], str)
        assert isinstance(opt["label"], str)
        assert isinstance(opt["needs_baseline"], bool)
        assert "description" in opt
        assert "default" in opt
    defaults = [opt for opt in options if opt["default"]]
    assert len(defaults) == 1
    assert defaults[0]["id"] == "hive:c-channel-yolo11n-320"


def test_algorithms_for_scope_matches_options() -> None:
    for scope in ("feeder", "carousel", "classification"):
        from_defs = {algo.id for algo in detection_registry.detection_algorithms_for_scope(scope)}
        from_options = {opt["id"] for opt in detection_registry.detection_algorithm_options(scope)}
        assert from_defs == from_options


def test_invalidate_clears_cache_and_forces_reload(monkeypatch: pytest.MonkeyPatch) -> None:
    # Prime the cache.
    first = detection_registry.all_detection_algorithms()
    assert first

    # After invalidate, a patched loader should be called again — proving we
    # aren't serving stale data.
    detection_registry.invalidate_registry()
    calls: list[int] = []

    original = detection_registry._index_hive_run_metadata

    def _tracking_index() -> dict[str, dict[str, object]]:
        calls.append(1)
        return original()

    monkeypatch.setattr(detection_registry, "_index_hive_run_metadata", _tracking_index)

    second = detection_registry.all_detection_algorithms()
    third = detection_registry.all_detection_algorithms()

    assert len(calls) == 1, "Should re-read metadata exactly once after invalidate"
    assert {algo.id for algo in second} == {algo.id for algo in third}
