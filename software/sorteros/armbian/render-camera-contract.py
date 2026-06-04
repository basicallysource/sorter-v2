#!/usr/bin/env python3
"""Render the SorterOS hardware acceptance contract for Armbian userpatches."""

from __future__ import annotations

import argparse
import json
import tomllib
from pathlib import Path


def build_contract(config_path: Path, *, branch: str) -> dict:
    config = tomllib.loads(config_path.read_text())
    section = config["camera_transport"]
    return {
        "schema_version": 1,
        "image_version": config["output"]["version"],
        "branch": branch,
        "profile": section.get("profile", "rk3588-rockchip-mpp-rga-rknn"),
        "description": section.get("description", ""),
        "required_kernel_release_patterns": list(section.get("required_kernel_release_patterns", [])),
        "required_machine": section.get("required_machine"),
        "required_runtime_gates": list(section.get("required_runtime_gates", [])),
        "required_device_nodes": list(section.get("required_device_nodes", [])),
        "required_packages": list(section.get("required_packages", [])),
        "backend_env": dict(section.get("backend_env", {})),
        "probe_command": section.get(
            "probe_command",
            "cd /home/orangepi/sorter-v2/software/sorter/backend && .venv/bin/python scripts/probe_camera_transport_stack.py",
        ),
        "acceptance_probe_commands": list(section.get("acceptance_probe_commands", [])),
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True, type=Path)
    parser.add_argument("--branch", default="sorthive")
    parser.add_argument("--out", required=True, type=Path)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    contract = build_contract(args.config, branch=args.branch)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(contract, indent=2, sort_keys=True) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
