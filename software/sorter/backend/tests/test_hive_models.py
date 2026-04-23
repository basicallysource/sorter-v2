"""Tests for ``server.hive_models``.

These tests never hit the network — ``HiveClient.get_model`` and
``HiveClient.download_model_variant`` are stubbed via monkeypatch.
"""

from __future__ import annotations

import io
import json
import tarfile
import threading
from pathlib import Path
from typing import Any, Callable

import pytest

from server import hive_models


HiveError = hive_models.HiveError


# ---------------------------------------------------------------------------
# Runtime selection
# ---------------------------------------------------------------------------


class TestPickRuntime:
    def setup_method(self) -> None:
        hive_models._reset_hailo_cache_for_tests()

    def teardown_method(self) -> None:
        hive_models._reset_hailo_cache_for_tests()

    def test_empty_list_returns_none(self) -> None:
        assert hive_models.pick_runtime_for_this_machine([]) is None

    def test_prefers_hailo_when_available(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(hive_models, "_has_hailo", lambda: True)
        assert (
            hive_models.pick_runtime_for_this_machine(["onnx", "hailo", "ncnn"])
            == "hailo"
        )

    def test_ncnn_on_aarch64(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(hive_models, "_has_hailo", lambda: False)
        monkeypatch.setattr(hive_models.platform, "machine", lambda: "aarch64")
        assert (
            hive_models.pick_runtime_for_this_machine(["onnx", "ncnn", "pytorch"])
            == "ncnn"
        )

    def test_onnx_on_x86_64(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(hive_models, "_has_hailo", lambda: False)
        monkeypatch.setattr(hive_models.platform, "machine", lambda: "x86_64")
        assert (
            hive_models.pick_runtime_for_this_machine(["onnx", "ncnn", "pytorch"])
            == "onnx"
        )

    def test_pytorch_only_falls_back_to_pytorch(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(hive_models, "_has_hailo", lambda: False)
        monkeypatch.setattr(hive_models.platform, "machine", lambda: "x86_64")
        assert hive_models.pick_runtime_for_this_machine(["pytorch"]) == "pytorch"

    def test_hailo_not_selected_when_hardware_missing(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(hive_models, "_has_hailo", lambda: False)
        monkeypatch.setattr(hive_models.platform, "machine", lambda: "x86_64")
        # Hailo is offered but hardware isn't present — we should pick onnx.
        assert (
            hive_models.pick_runtime_for_this_machine(["hailo", "onnx"]) == "onnx"
        )


# ---------------------------------------------------------------------------
# DownloadJobManager
# ---------------------------------------------------------------------------


def _configure_target(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        hive_models,
        "resolve_targets",
        lambda: [
            {
                "id": "hive-a",
                "name": "Hive A",
                "url": "https://hive.example",
                "api_token": "token-xyz",
                "machine_id": None,
            }
        ],
    )


class _StubClient:
    """Stand-in for ``HiveClient`` recording the last call."""

    def __init__(
        self,
        *,
        detail: dict,
        downloader: Callable[..., str] | None = None,
    ) -> None:
        self._detail = detail
        self._downloader = downloader or (lambda *a, **kw: "deadbeef")
        self.downloaded: list[tuple[str, str, Path]] = []

    def get_model(self, model_id: str) -> dict:
        return self._detail

    def list_models(self, **_: Any) -> dict:
        return {"items": [], "total": 0, "page": 1, "page_size": 30, "pages": 0}

    def download_model_variant(
        self,
        model_id: str,
        variant_id: str,
        dest_path: Path,
        on_progress: Callable[[int, int], None] | None = None,
        expected_sha256: str | None = None,
    ) -> str:
        self.downloaded.append((model_id, variant_id, Path(dest_path)))
        return self._downloader(
            model_id, variant_id, Path(dest_path), on_progress, expected_sha256
        )


def _install_stub_client(
    monkeypatch: pytest.MonkeyPatch, stub: _StubClient
) -> None:
    def _factory(target_id: str) -> tuple[_StubClient, dict]:
        return stub, {
            "id": target_id,
            "name": "Hive",
            "url": "https://hive.example",
            "api_token": "token",
        }

    monkeypatch.setattr(hive_models, "_get_client_for_target", _factory)


def _make_detail(model_id: str = "model-1") -> dict:
    return {
        "id": model_id,
        "name": "Test Detector",
        "model_family": "yolo",
        "training_metadata": {"imgsz": 320, "epochs": 200},
        "variants": [
            {
                "id": "variant-onnx",
                "runtime": "onnx",
                "file_name": "detector.onnx",
                "file_size": 1234,
                "sha256": "expected-sha",
                "format_meta": {},
                "uploaded_at": "2026-04-01T00:00:00Z",
            }
        ],
    }


class TestDownloadJobManager:
    def test_happy_path_writes_file_and_run_json(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(hive_models, "LOCAL_MODELS_DIR", tmp_path)
        _configure_target(monkeypatch)

        detail = _make_detail()
        payload = b"fake-onnx-bytes"

        def _downloader(
            model_id: str,
            variant_id: str,
            dest_path: Path,
            on_progress: Callable[[int, int], None] | None,
            expected_sha256: str | None,
        ) -> str:
            dest_path.parent.mkdir(parents=True, exist_ok=True)
            dest_path.write_bytes(payload)
            if on_progress is not None:
                on_progress(len(payload), len(payload))
            assert expected_sha256 == "expected-sha"
            return "expected-sha"

        stub = _StubClient(detail=detail, downloader=_downloader)
        _install_stub_client(monkeypatch, stub)

        manager = hive_models.DownloadJobManager()
        job_id = manager.enqueue("hive-a", "model-1")

        final = manager.wait_for_terminal(job_id, timeout=5.0)
        assert final.get("status") == "done", final
        assert final.get("error") is None
        assert final.get("progress_bytes") == len(payload)

        dest_file = tmp_path / "hive-model-1" / "exports" / "detector.onnx"
        assert dest_file.exists()
        assert dest_file.read_bytes() == payload

        run_json_path = tmp_path / "hive-model-1" / "run.json"
        assert run_json_path.exists()
        run_json = json.loads(run_json_path.read_text())
        assert hive_models.HIVE_SENTINEL_KEY in run_json
        sentinel = run_json[hive_models.HIVE_SENTINEL_KEY]
        assert sentinel["target_id"] == "hive-a"
        assert sentinel["model_id"] == "model-1"
        assert sentinel["variant_runtime"] == "onnx"
        assert sentinel["sha256"] == "expected-sha"
        # Training metadata + name/family carry over for installed-model UI.
        assert run_json.get("name") == "Test Detector"
        assert run_json.get("model_family") == "yolo"
        assert run_json.get("imgsz") == 320

        # And it should show up under list_installed_models().
        installed = hive_models.list_installed_models()
        assert len(installed) == 1
        assert installed[0]["local_id"] == "hive-model-1"
        assert installed[0]["target_id"] == "hive-a"

    def test_sha_mismatch_is_captured_as_failure(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(hive_models, "LOCAL_MODELS_DIR", tmp_path)
        _configure_target(monkeypatch)

        def _downloader(*_args: Any, **_kwargs: Any) -> str:
            raise HiveError(500, "SHA256 mismatch on download", "SHA256_MISMATCH")

        stub = _StubClient(detail=_make_detail(), downloader=_downloader)
        _install_stub_client(monkeypatch, stub)

        manager = hive_models.DownloadJobManager()
        job_id = manager.enqueue("hive-a", "model-1")

        final = manager.wait_for_terminal(job_id, timeout=5.0)
        assert final.get("status") == "failed"
        assert "SHA256 mismatch" in (final.get("error") or "")

        # No run.json should have been written on mismatch.
        assert not (tmp_path / "hive-model-1" / "run.json").exists()

    def test_ncnn_tarball_is_extracted_in_place(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(hive_models, "LOCAL_MODELS_DIR", tmp_path)
        _configure_target(monkeypatch)

        detail = _make_detail()
        detail["variants"] = [
            {
                "id": "variant-ncnn",
                "runtime": "ncnn",
                "file_name": "detector.tar.gz",
                "file_size": 1234,
                "sha256": "expected-sha",
                "format_meta": {},
                "uploaded_at": "2026-04-01T00:00:00Z",
            }
        ]

        def _downloader(
            model_id: str,
            variant_id: str,
            dest_path: Path,
            on_progress: Callable[[int, int], None] | None,
            expected_sha256: str | None,
        ) -> str:
            dest_path.parent.mkdir(parents=True, exist_ok=True)
            with tarfile.open(dest_path, "w:gz") as tar:
                payload = b"fake-ncnn-model"
                model_info = tarfile.TarInfo("best_ncnn_model/model.bin")
                model_info.size = len(payload)
                tar.addfile(model_info, io.BytesIO(payload))
            if on_progress is not None:
                size = dest_path.stat().st_size
                on_progress(size, size)
            assert expected_sha256 == "expected-sha"
            return "expected-sha"

        stub = _StubClient(detail=detail, downloader=_downloader)
        _install_stub_client(monkeypatch, stub)

        manager = hive_models.DownloadJobManager()
        job_id = manager.enqueue("hive-a", "model-1")

        final = manager.wait_for_terminal(job_id, timeout=5.0)
        assert final.get("status") == "done", final
        assert (tmp_path / "hive-model-1" / "exports" / "best_ncnn_model" / "model.bin").exists()

    def test_ncnn_tarball_rejects_path_traversal(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(hive_models, "LOCAL_MODELS_DIR", tmp_path)
        _configure_target(monkeypatch)

        detail = _make_detail()
        detail["variants"] = [
            {
                "id": "variant-ncnn",
                "runtime": "ncnn",
                "file_name": "detector.tar.gz",
                "file_size": 1234,
                "sha256": "expected-sha",
                "format_meta": {},
                "uploaded_at": "2026-04-01T00:00:00Z",
            }
        ]

        outside_target = tmp_path / "outside.txt"

        def _downloader(
            model_id: str,
            variant_id: str,
            dest_path: Path,
            on_progress: Callable[[int, int], None] | None,
            expected_sha256: str | None,
        ) -> str:
            dest_path.parent.mkdir(parents=True, exist_ok=True)
            with tarfile.open(dest_path, "w:gz") as tar:
                payload = b"nope"
                member = tarfile.TarInfo("../outside.txt")
                member.size = len(payload)
                tar.addfile(member, io.BytesIO(payload))
            if on_progress is not None:
                size = dest_path.stat().st_size
                on_progress(size, size)
            assert expected_sha256 == "expected-sha"
            return "expected-sha"

        stub = _StubClient(detail=detail, downloader=_downloader)
        _install_stub_client(monkeypatch, stub)

        manager = hive_models.DownloadJobManager()
        job_id = manager.enqueue("hive-a", "model-1")

        final = manager.wait_for_terminal(job_id, timeout=5.0)
        assert final.get("status") == "failed", final
        assert "unsafe archive member" in (final.get("error") or "")
        assert not outside_target.exists()

    def test_no_matching_variant_fails_fast(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(hive_models, "LOCAL_MODELS_DIR", tmp_path)
        _configure_target(monkeypatch)
        stub = _StubClient(detail=_make_detail())
        _install_stub_client(monkeypatch, stub)

        manager = hive_models.DownloadJobManager()
        job_id = manager.enqueue("hive-a", "model-1", variant_runtime="hailo")

        with hive_models._job_manager_lock if False else threading.Lock():
            pass
        final = manager.wait_for_terminal(job_id, timeout=1.0)
        assert final.get("status") == "failed"
        assert "no variant" in (final.get("error") or "").lower()


# ---------------------------------------------------------------------------
# remove_installed_model path safety
# ---------------------------------------------------------------------------


class TestRemoveInstalledModel:
    def test_rejects_path_traversal(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(hive_models, "LOCAL_MODELS_DIR", tmp_path)

        # Create a sibling directory outside LOCAL_MODELS_DIR we do NOT want
        # deleted.
        outside = tmp_path.parent / "outside_dir"
        outside.mkdir(exist_ok=True)
        sentinel_file = outside / "precious.txt"
        sentinel_file.write_text("do not delete")

        with pytest.raises(ValueError):
            hive_models.remove_installed_model("../outside_dir")

        assert sentinel_file.exists(), "traversal path must not touch sibling dir"
        assert outside.exists()

    def test_rejects_absolute_path(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(hive_models, "LOCAL_MODELS_DIR", tmp_path)
        with pytest.raises(ValueError):
            hive_models.remove_installed_model("/etc")

    def test_missing_dir_raises_filenotfounderror(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(hive_models, "LOCAL_MODELS_DIR", tmp_path)
        with pytest.raises(FileNotFoundError):
            hive_models.remove_installed_model("hive-does-not-exist")

    def test_removes_valid_directory(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(hive_models, "LOCAL_MODELS_DIR", tmp_path)
        target = tmp_path / "hive-abc"
        (target / "exports").mkdir(parents=True)
        (target / "run.json").write_text("{}")
        hive_models.remove_installed_model("hive-abc")
        assert not target.exists()
