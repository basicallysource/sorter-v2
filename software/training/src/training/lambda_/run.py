"""Drive a full r3-style training run on a Lambda Labs box from the local Mac.

Lambda is provisioned out-of-band: the user supplies an ssh host
(`ubuntu@<ip>`). This module ssh's in, rsyncs the local `software/training/`
checkout, pulls Hive samples + builds the dataset on the box, trains + exports
a head-stripped ONNX, converts to a quantized .rknn via the sidecar
rknn-toolkit2 venv, and finally rsyncs a self-contained bundle back to a local
output directory (default the user's T7 drive).

This deliberately does NOT mirror `vastai/` 1:1 because Lambda has no
auto-provision step. There's no `lambda offers` / `lambda launch`. One command
runs the whole pipeline for a single (zone, model_id) combination.

Layout assumed on the Lambda box:

    /lambda/nfs/one/sorter-npu/
        repo/software/training/          <-- rsynced from Mac
        rknn-venv/                       <-- preexisting Py3.10 + rknn-toolkit2 2.3.2
        runs/                            <-- training outputs
        bundles/                         <-- per-bundle output dir
        datasets/<zone>/...              <-- created by `train pull` + `train build`
"""

from __future__ import annotations

import json
import shlex
import subprocess
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from training.lambda_.status import PipelineStatus


REMOTE_ROOT = "/lambda/nfs/one/sorter-npu"
REMOTE_REPO = f"{REMOTE_ROOT}/repo"
REMOTE_TRAINING = f"{REMOTE_REPO}/software/training"
REMOTE_RKNN_VENV = f"{REMOTE_ROOT}/rknn-venv"
REMOTE_UV = "/home/ubuntu/.local/bin/uv"


@dataclass
class LambdaRunConfig:
    host: str  # e.g. "ubuntu@157.151.159.81"
    zone: str  # e.g. "c_channel" or "classification_channel"
    dataset_name: str  # e.g. "r3_c_channel_2026_05_22"
    bundle_name: str  # final dir on T7
    model_id: str = "A3"  # see scripts/lambda/train_export.py YOLO_MODELS
    epochs: int = 300
    target_size: int | None = None  # passed to `train build --target-size`
    min_detection_score: float = 0.98
    calibration_count: int = 150
    target_platform: str = "rk3588"
    quantization: str = "i8"
    hive_url: str = "https://hive.basically.website"
    output_root: Path = Path("/Volumes/T7/sorter-v2-vision-models")
    head_stripped: bool = True
    skip_pull: bool = False
    skip_build: bool = False
    extra_build_flags: list[str] = field(default_factory=lambda: ["--balance-source-role"])
    activation: str = "silu"  # "silu" or "relu6"

    @property
    def remote_run_dir(self) -> str:
        return f"{REMOTE_ROOT}/runs/{self.bundle_name}"

    @property
    def remote_bundle_dir(self) -> str:
        return f"{REMOTE_ROOT}/bundles/{self.bundle_name}"

    @property
    def local_bundle_dir(self) -> Path:
        return self.output_root / self.bundle_name


def _localRepoRoot() -> Path:
    here = Path(__file__).resolve()
    for parent in here.parents:
        if (parent / "pyproject.toml").exists() and parent.name == "training":
            return parent
    raise RuntimeError("could not find local software/training root")


def _streamSubprocess(cmd: list[str], status: PipelineStatus | None) -> str:
    """Run cmd, stream stdout+stderr live to terminal + status.log_line, return full stdout."""
    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )
    collected: list[str] = []
    assert proc.stdout is not None
    for line in proc.stdout:
        sys.stdout.write(line)
        sys.stdout.flush()
        collected.append(line)
        if status is not None:
            status.log_line(line)
    proc.wait()
    if proc.returncode != 0:
        raise subprocess.CalledProcessError(proc.returncode, cmd, output="".join(collected))
    return "".join(collected)


