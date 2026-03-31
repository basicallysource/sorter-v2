#!/usr/bin/env python3
"""Train zone-specific detection models on Vast.ai.

For each zone (classification_chamber, tray, c_channel), trains:
  - NanoDet-Plus-m-1.5x @ 416
  - YOLO11s @ 320

Usage:
    uv run python scripts/vastai_zone_training.py --zone tray --model nanodet
    uv run python scripts/vastai_zone_training.py --zone c_channel --model yolo11s
    uv run python scripts/vastai_zone_training.py --zone all --model all
    uv run python scripts/vastai_zone_training.py --package-only  # just create tarballs
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import tarfile
import time
from pathlib import Path

CLIENT_ROOT = Path(__file__).resolve().parents[1]
ZONE_DATASETS = CLIENT_ROOT / "blob" / "zone_datasets"
UPLOAD_DIR = CLIENT_ROOT / "blob" / "vastai_zone_uploads"
RUNS_DIR = CLIENT_ROOT / "blob" / "vastai_zone_runs"

ZONES = ["classification_chamber", "tray", "c_channel"]
MODELS = {
    "nanodet": {
        "label": "NanoDet-Plus-m-1.5x-416",
        "track_script": "vastai_track_bc.py",
        "model_ids": "B3",
        "family": "nanodet",
    },
    "yolo11s": {
        "label": "YOLO11s-320",
        "track_script": "vastai_track_a.py",
        "model_ids": "A5",
        "family": "yolo",
    },
}

VASTAI_IMAGE = "pytorch/pytorch:2.3.1-cuda12.1-cudnn8-runtime"
VASTAI_QUERY = "gpu_ram>=16 num_gpus=1 reliability>0.95 inet_down>200 disk_space>=40 cuda_vers>=12.0 gpu_name=RTX_3090"


def run(cmd: list[str], **kwargs) -> subprocess.CompletedProcess:
    print(f"  $ {' '.join(cmd[:6])}{'...' if len(cmd) > 6 else ''}")
    return subprocess.run(cmd, **kwargs)


def create_package(zone: str) -> Path:
    """Create a training tar.gz for a specific zone."""
    zone_dir = ZONE_DATASETS / zone
    if not zone_dir.exists():
        raise FileNotFoundError(f"Zone dataset not found: {zone_dir}")

    pkg_dir = UPLOAD_DIR / zone
    pkg_dir.mkdir(parents=True, exist_ok=True)

    # Copy dataset (resolve symlinks to actual files)
    ds_dir = pkg_dir / "dataset"
    if ds_dir.exists():
        shutil.rmtree(ds_dir)

    for split in ["train", "val"]:
        for sub in ["images", "labels"]:
            src = zone_dir / split / sub
            dst = ds_dir / split / sub
            dst.mkdir(parents=True, exist_ok=True)
            for f in src.iterdir():
                real = f.resolve()
                shutil.copy2(str(real), str(dst / f.name))

    # Write data.yaml
    (ds_dir / "data.yaml").write_text(
        "path: /workspace/dataset\ntrain: train/images\nval: val/images\nnames:\n  0: piece\n"
    )
    (ds_dir / "classes.txt").write_text("piece\n")

    # Copy training scripts
    scripts_dir = CLIENT_ROOT / "scripts"
    for script in ["vastai_track_a.py", "vastai_track_bc.py"]:
        src = scripts_dir / script
        if src.exists():
            shutil.copy2(str(src), str(pkg_dir / script))

    # Create tarball
    tarball = UPLOAD_DIR / f"zone_{zone}.tar.gz"
    print(f"Creating {tarball.name}...")
    with tarfile.open(tarball, "w:gz") as tar:
        tar.add(str(ds_dir), arcname="dataset")
        for script in ["vastai_track_a.py", "vastai_track_bc.py"]:
            sp = pkg_dir / script
            if sp.exists():
                tar.add(str(sp), arcname=script)

    size_mb = tarball.stat().st_size / 1024 / 1024
    n_train = len(list((ds_dir / "train" / "images").iterdir()))
    n_val = len(list((ds_dir / "val" / "images").iterdir()))
    print(f"  {zone}: {tarball.name} = {size_mb:.1f} MB ({n_train} train + {n_val} val)")
    return tarball


def launch_instance(zone: str, model_key: str) -> dict:
    """Create a Vast.ai instance and return connection info."""
    model_info = MODELS[model_key]
    label = f"zone-{zone}-{model_key}"

    # Search for offers
    print(f"\nSearching Vast.ai offers for {label}...")
    result = run(
        ["vastai", "search", "offers", VASTAI_QUERY, "--raw", "-o", "dph"],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(f"vastai search failed: {result.stderr}")

    offers = json.loads(result.stdout)
    if not offers:
        raise RuntimeError("No Vast.ai offers found")

    offer = offers[0]
    offer_id = offer["id"]
    dph = offer.get("dph_total", "?")
    gpu = offer.get("gpu_name", "?")
    print(f"  Best offer: #{offer_id} {gpu} @ ${dph}/hr")

    # Create instance
    result = run(
        [
            "vastai", "create", "instance", str(offer_id),
            "--image", VASTAI_IMAGE,
            "--disk", "40",
            "--label", label,
            "--raw",
        ],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(f"vastai create failed: {result.stderr}")

    resp = json.loads(result.stdout)
    contract_id = resp.get("new_contract")
    if not contract_id:
        raise RuntimeError(f"No contract ID in response: {resp}")

    print(f"  Created instance contract={contract_id}")
    return {"contract_id": contract_id, "offer_id": offer_id, "label": label}


def wait_for_ssh(contract_id: int, timeout: int = 300) -> str:
    """Wait for instance to be running and return SSH connection string."""
    print(f"  Waiting for instance {contract_id} to start...")
    start = time.time()
    while time.time() - start < timeout:
        result = run(
            ["vastai", "show", "instance", str(contract_id), "--raw"],
            capture_output=True, text=True,
        )
        if result.returncode == 0:
            info = json.loads(result.stdout)
            status = info.get("actual_status", "")
            ssh_host = info.get("ssh_host", "")
            ssh_port = info.get("ssh_port", "")
            if status == "running" and ssh_host and ssh_port:
                ssh_str = f"ssh -p {ssh_port} root@{ssh_host}"
                print(f"  Instance running: {ssh_str}")
                return f"root@{ssh_host} -p {ssh_port}"
        time.sleep(10)

    raise TimeoutError(f"Instance {contract_id} did not start within {timeout}s")


def upload_and_train(contract_id: int, ssh_info: str, tarball: Path, zone: str, model_key: str):
    """Upload package, extract, and start training."""
    model_info = MODELS[model_key]
    parts = ssh_info.split(" -p ")
    user_host = parts[0]
    port = parts[1]

    # Upload tarball
    print(f"  Uploading {tarball.name}...")
    run(
        ["scp", "-P", port, "-o", "StrictHostKeyChecking=no", str(tarball), f"{user_host}:/workspace/package.tar.gz"],
        check=True,
    )

    # Extract and setup
    setup_cmds = """
