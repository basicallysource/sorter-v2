from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parents[2]
RENDER_PATH = ROOT / "render-camera-contract.py"
SPEC = importlib.util.spec_from_file_location("render_camera_contract", RENDER_PATH)
assert SPEC is not None and SPEC.loader is not None
render = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = render
SPEC.loader.exec_module(render)


def test_armbian_board_file_targets_cm5_vendor_dtb() -> None:
    board_file = ROOT / "userpatches" / "config" / "boards" / "orangepi-cm5-sorter.csc"
    text = board_file.read_text()

    assert 'BOARDFAMILY="rockchip-rk3588"' in text
    assert 'KERNEL_TARGET="vendor"' in text
    assert 'BOOT_FDT_FILE="rockchip/rk3588s-orangepi-cm5-tablet.dtb"' in text
    assert 'BOOTCONFIG="orangepi_cm5_tablet_defconfig"' in text
    assert 'BOOT_SCENARIO="spl-blobs"' in text
    assert "post_family_config_branch_vendor__orangepi_cm5_sorter_use_vendor_uboot" in text
    assert 'BOOTSOURCE="https://github.com/orangepi-xunlong/u-boot-orangepi.git"' in text
    assert 'BOOTBRANCH="branch:v2017.09-rk3588"' in text
    assert 'BOOTPATCHDIR="legacy"' in text
    assert 'BOOTDIR="u-boot-orangepi-rk3588"' in text


def test_armbian_config_is_noninteractive_vendor61_cm5_build() -> None:
    config = (ROOT / "userpatches" / "config-sorter-cm5-vendor61.conf").read_text()

    assert "BOARD=orangepi-cm5-sorter" in config
    assert "BRANCH=vendor" in config
    assert "RELEASE=noble" in config
    assert "BUILD_MINIMAL=yes" in config
    assert "BUILD_DESKTOP=no" in config
    assert "KERNEL_CONFIGURE=no" in config
    assert "KERNEL_BTF=no" in config


def test_rendered_contract_keeps_npu_inference_as_phase0_gate(tmp_path: Path) -> None:
    out = tmp_path / "camera-transport-target.json"
    config = REPO / "software" / "sorteros" / "build" / "config-cm5-vendor61.toml"

    contract = render.build_contract(config, branch="sorthive")
    out.write_text(json.dumps(contract))
    payload = json.loads(out.read_text())

    assert payload["profile"] == "rk3588-rockchip-mpp-rga-rknn"
    assert "/dev/dri/by-path/platform-fdab0000.npu-render" in payload["required_device_nodes"]
    assert any(
        "probe_rk3588_npu_stack.py --require-inference" in command
        for command in payload["acceptance_probe_commands"]
    )


def test_build_wrapper_copies_existing_sorteros_overlay_and_chroot_installer() -> None:
    script = (ROOT / "build-sorteros-armbian-cm5.sh").read_text()

    assert "software/sorteros/build/overlay" in script
    assert "software/sorteros/build/chroot_apt.sh" in script
    assert "prepare_portal_overlay" in script
    assert "software/sorteros/portal" in script
    assert "sorteros-portal.py" in script
    assert "var/www/portal" in script
    assert "bootstrap_authorized_keys" in script
    assert "render-camera-contract.py" in script
    assert "rk3588s-orangepi-cm5-tablet.dtb" in script
    assert (
        ROOT
        / "userpatches"
        / "u-boot"
        / "legacy"
        / "board_orangepi-cm5-sorter"
        / "fix-noble-build.patch"
    ).exists()
    assert "--prepare-only" in script
    assert "KERNEL_BTF=no" in script


def test_armbian_build_wrapper_bakes_captive_portal_artifacts() -> None:
    script = (ROOT / "build-sorteros-armbian-cm5.sh").read_text()

    assert "PORTAL_DIR=" in script
    assert "portal_frontend_needs_build" in script
    assert "pnpm install --frozen-lockfile" in script
    assert "pnpm build" in script
    assert "baking SorterOS captive portal into overlay" in script
    assert "usr/local/sbin/sorteros-portal.py" in script
    assert "var/www/portal" in script
    assert "etc/sorteros-config.toml" in script
    assert (REPO / "software" / "sorteros" / "portal" / "backend" / "portal.py").exists()
    assert (REPO / "software" / "sorteros" / "portal" / "frontend" / "package.json").exists()


