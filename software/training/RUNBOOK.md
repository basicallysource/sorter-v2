# Training Runbook — Pull → Train → Publish

Concrete end-to-end recipe for shipping a new detection model into Hive,
mirroring the 2026-05-17 c-channel-combined yolo26s-320 run.

Every command runs from `software/training/`. Run `uv sync` once on the
workstation. `train` is the CLI; `vastai` is the upstream Vast.ai CLI.

---

## 0. One-time setup

```bash
# Hive API keys (one per target)
uv run train auth login --hive-url http://localhost:8002
uv run train auth login --hive-url https://hive.basically.website

# Vast.ai CLI auth — `vastai set api-key <key>` (see vast.ai/cli)
```

---

## 1. Pull samples from a Hive

`train pull` is incremental — re-running only fetches new sample IDs.

```bash
uv run train pull \
  --hive-url http://localhost:8002 \
  --zone c_channel_full \
  --status ""        # "" = any review_status (default is "accepted" only)
```

Zone → source-role mapping lives in `src/training/hive/pull.py:ZONE_SOURCE_ROLES`.
For the combined C-Channel detector we use `c_channel_full`, which expands
to `c_channel_2 + c_channel_3 + classification_channel`.

Output: `datasets/<zone>/raw/` with one dir per sample plus `manifest.json`.

---

## 2. Build the YOLO dataset

```bash
uv run train build \
  --zone c_channel_full \
  --name v6_maxout_score095 \
  --target-size 7500 \
  --keep-empty \
  --max-empty-fraction 0.1 \
  --min-detection-score 0.95
```

Flags worth knowing:

| Flag | Effect |
|---|---|
| `--target-size N` | Diversity-sample down to N positives (YOLO11n embeddings + farthest-point) |
| `--min-detection-score 0.95` | Drop Gemini auto-labels below this confidence |
| `--keep-empty` | Pull empty-frame negatives into the pool |
| `--max-empty-fraction 0.1` | Cap empties at 10 % of the final dataset (only with `--keep-empty`) |
| `--balance-source-role` | Equalise the per-source quota when diversity-sampling |
| `--balance-piece-count` | Add per-piece-count balancing on top (buckets `0,1,2…,9-12,13+`) |
| `--strict-balance` | Fail the build if a balance group can't fill its quota |

Output: `datasets/<zone>/<name>/` with `images/{train,val}/`, `labels/{train,val}/`,
`data.yaml`, `build.json` (the manifest used downstream).

---

## 3. Package + provision a Vast.ai box

The trainer image (`roothirsch/lego-sorter-training-image:latest`) ships
pre-baked ultralytics + numpy/opencv + cached YOLO base weights. To rebuild
after an Ultralytics bump, see [`docker/README.md`](docker/README.md).

```bash
uv run train vastai package \
  --zone c_channel_full \
  --name v6_maxout_score095 \
  --track yolo \
  --model-ids A7              # A7 = yolo26s @ 320; see src/training/vastai/tracks/yolo.py for the full table

uv run train vastai offers --limit 5
# Pick an offer ID — RTX 3090 / 4090 / A5000 / A6000. Watch reliability (>0.99)
# and inet_down (>500 Mbit). Pricing typically 0.13–0.20 $/h.

OFFER=36792868
TARBALL=runs/staging/<timestamp>-c_channel_full-yolo-v6_maxout_score095.tar.gz
INSTANCE=$(vastai create instance $OFFER \
  --image roothirsch/lego-sorter-training-image:latest \
  --disk 60 \
  --ssh \
  --label c_channel_full-yolo26s-v6 \
  | grep -oE 'new_contract.*[0-9]+' | grep -oE '[0-9]+')
echo "instance=$INSTANCE"
```

Wait for `actual_status=running` (boot + image pull ≈ 1–3 min):

```bash
until [ "$(vastai show instance $INSTANCE --raw \
            | uv run --no-project python -c 'import json,sys;print(json.load(sys.stdin)["actual_status"])')" \
        = "running" ]; do sleep 20; done
```

---

## 4. Upload + train

```bash
SSH=$(vastai ssh-url $INSTANCE | tail -1 | sed 's#ssh://##')
SSH_HOST=${SSH%:*}
SSH_PORT=${SSH##*:}

scp -P $SSH_PORT $TARBALL $SSH_HOST:/workspace/

ssh -p $SSH_PORT $SSH_HOST "
  cd /workspace &&
  tar xzf $(basename $TARBALL) --strip-components=1 &&
  nohup python yolo.py --model-ids A7 > training.log 2>&1 < /dev/null &
"
```

Monitor cleanly (epoch + metrics):

```bash
ssh -p $SSH_PORT $SSH_HOST "
  tail -1 /workspace/runs/A7-yolo26s-320/results.csv \
    | awk -F, '{printf \"e=%s mAP50=%.4f mAP50-95=%.4f\n\",\$1,\$8,\$9}'
"
```

`yolo.py` ships with `epochs=300, patience=100`. Reference run hit best
`mAP50-95 = 0.912 @ epoch 180`, full run 273 min.