cd /workspace && tar xzf package.tar.gz && rm package.tar.gz
cd /workspace/dataset && if [ -d labels_yolo ] && [ ! -e labels ]; then ln -s labels_yolo labels; fi
echo "piece" > /workspace/dataset/classes.txt
mkdir -p /workspace/results
"""
    run(
        ["ssh", "-p", port, "-o", "StrictHostKeyChecking=no", user_host, setup_cmds],
        check=True,
    )

    # Start training
    if model_key == "nanodet":
        train_cmd = f"cd /workspace && nohup python vastai_track_bc.py --model-ids B3 > /workspace/train.log 2>&1 &"
    else:  # yolo11s
        train_cmd = f"cd /workspace && nohup python vastai_track_a.py --model-ids A5 > /workspace/train.log 2>&1 &"

    print(f"  Starting training: {model_info['label']} on zone {zone}")
    run(
        ["ssh", "-p", port, "-o", "StrictHostKeyChecking=no", user_host, train_cmd],
        check=True,
    )

    # Save run info
    run_dir = RUNS_DIR / f"{zone}-{model_key}"
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "run_info.json").write_text(json.dumps({
        "zone": zone,
        "model_key": model_key,
        "model_label": model_info["label"],
        "contract_id": contract_id,
        "ssh_info": ssh_info,
        "started_at": time.time(),
    }, indent=2))

    print(f"  Training launched! Monitor: vastai logs {contract_id}")


def generate_monitor_script(zone: str, model_key: str, contract_id: int, ssh_info: str):
    """Generate a shell script to monitor training and download results."""
    model_info = MODELS[model_key]
    run_dir = RUNS_DIR / f"{zone}-{model_key}"
    run_dir.mkdir(parents=True, exist_ok=True)

    parts = ssh_info.split(" -p ")
    user_host = parts[0]
    port = parts[1]

    script = f"""#!/bin/bash
