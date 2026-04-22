#!/usr/bin/env python3
"""Helpers for staging Hailo compile sessions on Vast.ai."""
from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import tarfile
import tempfile
import textwrap
from pathlib import Path


TRAINING_ROOT = Path(__file__).resolve().parents[3]
HAILO_BUNDLES_DIR = TRAINING_ROOT / "hailo_bundles"
DEFAULT_BUNDLE = HAILO_BUNDLES_DIR / "classification_chamber_yolo11s"
DEFAULT_VENDOR_DOWNLOADS_DIR = Path.home() / "Downloads"
DEFAULT_QUERY = (
    "num_gpus=1 cpu_arch=amd64 reliability>0.98 disk_space>=80 inet_down>200 "
    "gpu_name in [RTX_3090,RTX_4090,RTX_A5000,RTX_A6000] rented=False"
)
DEFAULT_IMAGE = "ubuntu:22.04"
DEFAULT_TARGET_HW_ARCH = "hailo8"


def _run(args: list[str], *, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, text=True, capture_output=True, check=check)


def _load_vastai_json(args: list[str]) -> list[dict]:
    result = _run(args, check=False)
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or result.stdout.strip() or "vastai command failed")
    return json.loads(result.stdout)


def _search_offers(args: argparse.Namespace) -> int:
    offers = _load_vastai_json(
        [
            "vastai",
            "search",
            "offers",
            args.query,
            "--raw",
            "-o",
            args.order,
        ]
    )
    print(f"offers={len(offers)}")
    for offer in offers[: args.limit]:
        trimmed = {
            "id": offer.get("id"),
            "gpu_name": offer.get("gpu_name"),
            "num_gpus": offer.get("num_gpus"),
            "gpu_ram": offer.get("gpu_ram"),
            "cpu_cores_effective": offer.get("cpu_cores_effective"),
            "cpu_ram": offer.get("cpu_ram"),
            "driver_version": offer.get("driver_version"),
            "cuda_max_good": offer.get("cuda_max_good"),
            "dph_total": offer.get("dph_total"),
            "reliability": offer.get("reliability"),
            "inet_down": offer.get("inet_down"),
            "geolocation": offer.get("geolocation"),
        }
        print(json.dumps(trimmed, indent=2))
    return 0


def _version_key(path: Path) -> tuple[int, ...]:
    match = re.search(r"(\d+(?:\.\d+)+)", path.name)
    if not match:
        return tuple()
    return tuple(int(part) for part in match.group(1).split("."))


def _pick_best(paths: list[Path], preferred_version: tuple[int, ...] | None = None) -> Path | None:
    if not paths:
        return None
    if preferred_version is not None:
        for path in sorted(paths, key=lambda path: (_version_key(path), " (" not in path.name), reverse=True):
            if _version_key(path) == preferred_version:
                return path
    return max(paths, key=lambda path: (_version_key(path), " (" not in path.name))


def _pick_highest_matching_major(paths: list[Path], major: int) -> Path | None:
    matches = [path for path in paths if _version_key(path)[:1] == (major,)]
    if not matches:
        return None
    return max(matches, key=lambda path: (_version_key(path), " (" not in path.name))


def _discover_vendor_assets(downloads_dir: Path, target_hw_arch: str) -> dict[str, Path]:
    files = [path for path in downloads_dir.iterdir() if path.is_file()]
    dfc_wheels = [
        path for path in files if path.name.startswith("hailo_dataflow_compiler-") and path.suffix == ".whl"
    ]
    if not dfc_wheels:
        raise FileNotFoundError(f"No Hailo Dataflow Compiler wheel found in {downloads_dir}")

    model_zoo_wheels = [
        path for path in files if path.name.startswith("hailo_model_zoo-") and path.suffix == ".whl"
    ]
    hailort_debs = [
        path for path in files if path.name.startswith("hailort_") and path.name.endswith("_amd64.deb")
    ]
    hailort_wheels = [
        path for path in files if path.name.startswith("hailort-") and path.suffix == ".whl"
    ]
    pcie_driver_debs = [
        path for path in files if path.name.startswith("hailort-pcie-driver_") and path.suffix == ".deb"
    ]

    if target_hw_arch.startswith("hailo8"):
        dfc = _pick_highest_matching_major(dfc_wheels, 3)
        model_zoo = _pick_highest_matching_major(model_zoo_wheels, 2)
        hailort_deb = _pick_highest_matching_major(hailort_debs, 4)
        hailort_wheel = _pick_highest_matching_major(hailort_wheels, 4)
        pcie_driver = _pick_highest_matching_major(pcie_driver_debs, 4)
    else:
        dfc = max(dfc_wheels, key=_version_key)
        version = _version_key(dfc)
        model_zoo = _pick_best(model_zoo_wheels, preferred_version=version)
        hailort_deb = _pick_best(hailort_debs, preferred_version=version)
        hailort_wheel = _pick_best(hailort_wheels, preferred_version=version)
        pcie_driver = _pick_best(pcie_driver_debs, preferred_version=version)

    if dfc is None:
        raise FileNotFoundError(f"No compatible Hailo Dataflow Compiler wheel found in {downloads_dir}")
    if model_zoo is None:
        raise FileNotFoundError(f"No hailo_model_zoo wheel found in {downloads_dir}")

    selected = {
        "dataflow_compiler": dfc,
        "model_zoo": model_zoo,
    }
    if hailort_deb is not None:
        selected["hailort_deb"] = hailort_deb
    if hailort_wheel is not None:
        selected["hailort_wheel"] = hailort_wheel
    if pcie_driver is not None:
        selected["pcie_driver"] = pcie_driver

    return selected


