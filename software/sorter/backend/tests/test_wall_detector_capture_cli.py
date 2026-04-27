"""Argparse + import smoke for ``scripts/wall_detector_capture.py``.

The full capture loop hits a live websocket and the
``sample_transport`` HTTP API, so the actual end-to-end exercise is
operator-side (with the rotor installed). These tests just verify
the CLI is wired correctly: arg validation rejects bad inputs and
the module imports cleanly so the operator hits real errors instead
of import failures during the install pass.
"""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest


_SCRIPT_PATH = (
    Path(__file__).resolve().parents[1]
    / "scripts"
    / "wall_detector_capture.py"
)


def _load_module():
    spec = importlib.util.spec_from_file_location(
        "wall_detector_capture", _SCRIPT_PATH
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_module_imports_cleanly() -> None:
    module = _load_module()
    # Sanity: the public entry points exist.
    assert callable(module.main)
    assert callable(module._capture_loop)
    assert callable(module._start_c4_sample_transport)
    assert callable(module._cancel_c4_sample_transport)


def test_default_constants_are_sensible() -> None:
    module = _load_module()
    assert module.DEFAULT_C4_CAMERA_INDEX == 0
    assert module.DEFAULT_C4_RPM == 1.0
    assert module.DEFAULT_FRAME_PERIOD_S == 0.5
    assert module.DEFAULT_DURATION_S > 0


def test_cli_help_includes_required_args() -> None:
    """``--help`` mentions the operator-facing flags so the workflow doc
    matches the implementation."""
    result = subprocess.run(
        [sys.executable, str(_SCRIPT_PATH), "--help"],
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0
    out = result.stdout
    for flag in (
        "--output-dir",
        "--duration-s",
        "--frame-period-s",
        "--c4-rpm",
        "--camera-index",
        "--skip-hardware-check",
    ):
        assert flag in out, f"CLI help missing {flag}"


@pytest.mark.parametrize(
    ("flag", "value"),
    [
        ("--duration-s", "0"),
        ("--duration-s", "-1"),
        ("--frame-period-s", "0"),
    ],
)
def test_cli_rejects_nonpositive_durations(flag: str, value: str, tmp_path: Path) -> None:
    """Non-positive durations or frame periods would otherwise spin
    forever or never trigger a frame save. Reject upfront so the
    operator gets immediate feedback."""
    result = subprocess.run(
        [
            sys.executable,
            str(_SCRIPT_PATH),
            "--output-dir",
            str(tmp_path / "should_not_create"),
            flag,
            value,
            "--skip-hardware-check",
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0
    assert "must be > 0" in result.stderr