# Monitor {zone} / {model_info['label']} on Vast.ai instance {contract_id}
set -e

SSH="ssh -p {port} -o StrictHostKeyChecking=no {user_host}"
SCP="scp -P {port} -o StrictHostKeyChecking=no"
CONTRACT={contract_id}
RESULTS_DIR="{run_dir}/results"

mkdir -p "$RESULTS_DIR"

echo "Monitoring {zone}/{model_key} on contract $CONTRACT..."

while true; do
    # Check if training process is still running
    RUNNING=$($SSH "pgrep -f 'vastai_track_' || true" 2>/dev/null)
    if [ -z "$RUNNING" ]; then
        echo "Training finished! Downloading results..."
        $SCP "{user_host}:/workspace/results/*" "$RESULTS_DIR/" 2>/dev/null || true
        $SCP "{user_host}:/workspace/train.log" "$RESULTS_DIR/" 2>/dev/null || true
        echo "Results downloaded to $RESULTS_DIR"
        echo "Destroying instance $CONTRACT..."
        vastai destroy instance $CONTRACT
        echo "Done!"
        exit 0
    fi

    # Show last log line
    $SSH "tail -1 /workspace/train.log 2>/dev/null" || true
    sleep 180
done
"""
    script_path = run_dir / "monitor.sh"
    script_path.write_text(script)
    script_path.chmod(0o755)
    print(f"  Monitor script: {script_path}")
    return script_path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--zone", default="all", help="Zone: classification_chamber, tray, c_channel, or all")
    parser.add_argument("--model", default="all", help="Model: nanodet, yolo11s, or all")
    parser.add_argument("--package-only", action="store_true", help="Only create packages, don't launch")
    args = parser.parse_args()

    zones = ZONES if args.zone == "all" else [args.zone]
    model_keys = list(MODELS.keys()) if args.model == "all" else [args.model]

    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

    # Step 1: Create packages for each zone
    print("=== Creating training packages ===")
    tarballs = {}
    for zone in zones:
        tarballs[zone] = create_package(zone)

    if args.package_only:
        print("\nPackages created. Use --zone/--model to launch training.")
        return

    # Step 2: Launch instances and start training
    print("\n=== Launching Vast.ai instances ===")
    for zone in zones:
        for model_key in model_keys:
            try:
                info = launch_instance(zone, model_key)
                contract_id = info["contract_id"]
                ssh_info = wait_for_ssh(contract_id)
                upload_and_train(contract_id, ssh_info, tarballs[zone], zone, model_key)
                generate_monitor_script(zone, model_key, contract_id, ssh_info)
            except Exception as e:
                print(f"  ERROR launching {zone}/{model_key}: {e}")
                continue

    print("\n=== All training jobs launched ===")
    print("Run monitor scripts to track progress and download results.")


if __name__ == "__main__":
    raise SystemExit(main() or 0)