def _validate_target_compatibility(
    selected_assets: dict[str, Path], target_hw_arch: str, allow_unsupported_suite: bool
) -> None:
    dfc_version = _version_key(selected_assets["dataflow_compiler"])
    if target_hw_arch.startswith("hailo8") and dfc_version >= (5,):
        message = (
            f"The selected Dataflow Compiler {selected_assets['dataflow_compiler'].name} is not compatible "
            f"with target hw-arch '{target_hw_arch}'. A remote validation run on 2026-04-06 showed that "
            "DFC 5.3.0 only exposes hailo15*/hailo10* parser/compiler targets, not hailo8/hailo8l. "
            "For Raspberry Pi AI HAT (Hailo-8), use the older Hailo-8-era suite such as "
            "DFC 3.33.0 + HailoRT 4.23.0 + hailo_model_zoo v2.18.x."
        )
        if allow_unsupported_suite:
            print(f"WARNING: {message}")
            return
        raise RuntimeError(message)


def _make_install_script(selected_assets: dict[str, Path]) -> str:
    hailort_deb = selected_assets.get("hailort_deb")
    python_bin = "python3"
    install_hailort = ""
    if hailort_deb is not None:
        install_hailort = textwrap.dedent(
            f"""
            dpkg -i "$SCRIPT_DIR/{hailort_deb.name}" || true
            apt-get -f install -y
            """
        ).strip()

    return textwrap.dedent(
        f"""\
        #!/usr/bin/env bash
        set -euo pipefail

        SCRIPT_DIR=$(cd "$(dirname "${{BASH_SOURCE[0]}}")" && pwd)
        VENV_DIR=${{VENV_DIR:-/opt/hailo_venv}}

        export DEBIAN_FRONTEND=noninteractive
        apt-get update
        apt-get install -y \\
          {python_bin} \\
          {python_bin}-venv \\
          {python_bin}-dev \\
          python3-pip \\
          python3-tk \\
          build-essential \\
          bsdextrautils \\
          pkg-config \\
          libgl1 \\
          libglib2.0-0 \\
          libglib2.0-dev \\
          libgstreamer1.0-0 \\
          libgstreamer-plugins-base1.0-0 \\
          libgraphviz-dev \\
          graphviz

        {install_hailort}

        {python_bin} -m venv "$VENV_DIR"
        . "$VENV_DIR/bin/activate"
        pip install --upgrade pip setuptools wheel
        pip install "$SCRIPT_DIR/{selected_assets['dataflow_compiler'].name}"
        pip install "$SCRIPT_DIR/{selected_assets['model_zoo'].name}"

        echo
        echo "Installed Hailo toolchain into $VENV_DIR"
        echo "Activate with: source $VENV_DIR/bin/activate"
        echo "Check CLIs with: hailo --help && hailomz --help"
        """
    )


