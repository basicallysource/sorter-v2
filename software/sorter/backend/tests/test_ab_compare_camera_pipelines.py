from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "ab_compare_camera_pipelines.py"
SPEC = importlib.util.spec_from_file_location("ab_compare_camera_pipelines", SCRIPT_PATH)
assert SPEC is not None and SPEC.loader is not None
ab = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = ab
SPEC.loader.exec_module(ab)


def test_modes_cover_both_pipelines_with_opposite_switches() -> None:
    legacy = ab.MODES["legacy"]
    rkmpp = ab.MODES["rkmpp"]
    assert legacy["SORTER_ENABLE_FFMPEG_RKMPP_WEBRTC"] == "0"
    assert rkmpp["SORTER_ENABLE_FFMPEG_RKMPP_WEBRTC"] == "1"
    assert legacy["SORTER_CAMERA_CAPTURE_BACKEND"] == "opencv"
    assert rkmpp["SORTER_CAMERA_CAPTURE_BACKEND"] == "gstreamer_mpp"
    assert set(legacy) == set(rkmpp)


def test_apply_env_block_appends_after_existing_content(tmp_path: Path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text("SORTER_ENABLE_FFMPEG_RKMPP_WEBRTC=1\nOTHER=x\n")

    ab.apply_env_block(env_file, ab.MODES["legacy"])

    text = env_file.read_text()
    # The block must come after the firstboot contract env so that sourcing
    # the file lets the benchmark values win.
    assert text.index("OTHER=x") < text.index(ab.ENV_BLOCK_BEGIN)
    assert "SORTER_CAMERA_CAPTURE_BACKEND=opencv" in text
    assert text.rstrip().endswith(ab.ENV_BLOCK_END)


def test_apply_env_block_is_idempotent_and_strippable(tmp_path: Path) -> None:
    env_file = tmp_path / ".env"
    original = "KEEP=1\n"
    env_file.write_text(original)

    ab.apply_env_block(env_file, ab.MODES["rkmpp"])
    ab.apply_env_block(env_file, ab.MODES["legacy"])

    text = env_file.read_text()
    assert text.count(ab.ENV_BLOCK_BEGIN) == 1
    assert "gstreamer_mpp" not in text  # second apply replaced the first block

    assert ab.strip_env_block(text) == original


def test_strip_env_block_without_block_is_identity() -> None:
    text = "A=1\nB=2\n"
    assert ab.strip_env_block(text) == text


def test_parse_args_rejects_unknown_mode() -> None:
    with pytest.raises(SystemExit):
        ab.parse_args(["--modes", "legacy,warp-drive"])


def test_parse_args_defaults_point_at_software_env() -> None:
    args = ab.parse_args([])
    assert args.modes == ["legacy", "rkmpp"]
    assert Path(args.env_file).name == ".env"
    assert Path(args.env_file).parent.name == "software"


def test_render_markdown_contains_both_modes_and_metrics() -> None:
    results = {
        mode: {
            "roles": ["c_channel_2"],
            "selected_encoder_path": "h264_rkmpp" if mode == "rkmpp" else "mjpeg",
            "idle": {"backend_tree_cpu_pct_mean": 10.0, "system_cpu_pct_mean": 20.0,
                     "backend_tree_rss_mb_max": 300.0},
            "stream": {
                "clients_requested": 3,
                "clients_connected": 3,
                "mbps_total": 12.3,
                "fps_total": 90.0 if mode == "rkmpp" else None,
                "sampler": {
                    "backend_tree_cpu_pct_mean": 150.0,
                    "backend_tree_cpu_pct_max": 200.0,
                    "system_cpu_pct_mean": 250.0,
                    "benchmark_client_cpu_pct_mean": 40.0,
                    "backend_tree_rss_mb_max": 400.0,
                    "temp_max_c": 65.0,
                    "temp_max_zone": "thermal_zone0:soc-thermal",
                    "cpu_freq_min_mhz": 1800,
                    "npu_load_last": "Core0: 10%",
                },
            },
        }
        for mode in ("legacy", "rkmpp")
    }

    report = ab.render_markdown(results, "2026-06-09 12:00:00")

    assert "| Metric | legacy | rkmpp |" in report
    assert "h264_rkmpp" in report
    assert "Glass-to-glass" in report
