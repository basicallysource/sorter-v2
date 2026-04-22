#!/usr/bin/env python3
"""Track B+C: Train NanoDet-Plus (B1-B3) and YOLOX (C1-C2) models on GPU.

Models:
  B1: NanoDet-Plus-m   @ 320  (ShuffleNetV2 1.0x)
  B2: NanoDet-Plus-m   @ 416  (ShuffleNetV2 1.0x)
  B3: NanoDet-Plus-m-1.5x @ 416  (ShuffleNetV2 1.5x)
  C1: YOLOX-Nano       @ 416
  C2: YOLOX-Tiny       @ 416

Runs on Vast.ai GPU instance.
Expects dataset at /workspace/dataset/ with COCO JSON annotations.

Usage: python vastai_track_bc.py
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

NANODET_DIR = Path("/workspace/nanodet")
YOLOX_DIR = Path("/workspace/YOLOX")
NCNN_DIR = Path("/workspace/ncnn")
NCNN_BUILD_DIR = NCNN_DIR / "build"
NCNN_ONNX2NCNN = NCNN_BUILD_DIR / "tools" / "onnx" / "onnx2ncnn"
NCNN_OPTIMIZE = NCNN_BUILD_DIR / "tools" / "ncnnoptimize"
NCNN_TOOLS_CMAKELISTS = NCNN_DIR / "tools" / "CMakeLists.txt"

# ── NanoDet variants ──────────────────────────────────────

NANODET_VARIANTS = [
    {
        "id": "B1", "name": "nanodet-plus-m-320",
        "model_size": "1.0x", "imgsz": 320,
        "fpn_in": [116, 232, 464], "fpn_out": 96,
        "aux_in": 192, "aux_feat": 192, "batch": 96,
    },
    {
        "id": "B2", "name": "nanodet-plus-m-416",
        "model_size": "1.0x", "imgsz": 416,
        "fpn_in": [116, 232, 464], "fpn_out": 96,
        "aux_in": 192, "aux_feat": 192, "batch": 64,
    },
    {
        "id": "B3", "name": "nanodet-plus-m-1.5x-416",
        "model_size": "1.5x", "imgsz": 416,
        "fpn_in": [176, 352, 704], "fpn_out": 128,
        "aux_in": 256, "aux_feat": 256, "batch": 32,
    },
]

# ── YOLOX variants ────────────────────────────────────────

YOLOX_VARIANTS = [
    {"id": "C1", "name": "yolox-nano-416", "exp": "nano", "imgsz": 416, "batch": 64},
    {"id": "C2", "name": "yolox-tiny-416", "exp": "tiny", "imgsz": 416, "batch": 32},
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
    """Install OS and Python dependencies shared by NanoDet and YOLOX."""
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


def gen_nanodet_config(v: dict, save_dir: str) -> str:
    """Generate a NanoDet-Plus training config YAML."""
    return f"""save_dir: {save_dir}
check_point_save_period: 10
keep_checkpoint_max: 3
log:
  interval: 50
model:
  weight_averager:
    name: ExpMovingAverager
    decay: 0.9998
  arch:
    name: NanoDetPlus
    detach_epoch: 10
    backbone:
      name: ShuffleNetV2
      model_size: {v['model_size']}
      out_stages: [2, 3, 4]
      activation: LeakyReLU
    fpn:
      name: GhostPAN
      in_channels: {v['fpn_in']}
      out_channels: {v['fpn_out']}
      kernel_size: 5
      num_extra_level: 1
      use_depthwise: True
      activation: LeakyReLU
    head:
      name: NanoDetPlusHead
      num_classes: 1
      input_channel: {v['fpn_out']}
      feat_channels: {v['fpn_out']}
      stacked_convs: 2
      kernel_size: 5
      strides: [8, 16, 32, 64]
      activation: LeakyReLU
      reg_max: 7
      norm_cfg:
        type: BN
      loss:
        loss_qfl:
          name: QualityFocalLoss
          use_sigmoid: True
          beta: 2.0
          loss_weight: 1.0
        loss_dfl:
          name: DistributionFocalLoss
          loss_weight: 0.25
        loss_bbox:
          name: GIoULoss
          loss_weight: 2.0
    aux_head:
      name: SimpleConvHead
      num_classes: 1
      input_channel: {v['aux_in']}
      feat_channels: {v['aux_feat']}
      stacked_convs: 4
      strides: [8, 16, 32, 64]
      activation: LeakyReLU
      reg_max: 7