def test_build_wrapper_embeds_npu_smoke_fallback_artifacts() -> None:
    script = (ROOT / "build-sorteros-armbian-cm5.sh").read_text()
    chroot = (REPO / "software" / "sorteros" / "build" / "chroot_apt.sh").read_text()
    firstboot = (
        REPO
        / "software"
        / "sorteros"
        / "build"
        / "overlay"
        / "usr"
        / "local"
        / "sbin"
        / "sorteros-firstboot.py"
    ).read_text()

    assert "embedding camera transport code + NPU smoke fallback artifacts" in script
    assert "camera transport/NPU smoke artifacts are required" in script
    assert "FALLBACK_RELATIVE_PATHS" in script
    assert "software/sorter/backend/pyproject.toml" in script
    assert "software/sorter/backend/uv.lock" in script
    assert "software/sorter/backend/server/routers/cameras.py" in script
    assert "software/sorter/backend/vision/media_plane.py" in script
    assert "probe_camera_transport_stack.py" in script
    assert "probe_camera_handle_stability.py" in script
    assert "probe_gstreamer_target_capture_pipeline.py" in script
    assert "probe_camera_calibration_ring.py" in script
    assert "probe_webrtc_view_scaling.py" in script
    assert "probe_rk3588_npu_stack.py" in script
    assert "c_channel_full_yolo26s_320_rk3588.rknn" in script
    for probe_name in (
        "probe_camera_transport_stack.py",
        "probe_camera_handle_stability.py",
        "probe_gstreamer_target_capture_pipeline.py",
        "probe_camera_calibration_ring.py",
        "probe_webrtc_view_scaling.py",
        "probe_rk3588_npu_stack.py",
    ):
        assert (REPO / "software" / "sorter" / "backend" / "scripts" / probe_name).exists()
    assert (REPO / "software" / "sorter" / "backend" / "scripts" / "probe_rk3588_npu_stack.py").exists()
    assert (
        REPO
        / "software"
        / "training"
        / "rknn_bundles"
        / "c_channel_full_yolo26s_320_rk3588"
        / "results"
        / "c_channel_full_yolo26s_320_rk3588.rknn"
    ).exists()

    assert "NPU_SMOKE_FALLBACK_DIR" in firstboot
    assert "CODE_FALLBACK_RELATIVE_PATHS" in firstboot
    assert "pyproject.toml" in firstboot
    assert "server/routers/cameras.py" in firstboot
    assert "vision/media_plane.py" in firstboot
    assert "_install_npu_smoke_fallbacks" in firstboot
    assert "version https://git-lfs.github.com/spec/v1" in firstboot
    assert (REPO / "software" / "sorteros" / "build" / "overlay" / "usr" / "lib" / "librknnrt.so").exists()
    assert "librknnrt.so" in chroot
    assert "ldconfig" in chroot


def test_cm5_tablet_dtb_contains_runtime_accelerator_nodes() -> None:
    dtb = ROOT / "artifacts" / "rk3588s-orangepi-cm5-tablet.dtb"
    payload = dtb.read_bytes()

    assert b"rockchip,rk3588-rknpu" in payload
    assert b"rknpu-supply" in payload
    assert b"rknpu_mmu" in payload
    assert b"rockchip,mpp-service" in payload
    assert b"rockchip,rga3_core0" in payload
    assert b"rockchip,vpu-encoder-v2" in payload
    assert b"rockchip,vpu-decoder-v2" in payload


def test_cm5_tablet_dtb_has_versioned_source_and_regenerator() -> None:
    source_dir = ROOT / "dt-src" / "rk35xx-vendor-6.1"
    readme = (source_dir / "README.md").read_text()
    regenerator = (ROOT / "compile-cm5-tablet-dtb.sh").read_text()

    assert "85a312eaf21a4a867efac33a39181ff8be425b40" in readme
    assert "713542620f7c9c6287ef11487748e7bae13a63df" in readme
    assert (source_dir / "rk3588s-orangepi-cm5-tablet.dts").exists()
    assert (source_dir / "rk3588s-orangepi-cm5-tablet-camera1.dtsi").exists()
    assert (source_dir / "rk3588s-orangepi-cm5-tablet-camera2.dtsi").exists()
    assert (source_dir / "rk3588s-orangepi-cm5-tablet-camera3.dtsi").exists()
    assert (source_dir / "rk3588s-orangepi-cm5-tablet-lcd.dtsi").exists()
    assert "dtc -@ -I dts -O dtb" in regenerator
    assert "rk3588s-orangepi-cm5-tablet.dts" in regenerator


def test_maskrom_flash_script_verifies_readback_before_reboot() -> None:
    script = (ROOT / "flash-cm5-maskrom.sh").read_text()

    assert "rkdeveloptool db" in script
    assert "rkdeveloptool wl 0x0" in script
    assert "rkdeveloptool rl 0 32768" in script
    assert "Readback mismatch" in script
    assert "rkdeveloptool rd" in script
    assert "not found any devices" in script