def _runLocal(cmd: list[str], *, status: PipelineStatus | None = None, capture: bool = False) -> str:
    printable = " ".join(shlex.quote(c) for c in cmd)
    print(f"[local] {printable}")
    if status is not None:
        status.log_line(f"$ {printable}")
    if capture:
        result = subprocess.run(cmd, check=True, capture_output=True, text=True)
        return result.stdout
    return _streamSubprocess(cmd, status)


def _runRemote(host: str, remote_cmd: str, *, status: PipelineStatus | None = None, capture: bool = False) -> str:
    # ssh joins positional args with spaces on the remote, which would split
    # multi-word args. Pass remote_cmd as ONE string so the remote shell
    # parses it as-is.
    cmd = ["ssh", host, remote_cmd]
    shown = remote_cmd[:200] + ("…" if len(remote_cmd) > 200 else "")
    print(f"[ssh {host}] {shown}")
    if status is not None:
        status.log_line(f"[ssh] {shown}")
    if capture:
        result = subprocess.run(cmd, check=True, capture_output=True, text=True)
        return result.stdout
    return _streamSubprocess(cmd, status)


def _rsyncToRemote(host: str, local: Path, remote_path: str, *, status: PipelineStatus | None = None) -> None:
    cmd = [
        "rsync",
        "-az",
        "--delete",
        "--exclude=__pycache__",
        "--exclude=.venv",
        "--exclude=.ruff_cache",
        "--exclude=.pytest_cache",
        # Top-level data dirs only — leading slash anchors to the rsync root
        # so we don't accidentally drop src/training/datasets/ (the Python pkg).
        "--exclude=/datasets/",
        "--exclude=/runs/",
        "--exclude=/hailo_bundles/",
        "--exclude=/node_modules/",
        f"{local}/",
        f"{host}:{remote_path}/",
    ]
    _runLocal(cmd, status=status)


def _rsyncFromRemote(host: str, remote_path: str, local_path: Path, *, status: PipelineStatus | None = None) -> None:
    local_path.mkdir(parents=True, exist_ok=True)
    cmd = ["rsync", "-az", f"{host}:{remote_path}/", f"{local_path}/"]
    _runLocal(cmd, status=status)


def _ensureRemoteUv(host: str, *, status: PipelineStatus | None = None) -> None:
    check = subprocess.run(
        ["ssh", host, f"test -x {REMOTE_UV} && echo ok || echo missing"],
        capture_output=True,
        text=True,
    )
    if check.stdout.strip() == "ok":
        return
    print(f"[setup] installing uv on {host}")
    _runRemote(host, "curl -LsSf https://astral.sh/uv/install.sh | sh", status=status)


def _ensureRemoteVenv(host: str, *, status: PipelineStatus | None = None) -> None:
    _runRemote(
        host,
        f"cd {REMOTE_TRAINING} && echo 3.11 > .python-version && {REMOTE_UV} sync --python 3.11",
        status=status,
    )


def _ensureRknnVenv(host: str) -> None:
    check = subprocess.run(
        ["ssh", host, f"{REMOTE_RKNN_VENV}/bin/python -c 'from rknn.api import RKNN; print(\"ok\")'"],
        capture_output=True,
        text=True,
    )
    if check.stdout.strip() == "ok":
        return
    raise SystemExit(
        f"rknn sidecar venv missing or broken at {REMOTE_RKNN_VENV}. "
        "Provision it manually with Python 3.10 + setuptools<81 + onnx==1.14.1 + protobuf<5 + rknn-toolkit2==2.3.2 "
        "(see training-npu-r2/README.md §'Dependency pin trail')."
    )


