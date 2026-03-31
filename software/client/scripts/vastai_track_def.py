#!/usr/bin/env python3
"""Track D+E+F: Train PicoDet (D1-D2), YOLOv9t (E1), and FastestDet (F1) on GPU.

Models:
  D1: PicoDet-XS  @ 320  (PaddleDetection, extra-small)
  D2: PicoDet-S   @ 320  (PaddleDetection, lightweight)
  E1: YOLOv9t     @ 320  (WongKinYiu/YOLO, tiny variant)
  F1: FastestDet  @ 352  (dog-qiuqiu/FastestDet, ultra-lightweight)

Runs on Vast.ai GPU instance.
Expects dataset at /workspace/dataset/ with:
  - COCO JSON: annotations/{train,val,test}.json
  - YOLO TXT:  labels_yolo/{train,val,test}/*.txt
  - Images:    images/{train,val,test}/*.jpg
  - dataset.yaml for Ultralytics-compatible tools

Usage: python vastai_track_def.py
"""
import argparse
import subprocess
import json
import time
import os
import glob
import shutil
import traceback
from pathlib import Path
import tempfile

DATASET = Path("/workspace/dataset")
RESULTS = Path("/workspace/results")
RESULTS.mkdir(exist_ok=True)

PADDLEDET_DIR = Path("/workspace/PaddleDetection")
YOLOV9_DIR = Path("/workspace/YOLO")  # WongKinYiu/YOLO
FASTESTDET_DIR = Path("/workspace/FastestDet")
NCNN_DIR = Path("/workspace/ncnn")
NCNN_BUILD_DIR = NCNN_DIR / "build"
NCNN_ONNX2NCNN = NCNN_BUILD_DIR / "tools" / "onnx" / "onnx2ncnn"
NCNN_OPTIMIZE = NCNN_BUILD_DIR / "tools" / "ncnnoptimize"
NCNN_TOOLS_CMAKELISTS = NCNN_DIR / "tools" / "CMakeLists.txt"


# ── PicoDet variants ──────────────────────────────────────

PICODET_VARIANTS = [
    {"id": "D1", "name": "picodet-xs-320", "arch": "xs", "imgsz": 320, "batch": 96},
    {"id": "D2", "name": "picodet-s-320", "arch": "s", "imgsz": 320, "batch": 64},
]

# ── YOLOv9t ───────────────────────────────────────────────

YOLOV9_VARIANTS = [
    {"id": "E1", "name": "yolov9t-320", "imgsz": 320, "batch": 64},
]

# ── FastestDet ────────────────────────────────────────────

