from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path


FIRSTBOOT_PATH = (
    Path(__file__).resolve().parents[1]
    / "overlay"
    / "usr"
    / "local"
    / "sbin"
    / "sorteros-firstboot.py"
)
SPEC = importlib.util.spec_from_file_location("sorteros_firstboot", FIRSTBOOT_PATH)
assert SPEC is not None and SPEC.loader is not None
firstboot = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = firstboot
SPEC.loader.exec_module(firstboot)


def _backend_start_result() -> dict:
    return {
        "attempted": True,
        "units": ["sorter-backend-dev.service"],
        "returncode": 0,
        "stdout_tail": "",
        "stderr_tail": "",
    }


def _passing_acceptance_result(command: str = "acceptance --json") -> dict:
    return {
        "command": command,
        "returncode": 0,
        "stdout_tail": "{}",
        "stderr_tail": "",
        "report": {"ok": True},
    }


class FirstbootCameraTransportEnvTests(unittest.TestCase):
    def test_merge_export_env_lines_updates_existing_keys_and_preserves_other_lines(self) -> None:
        updates = {
            "DEBUG_LEVEL": "2",
            "SORTER_UI_PORT": "80",
            "SORTER_CAMERA_CAPTURE_BACKEND": "gstreamer_mpp",
            "SORTER_ENABLE_FFMPEG_RKMPP_WEBRTC": "1",
        }
        lines, seen = firstboot._merge_export_env_lines(
            [
                "export DEBUG_LEVEL=1",
                "# keep this",
                "export EXISTING_ONLY=yes",
                "export SORTER_ENABLE_FFMPEG_RKMPP_WEBRTC=0",
            ],
            updates,
        )
        for key, value in updates.items():
            if key not in seen:
                lines.append(f"export {key}={value}")

        self.assertEqual(
            lines,
            [
                "export DEBUG_LEVEL=2",
                "# keep this",
                "export EXISTING_ONLY=yes",
                "export SORTER_ENABLE_FFMPEG_RKMPP_WEBRTC=1",
                "export SORTER_UI_PORT=80",
                "export SORTER_CAMERA_CAPTURE_BACKEND=gstreamer_mpp",
            ],
        )
        self.assertEqual(seen, {"DEBUG_LEVEL", "SORTER_ENABLE_FFMPEG_RKMPP_WEBRTC"})

    def test_camera_transport_backend_env_reads_contract_and_filters_invalid_keys(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            contract_path = Path(tmp) / "camera-transport-target.json"
            contract_path.write_text(
                json.dumps(
                    {
                        "backend_env": {
                            "SORTER_CAMERA_CAPTURE_BACKEND": "gstreamer_mpp",
                            "SORTER_ENABLE_GSTREAMER_MPP_CAPTURE": "1",
                            "SORTER_ENABLE_FFMPEG_RKMPP_WEBRTC": "1",
                            "bad-name": "ignored",
                        }
                    }
                )
            )
            old_path = firstboot.CAMERA_TRANSPORT_TARGET_PATH
            try:
                firstboot.CAMERA_TRANSPORT_TARGET_PATH = contract_path

                env = firstboot._camera_transport_backend_env()
            finally:
                firstboot.CAMERA_TRANSPORT_TARGET_PATH = old_path

            self.assertEqual(
                env,
                {
                    "SORTER_CAMERA_CAPTURE_BACKEND": "gstreamer_mpp",
                    "SORTER_ENABLE_GSTREAMER_MPP_CAPTURE": "1",
                    "SORTER_ENABLE_FFMPEG_RKMPP_WEBRTC": "1",
                },
            )

    def test_camera_transport_backend_env_is_empty_without_contract(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            old_path = firstboot.CAMERA_TRANSPORT_TARGET_PATH
            try:
                firstboot.CAMERA_TRANSPORT_TARGET_PATH = Path(tmp) / "missing.json"

                env = firstboot._camera_transport_backend_env()
            finally:
                firstboot.CAMERA_TRANSPORT_TARGET_PATH = old_path

            self.assertEqual(env, {})

    def test_camera_transport_status_reports_missing_contract(self) -> None:
        payload = firstboot._camera_transport_status_payload(contract=None)

        self.assertFalse(payload["contract_present"])
        self.assertFalse(payload["target_ready"])
        self.assertIn("No camera transport target contract", payload["summary"])

    def test_camera_transport_status_compares_contract_to_probe_and_runtime(self) -> None:
        contract = {
            "profile": "rk3588-rockchip-mpp-h264-webrtc",
            "image_version": "test",
            "branch": "sorthive",
            "required_machine": "aarch64",
            "required_kernel_release_patterns": ["^6\\.1\\."],
            "required_runtime_gates": [
                "python_webrtc",
                "ffmpeg_rkmpp_runtime",
                "target_architecture_compliant",
            ],
            "required_device_nodes": [
                "/dev/mpp_service",
                "/dev/rga",
                "/dev/rknpu",
            ],
            "required_packages": [
                "ffmpeg",
                "rockchip-multimedia-config",
            ],
            "probe_command": "probe",
            "acceptance_probe_commands": ["acceptance"],
        }
        probe_result = {
            "command": "probe --json",
            "returncode": 2,
            "stdout_tail": "{}",
            "stderr_tail": "",
            "report": {
                "evaluation": {
                    "gates": {
                        "python_webrtc": True,
                        "ffmpeg_rkmpp_runtime": False,
                        "target_ready": False,
                        "target_architecture_compliant": False,
                    },
                    "blockers": ["ffmpeg runtime failed"],
                }
            },
        }

        payload = firstboot._camera_transport_status_payload(
            contract=contract,
            package_versions={
                "ffmpeg": "6.1+rkmpp",
                "rockchip-multimedia-config": None,
            },
            probe_result=probe_result,
            acceptance_probe_results=[_passing_acceptance_result()],
            backend_start_result=_backend_start_result(),
            path_exists=lambda path: path == "/dev/mpp_service",
            kernel_release="6.13.0",
            machine="aarch64",
        )

        self.assertFalse(payload["ok"])
        self.assertEqual(payload["profile"], "rk3588-rockchip-mpp-h264-webrtc")
        self.assertEqual(payload["platform"]["kernel_release"], "6.13.0")
        self.assertEqual(payload["missing_kernel_release_patterns"], ["^6\\.1\\."])
        self.assertFalse(payload["machine_mismatch"])
        self.assertEqual(payload["missing_device_nodes"], ["/dev/rga", "/dev/rknpu"])
        self.assertEqual(payload["missing_packages"], ["rockchip-multimedia-config"])
        self.assertIn("ffmpeg_rkmpp_runtime", payload["missing_runtime_gates"])
        self.assertIn("target_architecture_compliant", payload["missing_runtime_gates"])
        self.assertEqual(payload["blockers"], ["ffmpeg runtime failed"])
        self.assertTrue(payload["acceptance_probes_ok"])
        self.assertEqual(payload["acceptance_probe_commands"], ["acceptance"])

    def test_camera_transport_status_passes_when_contract_requirements_are_met(self) -> None:
        contract = {
            "profile": "rk3588-rockchip-mpp-h264-webrtc",
            "required_machine": "aarch64",
            "required_kernel_release_patterns": ["^6\\.1\\."],
            "required_runtime_gates": ["target_architecture_compliant"],
            "required_device_nodes": ["/dev/mpp_service"],
            "required_packages": ["ffmpeg"],
            "acceptance_probe_commands": ["acceptance"],
        }
        payload = firstboot._camera_transport_status_payload(
            contract=contract,
            package_versions={"ffmpeg": "6.1+rkmpp"},
            probe_result={
                "command": "probe --json",
                "returncode": 0,
                "stdout_tail": "{}",
                "stderr_tail": "",
                "report": {
                    "evaluation": {
                        "gates": {
                            "target_ready": True,
                            "target_architecture_compliant": True,
                        },
                        "blockers": [],
                    }
                },
            },
            acceptance_probe_results=[_passing_acceptance_result()],
            backend_start_result=_backend_start_result(),
            path_exists=lambda _path: True,
            kernel_release="6.1.99-rockchip",
            machine="aarch64",
        )

        self.assertTrue(payload["ok"])
        self.assertEqual(payload["missing_kernel_release_patterns"], [])
        self.assertFalse(payload["machine_mismatch"])
        self.assertTrue(payload["target_ready"])
        self.assertEqual(payload["missing_device_nodes"], [])
        self.assertEqual(payload["missing_packages"], [])
        self.assertEqual(payload["missing_runtime_gates"], [])
        self.assertTrue(payload["acceptance_probes_ok"])
        self.assertEqual(payload["acceptance_probe_failures"], [])

    def test_camera_transport_status_rejects_wrong_kernel_even_when_runtime_gates_pass(self) -> None:
        contract = {
            "profile": "rk3588-rockchip-mpp-h264-webrtc",
            "required_machine": "aarch64",
            "required_kernel_release_patterns": ["^6\\.1\\."],
            "required_runtime_gates": ["target_architecture_compliant"],
            "required_device_nodes": ["/dev/mpp_service"],
            "required_packages": ["ffmpeg"],
            "acceptance_probe_commands": ["acceptance"],
        }
        payload = firstboot._camera_transport_status_payload(
            contract=contract,
            package_versions={"ffmpeg": "6.1+rkmpp"},
            probe_result={
                "command": "probe --json",
                "returncode": 0,
                "stdout_tail": "{}",
                "stderr_tail": "",
                "report": {
                    "evaluation": {
                        "gates": {
                            "target_ready": True,
                            "target_architecture_compliant": True,
                        },
                        "blockers": [],
                    }
                },
            },
            acceptance_probe_results=[_passing_acceptance_result()],
            backend_start_result=_backend_start_result(),
            path_exists=lambda _path: True,
            kernel_release="6.13.0",
            machine="aarch64",
        )

        self.assertFalse(payload["ok"])
        self.assertTrue(payload["target_architecture_compliant"])
        self.assertEqual(payload["missing_kernel_release_patterns"], ["^6\\.1\\."])
        self.assertEqual(payload["missing_device_nodes"], [])
        self.assertEqual(payload["missing_packages"], [])
        self.assertEqual(payload["missing_runtime_gates"], [])
        self.assertTrue(payload["acceptance_probes_ok"])

    def test_camera_transport_status_requires_acceptance_probes_to_pass(self) -> None:
        contract = {
            "profile": "rk3588-rockchip-mpp-h264-webrtc",
            "required_machine": "aarch64",
            "required_kernel_release_patterns": ["^6\\.1\\."],
            "required_runtime_gates": ["target_architecture_compliant"],
            "required_device_nodes": ["/dev/mpp_service"],
            "required_packages": ["ffmpeg"],
            "acceptance_probe_commands": [
                "probe_camera_handle_stability.py --clients 2",
                "probe_webrtc_view_scaling.py --views 3",
            ],
        }
        payload = firstboot._camera_transport_status_payload(
            contract=contract,
            package_versions={"ffmpeg": "6.1+rkmpp"},
            probe_result={
                "command": "probe --json",
                "returncode": 0,
                "stdout_tail": "{}",
                "stderr_tail": "",
                "report": {
                    "evaluation": {
                        "gates": {
                            "target_ready": True,
                            "target_architecture_compliant": True,
                        },
                        "blockers": [],
                    }
                },
            },
            acceptance_probe_results=[
                _passing_acceptance_result("probe_camera_handle_stability.py --clients 2 --json"),
                {
                    "command": "probe_webrtc_view_scaling.py --views 3 --json",
                    "returncode": 2,
                    "stdout_tail": "{}",
                    "stderr_tail": "view scaling failed",
                    "report": {"ok": False},
                },
            ],
            backend_start_result=_backend_start_result(),
            path_exists=lambda _path: True,
            kernel_release="6.1.99-rockchip",
            machine="aarch64",
        )

        self.assertFalse(payload["ok"])
        self.assertTrue(payload["target_architecture_compliant"])
        self.assertFalse(payload["acceptance_probes_ok"])
        self.assertEqual(len(payload["acceptance_probe_failures"]), 1)
        self.assertIn(
            "probe_webrtc_view_scaling.py",
            payload["acceptance_probe_failures"][0]["command"],
        )

    def test_stage_camera_transport_probe_writes_status_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            contract_path = root / "camera-transport-target.json"
            status_path = root / "camera-transport-status.json"
            contract_path.write_text(
                json.dumps(
                    {
                        "profile": "rk3588-rockchip-mpp-h264-webrtc",
                        "required_runtime_gates": ["target_architecture_compliant"],
                        "required_device_nodes": [],
                        "required_packages": [],
                        "probe_command": "probe",
                        "acceptance_probe_commands": ["acceptance"],
                    }
                )
            )
            old_contract = firstboot.CAMERA_TRANSPORT_TARGET_PATH
            old_status = firstboot.CAMERA_TRANSPORT_STATUS_PATH
            try:
                firstboot.CAMERA_TRANSPORT_TARGET_PATH = contract_path
                firstboot.CAMERA_TRANSPORT_STATUS_PATH = status_path
                original_probe = firstboot._run_camera_transport_probe
                original_start = firstboot._start_camera_transport_backend_for_probe
                firstboot._run_camera_transport_probe = lambda _command: {
                    "command": "probe --json",
                    "returncode": 0,
                    "stdout_tail": "{}",
                    "stderr_tail": "",
                    "report": {
                        "evaluation": {
                            "gates": {
                                "target_ready": True,
                                "target_architecture_compliant": True,
                            },
                            "blockers": [],
                        }
                    },
                }
                firstboot._start_camera_transport_backend_for_probe = _backend_start_result

                firstboot.stage_camera_transport_probe()
            finally:
                firstboot.CAMERA_TRANSPORT_TARGET_PATH = old_contract
                firstboot.CAMERA_TRANSPORT_STATUS_PATH = old_status
                firstboot._run_camera_transport_probe = original_probe
                firstboot._start_camera_transport_backend_for_probe = original_start

            payload = json.loads(status_path.read_text())
            self.assertTrue(payload["ok"])
            self.assertEqual(payload["profile"], "rk3588-rockchip-mpp-h264-webrtc")
            self.assertTrue(payload["acceptance_probes_ok"])


if __name__ == "__main__":
    unittest.main()