def test_chroot_installer_enables_first_boot_ssh_and_networkmanager() -> None:
    script = (REPO / "software" / "sorteros" / "build" / "chroot_apt.sh").read_text()

    assert "openssh-server" in script
    assert "avahi-daemon" in script
    assert "python3-gi" in script
    assert "python3-dev" in script
    assert "gir1.2-gstreamer-1.0" in script
    assert "gir1.2-gst-plugins-base-1.0" in script
    assert "99-sorteros-networkmanager.yaml" in script
    assert "find /etc/netplan" in script
    assert "renderer: NetworkManager" in script
    assert 'name: "e*"' in script
    assert "dhcp4: true" in script
    assert "systemctl enable NetworkManager.service" in script
    assert "systemctl enable sorteros-usb-gadget.service" in script
    assert "systemctl enable ssh.service" in script
    assert "sorteros-bootstrap-users.service" in script
    assert "bootstrap_authorized_keys" in script
    assert "SORTEROS_DEFAULT_PASSWORD" in script
    assert "set_login_password root" in script
    assert "set_login_password orangepi" in script
    assert "/root/.not_logged_in_yet" in script
    assert "armbian-check-first-login.sh" in script
    assert "systemctl disable armbian-firstrun.service" in script

    bootstrap = (
        REPO
        / "software"
        / "sorteros"
        / "build"
        / "overlay"
        / "usr"
        / "local"
        / "sbin"
        / "sorteros-bootstrap-users.sh"
    ).read_text()
    service = (
        REPO
        / "software"
        / "sorteros"
        / "build"
        / "overlay"
        / "etc"
        / "systemd"
        / "system"
        / "sorteros-bootstrap-users.service"
    ).read_text()
    gadget_script = (
        REPO
        / "software"
        / "sorteros"
        / "build"
        / "overlay"
        / "usr"
        / "local"
        / "sbin"
        / "sorteros-usb-gadget.sh"
    ).read_text()
    gadget_service = (
        REPO
        / "software"
        / "sorteros"
        / "build"
        / "overlay"
        / "etc"
        / "systemd"
        / "system"
        / "sorteros-usb-gadget.service"
    ).read_text()

    assert "/home/orangepi" in bootstrap
    assert "bootstrap_authorized_keys" in bootstrap
    assert "SORTEROS_DEFAULT_PASSWORD" in bootstrap
    assert "set_login_password root" in bootstrap
    assert "set_login_password orangepi" in bootstrap
    assert "/root/.not_logged_in_yet" in bootstrap
    assert "armbian-check-first-login.sh" in bootstrap
    assert "Before=ssh.service sorteros-firstboot.service" in service
    assert "modprobe g_ether" in gadget_script
    assert "172.31.42.2/24" in gadget_script
    assert "Before=sorteros-onboarding.service sorteros-firstboot.service" in gadget_service


def test_wifi_onboarding_is_portal_first_and_interface_agnostic() -> None:
    ap_up = (
        REPO
        / "software"
        / "sorteros"
        / "build"
        / "overlay"
        / "usr"
        / "local"
        / "sbin"
        / "sorteros-ap-up.sh"
    ).read_text()
    onboarding = (
        REPO
        / "software"
        / "sorteros"
        / "build"
        / "overlay"
        / "usr"
        / "local"
        / "sbin"
        / "sorteros-onboarding.sh"
    ).read_text()
    firstboot = (
        REPO
        / "software"
        / "sorteros"
        / "build"
        / "overlay"
        / "usr"
        / "local"
        / "sbin"
        / "sorteros-firstboot.py"
    ).read_text()
    wifi_add = (
        REPO
        / "software"
        / "sorteros"
        / "build"
        / "overlay"
        / "usr"
        / "local"
        / "bin"
        / "sorteros-wifi-add"
    ).read_text()

    assert "SORTEROS_ONBOARDING_WIFI_IFACE" in ap_up
    assert "resolve_wifi_iface" in ap_up
    assert "nmcli -t -f DEVICE,TYPE dev status" in ap_up
    assert "IFACE=wlan0" not in ap_up
    assert "SORTEROS_ONBOARDING_SKIP_WHEN_ONLINE" in onboarding
    assert "the portal is" in onboarding
    assert '"systemctl", "is-active", "--quiet"' in firstboot
    assert "waiting for Wi-Fi onboarding" in firstboot
    assert "interface-name=wlan0" not in wifi_add


def test_customize_image_keeps_armbian_dtb_path_as_special_case() -> None:
    script = (ROOT / "userpatches" / "customize-image.sh").read_text()

    assert "copy_dtb_overlay" in script
    assert "copy_sorteros_overlay" in script
    assert "cp -a /tmp/overlay/. /" not in script
    assert "copying SorterOS DTB overlay into" in script
    assert 'if [ "${entry}" = "/tmp/overlay/tmp" ]; then' in script
    assert "chmod 1777 /tmp" in script
