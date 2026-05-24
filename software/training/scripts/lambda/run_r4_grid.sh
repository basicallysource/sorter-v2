#!/usr/bin/env bash
# r4: drive 8 lambda training runs from the local Mac in 4 sequential pairs.
# Each pair runs 2 concurrent `train lambda run` invocations against the same
# A100 (matches the r3 2-up pattern). The pair only advances once both members
# have finished and rsynced their bundle back to T7.
#
# Designed to be launched via `nohup .../run_r4_grid.sh &` so it survives the
# parent shell closing. All output goes to /tmp/r4_grid_<idx>.log per run.
#
# Required env (typically sourced from software/.env earlier):
#   - none — host IP, dataset names, bundle names hardcoded for the r4 grid.
#
# Pairs:
#   1: nano c_channel        (silu, relu6)
#   2: nano c_channel_full   (silu, relu6)
#   3: small c_channel       (silu, relu6)
#   4: small c_channel_full  (silu, relu6)
set -euo pipefail

cd "$(dirname "$0")/../.."   # cd into software/training
HOST=ubuntu@132.145.130.118
DATE=2026-05-23

run_one() {
  local idx="$1"
  local model_id="$2"     # A3 = yolo11n-320, A5 = yolo11s-320
  local zone="$3"
  local dataset_name="$4"
  local activation="$5"
  local short_arch="$6"   # n or s
  local short_zone="$7"   # c-channel or c-channel-full
  local bundle="sorter-npu-r4_yolo11${short_arch}-320_rk3588-int8_${short_zone}-${activation}_${DATE}"
  local log="/tmp/r4_grid_${idx}_${short_arch}_${short_zone}_${activation}.log"
  echo "=== r4 run #${idx} -> ${bundle} (log: ${log}) ==="
  uv run train lambda run \
      --host "$HOST" \
      --zone "$zone" \
      --dataset-name "$dataset_name" \
      --bundle-name "$bundle" \
      --model-id "$model_id" \
      --activation "$activation" \
      --epochs 300 \
      --calibration-count 150 \
      --skip-pull --skip-build \
      --no-status-server \
      --build-flag --balance-source-role --build-flag --balance-machine \
      >"$log" 2>&1
}

pair() {
  local pair_idx="$1"; shift
  local idx_a="$1"; shift
  local model_a="$1"; shift
  local zone_a="$1"; shift
  local dataset_a="$1"; shift
  local activation_a="$1"; shift
  local arch_a="$1"; shift
  local szone_a="$1"; shift
  local idx_b="$1"; shift
  local model_b="$1"; shift
  local zone_b="$1"; shift
  local dataset_b="$1"; shift
  local activation_b="$1"; shift
  local arch_b="$1"; shift
  local szone_b="$1"; shift

  echo ">>> pair ${pair_idx}: launching #${idx_a} and #${idx_b} in parallel"
  run_one "$idx_a" "$model_a" "$zone_a" "$dataset_a" "$activation_a" "$arch_a" "$szone_a" &
  local pid_a=$!
  run_one "$idx_b" "$model_b" "$zone_b" "$dataset_b" "$activation_b" "$arch_b" "$szone_b" &
  local pid_b=$!
  wait "$pid_a" || echo "WARN: run #${idx_a} exited non-zero"
  wait "$pid_b" || echo "WARN: run #${idx_b} exited non-zero"
  echo ">>> pair ${pair_idx}: both done"
}

DS_CC=r4_c_channel_2026_05_23
DS_CCF=r4_c_channel_full_2026_05_23

pair 1  1 A3 c_channel      "$DS_CC"  silu  n c-channel        2 A3 c_channel      "$DS_CC"  relu6 n c-channel
pair 2  3 A3 c_channel_full "$DS_CCF" silu  n c-channel-full   4 A3 c_channel_full "$DS_CCF" relu6 n c-channel-full
pair 3  5 A5 c_channel      "$DS_CC"  silu  s c-channel        6 A5 c_channel      "$DS_CC"  relu6 s c-channel
pair 4  7 A5 c_channel_full "$DS_CCF" silu  s c-channel-full   8 A5 c_channel_full "$DS_CCF" relu6 s c-channel-full

echo "=== r4 grid: ALL 8 RUNS COMPLETE ==="