def _remoteTrainCmd(cfg: LambdaRunConfig, data_yaml_remote: str, result_json_remote: str) -> str:
    head_flag = "" if cfg.head_stripped else "--no-head-strip"
    activation_flag = f"--activation {cfg.activation}" if cfg.activation != "silu" else ""
    return (
        f"cd {REMOTE_TRAINING} && "
        f"PYTHONUNBUFFERED=1 {REMOTE_UV} run python scripts/lambda/train_export.py "
        f"--data-yaml {shlex.quote(data_yaml_remote)} "
        f"--project-dir {shlex.quote(cfg.remote_run_dir)} "
        f"--run-name train "
        f"--model-id {shlex.quote(cfg.model_id)} "
        f"--epochs {cfg.epochs} "
        f"--workers 4 "
        f"{head_flag} "
        f"{activation_flag} "
        f"--result-json {shlex.quote(result_json_remote)}"
    )


def _remoteConvertCmd(
    cfg: LambdaRunConfig, onnx_remote: str, calibration_dir_remote: str, result_json_remote: str, output_rknn_remote: str,
) -> str:
    return (
        f"PYTHONUNBUFFERED=1 {REMOTE_RKNN_VENV}/bin/python {REMOTE_TRAINING}/scripts/lambda/convert_rknn.py "
        f"--onnx {shlex.quote(onnx_remote)} "
        f"--calibration-dir {shlex.quote(calibration_dir_remote)} "
        f"--calibration-count {cfg.calibration_count} "
        f"--target-platform {cfg.target_platform} "
        f"--quantization {cfg.quantization} "
        f"--output-rknn {shlex.quote(output_rknn_remote)} "
        f"--result-json {shlex.quote(result_json_remote)}"
    )


def _writeBundleMetadata(cfg: LambdaRunConfig, host: str, train_result: dict, convert_result: dict) -> dict:
    return {
        "schema_version": 1,
        "bundle_name": cfg.bundle_name,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "lambda": {
            "host": host,
            "remote_run_dir": cfg.remote_run_dir,
            "remote_bundle_dir": cfg.remote_bundle_dir,
        },
        "config": {
            "zone": cfg.zone,
            "dataset_name": cfg.dataset_name,
            "model_id": cfg.model_id,
            "epochs": cfg.epochs,
            "target_size": cfg.target_size,
            "min_detection_score": cfg.min_detection_score,
            "calibration_count": cfg.calibration_count,
            "target_platform": cfg.target_platform,
            "quantization": cfg.quantization,
            "head_stripped": cfg.head_stripped,
            "activation": cfg.activation,
            "hive_url": cfg.hive_url,
            "extra_build_flags": cfg.extra_build_flags,
        },
        "train": train_result,
        "convert": convert_result,
    }