def _make_vendor_readme(selected_assets: dict[str, Path]) -> str:
    relevant = [
        f"- `dataflow compiler`: `{selected_assets['dataflow_compiler'].name}`",
        f"- `model zoo / hailomz`: `{selected_assets['model_zoo'].name}`",
    ]
    if "hailort_deb" in selected_assets:
        relevant.append(f"- `hailort runtime (amd64 .deb)`: `{selected_assets['hailort_deb'].name}`")
    if "hailort_wheel" in selected_assets:
        relevant.append(f"- `hailort python wheel`: `{selected_assets['hailort_wheel'].name}`")
    if "pcie_driver" in selected_assets:
        relevant.append(f"- `pcie driver package`: `{selected_assets['pcie_driver'].name}`")

    return textwrap.dedent(
        f"""\
        # Vendor Payload

        This directory contains the Hailo SDK payload that was auto-selected from the local download cache.

        ## Selected files

        {chr(10).join(relevant)}

        ## Recommended use on Vast.ai

        1. Run `./install_hailo_sdk.sh` as `root`.
        2. Activate the created venv with `source /opt/hailo_venv/bin/activate`.
        3. Verify `hailo --help` and `hailomz --help`.

        ## Notes

        - The `hailort-pcie-driver` package is kept for completeness, but it is not required on a cloud compile host without a local Hailo PCIe device.
        - `hailo_gen_ai_model_zoo` packages are intentionally not included because they are for the generative AI / Ollama path, not for our detector compile flow.
        - For this detector workflow, the key pair is the Dataflow Compiler plus the classic `hailo_model_zoo` wheel.
        """
    )


def _stage_auto_vendor_payload(downloads_dir: Path, vendor_dest: Path, target_hw_arch: str) -> dict[str, Path]:
    selected = _discover_vendor_assets(downloads_dir, target_hw_arch)
    vendor_dest.mkdir(parents=True, exist_ok=True)
    for path in selected.values():
        shutil.copy2(path, vendor_dest / path.name)

    (vendor_dest / "README.md").write_text(_make_vendor_readme(selected))
    (vendor_dest / "manifest.json").write_text(
        json.dumps(
            {
                "downloads_dir": str(downloads_dir),
                "selected_assets": {key: value.name for key, value in selected.items()},
            },
            indent=2,
        )
    )
    install_script = vendor_dest / "install_hailo_sdk.sh"
    install_script.write_text(_make_install_script(selected))
    install_script.chmod(0o755)
    return selected


def _make_workspace_readme(bundle_name: str, image: str, label: str, disk_gb: int, vendor_mode: str) -> str:
    vendor_steps = [
        "3. Install the Hailo Dataflow Compiler and matching runtime/toolchain from your Hailo developer downloads.",
        "4. Clone `hailo_model_zoo` `v2.18` if it is not already included.",
        "5. Run `bundle/compile_commands.sh`.",
        "6. Copy the resulting `.hef` and `.har` files back to the local workspace.",
    ]
    notes = [
        "- This archive does not include the proprietary Hailo Dataflow Compiler payload.",
        f"- The bundled model is `{bundle_name}`.",
        "- The compile target for the current Raspberry Pi AI HAT setup is `hailo8`, not `hailo8l`.",
    ]
    if vendor_mode == "auto":
        vendor_steps = [
            "3. Run `vendor/install_hailo_sdk.sh` as `root`.",
            "4. Activate `/opt/hailo_venv` with `source /opt/hailo_venv/bin/activate`.",
            "5. Run `bundle/compile_commands.sh`.",
            "6. Copy the resulting `.hef` and `.har` files back to the local workspace.",
        ]
        notes = [
            "- This archive already includes the locally provided Hailo SDK downloads.",
            f"- The bundled model is `{bundle_name}`.",
            "- The compile target for the current Raspberry Pi AI HAT setup is `hailo8`, not `hailo8l`.",
        ]

    return f"""# Vast.ai Hailo Session

This archive is the staging workspace for compiling a Hailo HEF.

## Recommended launch settings

- Image: `{image}`
- Label: `{label}`
- Disk: `{disk_gb} GB`
- CPU arch: `amd64`
- OS target: `Ubuntu 22.04` or `Ubuntu 24.04`

## Session flow

1. Launch a Vast.ai instance with the recommended image.
2. Upload this tarball to the instance and extract it under `/workspace`.
{chr(10).join(vendor_steps)}

## Notes

{chr(10).join(notes)}
"""


def _make_launch_commands(bundle_archive_name: str, image: str, query: str, label: str, disk_gb: int) -> str:
    return f"""# Example Vast.ai launch flow

# 1. Search offers
vastai search offers '{query}' --raw -o dph_total

# 2. Launch one instance from a chosen offer id
vastai create instance <offer-id> --image {image} --disk {disk_gb} --label {label}

# 3. Upload this archive after the instance is running
scp -P <ssh-port> {bundle_archive_name} root@<ssh-host>:/workspace/{bundle_archive_name}

# 4. Extract on the remote side
ssh -p <ssh-port> root@<ssh-host> 'cd /workspace && tar xzf {bundle_archive_name}'

# 5. Continue with the README inside the extracted workspace
"""


