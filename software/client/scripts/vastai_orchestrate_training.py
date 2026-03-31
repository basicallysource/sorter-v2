#!/usr/bin/env python3
"""One-command launcher for remote Vast.ai detector training.

This orchestrates the full remote workflow from the local machine:
1. Prepare the unified training dataset/package
2. Allocate Vast.ai instances
3. Upload the package and run remote setup
4. Start each track detached on its instance
5. Start the local watcher that downloads results and destroys finished instances

Usage:
    uv run python scripts/vastai_orchestrate_training.py --dry-run
    uv run python scripts/vastai_orchestrate_training.py --label benchmark16
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import tarfile
import time

from model_identity import build_model_identity, collect_dataset_counts, compute_dataset_fingerprint, slugify

CLIENT_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = CLIENT_ROOT / "scripts"
BLOB_DIR = CLIENT_ROOT / "blob"
DATASET_DIR = BLOB_DIR / "kaggle_dataset"
UPLOAD_DIR = BLOB_DIR / "vastai_upload"
RUNS_DIR = BLOB_DIR / "vastai_runs"
PACKAGE_PATH = UPLOAD_DIR / "vastai_training_package.tar.gz"
WATCHER_SCRIPT = SCRIPTS_DIR / "watch_vastai_runs.py"

REMOTE_SETUP_SCRIPT = """#!/bin/bash
set -e

