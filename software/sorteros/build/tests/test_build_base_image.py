from __future__ import annotations

import hashlib
import importlib.util
import json
import lzma
import shutil
import sys
import tempfile
import tomllib
import unittest
from pathlib import Path
from unittest import mock


BUILD_PATH = Path(__file__).resolve().parents[1] / "build.py"
SPEC = importlib.util.spec_from_file_location("sorteros_build", BUILD_PATH)
assert SPEC is not None and SPEC.loader is not None
build = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = build
SPEC.loader.exec_module(build)


def _ctx(root: Path, base: dict) -> build.BuildCtx:
    return build.BuildCtx(
        config={
            "base": base,
            "output": {"version": "test", "name": "sorteros-v{version}-{date}.img"},
            "branch": {"default": "test"},
        },
        work_img=root / "out" / "work.img",
        cache_dir=root / "cache",
        overlay_dir=root / "overlay",
        mnt=root / "mnt",
        out_dir=root / "out",
        state_file=root / "out" / ".build-state.json",
        branch="test",
    )


def _ctx_with_config(root: Path, config: dict) -> build.BuildCtx:
    return build.BuildCtx(
        config=config,
        work_img=root / "out" / "work.img",
        cache_dir=root / "cache",
        overlay_dir=root / "overlay",
        mnt=root / "mnt",
        out_dir=root / "out",
        state_file=root / "out" / ".build-state.json",
        branch=config.get("branch", {}).get("default", "test"),
    )


