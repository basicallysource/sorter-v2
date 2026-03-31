#!/usr/bin/env bash
# Train all 3 NanoDet-Plus variants on Vast.ai GPU
# Usage: ./scripts/vastai_train_nanodet.sh
set -euo pipefail

CLIENT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
DATASET_DIR="$CLIENT_DIR/blob/kaggle_dataset"
OUTPUT_DIR="$CLIENT_DIR/blob/vastai_results"
mkdir -p "$OUTPUT_DIR"

# --- Step 1: Prepare dataset zip ---
echo "=== Preparing dataset ==="
if [ ! -f "$DATASET_DIR/annotations/train.json" ]; then
    echo "Dataset not found, generating..."
    cd "$CLIENT_DIR" && uv run python scripts/kaggle_prepare_dataset.py
fi

UPLOAD_DIR=$(mktemp -d)
cp -r "$DATASET_DIR/images" "$UPLOAD_DIR/"
cp -r "$DATASET_DIR/annotations" "$UPLOAD_DIR/"

# Create the training script that runs on the remote machine
cat > "$UPLOAD_DIR/train_all.py" << 'TRAINSCRIPT'
#!/usr/bin/env python3
"""Train all 3 NanoDet-Plus variants on GPU."""
import os, subprocess, json, time, glob, shutil
from pathlib import Path

DATASET = Path("/workspace/dataset")
NANODET = Path("/workspace/nanodet")
RESULTS = Path("/workspace/results")
RESULTS.mkdir(exist_ok=True)

VARIANTS = [
    {"name": "nanodet-plus-m-320", "model_size": "1.0x", "imgsz": 320,
     "fpn_in": [116,232,464], "fpn_out": 96, "aux_in": 192, "aux_feat": 192, "batch": 96},
    {"name": "nanodet-plus-m-416", "model_size": "1.0x", "imgsz": 416,
     "fpn_in": [116,232,464], "fpn_out": 96, "aux_in": 192, "aux_feat": 192, "batch": 64},
    {"name": "nanodet-plus-m-1.5x-416", "model_size": "1.5x", "imgsz": 416,
     "fpn_in": [176,352,704], "fpn_out": 128, "aux_in": 256, "aux_feat": 256, "batch": 32},
]

def gen_config(v, save_dir):
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

all_results = {}
for v in VARIANTS:
    print(f"\n{'='*60}\nTraining {v['name']}\n{'='*60}")
    save_dir = f"/workspace/runs/{v['name']}"
    cfg_path = f"/workspace/configs/{v['name']}.yml"
    os.makedirs(os.path.dirname(cfg_path), exist_ok=True)
    with open(cfg_path, "w") as f:
        f.write(gen_config(v, save_dir))

    t0 = time.time()
    r = subprocess.run(["python", "tools/train.py", cfg_path], cwd=str(NANODET))
    elapsed = time.time() - t0
    print(f"{v['name']} training: {elapsed/60:.1f} min, rc={r.returncode}")

    # Export ONNX
    best = glob.glob(f"{save_dir}/**/nanodet_model_best.pth", recursive=True)
    onnx_path = f"/workspace/results/{v['name']}.onnx"
    if best:
        subprocess.run([
            "python", "tools/export_onnx.py",
            "--cfg_path", cfg_path, "--model_path", best[0], "--out_path", onnx_path
        ], cwd=str(NANODET))
        # Simplify
        sim = onnx_path.replace(".onnx", "-sim.onnx")
        subprocess.run(["python", "-m", "onnxsim", onnx_path, sim])
        final = sim if os.path.exists(sim) else onnx_path
        # Copy checkpoint too
        shutil.copy2(best[0], f"/workspace/results/{v['name']}_best.pth")
    else:
        final = None

    # Read eval results
    eval_files = glob.glob(f"{save_dir}/**/eval_results.txt", recursive=True)
    eval_data = open(eval_files[-1]).read() if eval_files else "no eval"

    all_results[v['name']] = {
        "elapsed_min": round(elapsed/60, 1),
        "returncode": r.returncode,
        "onnx": final,
        "onnx_size_kb": round(os.path.getsize(final)/1024, 1) if final and os.path.exists(final) else None,
        "eval": eval_data,
    }

with open("/workspace/results/summary.json", "w") as f:
    json.dump(all_results, f, indent=2)
print("\n\nDone! Results in /workspace/results/")
print(json.dumps(all_results, indent=2))
TRAINSCRIPT

