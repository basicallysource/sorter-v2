"""Tests for ``server.default_model``: Hive's default detection model, installed
and assigned when a slot has none. ``HiveClient`` is replaced by a fake, so no
test touches the network."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
import requests

import basically_services
from server import default_model, hive_models, shared_state
from toml_config import getDetectionConfig, setDetectionConfig
from vision import detection_registry


C2 = ("feeder", "c_channel_2")
C3 = ("feeder", "c_channel_3")


def _default_item(model_id: str, runtime: str, file_name: str, sha: str = "sha-default") -> dict:
    return {
        "purpose": "detection",
        "runtime": runtime,
        "model": {
            "id": model_id,
            "name": f"Default {model_id}",
            "model_family": "yolo",
            "scopes": ["c_channel"],
            "purpose": "detection",
            "codename": "Ember",
            "codename_color": "#E25822",
            "training_metadata": {"imgsz": 320},
        },
        "variant": {
            "id": f"variant-{runtime}",
            "runtime": runtime,
            "file_name": file_name,
            "file_size": 5,
            "sha256": sha,
            "format_meta": {},
        },
        "download_path": f"/api/model-defaults/detection/{runtime}/download",
        "updated_at": "2026-09-23T00:00:00Z",
    }


class FakeHive:
    """Stands in for ``HiveClient``: per-runtime defaults, 404 for the rest."""

    def __init__(self, defaults: dict[str, dict]) -> None:
        self.defaults = defaults
        self.urls: list[str] = []
        self.asked: list[str] = []
        self.downloads: list[str] = []
        self.fail_next: list[Exception] = []

    def __call__(self, url: str, api_token: str | None = None) -> "FakeHive":
        self.urls.append(url)
        return self

    def get_default_model(self, purpose: str, runtime: str) -> dict:
        assert purpose == "detection"
        if self.fail_next:
            raise self.fail_next.pop(0)
        self.asked.append(runtime)
        if runtime not in self.defaults:
            raise hive_models.HiveError(404, "no default", "MODEL_DEFAULT_NOT_SET")
        return self.defaults[runtime]

    def download_default_model(
        self, purpose: str, runtime: str, dest_path: Path, on_progress=None, expected_sha256=None
    ) -> str:
        self.downloads.append(runtime)
        dest_path = Path(dest_path)
        dest_path.parent.mkdir(parents=True, exist_ok=True)
        dest_path.write_bytes(b"model")
        if on_progress is not None:
            on_progress(5, 5)
        return expected_sha256 or "sha-default"


class NoNetwork:
    def __call__(self, *args: Any, **kwargs: Any):
        raise AssertionError("no Hive call expected")


class RecordingLogger:
    def __init__(self) -> None:
        self.infos: list[str] = []
        self.warnings: list[str] = []

    def info(self, msg: str) -> None:
        self.infos.append(msg)

    def warning(self, msg: str) -> None:
        self.warnings.append(msg)


@pytest.fixture
def models_dir(_isolate_installed_models_dir: Path) -> Path:
    return _isolate_installed_models_dir


@pytest.fixture(autouse=True)
def _machine(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("MACHINE_SPECIFIC_PARAMS_PATH", str(tmp_path / "machine_params.toml"))
    monkeypatch.setattr(shared_state, "vision_manager", None)
    monkeypatch.setattr(shared_state, "gc_ref", None)
    monkeypatch.setattr(
        hive_models, "compatible_runtimes_for_this_machine", lambda: ["rknn", "ncnn", "onnx"]
    )
    hive_models._reset_job_manager_for_tests()
    yield
    hive_models._reset_job_manager_for_tests()


def _assigned(scope: str, role: str | None = None) -> str | None:
    cfg = getDetectionConfig(scope) or {}
    if role is None:
        return cfg.get("algorithm")
    return (cfg.get("algorithm_by_role") or {}).get(role)


def _seed_hive_model(
    root: Path,
    model_id: str,
    runtime: str,
    *,
    installed_as_default: bool = False,
    sha: str = "sha-default",
    downloaded_at: str = "2026-09-01T00:00:00+00:00",
) -> str:
    local_id = f"hive-{model_id}-{runtime}"
    exports = root / local_id / "exports"
    exports.mkdir(parents=True)
    artifact = {"rknn": "model.rknn", "onnx": "best.onnx"}[runtime]
    (exports / artifact).write_bytes(b"model")
    (root / local_id / "run.json").write_text(
        json.dumps(
            {
                "name": f"Model {model_id}",
                "model_family": "yolo",
                "hive": {
                    "target_id": None,
                    "model_id": model_id,
                    "variant_runtime": runtime,
                    "sha256": sha,
                    "downloaded_at": downloaded_at,
                    "installed_as_default": installed_as_default,
                },
            }
        )
    )
    detection_registry.invalidate_registry()
    return f"hive:{local_id}"


def test_fresh_install_downloads_the_default_and_assigns_it_to_every_slot(
    models_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    hive = FakeHive({"rknn": _default_item("m1", "rknn", "r5.rknn", sha="sha-r5")})
    monkeypatch.setattr(hive_models, "HiveClient", hive)
    logger = RecordingLogger()

    assert [slot["label"] for slot in default_model.slots_needing_model()] == [
        "C-Channel 2",
        "C-Channel 3",
        "Classification C-Channel (C4)",
    ]

    assert default_model.DefaultModelInstaller(logger).run_once() is True

    algorithm_id = "hive:hive-m1-rknn"
    assert _assigned(*C2) == algorithm_id
    assert _assigned(*C3) == algorithm_id
    assert _assigned("carousel") == algorithm_id
    assert default_model.slots_needing_model() == []

    # Asked the main Hive, no account, and downloaded through the job queue.
    assert hive.urls and set(hive.urls) == {basically_services._endpoint()}
    assert hive.asked == ["rknn"]
    assert hive.downloads == ["rknn"]
    jobs = hive_models.get_job_manager().snapshot()
    assert [(job["model_id"], job["status"]) for job in jobs] == [("m1", "done")]

    hive_block = json.loads((models_dir / "hive-m1-rknn" / "run.json").read_text())["hive"]
    assert hive_block["installed_as_default"] is True
    assert hive_block["source_url"] == basically_services._endpoint()
    assert hive_block["target_id"] is None
    assert hive_block["sha256"] == "sha-r5"

    (entry,) = hive_models.list_installed_models()
    assert entry["source"] == "hive"
    assert entry["source_url"] == basically_services._endpoint()
    assert entry["codename"] == "Ember"

    assert logger.infos == [
        "Installed Hive default detection model Default m1 (rknn) and assigned it to: "
        "C-Channel 2, C-Channel 3, Classification C-Channel (C4)"
    ]


def test_every_slot_of_a_carousel_setup_is_filled(
    models_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from toml_config import _update_toml

    _update_toml(lambda cfg: cfg.update({"machine_setup": {"type": "standard_carousel"}}))
    monkeypatch.setattr(
        hive_models, "HiveClient", FakeHive({"rknn": _default_item("m1", "rknn", "r5.rknn")})
    )

    default_model.DefaultModelInstaller(RecordingLogger()).run_once()

    algorithm_id = "hive:hive-m1-rknn"
    assert _assigned("classification") == algorithm_id
    assert _assigned(*C2) == algorithm_id
    assert _assigned(*C3) == algorithm_id
    assert _assigned("feeder", "carousel") == algorithm_id
    assert _assigned("carousel") == algorithm_id


def test_only_slots_without_a_resolvable_model_are_filled(
    models_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    existing = _seed_hive_model(models_dir, "chosen", "onnx")
    setDetectionConfig(
        "feeder",
        {
            "algorithm": "mog2",
            # A model from before models came from Hive: no longer resolves.
            "algorithm_by_role": {"c_channel_2": "bundled:r4-c-channel-yolo11s-320-silu", "c_channel_3": "mog2"},
        },
    )
    setDetectionConfig("carousel", {"algorithm": existing})
    monkeypatch.setattr(
        hive_models, "HiveClient", FakeHive({"rknn": _default_item("m1", "rknn", "r5.rknn")})
    )

    assert [slot["label"] for slot in default_model.slots_needing_model()] == ["C-Channel 2"]

    default_model.DefaultModelInstaller(RecordingLogger()).run_once()

    assert _assigned(*C2) == "hive:hive-m1-rknn"
    assert _assigned(*C3) == "mog2"  # the operator's explicit built-in
    assert _assigned("carousel") == existing  # an installed model that resolves
    assert getDetectionConfig("feeder")["algorithm"] == "mog2"


def test_nothing_to_do_means_no_network(models_dir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    setDetectionConfig(
        "feeder", {"algorithm_by_role": {"c_channel_2": "mog2", "c_channel_3": "gemini_sam"}}
    )
    setDetectionConfig("carousel", {"algorithm": "heatmap_diff"})
    monkeypatch.setattr(hive_models, "HiveClient", NoNetwork())

    assert default_model.DefaultModelInstaller(RecordingLogger()).run_once() is True
    assert hive_models.get_job_manager().snapshot() == []


def test_runtime_falls_back_in_order_on_404(models_dir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    hive = FakeHive({"onnx": _default_item("m2", "onnx", "best.onnx")})
    monkeypatch.setattr(hive_models, "HiveClient", hive)

    default_model.DefaultModelInstaller(RecordingLogger()).run_once()

    assert hive.asked == ["rknn", "ncnn", "onnx"]
    assert _assigned(*C2) == "hive:hive-m2-onnx"


def test_no_default_for_any_runtime_raises(models_dir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(hive_models, "HiveClient", FakeHive({}))

    with pytest.raises(default_model.NoDefaultModel):
        default_model.DefaultModelInstaller(RecordingLogger()).run_once()
    assert _assigned(*C2) is None


def test_reuses_a_default_installed_before_without_asking_hive(
    models_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    older = _seed_hive_model(
        models_dir, "old", "rknn", installed_as_default=True, downloaded_at="2026-08-01T00:00:00+00:00"
    )
    newer = _seed_hive_model(
        models_dir, "new", "rknn", installed_as_default=True, downloaded_at="2026-09-01T00:00:00+00:00"
    )
    _seed_hive_model(models_dir, "cpu", "onnx", installed_as_default=True)
    # Downloaded by hand, not as a default: never picked on its own.
    _seed_hive_model(models_dir, "manual", "rknn", downloaded_at="2026-09-20T00:00:00+00:00")
    monkeypatch.setattr(hive_models, "HiveClient", NoNetwork())
    logger = RecordingLogger()

    default_model.DefaultModelInstaller(logger).run_once()

    assert older != newer
    assert _assigned(*C2) == newer  # best runtime, newest download
    assert _assigned("carousel") == newer
    assert logger.infos[0].startswith("Assigned Hive default detection model Model new (rknn, already installed)")


def test_the_same_default_already_downloaded_is_not_downloaded_again(
    models_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    installed = _seed_hive_model(models_dir, "m1", "rknn", sha="sha-r5")
    hive = FakeHive({"rknn": _default_item("m1", "rknn", "r5.rknn", sha="sha-r5")})
    monkeypatch.setattr(hive_models, "HiveClient", hive)

    default_model.DefaultModelInstaller(RecordingLogger()).run_once()

    assert hive.asked == ["rknn"]
    assert hive.downloads == []
    assert _assigned(*C3) == installed


def test_network_error_is_logged_once_and_retried(
    models_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    hive = FakeHive({"rknn": _default_item("m1", "rknn", "r5.rknn")})
    hive.fail_next = [requests.ConnectionError("hive unreachable")]
    monkeypatch.setattr(hive_models, "HiveClient", hive)
    logger = RecordingLogger()
    installer = default_model.DefaultModelInstaller(logger)
    sleeps: list[float] = []
    monkeypatch.setattr(installer, "_sleep", sleeps.append)

    installer._loop()

    assert sleeps == [default_model.RETRY_INTERVAL_S]
    assert len(logger.warnings) == 1
    assert "hive unreachable" in logger.warnings[0]
    assert _assigned(*C2) == "hive:hive-m1-rknn"
    assert len(logger.infos) == 1


def test_the_loop_stops_once_no_slot_needs_a_model(
    models_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(hive_models, "HiveClient", FakeHive({}))
    installer = default_model.DefaultModelInstaller(RecordingLogger())

    def _operator_picks_models(_seconds: float) -> None:
        setDetectionConfig(
            "feeder", {"algorithm_by_role": {"c_channel_2": "mog2", "c_channel_3": "mog2"}}
        )
        setDetectionConfig("carousel", {"algorithm": "heatmap_diff"})

    monkeypatch.setattr(installer, "_sleep", _operator_picks_models)

    installer._loop()  # returns: after one failed attempt nothing needs a model

    assert _assigned(*C2) == "mog2"