FASTESTDET_VARIANTS = [
    {"id": "F1", "name": "fastestdet-352", "imgsz": 352, "batch": 64},
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model-ids", nargs="+", default=None, help="Optional specific model IDs to run.")
    return parser.parse_args()


def select_variants(variants: list[dict], selected_ids: set[str]) -> list[dict]:
    if not selected_ids:
        return variants
    return [variant for variant in variants if variant["id"] in selected_ids]


def setup_system_dependencies():
    """Install shared OS/Python dependencies and pin a torch-compatible runtime."""
    subprocess.run(
        [
            "bash",
            "-lc",
            "apt-get update && "
            "DEBIAN_FRONTEND=noninteractive apt-get install -y "
            "build-essential g++ git cmake libprotobuf-dev protobuf-compiler "
            "libgl1 libglib2.0-0 libsm6 libxext6 libxrender1 libxcb1",
        ],
        check=True,
    )
    pin_runtime_stack()
    setup_ncnn_tools()


def pin_runtime_stack():
    """Keep the runtime on NumPy 1.x and headless OpenCV for torch/cv2 compatibility."""
    subprocess.run(
        ["pip", "uninstall", "-y", "opencv-python", "opencv-contrib-python"],
        check=False,
    )
    subprocess.run(
        ["pip", "install", "-q", "--force-reinstall", "numpy<2", "opencv-python-headless"],
        check=True,
    )


def setup_ncnn_tools():
    """Build the NCNN conversion tools once per instance."""
    global NCNN_ONNX2NCNN, NCNN_OPTIMIZE
    if NCNN_ONNX2NCNN.exists() and NCNN_OPTIMIZE.exists():
        return

    if not (NCNN_DIR / "CMakeLists.txt").exists():
        subprocess.run(
            ["git", "clone", "--depth", "1", "https://github.com/Tencent/ncnn.git", str(NCNN_DIR)],
            check=True,
        )

    if NCNN_TOOLS_CMAKELISTS.exists():
        tools_cmake = NCNN_TOOLS_CMAKELISTS.read_text()
        if "add_subdirectory(onnx)" not in tools_cmake and (NCNN_DIR / "tools" / "onnx").is_dir():
            marker = "add_subdirectory(darknet)\n"
            if marker in tools_cmake:
                tools_cmake = tools_cmake.replace(marker, marker + "add_subdirectory(onnx)\n", 1)
                NCNN_TOOLS_CMAKELISTS.write_text(tools_cmake)

    subprocess.run(
        [
            "cmake",
            "-S",
            str(NCNN_DIR),
            "-B",
            str(NCNN_BUILD_DIR),
            "-DNCNN_BUILD_TOOLS=ON",
            "-DNCNN_BUILD_EXAMPLES=OFF",
            "-DNCNN_BUILD_BENCHMARK=OFF",
            "-DNCNN_VULKAN=OFF",
        ],
        check=True,
    )
    subprocess.run(
        [
            "cmake",
            "--build",
            str(NCNN_BUILD_DIR),
            "--parallel",
            str(max(1, os.cpu_count() or 1)),
        ],
        check=True,
    )

    onnx_candidates = [
        NCNN_BUILD_DIR / "tools" / "onnx" / "onnx2ncnn",
        NCNN_BUILD_DIR / "tools" / "onnx2ncnn",
        NCNN_BUILD_DIR / "install" / "bin" / "onnx2ncnn",
    ]
    optimize_candidates = [
        NCNN_BUILD_DIR / "tools" / "ncnnoptimize",
        NCNN_BUILD_DIR / "install" / "bin" / "ncnnoptimize",
    ]

    resolved_onnx = next((path for path in onnx_candidates if path.exists()), None)
    if resolved_onnx is None:
        resolved_onnx = next((path for path in NCNN_BUILD_DIR.rglob("onnx2ncnn") if path.is_file()), None)
    resolved_opt = next((path for path in optimize_candidates if path.exists()), None)
    if resolved_opt is None:
        resolved_opt = next((path for path in NCNN_BUILD_DIR.rglob("ncnnoptimize") if path.is_file()), None)

    if resolved_onnx is None or resolved_opt is None:
        raise RuntimeError(
            "NCNN tools build completed but required converters were not found "
            f"(onnx2ncnn={resolved_onnx}, ncnnoptimize={resolved_opt})."
        )

    NCNN_ONNX2NCNN = resolved_onnx
    NCNN_OPTIMIZE = resolved_opt


def export_onnx_to_ncnn(onnx_path: str, model_name: str, *, model_id: str, family: str, imgsz: int) -> dict:
    """Convert an ONNX artifact into a standard NCNN result directory."""
    setup_ncnn_tools()

    output_dir = RESULTS / f"{model_name}-ncnn"
    if output_dir.exists():
        shutil.rmtree(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    raw_param = Path(tempfile.mktemp(prefix=f"{model_name}-", suffix=".param", dir="/tmp"))
    raw_bin = raw_param.with_suffix(".bin")
    final_param = output_dir / "model.ncnn.param"
    final_bin = output_dir / "model.ncnn.bin"

    convert = subprocess.run(
        [str(NCNN_ONNX2NCNN), onnx_path, str(raw_param), str(raw_bin)],
        capture_output=True,
        text=True,
    )
    payload: dict[str, object] = {"ncnn_export_rc": convert.returncode}
    if convert.returncode != 0:
        payload["ncnn_error"] = convert.stderr.strip() or convert.stdout.strip() or "onnx2ncnn failed"
        return payload

    optimize = subprocess.run(
        [str(NCNN_OPTIMIZE), str(raw_param), str(raw_bin), str(final_param), str(final_bin), "65536"],
        capture_output=True,
        text=True,
    )
    payload["ncnn_optimize_rc"] = optimize.returncode
    if optimize.returncode != 0 or not final_param.exists() or not final_bin.exists():
        shutil.copy2(raw_param, final_param)
        shutil.copy2(raw_bin, final_bin)
        payload["ncnn_optimized"] = False
        if optimize.returncode != 0:
            payload["ncnn_optimize_error"] = optimize.stderr.strip() or optimize.stdout.strip() or "ncnnoptimize failed"
    else:
        payload["ncnn_optimized"] = True

    metadata_path = output_dir / "metadata.json"
    metadata_path.write_text(
        json.dumps(
            {
                "model_id": model_id,
                "name": model_name,
                "family": family,
                "runtime": "ncnn",
                "imgsz": imgsz,
                "source_onnx": onnx_path,
            },
            indent=2,
        )
    )
    payload["ncnn_exported"] = True
    payload["ncnn_model_dir"] = str(output_dir)
    payload["ncnn_size_kb"] = round((final_param.stat().st_size + final_bin.stat().st_size) / 1024, 1)
    return payload


def gen_picodet_config(v: dict) -> str:
    """Generate PicoDet YAML config for PaddleDetection."""
    if v["arch"] == "s":
        backbone_scale = 1.0
        fpn_out = 96
        head_feat = 96
        stacked_convs = 2
    else:  # xs
        backbone_scale = 0.75
        fpn_out = 64
        head_feat = 64
        stacked_convs = 2

    return f"""use_gpu: true
use_xpu: false
log_iter: 50
save_dir: /workspace/runs/{v['name']}
snapshot_epoch: 10
print_flops: false

epoch: 200
LearningRate:
  base_lr: 0.04
  schedulers:
  - !CosineDecay
    max_epochs: 200
  - !LinearWarmup
    start_factor: 0.001
    steps: 500

OptimizerBuilder:
  optimizer:
    type: Momentum
    momentum: 0.9
  regularizer:
    factor: 0.00004
    type: L2

architecture: PicoDet

PicoDet:
  backbone: LCNet
  neck: LCPAN
  head: PicoHeadV2

LCNet:
  scale: {backbone_scale}
  feature_maps: [3, 4, 5]

LCPAN:
  out_channels: {fpn_out}
  use_depthwise: true

PicoHeadV2:
  conv_feat:
    name: PicoFeat
    feat_in: {fpn_out}
    feat_out: {head_feat}
    num_convs: {stacked_convs}
    num_fpn_stride: 4
    norm_type: bn
    share_cls_reg: true
    use_depthwise: true
  fpn_stride: [8, 16, 32, 64]
  feat_in_chan: {head_feat}
  nms:
    name: MultiClassNMS
    nms_top_k: 1000
    keep_top_k: 100
    score_threshold: 0.025
    nms_threshold: 0.6
  num_classes: 1

TrainDataset:
  !COCODataSet
    image_dir: images/train
    anno_path: annotations/train.json
    dataset_dir: {DATASET}
    data_fields: ['image', 'gt_bbox', 'gt_class', 'is_crowd']

EvalDataset:
  !COCODataSet
    image_dir: images/val
    anno_path: annotations/val.json
    dataset_dir: {DATASET}

TestDataset:
  !ImageFolder
    anno_path: annotations/val.json
    dataset_dir: {DATASET}

worker_num: 4

TrainReader:
  sample_transforms:
  - Decode: {{}}
  - RandomCrop: {{}}
  - RandomFlip: {{prob: 0.5}}
  - RandomDistort: {{}}
  batch_transforms:
  - BatchRandomResize:
      target_size: [{v['imgsz']}]
      random_size: true
      random_interp: true
      keep_ratio: false
  - NormalizeImage:
      is_scale: true
      mean: [0.485, 0.456, 0.406]
      std: [0.229, 0.224, 0.225]
  - Permute: {{}}
  batch_size: {v['batch']}
  shuffle: true
  drop_last: true

EvalReader:
  sample_transforms:
  - Decode: {{}}
  - Resize:
      target_size: [{v['imgsz']}, {v['imgsz']}]
      keep_ratio: false
      interp: 2
  - NormalizeImage:
      is_scale: true
      mean: [0.485, 0.456, 0.406]
      std: [0.229, 0.224, 0.225]
  - Permute: {{}}
  batch_size: 8

TestReader:
  inputs_def:
    image_shape: [1, 3, {v['imgsz']}, {v['imgsz']}]
  sample_transforms:
  - Decode: {{}}
  - Resize:
      target_size: [{v['imgsz']}, {v['imgsz']}]
      keep_ratio: false
      interp: 2
  - NormalizeImage:
      is_scale: true
      mean: [0.485, 0.456, 0.406]
      std: [0.229, 0.224, 0.225]
  - Permute: {{}}
"""


def gen_fastestdet_config(v: dict) -> str:
    """Generate FastestDet config YAML."""
    return f"""DATASET:
  TRAIN: "{DATASET}/train.txt"
  VAL: "{DATASET}/val.txt"
  NAMES: "{DATASET}/classes.txt"

MODEL:
  NC: 1
  INPUT_WIDTH: {v['imgsz']}
  INPUT_HEIGHT: {v['imgsz']}

TRAIN:
  LR: 0.001
  THRESH: 0.25
  WARMUP: true
  BATCH_SIZE: {v['batch']}
  END_EPOCH: 200
  MILESTIONES:
    - 100
    - 150
    - 180
"""


def gen_yolov9_dataset_config() -> str:
    """Generate a minimal dataset config for WongKinYiu/YOLO."""
    return f"""path: {DATASET}
train: train
validation: val
class_num: 1
class_list: ['piece']
"""


def setup_paddledet():
    """Install PaddlePaddle-GPU and PaddleDetection."""
    print("\n=== Setting up PaddleDetection ===")

    # Install PaddlePaddle GPU
    subprocess.run(
        ["pip", "install", "-q",
         "paddlepaddle-gpu",
         "-f", "https://www.paddlepaddle.org.cn/whl/linux/mkl/avx/stable.html"],
        check=True,
    )

    # Clone PaddleDetection
    if not (PADDLEDET_DIR / "setup.py").exists():
        subprocess.run(
            ["git", "clone", "--depth", "1",
             "https://github.com/PaddlePaddle/PaddleDetection.git",
             str(PADDLEDET_DIR)],
            check=True,
        )

    subprocess.run(
        ["pip", "install", "-q", "-r",
         str(PADDLEDET_DIR / "requirements.txt")],
        check=True,
    )
    subprocess.run(
        ["pip", "install", "-q", "pycocotools", "onnx", "onnxsim", "paddle2onnx"],
        check=True,
    )
    pin_runtime_stack()
    print("  PaddleDetection setup complete")


def setup_yolov9():
    """Clone and setup WongKinYiu/YOLO for YOLOv9."""
    print("\n=== Setting up YOLOv9 (WongKinYiu/YOLO) ===")
    if not (YOLOV9_DIR / "README.md").exists():
        subprocess.run(
            ["git", "clone", "--depth", "1",
             "https://github.com/WongKinYiu/YOLO.git",
             str(YOLOV9_DIR)],
            check=True,
        )

    subprocess.run(["pip", "install", "-q", "--no-deps", "-e", str(YOLOV9_DIR)], check=True)
    subprocess.run(
        ["pip", "install", "-q", "hydra-core", "omegaconf", "onnx", "onnxsim",
         "onnxruntime", "matplotlib", "tensorboard", "pandas", "seaborn",
         "PyYAML", "tqdm", "opencv-python-headless", "thop"],
        check=True,
    )
    pin_runtime_stack()
    print("  YOLOv9 setup complete")


def setup_fastestdet():
    """Clone and setup FastestDet."""
    print("\n=== Setting up FastestDet ===")
    if not (FASTESTDET_DIR / "README.md").exists():
        subprocess.run(
            ["git", "clone", "--depth", "1",
             "https://github.com/dog-qiuqiu/FastestDet.git",
             str(FASTESTDET_DIR)],
            check=True,
        )

    subprocess.run(
        ["pip", "install", "-q", "onnx", "onnxsim", "onnxruntime", "pycocotools",
         "opencv-python-headless", "PyYAML", "tqdm", "torchsummary",
         "tensorboard", "matplotlib"],
        check=True,
    )

    # Create classes.txt for FastestDet
    classes_file = DATASET / "classes.txt"
    if not classes_file.exists():
        classes_file.write_text("piece\n")

    pin_runtime_stack()
    print("  FastestDet setup complete")


def train_picodet(v: dict) -> dict:
    """Train a PicoDet variant via PaddleDetection."""
    model_id = v["id"]
    model_name = v["name"]
    print(f"\n{'=' * 60}")
    print(f"Training {model_id}: {model_name} (PicoDet)")
    print(f"{'=' * 60}")

    result = {"name": model_name, "framework": "paddledet"}
    t0 = time.time()

    try:
        cfg_dir = Path("/workspace/configs")
        cfg_dir.mkdir(exist_ok=True)
        cfg_path = cfg_dir / f"{model_name}.yml"
        cfg_path.write_text(gen_picodet_config(v))

        # Train
        cmd = [
            "python", "-m", "paddle.distributed.launch",
            "--gpus", "0",
            "tools/train.py",
            "-c", str(cfg_path),
            "--eval",
        ]
        r = subprocess.run(cmd, cwd=str(PADDLEDET_DIR), capture_output=False)
        result["train_returncode"] = r.returncode
        elapsed = time.time() - t0
        result["train_elapsed_min"] = round(elapsed / 60, 1)
        if r.returncode != 0:
            result["error"] = f"PicoDet training failed with return code {r.returncode}"
            return result

        # Find best model
        best_models = glob.glob(
            f"/workspace/runs/{model_name}/**/best_model.pdparams", recursive=True
        )
        if not best_models:
            best_models = glob.glob(
                f"/workspace/runs/{model_name}/**/*.pdparams", recursive=True
            )

        if best_models:
            best = sorted(best_models)[-1]
            result["best_checkpoint"] = best
            best_prefix = best.replace(".pdparams", "")

            # Export to ONNX via paddle2onnx
            onnx_path = str(RESULTS / f"{model_name}.onnx")

            # First export to Paddle inference model
            infer_dir = f"/workspace/runs/{model_name}/inference"
            subprocess.run(
                ["python", "tools/export_model.py",
                 "-c", str(cfg_path),
                 "-o", f"weights={best_prefix}",
                 f"--output_dir={infer_dir}"],
                cwd=str(PADDLEDET_DIR),
                capture_output=True,
            )

            # Then convert to ONNX
            model_file = glob.glob(f"{infer_dir}/**/*.pdmodel", recursive=True)
            params_file = glob.glob(f"{infer_dir}/**/*.pdiparams", recursive=True)
            if model_file and params_file:
                subprocess.run(
                    ["paddle2onnx",
                     "--model_dir", os.path.dirname(model_file[0]),
                     "--model_filename", os.path.basename(model_file[0]),
                     "--params_filename", os.path.basename(params_file[0]),
                     "--save_file", onnx_path,
                     "--opset_version", "11",
                     "--enable_onnx_checker", "True"],
                    capture_output=True,
                )

                if os.path.exists(onnx_path):
                    sim_path = onnx_path.replace(".onnx", "-sim.onnx")
                    subprocess.run(
                        ["python", "-m", "onnxsim", onnx_path, sim_path],
                        capture_output=True,
                    )
                    final = sim_path if os.path.exists(sim_path) else onnx_path
                    result["onnx_path"] = final
                    result["onnx_size_kb"] = round(os.path.getsize(final) / 1024, 1)
                    result.update(
                        export_onnx_to_ncnn(
                            final,
                            model_name,
                            model_id=model_id,
                            family="picodet",
                            imgsz=v["imgsz"],
                        )
                    )

    except Exception as exc:
        result["error"] = f"{exc}\n{traceback.format_exc()}"
        elapsed = time.time() - t0
        result["train_elapsed_min"] = round(elapsed / 60, 1)

    print(f"\n{model_id} done: {result.get('train_elapsed_min', '?')} min")
    return result


def train_yolov9(v: dict) -> dict:
    """Train YOLOv9t via WongKinYiu/YOLO."""
    model_id = v["id"]
    model_name = v["name"]
    print(f"\n{'=' * 60}")
    print(f"Training {model_id}: {model_name} (YOLOv9t)")
    print(f"{'=' * 60}")

    result = {"name": model_name, "framework": "yolov9"}
    t0 = time.time()

    try:
        # This repo uses Hydra configs, not the Ultralytics CLI.
        cfg_dir = Path("/workspace/configs")
        cfg_dir.mkdir(exist_ok=True)
        dataset_cfg = cfg_dir / "yolov9_dataset.yaml"
        dataset_cfg.write_text(gen_yolov9_dataset_config())

        cmd = [
            "python", "yolo/lazy.py",
            "task=train",
            f"dataset={dataset_cfg}",
            "model=v9-t",
            f"name={model_name}",
            "out_path=/workspace/runs",
            f"image_size=[{v['imgsz']},{v['imgsz']}]",
            "task.epoch=300",
            f"task.data.batch_size={v['batch']}",
            "task.validation.data.batch_size=8",
            "device=[0]",
            "use_wandb=False",
        ]
        r = subprocess.run(cmd, cwd=str(YOLOV9_DIR), capture_output=False)
        result["train_returncode"] = r.returncode
        elapsed = time.time() - t0
        result["train_elapsed_min"] = round(elapsed / 60, 1)
        if r.returncode != 0:
            result["error"] = f"YOLOv9 training failed with return code {r.returncode}"
            return result

        # Find the most recent checkpoint from the Lightning run.
        best_ckpts = glob.glob(
            f"/workspace/runs/train/{model_name}/**/*.ckpt", recursive=True
        )
        if best_ckpts:
            best = sorted(best_ckpts, key=os.path.getmtime)[-1]
            result["best_checkpoint"] = best

            sample_images = sorted((DATASET / "images" / "val").glob("*.jpg"))
            if not sample_images:
                sample_images = sorted((DATASET / "images" / "val").glob("*.png"))
            if not sample_images:
                raise RuntimeError("No validation image found for YOLOv9 ONNX export")

            onnx_path = str(RESULTS / f"{model_name}.onnx")
            subprocess.run(
                [
                    "python", "yolo/lazy.py",
                    "task=inference",
                    f"dataset={dataset_cfg}",
                    "model=v9-t",
                    f"weight={best}",
                    f"name={model_name}-export",
                    "out_path=/workspace/runs",
                    f"image_size=[{v['imgsz']},{v['imgsz']}]",
                    f"task.data.source={sample_images[0]}",
                    "task.fast_inference=onnx",
                    "device=cpu",
                    "use_wandb=False",
                    "+quiet=True",
                ],
                cwd=str(YOLOV9_DIR),
                capture_output=True,
            )

            exported_onnx = str(YOLOV9_DIR / f"{Path(best).stem}.onnx")
            if os.path.exists(exported_onnx):
                shutil.copy2(exported_onnx, onnx_path)
                sim_path = onnx_path.replace(".onnx", "-sim.onnx")
                subprocess.run(
                    ["python", "-m", "onnxsim", onnx_path, sim_path],
                    capture_output=True,
                )
                final = sim_path if os.path.exists(sim_path) else onnx_path
                result["onnx_path"] = final
                result["onnx_size_kb"] = round(os.path.getsize(final) / 1024, 1)
                result.update(
                    export_onnx_to_ncnn(
                        final,
                        model_name,
                        model_id=model_id,
                        family="yolov9",
                        imgsz=v["imgsz"],
                    )
                )

            shutil.copy2(best, RESULTS / f"{model_name}_best.ckpt")

    except Exception as exc:
        result["error"] = f"{exc}\n{traceback.format_exc()}"
        elapsed = time.time() - t0
        result["train_elapsed_min"] = round(elapsed / 60, 1)

    print(f"\n{model_id} done: {result.get('train_elapsed_min', '?')} min")
    return result


def train_fastestdet(v: dict) -> dict:
    """Train FastestDet."""
    model_id = v["id"]
    model_name = v["name"]
    print(f"\n{'=' * 60}")
    print(f"Training {model_id}: {model_name} (FastestDet)")
    print(f"{'=' * 60}")

    result = {"name": model_name, "framework": "fastestdet"}
    t0 = time.time()

    try:
        # Write config
        cfg_dir = Path("/workspace/configs")
        cfg_dir.mkdir(exist_ok=True)
        cfg_path = cfg_dir / f"{model_name}.yaml"
        cfg_path.write_text(gen_fastestdet_config(v))

        # Ensure classes.txt exists
        classes_file = DATASET / "classes.txt"
        if not classes_file.exists():
            classes_file.write_text("piece\n")

        # FastestDet expects train.txt / val.txt files listing absolute image paths,
        # and derives label paths by replacing "images" with "labels" in the path.
        # Ensure the labels symlink exists so labels_yolo is reachable as labels/.
        labels_link = DATASET / "labels"
        labels_yolo = DATASET / "labels_yolo"
        if labels_yolo.is_dir() and not labels_link.exists():
            labels_link.symlink_to(labels_yolo.name)

        for split in ["train", "val"]:
            img_dir = DATASET / "images" / split
            listing = DATASET / f"{split}.txt"
            images = sorted(img_dir.glob("*.jpg")) + sorted(img_dir.glob("*.png"))
            listing.write_text("\n".join(str(p) for p in images) + "\n")

        # Train
        cmd = [
            "python", "train.py",
            "--yaml", str(cfg_path),
        ]
        r = subprocess.run(cmd, cwd=str(FASTESTDET_DIR), capture_output=False)
        result["train_returncode"] = r.returncode
        elapsed = time.time() - t0
        result["train_elapsed_min"] = round(elapsed / 60, 1)
        if r.returncode != 0:
            result["error"] = f"FastestDet training failed with return code {r.returncode}"
            return result

        best_pts = glob.glob(f"{FASTESTDET_DIR}/checkpoint/*.pth", recursive=True)
        if best_pts:
            best = sorted(best_pts, key=os.path.getmtime)[-1]
            result["best_checkpoint"] = best

            sample_images = sorted((DATASET / "images" / "val").glob("*.jpg"))
            if not sample_images:
                sample_images = sorted((DATASET / "images" / "val").glob("*.png"))
            if not sample_images:
                raise RuntimeError("No validation image found for FastestDet ONNX export")

            onnx_path = str(RESULTS / f"{model_name}.onnx")
            e = subprocess.run(
                ["python", "test.py",
                 "--yaml", str(cfg_path),
                 "--weight", best,
                 "--img", str(sample_images[0]),
                 "--onnx"],
                cwd=str(FASTESTDET_DIR),
                capture_output=True, text=True,
            )
            result["onnx_export_rc"] = e.returncode
            exported_onnx = FASTESTDET_DIR / "FastestDet.onnx"
            if e.returncode != 0 and not exported_onnx.exists():
                result["export_error"] = e.stderr or e.stdout or "FastestDet ONNX export failed"

            if exported_onnx.exists():
                shutil.copy2(exported_onnx, onnx_path)
                sim_path = onnx_path.replace(".onnx", "-sim.onnx")
                subprocess.run(
                    ["python", "-m", "onnxsim", onnx_path, sim_path],
                    capture_output=True,
                )
                final = sim_path if os.path.exists(sim_path) else onnx_path
                result["onnx_path"] = final
                result["onnx_size_kb"] = round(os.path.getsize(final) / 1024, 1)
                result.update(
                    export_onnx_to_ncnn(
                        final,
                        model_name,
                        model_id=model_id,
                        family="fastestdet",
                        imgsz=v["imgsz"],
                    )
                )

            # Copy checkpoint
            shutil.copy2(best, RESULTS / f"{model_name}_best.pth")

    except Exception as exc:
        result["error"] = f"{exc}\n{traceback.format_exc()}"
        elapsed = time.time() - t0
        result["train_elapsed_min"] = round(elapsed / 60, 1)

    print(f"\n{model_id} done: {result.get('train_elapsed_min', '?')} min")
    return result


def main():
    args = parse_args()
    selected_ids = {model_id.strip().upper() for model_id in (args.model_ids or []) if model_id.strip()}
    picodet_variants = select_variants(PICODET_VARIANTS, selected_ids)
    yolov9_variants = select_variants(YOLOV9_VARIANTS, selected_ids)
    fastestdet_variants = select_variants(FASTESTDET_VARIANTS, selected_ids)

    print("=" * 60)
    print("Track D+E+F: PicoDet + YOLOv9t + FastestDet")
    print("=" * 60)

    results = {}

    try:
        setup_system_dependencies()
    except Exception as exc:
        print(f"Shared dependency setup failed: {exc}")
        for v in picodet_variants + yolov9_variants + fastestdet_variants:
            results[v["id"]] = {"name": v["name"], "error": f"Shared setup failed: {exc}"}
        summary_path = RESULTS / "track_def_results.json"
        with open(summary_path, "w") as f:
            json.dump(results, f, indent=2)
        return

    # Setup frameworks (each one independently, so failures don't block others)
    paddle_ok = True
    try:
        setup_paddledet()
    except Exception as exc:
        print(f"PaddleDetection setup failed: {exc}")
        paddle_ok = False
        for v in picodet_variants:
            results[v["id"]] = {
                "name": v["name"],
                "error": f"PaddleDetection setup failed: {exc}",
            }

    yolov9_ok = True
    try:
        setup_yolov9()
    except Exception as exc:
        print(f"YOLOv9 setup failed: {exc}")
        yolov9_ok = False
        for v in yolov9_variants:
            results[v["id"]] = {
                "name": v["name"],
                "error": f"YOLOv9 setup failed: {exc}",
            }

    fastestdet_ok = True
    try:
        setup_fastestdet()
    except Exception as exc:
        print(f"FastestDet setup failed: {exc}")
        fastestdet_ok = False
        for v in fastestdet_variants:
            results[v["id"]] = {
                "name": v["name"],
                "error": f"FastestDet setup failed: {exc}",
            }

    # Train PicoDet variants
    if paddle_ok:
        for v in picodet_variants:
            results[v["id"]] = train_picodet(v)

    # Train YOLOv9t
    if yolov9_ok:
        for v in yolov9_variants:
            results[v["id"]] = train_yolov9(v)

    # Train FastestDet
    if fastestdet_ok:
        for v in fastestdet_variants:
            results[v["id"]] = train_fastestdet(v)

    # Write summary
    summary_path = RESULTS / "track_def_results.json"
    with open(summary_path, "w") as f:
        json.dump(results, f, indent=2)

    print(f"\n\n{'=' * 60}")
    print("Track D+E+F Complete")
    print(f"{'=' * 60}")
    print(f"Results saved to: {summary_path}")
    for mid, r in results.items():
        status = "OK" if "error" not in r else "FAILED"
        onnx_size = r.get("onnx_size_kb", "N/A")
        ncnn_size = r.get("ncnn_size_kb", "N/A")
        elapsed = r.get("train_elapsed_min", "?")
        print(f"  {mid} ({r['name']}): {status} - ONNX={onnx_size}KB - NCNN={ncnn_size}KB - {elapsed} min")


if __name__ == "__main__":
    main()