data:
  train:
    name: CocoDataset
    img_path: {DATASET}/images/train
    ann_path: {DATASET}/annotations/train.json
    input_size: [{v['imgsz']}, {v['imgsz']}]
    keep_ratio: False
    pipeline:
      perspective: 0.0
      scale: [0.6, 1.4]
      stretch: [[0.8, 1.2], [0.8, 1.2]]
      rotation: 0
      shear: 0
      translate: 0.2
      flip: 0.5
      brightness: 0.2
      contrast: [0.6, 1.4]
      saturation: [0.5, 1.2]
      normalize: [[103.53, 116.28, 123.675], [57.375, 57.12, 58.395]]
  val:
    name: CocoDataset
    img_path: {DATASET}/images/val
    ann_path: {DATASET}/annotations/val.json
    input_size: [{v['imgsz']}, {v['imgsz']}]
    keep_ratio: False
    pipeline:
      normalize: [[103.53, 116.28, 123.675], [57.375, 57.12, 58.395]]
device:
  gpu_ids: [0]
  workers_per_gpu: 4
  batchsize_per_gpu: {v['batch']}
  precision: 32
schedule:
  optimizer:
    name: AdamW
    lr: 0.001
    weight_decay: 0.05
  warmup:
    name: linear
    steps: 500
    ratio: 0.0001
  total_epochs: 200
  lr_schedule:
    name: CosineAnnealingLR
    T_max: 200
    eta_min: 0.0
  val_intervals: 10
grad_clip: 35
evaluator:
  name: CocoDetectionEvaluator
  save_key: mAP
class_names: ['piece']
"""


def gen_yolox_exp(v: dict) -> str:
    """Generate a YOLOX experiment file for 1-class detection."""
    if v["exp"] == "nano":
        depth, width = 0.33, 0.25
        depthwise = True
    else:  # tiny
        depth, width = 0.33, 0.375
        depthwise = False

    return f"""#!/usr/bin/env python3
import os
from yolox.exp import Exp as MyExp

class Exp(MyExp):
    def __init__(self):
        super().__init__()
        self.num_classes = 1
        self.depth = {depth}
        self.width = {width}
        self.input_size = ({v['imgsz']}, {v['imgsz']})
        self.test_size = ({v['imgsz']}, {v['imgsz']})
        self.random_size = (10, 20)  # multiples of 32
        self.max_epoch = 200
        self.data_num_workers = 4
        self.eval_interval = 10
        self.enable_mixup = True
        self.mosaic_prob = 1.0
        self.mixup_prob = 1.0
        self.hsv_prob = 1.0
        self.flip_prob = 0.5
        self.no_aug_epochs = 15
        self.warmup_epochs = 5
        self.basic_lr_per_img = 0.01 / 64.0
        self.exp_name = "{v['name']}"
        self.output_dir = "/workspace/runs"
        {"self.depthwise = True" if depthwise else "# standard convs"}

    def get_data_dir(self):
        return str("{DATASET}")

    def get_dataset(self, cache=False, cache_type="ram"):
        from yolox.data import COCODataset, TrainTransform
        return COCODataset(
            data_dir=str("{DATASET}"),
            json_file="train.json",
            img_size=self.input_size,
            preproc=TrainTransform(
                max_labels=50,
                flip_prob=self.flip_prob,
                hsv_prob=self.hsv_prob,
            ),
            name="images/train",
            cache=cache,
            cache_type=cache_type,
        )

    def get_eval_dataset(self, **kwargs):
        from yolox.data import COCODataset, ValTransform
        return COCODataset(
            data_dir=str("{DATASET}"),
            json_file="val.json",
            img_size=self.test_size,
            preproc=ValTransform(legacy=False),
            name="images/val",
        )
