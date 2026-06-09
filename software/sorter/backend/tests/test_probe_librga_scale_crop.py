from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "probe_librga_scale_crop.py"


def _load_probe_module():
    spec = importlib.util.spec_from_file_location("probe_librga_scale_crop", SCRIPT_PATH)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_librga_probe_reports_successful_runtime(monkeypatch, tmp_path) -> None:
    module = _load_probe_module()
    monkeypatch.setattr(module.shutil, "which", lambda name: f"/usr/bin/{name}")

    def fake_runner(args, **kwargs):
        if "pkg-config" in args[0]:
            return module.CommandResult(returncode=0, stdout="-I/usr/include -lrga\n")
        if args[0].endswith("cc"):
            return module.CommandResult(returncode=0)
        return module.CommandResult(
            returncode=0,
            stdout=(
                "720p_to_yolo resize=1 crop=1 crop_scale=1 resize_sum=1 crop_sum=1 crop_scale_sum=1\n"
                "4k_to_yolo resize=1 crop=1 crop_scale=1 resize_sum=1 crop_sum=1 crop_scale_sum=1\n"
            ),
        )

    report = module.build_probe_report(runner=fake_runner)

    assert report["ok"] is True
    assert report["runtime_ready"] is True
    assert report["input_memory"] == "virtualaddr"
    assert report["pixel_format"] == "NV12"
    assert report["operations"] == {"resize": True, "crop": True, "crop_scale": True}
    assert [case["name"] for case in report["tested_cases"]] == ["720p_to_yolo", "4k_to_yolo"]


def test_librga_probe_reports_missing_pkg_config(monkeypatch) -> None:
    module = _load_probe_module()
    monkeypatch.setattr(
        module.shutil,
        "which",
        lambda name: "/usr/bin/cc" if name == "cc" else None,
    )

    report = module.build_probe_report()

    assert report["ok"] is False
    assert report["available"] is False
    assert report["reason"] == "pkg-config is not available."