echo "=== LEGO Detector Training Package ==="
mkdir -p /workspace/dataset
cp -r /workspace/upload/dataset/* /workspace/dataset/

cd /workspace/dataset
if [ -d labels_yolo ] && [ ! -e labels ]; then
    ln -s labels_yolo labels
fi

echo "piece" > /workspace/dataset/classes.txt

cp /workspace/upload/vastai_track_a.py /workspace/
cp /workspace/upload/vastai_track_bc.py /workspace/
cp /workspace/upload/vastai_track_def.py /workspace/
cp /workspace/upload/training_plan.json /workspace/

mkdir -p /workspace/results

echo "=== Setup complete ==="
"""


@dataclass(frozen=True)
class ModelPlan:
    model_id: str
    family: str
    base_model: str
    imgsz: int | None
    epochs: int
    variant: str | None = None


@dataclass(frozen=True)
class TrackSpec:
    name: str
    remote_script: str
    process_pattern: str
    log_path: str
    disk_gb: int
    offer_query: str
    models: tuple[ModelPlan, ...]


@dataclass(frozen=True)
class ImageProfile:
    name: str
    image: str
    description: str


@dataclass(frozen=True)
class HardwareProfile:
    name: str
    extra_query: str
    description: str


TRACK_SPECS: dict[str, TrackSpec] = {
    "track_a": TrackSpec(
        name="track_a",
        remote_script="vastai_track_a.py",
        process_pattern="vastai_track_a.py",
        log_path="/workspace/track_a.log",
        disk_gb=40,
        offer_query="gpu_ram>=16 num_gpus=1 reliability>0.95 inet_down>200 disk_space>=40 cuda_vers>=12.0",
        models=(
            ModelPlan("A1", "yolo", "yolo26n", 320, 300),
            ModelPlan("A2", "yolo", "yolo26n", 416, 300),
            ModelPlan("A3", "yolo", "yolo11n", 320, 300),
            ModelPlan("A4", "yolo", "yolo11n", 416, 300),
            ModelPlan("A5", "yolo", "yolo11s", 320, 300),
            ModelPlan("A6", "yolo", "yolov8n", 320, 300),
        ),
    ),
    "track_bc": TrackSpec(
        name="track_bc",
        remote_script="vastai_track_bc.py",
        process_pattern="vastai_track_bc.py",
        log_path="/workspace/track_bc.log",
        disk_gb=40,
        offer_query="gpu_ram>=16 num_gpus=1 reliability>0.95 inet_down>200 disk_space>=40 cuda_vers>=12.0",
        models=(
            ModelPlan("B1", "nanodet", "nanodet-plus-m", 320, 200),
            ModelPlan("B2", "nanodet", "nanodet-plus-m", 416, 200),
            ModelPlan("B3", "nanodet", "nanodet-plus-m", 416, 200, variant="1.5x"),
            ModelPlan("C1", "yolox", "yolox-nano", 416, 200),
            ModelPlan("C2", "yolox", "yolox-tiny", 416, 200),
        ),
    ),
    "track_def": TrackSpec(
        name="track_def",
        remote_script="vastai_track_def.py",
        process_pattern="vastai_track_def.py",
        log_path="/workspace/track_def.log",
        disk_gb=40,
        offer_query="gpu_ram>=16 num_gpus=1 reliability>0.95 inet_down>200 disk_space>=40 cuda_vers>=12.0",
        models=(
            ModelPlan("D1", "picodet", "picodet-xs", 320, 200),
            ModelPlan("D2", "picodet", "picodet-s", 320, 200),
            ModelPlan("E1", "yolov9", "yolov9t", 320, 300),
            ModelPlan("F1", "fastestdet", "fastestdet", 352, 200, variant="v2"),
        ),
    ),
}

IMAGE_PROFILES: dict[str, ImageProfile] = {
    "pytorch-cu121-compat": ImageProfile(
        name="pytorch-cu121-compat",
        image="pytorch/pytorch:2.3.1-cuda12.1-cudnn8-runtime",
        description="Pinned PyTorch CUDA 12.1 runtime with broad compatibility for the mixed framework stack.",
    ),
    "pytorch-cu121-modern": ImageProfile(
        name="pytorch-cu121-modern",
        image="pytorch/pytorch:2.4.1-cuda12.1-cudnn9-runtime",
        description="Newer pinned PyTorch CUDA 12.1 runtime for when we want a more current torch base.",
    ),
}

HARDWARE_PROFILES: dict[str, HardwareProfile] = {
    "stable_3090": HardwareProfile(
        name="stable_3090",
        extra_query="gpu_name=RTX_3090 gpu_ram>=20 reliability>0.98 inet_down>500",
        description="Preferred default: 24 GB RTX 3090 offers a stable balance of VRAM, availability, and cost.",
    ),
    "economy_4070s_ti": HardwareProfile(
        name="economy_4070s_ti",
        extra_query="gpu_name=RTX_4070S_Ti gpu_ram>=16 reliability>0.98 inet_down>500",
        description="Lower-cost fallback with good availability, but less VRAM headroom than the 3090 profile.",
    ),
    "fast_4090": HardwareProfile(
        name="fast_4090",
        extra_query="gpu_name=RTX_4090 gpu_ram>=20 reliability>0.98 inet_down>500",
        description="Fastest single-GPU option, usually at a noticeable price premium.",
    ),
}


def run_command(args: list[str], *, check: bool = True, capture_output: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, check=check, text=True, capture_output=capture_output)


def ssh_command(host: str, port: int, remote_cmd: str, *, check: bool = True) -> subprocess.CompletedProcess[str]:
    return run_command(
        [
            "ssh",
            "-o",
            "StrictHostKeyChecking=no",
            "-o",
            "ConnectTimeout=20",
            "-p",
            str(port),
            f"root@{host}",
            remote_cmd,
        ],
        check=check,
    )


def scp_to_remote(host: str, port: int, local_path: Path, remote_path: str) -> None:
    run_command(
        [
            "scp",
            "-P",
            str(port),
            "-o",
            "StrictHostKeyChecking=no",
            str(local_path),
            f"root@{host}:{remote_path}",
        ]
    )


def ensure_dataset_ready() -> None:
    run_command(["python3", str(SCRIPTS_DIR / "vastai_prepare_all_tracks.py")], capture_output=False)


def filter_tracks(track_names: list[str], selected_model_ids: list[str] | None) -> list[TrackSpec]:
    requested_ids = {model_id.strip().upper() for model_id in (selected_model_ids or []) if model_id.strip()}
    filtered_tracks: list[TrackSpec] = []
    matched_ids: set[str] = set()
    for track_name in track_names:
        base_track = TRACK_SPECS[track_name]
        models = tuple(model for model in base_track.models if not requested_ids or model.model_id in requested_ids)
        matched_ids.update(model.model_id for model in models)
        if not models:
            continue
        filtered_tracks.append(
            TrackSpec(
                name=base_track.name,
                remote_script=base_track.remote_script,
                process_pattern=base_track.process_pattern,
                log_path=base_track.log_path,
                disk_gb=base_track.disk_gb,
                offer_query=base_track.offer_query,
                models=models,
            )
        )
    unknown_ids = sorted(requested_ids - matched_ids)
    if unknown_ids:
        raise ValueError(f"Unknown or unselected model IDs: {', '.join(unknown_ids)}")
    if not filtered_tracks:
        raise ValueError("No tracks remain after applying the requested model filter.")
    return filtered_tracks


def build_run_plan(
    label: str,
    selected_tracks: list[TrackSpec],
    *,
    image_profile: ImageProfile,
    hardware_profile: HardwareProfile,
    selected_model_ids: list[str] | None,
) -> dict[str, object]:
    dataset_fingerprint = compute_dataset_fingerprint(DATASET_DIR)
    dataset_counts = collect_dataset_counts(DATASET_DIR)
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    run_nickname = build_model_identity(
        model_id="RUN",
        family="vastai",
        base_model=label,
        variant="multi-track",
        imgsz=None,
        epochs=None,
        dataset_fingerprint=dataset_fingerprint,
    )
    run_name = f"{timestamp}-{slugify(label)}-{run_nickname.nickname}"

    tracks_payload = []
    for track in selected_tracks:
        identities = [
            build_model_identity(
                model_id=model.model_id,
                family=model.family,
                base_model=model.base_model,
                variant=model.variant,
                imgsz=model.imgsz,
                epochs=model.epochs,
                dataset_fingerprint=dataset_fingerprint,
            ).to_dict()
            for model in track.models
        ]
        tracks_payload.append(
            {
                "name": track.name,
                "remote_script": track.remote_script,
                "process_pattern": track.process_pattern,
                "log_path": track.log_path,
                "disk_gb": track.disk_gb,
                "offer_query": track.offer_query,
                "models": identities,
            }
        )

    return {
        "created_at": time.time(),
        "label": label,
        "run_name": run_name,
        "run_nickname": run_nickname.nickname,
        "run_friendly_name": run_nickname.friendly_name,
        "dataset": {
            "dataset_dir": str(DATASET_DIR),
            "fingerprint": dataset_fingerprint,
            "counts": dataset_counts,
        },
        "execution": {
            "image_profile": image_profile.name,
            "image": image_profile.image,
            "hardware_profile": hardware_profile.name,
            "hardware_query": hardware_profile.extra_query,
            "selected_model_ids": [model_id.strip().upper() for model_id in (selected_model_ids or []) if model_id.strip()],
        },
        "tracks": tracks_payload,
    }


def _ignore_stage_files(_dir: str, names: list[str]) -> set[str]:
    ignored = {".DS_Store", "__pycache__"}
    ignored.update({name for name in names if name.startswith("._")})
    return ignored


def build_upload_package(plan: dict[str, object]) -> Path:
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    stage_dir = UPLOAD_DIR / "_staging"
    if stage_dir.exists():
        shutil.rmtree(stage_dir)
    stage_dir.mkdir(parents=True, exist_ok=True)

    shutil.copytree(DATASET_DIR, stage_dir / "dataset", ignore=_ignore_stage_files)
    for script_name in ["vastai_track_a.py", "vastai_track_bc.py", "vastai_track_def.py"]:
        shutil.copy2(SCRIPTS_DIR / script_name, stage_dir / script_name)
    (stage_dir / "setup.sh").write_text(REMOTE_SETUP_SCRIPT)
    os.chmod(stage_dir / "setup.sh", 0o755)
    (stage_dir / "training_plan.json").write_text(json.dumps(plan, indent=2))

    if PACKAGE_PATH.exists():
        PACKAGE_PATH.unlink()
    with tarfile.open(PACKAGE_PATH, "w:gz", format=tarfile.GNU_FORMAT) as archive:
        for path in sorted(stage_dir.rglob("*")):
            if path.is_dir():
                continue
            archive.add(path, arcname=str(Path("upload") / path.relative_to(stage_dir)))
    return PACKAGE_PATH


def search_offers(query: str, limit: int) -> list[dict[str, object]]:
    result = run_command(
        ["vastai", "search", "offers", query, "-o", "dph", "--limit", str(limit), "--raw"]
    )
    return json.loads(result.stdout)


def _offer_sort_key(offer: dict[str, object]) -> tuple[float, float, float, float]:
    reliability = float(offer.get("reliability2") or offer.get("reliability") or 0.0)
    net_down = float(offer.get("inet_down") or 0.0)
    dlperf = float(offer.get("dlperf_per_dphtotal") or offer.get("dlperf_usd") or 0.0)
    price = float(offer.get("dph_total") or 9999.0)
    return (reliability, net_down, dlperf, -price)


def build_offer_query(track: TrackSpec, hardware_profile: HardwareProfile) -> str:
    return f"{track.offer_query} {hardware_profile.extra_query}".strip()


def pick_offers(track_specs: list[TrackSpec], limit: int, hardware_profile: HardwareProfile) -> dict[str, dict[str, object]]:
    selected: dict[str, dict[str, object]] = {}
    used_machine_ids: set[object] = set()
    for track in track_specs:
        offers = sorted(search_offers(build_offer_query(track, hardware_profile), limit), key=_offer_sort_key, reverse=True)
        for offer in offers:
            machine_id = offer.get("machine_id")
            if machine_id in used_machine_ids:
                continue
            selected[track.name] = offer
            used_machine_ids.add(machine_id)
            break
        if track.name not in selected:
            raise RuntimeError(f"No suitable Vast.ai offer found for {track.name}")
    return selected


def create_instance(offer_id: int, image: str, disk_gb: int) -> dict[str, object]:
    result = run_command(
        [
            "vastai",
            "create",
            "instance",
            str(offer_id),
            "--image",
            image,
            "--disk",
            str(disk_gb),
            "--onstart-cmd",
            "sleep infinity",
            "--raw",
        ]
    )
    payload = json.loads(result.stdout)
    contract = payload.get("new_contract")
    if not contract:
        raise RuntimeError(f"Vast.ai create instance returned no contract: {payload}")
    return payload


def destroy_instance(contract: str) -> None:
    run_command(["vastai", "destroy", "instance", contract, "--raw"], check=False)


def show_instance(contract: str) -> dict[str, object]:
    result = run_command(["vastai", "show", "instance", contract, "--raw"])
    return json.loads(result.stdout)


def wait_for_running(contract: str, timeout_seconds: int = 600) -> dict[str, object]:
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        payload = show_instance(contract)
        if payload.get("actual_status") == "running":
            return payload
        time.sleep(10)
    raise TimeoutError(f"Instance {contract} did not reach running state within {timeout_seconds}s")


def remote_setup_and_launch(track: TrackSpec, host: str, port: int, package_path: Path) -> None:
    scp_to_remote(host, port, package_path, "/workspace/upload.tar.gz")
    ssh_command(
        host,
        port,
        """
set -e
rm -rf /workspace/upload /workspace/dataset /workspace/results
mkdir -p /workspace
tar xzf /workspace/upload.tar.gz -C /workspace
bash /workspace/upload/setup.sh
""".strip(),
    )

    selected_ids = [model.model_id for model in track.models]
    selected_args = ", ".join(repr(value) for value in selected_ids)

    launch_cmd = f"""
python - <<'PY'
import subprocess
from pathlib import Path

log_path = Path({track.log_path!r})
log_path.unlink(missing_ok=True)
results_path = Path('/workspace/results/{track.name}_results.json')
results_path.unlink(missing_ok=True)

handle = open(log_path, 'ab', buffering=0)
subprocess.Popen(
    ['python', '/workspace/{track.remote_script}', '--model-ids', {selected_args}],
    stdout=handle,
    stderr=subprocess.STDOUT,
    stdin=subprocess.DEVNULL,
    start_new_session=True,
    cwd='/workspace',
)
print('started')
PY
""".strip()
    ssh_command(host, port, launch_cmd)


def start_watcher(run_dir: Path, tracks: list[dict[str, object]], poll_seconds: int) -> tuple[int, Path]:
    watcher_log = run_dir / "watcher.log"
    results_output_dir = run_dir / "results"
    cmd = [
        "python3",
        str(WATCHER_SCRIPT),
        "--output-dir",
        str(results_output_dir),
        "--poll-seconds",
        str(poll_seconds),
    ]
    for track in tracks:
        cmd.extend(
            [
                "--run",
                str(track["name"]),
                str(track["contract"]),
                str(track["ssh_host"]),
                str(track["ssh_port"]),
                str(track["process_pattern"]),
                str(track["log_path"]),
            ]
        )

    watcher_log.parent.mkdir(parents=True, exist_ok=True)
    with watcher_log.open("ab") as handle:
        proc = subprocess.Popen(cmd, stdout=handle, stderr=subprocess.STDOUT, start_new_session=True)
    return proc.pid, results_output_dir


def print_plan(plan: dict[str, object]) -> None:
    print(f"Run: {plan['run_name']}")
    print(f"Nickname: {plan['run_friendly_name']}")
    dataset = plan["dataset"]
    execution = plan["execution"]
    print(f"Dataset fingerprint: {dataset['fingerprint']}")
    print(f"Image: {execution['image']} ({execution['image_profile']})")
    print(f"Hardware: {execution['hardware_profile']} [{execution['hardware_query']}]")
    if execution["selected_model_ids"]:
        print(f"Selected models: {', '.join(execution['selected_model_ids'])}")
    print("Tracks:")
    for track in plan["tracks"]:
        print(f"  - {track['name']}")
        for model in track["models"]:
            print(f"      {model['display_name']} [{model['short_code']}]")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--tracks",
        nargs="+",
        choices=sorted(TRACK_SPECS.keys()),
        default=sorted(TRACK_SPECS.keys()),
        help="Which remote track scripts to launch.",
    )
    parser.add_argument(
        "--model-ids",
        nargs="+",
        default=None,
        help="Optional specific model IDs to launch, e.g. B1 B2 D1 E1.",
    )
    parser.add_argument("--label", default="benchmark16", help="Human label for this orchestration run.")
    parser.add_argument(
        "--image-profile",
        choices=sorted(IMAGE_PROFILES.keys()),
        default="pytorch-cu121-compat",
        help="Pinned container image preset for Vast.ai instances.",
    )
    parser.add_argument(
        "--hardware-profile",
        choices=sorted(HARDWARE_PROFILES.keys()),
        default="stable_3090",
        help="Pinned Vast.ai hardware preference preset.",
    )
    parser.add_argument("--image", default=None, help="Optional raw Vast.ai base image override.")
    parser.add_argument("--offer-limit", type=int, default=20, help="How many offers to inspect per track.")
    parser.add_argument(
        "--running-timeout-seconds",
        type=int,
        default=600,
        help="How long to wait for a fresh Vast.ai instance to reach running before destroying it.",
    )
    parser.add_argument("--poll-seconds", type=int, default=120, help="Watcher polling interval.")
    parser.add_argument("--dry-run", action="store_true", help="Prepare package/plan only; do not call Vast.ai.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    image_profile = IMAGE_PROFILES[args.image_profile]
    hardware_profile = HARDWARE_PROFILES[args.hardware_profile]
    selected_tracks = filter_tracks(args.tracks, args.model_ids)

    ensure_dataset_ready()
    plan = build_run_plan(
        args.label,
        selected_tracks,
        image_profile=image_profile,
        hardware_profile=hardware_profile,
        selected_model_ids=args.model_ids,
    )
    package_path = build_upload_package(plan)

    run_dir = RUNS_DIR / str(plan["run_name"])
    run_dir.mkdir(parents=True, exist_ok=True)
    local_manifest_path = run_dir / "run.json"

    local_manifest: dict[str, object] = {
        **plan,
        "package_path": str(package_path),
        "package_size_bytes": package_path.stat().st_size,
        "instances": [],
        "watcher": None,
    }
    local_manifest_path.write_text(json.dumps(local_manifest, indent=2))

    print_plan(plan)
    print(f"Package: {package_path}")

    if args.dry_run:
        print("Dry-run complete. No Vast.ai instances were created.")
        return 0

    offers = pick_offers(selected_tracks, args.offer_limit, hardware_profile)
    image = args.image or image_profile.image
    launched_tracks: list[dict[str, object]] = []
    for track in selected_tracks:
        offer = offers[track.name]
        creation = create_instance(int(offer["id"]), image, track.disk_gb)
        contract = str(creation["new_contract"])
        try:
            instance = wait_for_running(contract, args.running_timeout_seconds)
            ssh_host = str(instance["ssh_host"])
            ssh_port = int(instance["ssh_port"])

            remote_setup_and_launch(track, ssh_host, ssh_port, package_path)
        except Exception:
            destroy_instance(contract)
            raise

        launched_tracks.append(
            {
                "name": track.name,
                "contract": contract,
                "ssh_host": ssh_host,
                "ssh_port": ssh_port,
                "offer_id": offer["id"],
                "machine_id": offer.get("machine_id"),
                "gpu_name": offer.get("gpu_name"),
                "price_per_hour": offer.get("dph_total"),
                "process_pattern": track.process_pattern,
                "log_path": track.log_path,
                "remote_script": track.remote_script,
                "model_ids": [model.model_id for model in track.models],
            }
        )
        local_manifest["instances"] = launched_tracks
        local_manifest_path.write_text(json.dumps(local_manifest, indent=2))
        print(f"Launched {track.name}: contract={contract} ssh={ssh_host}:{ssh_port}")

    watcher_pid, watcher_results_dir = start_watcher(run_dir, launched_tracks, args.poll_seconds)
    local_manifest["watcher"] = {
        "pid": watcher_pid,
        "log_path": str(run_dir / "watcher.log"),
        "poll_seconds": args.poll_seconds,
        "results_dir": str(watcher_results_dir),
    }
    local_manifest_path.write_text(json.dumps(local_manifest, indent=2))

    print(f"Watcher started with PID {watcher_pid}")
    print(f"Run manifest: {local_manifest_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