"""


def setup_nanodet():
    """Clone and setup NanoDet with fixes."""
    print("\n=== Setting up NanoDet ===")
    if not (NANODET_DIR / "setup.py").exists():
        subprocess.run(
            ["git", "clone", "--depth", "1",
             "https://github.com/RangiLyu/nanodet.git", str(NANODET_DIR)],
            check=True,
        )

    # Fix torch._six import (removed in PyTorch 2.x)
    collate_file = NANODET_DIR / "nanodet" / "data" / "collate.py"
    if collate_file.exists():
        content = collate_file.read_text()
        if "torch._six" in content:
            content = content.replace(
                "from torch._six import string_classes",
                "string_classes = (str,)",
            )
            collate_file.write_text(content)
            print("  Fixed torch._six import in collate.py")

    # Install nanodet + pinned pytorch-lightning
    subprocess.run(["pip", "install", "-q", "--no-deps", "-e", str(NANODET_DIR)], check=True)
    subprocess.run(
        ["pip", "install", "-q",
         "imagesize",
         "termcolor",
         "matplotlib",
         "pytorch-lightning==1.9.5",
         "onnx", "onnxsim", "onnxruntime", "pycocotools"],
        check=True,
    )
    pin_runtime_stack()
    print("  NanoDet setup complete")


def setup_yolox():
    """Clone and setup YOLOX."""
    print("\n=== Setting up YOLOX ===")
    if not (YOLOX_DIR / "setup.py").exists():
        subprocess.run(
            ["git", "clone", "--depth", "1",
             "https://github.com/Megvii-BaseDetection/YOLOX.git", str(YOLOX_DIR)],
            check=True,
        )

    subprocess.run(
        ["pip", "install", "-q", "cython", "cython_bbox", "loguru", "ninja", "tabulate",
         "thop", "onnx", "onnxsim", "onnxruntime", "onnx-simplifier==0.4.10",
         "pycocotools", "tensorboard", "matplotlib"],
        check=True,
    )
    subprocess.run(["pip", "install", "-q", "--no-deps", "-e", str(YOLOX_DIR)], check=True)
    pin_runtime_stack()

    # YOLOX expects annotations in a specific location: <data_dir>/annotations/
    # Our dataset already has this structure, so just make sure the symlink is correct
    ann_dir = DATASET / "annotations"
    if ann_dir.exists():
        # YOLOX expects instances_train2017.json etc. but we can pass custom names via exp
        print("  YOLOX setup complete")


def train_nanodet(v: dict) -> dict:
    """Train a single NanoDet-Plus variant."""
    model_id = v["id"]
    model_name = v["name"]
    print(f"\n{'=' * 60}")
    print(f"Training {model_id}: {model_name} (NanoDet-Plus)")
    print(f"{'=' * 60}")

    result = {"name": model_name, "framework": "nanodet"}
    t0 = time.time()

    try:
        save_dir = f"/workspace/runs/{model_name}"
        cfg_path = f"/workspace/configs/{model_name}.yml"
        os.makedirs(os.path.dirname(cfg_path), exist_ok=True)

        with open(cfg_path, "w") as f:
            f.write(gen_nanodet_config(v, save_dir))

        # Train
        r = subprocess.run(
            ["python", "tools/train.py", cfg_path],
            cwd=str(NANODET_DIR),
            capture_output=False,
        )
        result["train_returncode"] = r.returncode
        elapsed = time.time() - t0
        result["train_elapsed_min"] = round(elapsed / 60, 1)
        if r.returncode != 0:
            result["error"] = f"NanoDet training failed with return code {r.returncode}"
            return result

        # Find best checkpoint
        best_pth = glob.glob(f"{save_dir}/**/nanodet_model_best.pth", recursive=True)
        if best_pth:
            best = best_pth[0]
            result["best_checkpoint"] = best

            # Export to ONNX
            onnx_path = str(RESULTS / f"{model_name}.onnx")
            e = subprocess.run(
                ["python", "tools/export_onnx.py",
                 "--cfg_path", cfg_path,
                 "--model_path", best,
                 "--out_path", onnx_path],
                cwd=str(NANODET_DIR),
                capture_output=True, text=True,
            )
            result["onnx_export_rc"] = e.returncode

            if os.path.exists(onnx_path):
                # Simplify ONNX
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
                        family="nanodet",
                        imgsz=v["imgsz"],
                    )
                )

            # Copy checkpoint
            shutil.copy2(best, RESULTS / f"{model_name}_best.pth")

        # Read eval results
        eval_files = glob.glob(f"{save_dir}/**/eval_results.txt", recursive=True)
        if eval_files:
            result["eval_results"] = open(eval_files[-1]).read().strip()

    except Exception as exc:
        result["error"] = f"{exc}\n{traceback.format_exc()}"
        elapsed = time.time() - t0
        result["train_elapsed_min"] = round(elapsed / 60, 1)

    print(f"\n{model_id} done: {result.get('train_elapsed_min', '?')} min")
    return result


def train_yolox(v: dict) -> dict:
    """Train a single YOLOX variant."""
    model_id = v["id"]
    model_name = v["name"]
    print(f"\n{'=' * 60}")
    print(f"Training {model_id}: {model_name} (YOLOX)")
    print(f"{'=' * 60}")

    result = {"name": model_name, "framework": "yolox"}
    t0 = time.time()

    try:
        # Write experiment file
        exp_dir = Path("/workspace/exps")
        exp_dir.mkdir(exist_ok=True)
        exp_file = exp_dir / f"{model_name}.py"
        exp_file.write_text(gen_yolox_exp(v))

        # Train
        cmd = [
            "python", "-m", "yolox.tools.train",
            "-f", str(exp_file),
            "-d", "1",  # 1 GPU
            "-b", str(v["batch"]),
            "--fp16",
            "-o",  # occupy GPU memory first
        ]
        r = subprocess.run(cmd, cwd=str(YOLOX_DIR), capture_output=False)
        result["train_returncode"] = r.returncode
        elapsed = time.time() - t0
        result["train_elapsed_min"] = round(elapsed / 60, 1)
        if r.returncode != 0:
            result["error"] = f"YOLOX training failed with return code {r.returncode}"
            return result

        # Find best checkpoint
        best_ckpts = glob.glob(
            f"/workspace/runs/{model_name}/**/best_ckpt.pth", recursive=True
        )
        if not best_ckpts:
            best_ckpts = glob.glob(
                f"/workspace/runs/{model_name}/**/*.pth", recursive=True
            )
        if best_ckpts:
            best = sorted(best_ckpts)[-1]
            result["best_checkpoint"] = best

            # Export to ONNX
            onnx_path = str(RESULTS / f"{model_name}.onnx")
            e = subprocess.run(
                ["python", "-m", "yolox.tools.export_onnx",
                 "--output-name", onnx_path,
                 "-f", str(exp_file),
                 "-c", best,
                 "--decode_in_inference"],
                cwd=str(YOLOX_DIR),
                capture_output=True, text=True,
            )
            result["onnx_export_rc"] = e.returncode

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
                        family="yolox",
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
    nanodet_variants = select_variants(NANODET_VARIANTS, selected_ids)
    yolox_variants = select_variants(YOLOX_VARIANTS, selected_ids)

    print("=" * 60)
    print("Track B+C: NanoDet-Plus + YOLOX Models")
    print("=" * 60)

    results = {}

    try:
        setup_system_dependencies()
    except Exception as exc:
        print(f"Shared dependency setup failed: {exc}")
        for v in nanodet_variants + yolox_variants:
            results[v["id"]] = {"name": v["name"], "error": f"Shared setup failed: {exc}"}
        summary_path = RESULTS / "track_bc_results.json"
        with open(summary_path, "w") as f:
            json.dump(results, f, indent=2)
        return

    # Setup frameworks
    try:
        setup_nanodet()
    except Exception as exc:
        print(f"NanoDet setup failed: {exc}")
        for v in nanodet_variants:
            results[v["id"]] = {"name": v["name"], "error": f"Setup failed: {exc}"}

    try:
        setup_yolox()
    except Exception as exc:
        print(f"YOLOX setup failed: {exc}")
        for v in yolox_variants:
            results[v["id"]] = {"name": v["name"], "error": f"Setup failed: {exc}"}

    # Train NanoDet variants
    for v in nanodet_variants:
        if v["id"] not in results:  # skip if setup failed
            results[v["id"]] = train_nanodet(v)

    # Train YOLOX variants
    for v in yolox_variants:
        if v["id"] not in results:
            results[v["id"]] = train_yolox(v)

    # Write summary
    summary_path = RESULTS / "track_bc_results.json"
    with open(summary_path, "w") as f:
        json.dump(results, f, indent=2)

    print(f"\n\n{'=' * 60}")
    print("Track B+C Complete")
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