# Create setup script
cat > "$UPLOAD_DIR/setup.sh" << 'SETUPSCRIPT'
#!/bin/bash
set -e
echo "=== Setting up NanoDet ==="
cd /workspace
git clone --depth 1 https://github.com/RangiLyu/nanodet.git
cd nanodet
pip install -e . -q
pip install onnx onnxsim onnxruntime pycocotools -q

# Fix torch._six import (removed in PyTorch 2.x)
COLLATE_FILE="nanodet/data/collate.py"
if grep -q "torch._six" "$COLLATE_FILE" 2>/dev/null; then
    sed -i 's/from torch._six import string_classes/string_classes = (str,)/' "$COLLATE_FILE"
fi

echo "=== Moving dataset ==="
mkdir -p /workspace/dataset
mv /workspace/upload/images /workspace/dataset/
mv /workspace/upload/annotations /workspace/dataset/

echo "=== Starting training ==="
cd /workspace
python /workspace/upload/train_all.py
SETUPSCRIPT
chmod +x "$UPLOAD_DIR/setup.sh"

# Tar it up
TAR_FILE="$OUTPUT_DIR/upload.tar.gz"
cd "$UPLOAD_DIR" && tar czf "$TAR_FILE" .
echo "Upload package: $(du -h "$TAR_FILE" | cut -f1)"

# --- Step 2: Find and rent a GPU ---
echo ""
echo "=== Finding GPU instance ==="
INSTANCE_ID=$(vastai search offers 'gpu_ram>=12 num_gpus=1 reliability>0.95 inet_down>100 disk_space>=20' -o 'dph' --limit 1 --raw 2>/dev/null | python3 -c "import sys,json; print(json.load(sys.stdin)[0]['id'])")
echo "Best offer: $INSTANCE_ID"

echo "=== Creating instance ==="
CREATE_OUT=$(vastai create instance "$INSTANCE_ID" --image pytorch/pytorch:latest --disk 20 --onstart-cmd "sleep infinity" --raw 2>&1)
echo "$CREATE_OUT"
CONTRACT_ID=$(echo "$CREATE_OUT" | python3 -c "import sys,json; print(json.load(sys.stdin)['new_contract'])")
echo "Contract ID: $CONTRACT_ID"

echo "=== Waiting for instance to start ==="
for i in $(seq 1 120); do
    STATUS=$(vastai show instance "$CONTRACT_ID" --raw 2>/dev/null | python3 -c "import sys,json; print(json.load(sys.stdin)['actual_status'])" 2>/dev/null || echo "unknown")
    echo "  Status: $STATUS ($i/120)"
    if [ "$STATUS" = "running" ]; then break; fi
    sleep 10
done

if [ "$STATUS" != "running" ]; then
    echo "ERROR: Instance failed to start after 20 minutes. Destroying..."
    vastai destroy instance "$CONTRACT_ID"
    exit 1
fi

# Get SSH details
SSH_INFO=$(vastai ssh-url "$CONTRACT_ID" 2>&1)
echo "SSH: $SSH_INFO"

# Extract host and port
SSH_HOST=$(echo "$SSH_INFO" | grep -oE '[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+' | head -1)
SSH_PORT=$(echo "$SSH_INFO" | grep -oE ':[0-9]+' | head -1 | tr -d ':')
if [ -z "$SSH_HOST" ]; then
    SSH_HOST=$(echo "$SSH_INFO" | sed 's/ssh:\/\///' | cut -d: -f1)
fi

echo ""
echo "=== Uploading training package ==="
scp -P "$SSH_PORT" -o StrictHostKeyChecking=no "$TAR_FILE" "root@$SSH_HOST:/workspace/upload.tar.gz"

echo "=== Starting remote training ==="
ssh -p "$SSH_PORT" -o StrictHostKeyChecking=no "root@$SSH_HOST" << 'REMOTECMD'
cd /workspace
mkdir -p upload && cd upload
tar xzf /workspace/upload.tar.gz
bash setup.sh
REMOTECMD

echo ""
echo "=== Downloading results ==="
scp -P "$SSH_PORT" -o StrictHostKeyChecking=no -r "root@$SSH_HOST:/workspace/results/*" "$OUTPUT_DIR/"

echo "=== Destroying instance ==="
vastai destroy instance "$CONTRACT_ID"

echo ""
echo "=== DONE ==="
echo "Results in: $OUTPUT_DIR/"
ls -la "$OUTPUT_DIR/"

# Cleanup
rm -rf "$UPLOAD_DIR"