def _package_workspace(args: argparse.Namespace) -> int:
    bundle_dir = Path(args.bundle_dir).resolve()
    if not bundle_dir.exists():
        raise FileNotFoundError(f"Bundle directory not found: {bundle_dir}")

    vendor_mode = "none"
    vendor_dir = Path(args.vendor_dir).resolve() if args.vendor_dir else None
    if vendor_dir is not None and not vendor_dir.exists():
        raise FileNotFoundError(f"Vendor directory not found: {vendor_dir}")
    vendor_downloads_dir = Path(args.vendor_downloads_dir).resolve() if args.vendor_downloads_dir else None
    if vendor_downloads_dir is not None and not vendor_downloads_dir.exists():
        raise FileNotFoundError(f"Vendor downloads directory not found: {vendor_downloads_dir}")

    output_path = Path(args.output).resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if output_path.exists():
        output_path.unlink()

    with tempfile.TemporaryDirectory(prefix="vastai-hailo-session-") as tmp:
        workspace_dir = Path(tmp) / output_path.stem
        bundle_dest = workspace_dir / "bundle"
        bundle_dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(bundle_dir, bundle_dest)

        if vendor_dir is not None:
            shutil.copytree(vendor_dir, workspace_dir / "vendor")
            vendor_mode = "manual"
        elif vendor_downloads_dir is not None:
            selected = _stage_auto_vendor_payload(
                vendor_downloads_dir,
                workspace_dir / "vendor",
                args.target_hw_arch,
            )
            _validate_target_compatibility(selected, args.target_hw_arch, args.allow_unsupported_suite)
            vendor_mode = "auto"
            print(
                "Selected vendor assets:\n"
                + json.dumps({key: value.name for key, value in selected.items()}, indent=2)
            )

        (workspace_dir / "README.md").write_text(
            _make_workspace_readme(bundle_dir.name, args.image, args.label, args.disk_gb, vendor_mode)
        )
        (workspace_dir / "launch_commands.sh").write_text(
            _make_launch_commands(output_path.name, args.image, args.query, args.label, args.disk_gb)
        )

        with tarfile.open(output_path, "w:gz") as handle:
            handle.add(workspace_dir, arcname=workspace_dir.name)

    print(f"Created session archive: {output_path}")
    return 0


def _print_launch_template(args: argparse.Namespace) -> int:
    print(_make_launch_commands(Path(args.bundle_archive).name, args.image, args.query, args.label, args.disk_gb))
    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    search = subparsers.add_parser("search-offers", help="Search Vast.ai offers without launching anything.")
    search.add_argument("--query", default=DEFAULT_QUERY)
    search.add_argument("--order", default="dph_total")
    search.add_argument("--limit", type=int, default=5)

    package = subparsers.add_parser("package-workspace", help="Create a tar.gz workspace for a manual Vast.ai compile session.")
    package.add_argument("--bundle-dir", default=str(DEFAULT_BUNDLE))
    package.add_argument("--vendor-dir", help="Optional directory with Hailo installer payloads/downloads.")
    package.add_argument(
        "--vendor-downloads-dir",
        default=str(DEFAULT_VENDOR_DOWNLOADS_DIR),
        help="Optional directory to auto-pick the needed Hailo SDK payloads from. Set to '' to disable.",
    )
    package.add_argument("--target-hw-arch", default=DEFAULT_TARGET_HW_ARCH)
    package.add_argument(
        "--allow-unsupported-suite",
        action="store_true",
        help="Allow packaging a vendor payload even if the selected Hailo suite is incompatible with the target hw-arch.",
    )
    package.add_argument("--output", required=True, help="Target .tar.gz archive path.")
    package.add_argument("--image", default=DEFAULT_IMAGE)
    package.add_argument("--query", default=DEFAULT_QUERY)
    package.add_argument("--label", default="hailo-hef-yolo11s")
    package.add_argument("--disk-gb", type=int, default=80)

    launch = subparsers.add_parser("print-launch-template", help="Print the manual Vast.ai launch/upload commands for a prepared archive.")
    launch.add_argument("--bundle-archive", required=True)
    launch.add_argument("--image", default=DEFAULT_IMAGE)
    launch.add_argument("--query", default=DEFAULT_QUERY)
    launch.add_argument("--label", default="hailo-hef-yolo11s")
    launch.add_argument("--disk-gb", type=int, default=80)

    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.command == "search-offers":
        return _search_offers(args)
    if args.command == "package-workspace":
        return _package_workspace(args)
    if args.command == "print-launch-template":
        return _print_launch_template(args)
    raise RuntimeError(f"Unhandled command: {args.command}")


if __name__ == "__main__":
    raise SystemExit(main())