def runLambdaPipeline(cfg: LambdaRunConfig, *, status: PipelineStatus | None = None) -> Path:
    """End-to-end r3 pipeline on a Lambda host. Returns local bundle dir."""
    import tempfile

    start_ts = time.time()
    host = cfg.host
    print(f"\n=== Lambda pipeline: {cfg.bundle_name} on {host} ===\n")
    if status is not None:
        status.configure(bundle_name=cfg.bundle_name, host=host)

    def _step(name: str):
        if status is not None:
            return status.step(name)
        import contextlib
        return contextlib.nullcontext()

    with _step("ssh + bootstrap remote env"):
        _ensureRemoteUv(host, status=status)
        _runRemote(
            host,
            f"mkdir -p {REMOTE_REPO}/software/training {REMOTE_ROOT}/runs {REMOTE_ROOT}/bundles",
            status=status,
        )

    local_training = _localRepoRoot()
    with _step(f"rsync repo → {host}"):
        print(f"[sync] {local_training} -> {host}:{REMOTE_TRAINING}")
        _rsyncToRemote(host, local_training, REMOTE_TRAINING, status=status)
        _ensureRemoteVenv(host, status=status)
        _ensureRknnVenv(host)

    if not cfg.skip_pull:
        with _step(f"pull samples from Hive ({cfg.zone})"):
            _runRemote(
                host,
                f"cd {REMOTE_TRAINING} && PYTHONUNBUFFERED=1 {REMOTE_UV} run train pull "
                f"--hive-url {shlex.quote(cfg.hive_url)} --zone {shlex.quote(cfg.zone)} --status ''",
                status=status,
            )

    dataset_dir_remote = f"{REMOTE_TRAINING}/datasets/{cfg.zone}/{cfg.dataset_name}"
    data_yaml_remote = f"{dataset_dir_remote}/data.yaml"
    if not cfg.skip_build:
        with _step(f"build YOLO dataset ({cfg.dataset_name})"):
            build_cmd = (
                f"cd {REMOTE_TRAINING} && PYTHONUNBUFFERED=1 {REMOTE_UV} run train build "
                f"--zone {shlex.quote(cfg.zone)} --name {shlex.quote(cfg.dataset_name)} "
                f"--min-detection-score {cfg.min_detection_score} --keep-empty --max-empty-fraction 0.1"
            )
            if cfg.target_size is not None:
                build_cmd += f" --target-size {cfg.target_size}"
            for flag in cfg.extra_build_flags:
                build_cmd += f" {flag}"
            _runRemote(host, build_cmd, status=status)

    train_result_json_remote = f"{cfg.remote_run_dir}/train_result.json"
    with _step(f"train + head-stripped ONNX ({cfg.model_id}, {cfg.epochs} epochs)"):
        _runRemote(host, _remoteTrainCmd(cfg, data_yaml_remote, train_result_json_remote), status=status)

    train_result_raw = _runRemote(host, f"cat {shlex.quote(train_result_json_remote)}", capture=True)
    train_result = json.loads(train_result_raw)
    onnx_remote = train_result["best_onnx"]

    calibration_dir_remote = f"{dataset_dir_remote}/images/train"
    convert_result_json_remote = f"{cfg.remote_bundle_dir}/convert_result.json"
    output_rknn_remote = f"{cfg.remote_bundle_dir}/{cfg.bundle_name}.rknn"
    with _step(f"convert ONNX → RKNN ({cfg.target_platform}, {cfg.quantization})"):
        _runRemote(host, f"mkdir -p {cfg.remote_bundle_dir}", status=status)
        _runRemote(
            host,
            _remoteConvertCmd(cfg, onnx_remote, calibration_dir_remote, convert_result_json_remote, output_rknn_remote),
            status=status,
        )
    convert_result_raw = _runRemote(host, f"cat {shlex.quote(convert_result_json_remote)}", capture=True)
    convert_result = json.loads(convert_result_raw)

    with _step(f"stage bundle + rsync back → {cfg.local_bundle_dir}"):
        bundle_metadata = _writeBundleMetadata(cfg, host, train_result, convert_result)
        metadata_path_remote = f"{cfg.remote_bundle_dir}/run_metadata.json"
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as tmp:
            tmp.write(json.dumps(bundle_metadata, indent=2) + "\n")
            tmp_path = tmp.name
        _runLocal(["scp", tmp_path, f"{host}:{metadata_path_remote}"], status=status)
        Path(tmp_path).unlink(missing_ok=True)

        stage_cmd = (
            f"mkdir -p {cfg.remote_bundle_dir} && "
            f"cp {shlex.quote(train_result['best_pt'])} {cfg.remote_bundle_dir}/best.pt && "
            f"cp {shlex.quote(train_result['best_onnx'])} {cfg.remote_bundle_dir}/best.onnx && "
            f"cp {cfg.remote_run_dir}/train/results.csv {cfg.remote_bundle_dir}/results.csv 2>/dev/null || true; "
            f"cp {cfg.remote_run_dir}/train/args.yaml {cfg.remote_bundle_dir}/args.yaml 2>/dev/null || true; "
        )
        _runRemote(host, stage_cmd, status=status)

        print(f"[sync back] {host}:{cfg.remote_bundle_dir} -> {cfg.local_bundle_dir}")
        _rsyncFromRemote(host, cfg.remote_bundle_dir, cfg.local_bundle_dir, status=status)

    elapsed_min = round((time.time() - start_ts) / 60, 2)
    print(f"\n=== Lambda pipeline done in {elapsed_min} min: {cfg.local_bundle_dir} ===")
    return cfg.local_bundle_dir