class BaseImagePrepTests(unittest.TestCase):
    def test_vendor61_camera_transport_contract_requires_full_target_gates(self) -> None:
        config_path = Path(__file__).resolve().parents[1] / "config-cm5-vendor61.toml"
        payload = tomllib.loads(config_path.read_text())
        required_gates = set(payload["camera_transport"]["required_runtime_gates"])

        self.assertEqual(payload["output"]["version"], "4.0.9-cm5-vendor61.0")
        self.assertEqual(payload["camera_transport"]["profile"], "rk3588-rockchip-mpp-rga-rknn")
        self.assertIn("^6\\.1\\.", payload["camera_transport"]["required_kernel_release_patterns"])
        self.assertTrue(
            {
                "ffmpeg_rkmpp_advertised",
                "ffmpeg_rkmpp_runtime",
                "ffmpeg_rkrga_filters_advertised",
                "ffmpeg_rkrga_runtime",
                "mpp_service_node",
                "rga_node",
                "dma_heap_node",
                "drm_render_node",
                "hardware_scale_convert_source_pipeline",
                "zero_copy_source_pipeline",
                "source_pipeline_target_compliant",
                "target_capture_backend_integrated",
                "os_video_handle_audit_available",
                "assigned_camera_sources_exist",
                "target_ready",
                "target_architecture_compliant",
            }
            <= required_gates
        )
        self.assertIn(
            "/dev/dri/by-path/platform-fdab0000.npu-render",
            payload["camera_transport"]["required_device_nodes"],
        )
        self.assertTrue(
            any(
                "probe_webrtc_view_scaling.py --role c_channel_2 --views 3" in command
                for command in payload["camera_transport"]["acceptance_probe_commands"]
            )
        )
        self.assertTrue(
            any(
                "probe_camera_handle_stability.py --role c_channel_2 --clients 2" in command
                for command in payload["camera_transport"]["acceptance_probe_commands"]
            )
        )
        self.assertTrue(
            any(
                "probe_rk3588_npu_stack.py --require-inference" in command
                for command in payload["camera_transport"]["acceptance_probe_commands"]
            )
        )
        self.assertTrue(
            any(
                "probe_camera_calibration_ring.py --all-assigned" in command
                for command in payload["camera_transport"]["acceptance_probe_commands"]
            )
        )
        self.assertTrue(
            any(
                "probe_gstreamer_target_capture_pipeline.py --all-assigned" in command
                for command in payload["camera_transport"]["acceptance_probe_commands"]
            )
        )

    def test_xz_url_sha_applies_to_archive_not_decompressed_image(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            ctx = _ctx(
                Path(tmp),
                {
                    "filename": "base.img",
                    "url": "https://example.test/base.img.xz",
                    "sha256": "archive-sha",
                },
            )

            self.assertEqual(build._expected_sha256(ctx, ctx.cache_dir / "base.img.xz"), "archive-sha")
            self.assertEqual(build._expected_sha256(ctx, ctx.cache_dir / "base.img"), "")

    def test_explicit_image_sha_applies_to_decompressed_image(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            ctx = _ctx(
                Path(tmp),
                {
                    "filename": "base.img",
                    "url": "https://example.test/base.img.xz",
                    "sha256": "archive-sha",
                    "sha256_img": "image-sha",
                },
            )

            self.assertEqual(build._expected_sha256(ctx, ctx.cache_dir / "base.img"), "image-sha")

    def test_root_partition_defaults_to_p1_and_can_be_configured(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            default_ctx = _ctx(Path(tmp), {"filename": "base.img", "url": "", "sha256": ""})
            configured_ctx = _ctx(
                Path(tmp),
                {"filename": "base.img", "url": "", "sha256": "", "root_partition": 2},
            )

            self.assertEqual(build._root_partition_number(default_ctx), 1)
            self.assertEqual(build._root_partition_number(configured_ctx), 2)
            self.assertEqual(build._loop_partition("/dev/loop7", 2), "/dev/loop7p2")

    @unittest.skipUnless(shutil.which("xz"), "xz command is required")
    def test_ensure_base_image_decompresses_cached_xz_and_checks_archive_sha(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            ctx = _ctx(
                root,
                {
                    "filename": "base.img",
                    "url": "https://example.test/base.img.xz",
                    "sha256": "",
                },
            )
            ctx.cache_dir.mkdir()
            image_bytes = b"sorteros image bytes"
            archive_bytes = lzma.compress(image_bytes, format=lzma.FORMAT_XZ)
            archive_sha = hashlib.sha256(archive_bytes).hexdigest()
            (ctx.cache_dir / "base.img.xz").write_bytes(archive_bytes)
            ctx.config["base"]["sha256"] = archive_sha

            with mock.patch.dict(build.os.environ, {"HOME": str(root)}, clear=False):
                base = build._ensure_base_image(ctx)

            self.assertEqual(base, ctx.cache_dir / "base.img")
            self.assertEqual(base.read_bytes(), image_bytes)

    def test_ensure_base_image_rejects_non_direct_download_url(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            ctx = _ctx(
                root,
                {
                    "filename": "base.img",
                    "url": "https://drive.google.com/file/d/example/view",
                    "sha256": "",
                },
            )
            ctx.cache_dir.mkdir()

            with mock.patch.dict(build.os.environ, {"HOME": str(root)}, clear=False):
                with self.assertRaises(SystemExit) as raised:
                    build._ensure_base_image(ctx)

            self.assertIn("not a direct .img/.img.xz URL", str(raised.exception))

    def test_phase_overlay_bakes_camera_transport_contract(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            ctx = _ctx_with_config(
                root,
                {
                    "base": {"filename": "base.img", "url": "", "sha256": ""},
                    "output": {"version": "test-transport", "name": "sorteros-v{version}-{date}.img"},
                    "branch": {"default": "sorthive"},
                    "overlay": {"wifi_overlay": ""},
                    "camera_transport": {
                        "profile": "rk3588-rockchip-mpp-h264-webrtc",
                        "required_machine": "aarch64",
                        "required_kernel_release_patterns": ["^6\\.1\\."],
                        "required_runtime_gates": ["target_architecture_compliant"],
                        "required_device_nodes": [
                            "/dev/mpp_service",
                            "/dev/rga",
                            "/dev/dma_heap",
                            "/dev/dri/by-path/platform-fdab0000.npu-render",
                        ],
                        "required_packages": ["ffmpeg", "rockchip-multimedia-config"],
                        "backend_env": {
                            "SORTER_CAMERA_CAPTURE_BACKEND": "gstreamer_mpp",
                            "SORTER_ENABLE_GSTREAMER_MPP_CAPTURE": "1",
                            "SORTER_ENABLE_FFMPEG_RKMPP_WEBRTC": "1",
                        },
                        "acceptance_probe_commands": [
                            "probe_camera_transport_stack.py",
                            "probe_camera_handle_stability.py --clients 2",
                            "probe_gstreamer_target_capture_pipeline.py --all-assigned",
                            "probe_camera_calibration_ring.py --all-assigned",
                            "probe_webrtc_view_scaling.py --views 3",
                            "probe_rk3588_npu_stack.py --require-inference",
                        ],
                    },
                },
            )
            ctx.overlay_dir.mkdir(parents=True)
            ctx.mnt.mkdir(parents=True)

            with mock.patch.object(build, "is_mounted", return_value=True), \
                    mock.patch.object(build, "run"):
                build.phase_overlay(ctx)

            contract_path = ctx.mnt / "etc" / "sorteros" / "camera-transport-target.json"
            payload = json.loads(contract_path.read_text())

            self.assertEqual(payload["schema_version"], 1)
            self.assertEqual(payload["image_version"], "test-transport")
            self.assertEqual(payload["branch"], "sorthive")
            self.assertEqual(payload["profile"], "rk3588-rockchip-mpp-h264-webrtc")
            self.assertEqual(payload["required_machine"], "aarch64")
            self.assertEqual(payload["required_kernel_release_patterns"], ["^6\\.1\\."])
            self.assertEqual(
                payload["backend_env"],
                {
                    "SORTER_CAMERA_CAPTURE_BACKEND": "gstreamer_mpp",
                    "SORTER_ENABLE_GSTREAMER_MPP_CAPTURE": "1",
                    "SORTER_ENABLE_FFMPEG_RKMPP_WEBRTC": "1",
                },
            )
            self.assertIn("/dev/mpp_service", payload["required_device_nodes"])
            self.assertIn("/dev/dri/by-path/platform-fdab0000.npu-render", payload["required_device_nodes"])
            self.assertIn("target_architecture_compliant", payload["required_runtime_gates"])
            self.assertEqual(
                payload["acceptance_probe_commands"],
                [
                    "probe_camera_transport_stack.py",
                    "probe_camera_handle_stability.py --clients 2",
                    "probe_gstreamer_target_capture_pipeline.py --all-assigned",
                    "probe_camera_calibration_ring.py --all-assigned",
                    "probe_webrtc_view_scaling.py --views 3",
                    "probe_rk3588_npu_stack.py --require-inference",
                ],
            )


if __name__ == "__main__":
    unittest.main()