---

## 5. Fetch results + DESTROY the instance

```bash
uv run train vastai fetch \
  --instance $INSTANCE \
  --zone c_channel_full \
  --track yolo \
  --dataset-name v6_maxout_score095

# REQUIRED — storage keeps billing on `stop`. Always destroy.
vastai destroy instance $INSTANCE
vastai show instances   # confirm it's gone
```

Results land in `runs/<timestamp>-c_channel_full-yolo-v6_maxout_score095/`
with `A7-yolo26s-320-best.{pt,onnx}` plus `A7-yolo26s-320-ncnn/` and
`track_a_results.json`.

---

## 6. Re-shape the run dir for publish

The publish step expects `run.json` + `exports/best.{onnx,pt}` +
`exports/best_ncnn_model/`. The Vast.ai fetch writes the raw artifacts
flat, so move them into place once:

```bash
RUN=runs/<timestamp>-c_channel_full-yolo-v6_maxout_score095
mkdir -p $RUN/exports
mv $RUN/A7-yolo26s-320-best.onnx $RUN/exports/best.onnx
mv $RUN/A7-yolo26s-320-best.pt   $RUN/exports/best.pt
mv $RUN/A7-yolo26s-320-ncnn      $RUN/exports/best_ncnn_model
rm -rf $RUN/exports/best_ncnn_model/__pycache__
# Then write a minimal $RUN/run.json (see scripts/compose_v6_metadata.py
# for the shape; the real metadata gets composed by --dataset-dir below).
```

---

## 7. Local latency benchmark (optional but recommended)

`scripts/benchmark_v6_local.py` runs CPU + CoreML onnxruntime for 30
iterations at 320 × 320 and writes a JSON in the
`reports_out/device_benchmarks/` shape that the Hive page reads. Adapt
the `RUN_DIR` / `OUT_PATH` constants for the new run, then:

```bash
uv run python scripts/benchmark_v6_local.py
# → reports_out/device_benchmarks/local_<slug>_<date>.json
```

Reference: CoreML 3.4 ms (298 fps), CPU 12.1 ms (83 fps) on Apple Silicon.

---

## 8. Publish to Hive (composes metadata automatically)

```bash
SLUG=c-channel-combined-yolo26s-320

# Local Hive
uv run train publish \
  --run-dir $RUN \
  --slug $SLUG \
  --scopes c_channel,classification_chamber \
  --hive-url http://localhost:8002 \
  --family yolo \
  --name "c-channel-combined yolo26s-320" \
  --description "Combined C-Channel detector: yolo26s @ 320, 7568 samples (C2+C3+Classification Channel, score>=0.95, 10% empties)." \
  --dataset-dir datasets/c_channel_full/v6_maxout_score095 \
  --benchmark-json reports_out/device_benchmarks/local_v6_yolo26s_20260517.json \
  --model-key A7

# Public Hive — same command, swap --hive-url
uv run train publish ... --hive-url https://hive.basically.website ...
```

Key flags:

- `--dataset-dir` triggers auto-compose of the Hive-shaped
  `training_metadata` (model + dataset + selection + benchmarks) from
  `build.json` + `track_*_results.json`. **Always pass it.** Without it
  the Hive UI's hero cards stay blank.
- `--benchmark-json` adds the CPU/CoreML latency block.
- `--model-key A7` picks the right entry when the track ran several
  models — match the `A1/A3/A5/A7/A8` label from `track_a_results.json`.
- Visibility: `--public/--private` defaults to **public**. Drop the flag
  unless you specifically want the model hidden from other accounts.

Each `train publish` creates a new `version` row in the model table
(slug is the unique key, version auto-increments). If you re-publish to
fix metadata, delete the old version row afterwards so the slug only
carries the canonical one:

```bash
curl -X DELETE -H "Authorization: Bearer $HIVE_TOKEN" \
  https://hive.basically.website/api/models/<id-of-old-version>
```

---

## 9. Deploy the Hive (only if you touched frontend or backend code)

Frontend dev locally is hot-reloaded by Vite. To roll prod:

```bash
git push origin <branch>
ssh root@45.55.232.164 "
  cd /basically/sorter/sorter-v2 &&
  git pull --ff-only origin sorthive &&
  cd software/hive &&
  docker compose --env-file .env.prod -f docker-compose.prod.yml \
    up -d --build backend frontend
"
```

`--env-file .env.prod` is required — the compose file references env vars
that live there.

---

## TBD — Hailo HEF compile

A `c_channel_yolo26s` preset isn't in `src/training/exports/hailo.py:PRESETS`
yet. The current presets are `classification_chamber_yolo11s` and
`classification_chamber_nanodet`. To add it, mirror those entries:
network_name, parser_end_nodes (introspect from the YOLO26 ONNX), the
calibration dir under `datasets/c_channel_full/<name>/train/images`, and
a fresh reference benchmark. Then a separate Vast.ai session with the
Hailo Dataflow Compiler image runs `hailomz compile`. Examples of past
sessions: `hailo_bundles/vastai_session_20260406_*.md`.
