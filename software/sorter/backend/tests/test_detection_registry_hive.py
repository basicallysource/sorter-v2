"""Unit tests for the installed-model entries (Hive and local) in ``vision.detection_registry``."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from vision import detection_registry as registry


@pytest.fixture(autouse=True)
def _reset_registry():
    registry.invalidate_registry()
    yield
    registry.invalidate_registry()


def _seed_hive_model(
    tmp_path: Path,
    *,
    name: str,
    model_family: str,
    scopes: list[str],
    imgsz: int = 320,
    purpose: str | None = None,
) -> Path:
    entry = tmp_path / f"hive-{name}"
    (entry / "exports").mkdir(parents=True)
    (entry / "exports" / "best.onnx").write_bytes(b"not a real onnx")
    hive_meta = {
        "target_id": "target-1",
        "model_id": "abc",
        "variant_runtime": "onnx",
        "sha256": "deadbeef",
        "downloaded_at": "2026-04-17T00:00:00+00:00",
    }
    if purpose is not None:
        hive_meta["purpose"] = purpose
    meta = {
        "name": name,
        "model_family": model_family,
        "scopes": scopes,
        "imgsz": imgsz,
        "hive": hive_meta,
    }
    (entry / "run.json").write_text(json.dumps(meta))
    return entry


def test_hive_model_appears_in_registry(tmp_path, monkeypatch):
    monkeypatch.setattr(registry, "MODELS_DIR", tmp_path)
    _seed_hive_model(tmp_path, name="chamber-yolo", model_family="yolo", scopes=["classification_chamber"])
    registry.invalidate_registry()

    all_algos = registry.all_detection_algorithms()
    ids = [a.id for a in all_algos]
    assert any(a.startswith("hive:") for a in ids), ids

    classification = registry.detection_algorithms_for_scope("classification")
    hive_entries = [a for a in classification if a.kind == "hive"]
    assert len(hive_entries) == 1
    assert hive_entries[0].model_family == "yolo"
    assert hive_entries[0].imgsz == 320


def test_unsupported_family_is_skipped(tmp_path, monkeypatch):
    monkeypatch.setattr(registry, "MODELS_DIR", tmp_path)
    _seed_hive_model(tmp_path, name="exotic", model_family="detr", scopes=["classification_chamber"])
    registry.invalidate_registry()

    ids = [a.id for a in registry.all_detection_algorithms()]
    assert not any(a.startswith("hive:") for a in ids)


def test_non_detection_purpose_is_skipped(tmp_path, monkeypatch):
    """Hive publishes several purposes into one catalog and the sorter installs
    them all the same way. Only detection models become detection algorithms."""
    monkeypatch.setattr(registry, "MODELS_DIR", tmp_path)
    _seed_hive_model(
        tmp_path,
        name="link-v3",
        model_family="piece_link_matcher",
        scopes=[],
        purpose="piece_link",
    )
    registry.invalidate_registry()

    ids = [a.id for a in registry.all_detection_algorithms()]
    assert not any(a.startswith("hive:") for a in ids)


def test_absent_purpose_reads_as_detection(tmp_path, monkeypatch):
    """Models installed before Hive grew the field predate any other purpose."""
    monkeypatch.setattr(registry, "MODELS_DIR", tmp_path)
    _seed_hive_model(
        tmp_path, name="legacy", model_family="yolo", scopes=["classification_chamber"]
    )
    registry.invalidate_registry()

    ids = [a.id for a in registry.all_detection_algorithms()]
    assert any(a.startswith("hive:") for a in ids), ids


def test_scope_mapping_feeder(tmp_path, monkeypatch):
    monkeypatch.setattr(registry, "MODELS_DIR", tmp_path)
    _seed_hive_model(tmp_path, name="c-chan", model_family="nanodet", scopes=["c_channel"])
    registry.invalidate_registry()

    feeder = registry.detection_algorithms_for_scope("feeder")
    assert any(a.kind == "hive" for a in feeder)
    classification = registry.detection_algorithms_for_scope("classification")
    assert all(a.kind == "builtin" for a in classification)


@pytest.mark.parametrize(
    "scope",
    [
        "classification_channel",
        "classification-channel",
        "c4",
        "c4_sector",
        "c4-sector",
        "sector_yolo",
    ],
)
def test_scope_mapping_c4_sector_model_to_carousel(tmp_path, monkeypatch, scope):
    monkeypatch.setattr(registry, "MODELS_DIR", tmp_path)
    _seed_hive_model(tmp_path, name=f"{scope}-model", model_family="yolo", scopes=[scope])
    registry.invalidate_registry()

    carousel = registry.detection_algorithms_for_scope("carousel")
    hive_entries = [a for a in carousel if a.kind == "hive"]
    assert len(hive_entries) == 1
    assert hive_entries[0].model_family == "yolo"

    feeder = registry.detection_algorithms_for_scope("feeder")
    assert all(a.kind == "builtin" for a in feeder)


def test_invalidate_after_adding(tmp_path, monkeypatch):
    monkeypatch.setattr(registry, "MODELS_DIR", tmp_path)
    registry.invalidate_registry()
    assert not any(a.kind == "hive" for a in registry.all_detection_algorithms())

    _seed_hive_model(tmp_path, name="late", model_family="yolo", scopes=["classification_chamber"])
    # Without invalidation the cache should still be empty.
    assert not any(a.kind == "hive" for a in registry.all_detection_algorithms())
    registry.invalidate_registry()
    assert any(a.kind == "hive" for a in registry.all_detection_algorithms())


def _seed_local_model(tmp_path: Path, name: str, meta: dict, artifact: str | None = "best.onnx") -> Path:
    entry = tmp_path / name
    (entry / "exports").mkdir(parents=True)
    if artifact is not None:
        (entry / "exports" / artifact).write_bytes(b"x")
    (entry / "run.json").write_text(json.dumps(meta))
    return entry


def test_local_model_without_hive_block_is_registered(tmp_path, monkeypatch):
    """A directory someone put in the models dir by hand, with a run.json that
    has no hive block, is a local model."""
    monkeypatch.setattr(registry, "MODELS_DIR", tmp_path)
    _seed_local_model(
        tmp_path,
        "my-c-channel",
        {"name": "my c-channel", "model_family": "yolo", "scopes": ["c_channel"], "imgsz": 416},
    )
    registry.invalidate_registry()

    definition = registry.detection_algorithm_definition("local:my-c-channel")
    assert definition is not None
    assert definition.kind == "local"
    assert definition.label == "Local · my c-channel"
    assert definition.runtime == "onnx"
    assert definition.model_path == tmp_path / "my-c-channel" / "exports" / "best.onnx"
    assert definition.supported_scopes == frozenset({"feeder"})
    assert definition.imgsz == 416
    assert definition.hive_metadata is None


def test_local_model_uses_declared_runtime(tmp_path, monkeypatch):
    monkeypatch.setattr(registry, "MODELS_DIR", tmp_path)
    entry = _seed_local_model(
        tmp_path, "npu-model", {"model_family": "yolo", "runtime": "rknn"}, artifact="model.rknn"
    )
    # An onnx export next to it must not win over the declared runtime.
    (entry / "exports" / "best.onnx").write_bytes(b"x")
    registry.invalidate_registry()

    definition = registry.detection_algorithm_definition("local:npu-model")
    assert definition is not None
    assert definition.runtime == "rknn"
    assert definition.model_path == entry / "exports" / "model.rknn"
    # No scopes in run.json: usable everywhere.
    assert definition.supported_scopes == frozenset({"classification", "feeder", "carousel"})


def test_local_model_infers_runtime_from_artifact(tmp_path, monkeypatch):
    monkeypatch.setattr(registry, "MODELS_DIR", tmp_path)
    _seed_local_model(tmp_path, "hef-model", {"model_family": "yolo"}, artifact="model.hef")
    registry.invalidate_registry()

    definition = registry.detection_algorithm_definition("local:hef-model")
    assert definition is not None
    assert definition.runtime == "hailo"


@pytest.mark.parametrize(
    "meta,artifact",
    [
        ({"scopes": []}, "best.onnx"),  # no model_family
        ({"model_family": "detr"}, "best.onnx"),  # unsupported family
        ({"model_family": "yolo", "runtime": "rknn"}, "best.onnx"),  # declared runtime, no artifact
        ({"model_family": "yolo", "runtime": "pytorch"}, "best.pt"),  # runtime the sorter can't load
        ({"model_family": "yolo"}, None),  # nothing under exports/
    ],
)
def test_unusable_local_model_is_skipped(tmp_path, monkeypatch, meta, artifact):
    monkeypatch.setattr(registry, "MODELS_DIR", tmp_path)
    _seed_local_model(tmp_path, "not-a-model", meta, artifact=artifact)
    registry.invalidate_registry()

    assert not any(a.kind in {"hive", "local"} for a in registry.all_detection_algorithms())


def test_installed_models_are_never_the_default(tmp_path, monkeypatch):
    """With nothing assigned, the built-ins are the fallback — never an
    arbitrary installed model."""
    monkeypatch.setattr(registry, "MODELS_DIR", tmp_path)
    _seed_hive_model(tmp_path, name="c-chan", model_family="yolo", scopes=["c_channel"])
    _seed_local_model(tmp_path, "local-any", {"model_family": "yolo"})
    registry.invalidate_registry()

    assert registry.default_detection_algorithm("feeder") == "mog2"
    assert registry.default_detection_algorithm("classification") == "baseline_diff"
    assert registry.default_detection_algorithm("carousel") == "heatmap_diff"
    assert registry.normalize_detection_algorithm("feeder", "bundled:gone") == "mog2"
