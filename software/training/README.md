# LEGO Training Hub

Central workstation package for producing detection models. End-to-end pipeline:

```
Hive (samples + annotations)
      │  train pull
      ▼
datasets/<zone>/
      │  train build
      ▼
YOLO-ready dataset
      │  train train --track yolo|nanodet
      ▼
Vast.ai GPU
      │  (download best.pt + run.json)
      ▼
runs/<run-id>/
      │  train export --hailo
      ▼
hailo_bundles/<name>/
      │  train publish
      ▼
Hive (published detection_models + variants)
```

## Layout

```
software/training/
├── pyproject.toml
├── src/training/
│   ├── cli.py                 # `train <subcommand>`
│   ├── hive/
│   │   ├── pull.py            # samples + annotations → datasets/
│   │   └── publish.py         # runs/<id> → Hive model catalog
│   ├── datasets/build.py      # Hive dump → YOLO-format dataset
│   ├── vastai/
│   │   ├── session.py         # provision + attach to Vast.ai instance
│   │   └── tracks/            # training scripts shipped to the remote
│   │       ├── yolo.py        # Ultralytics YOLO (11n/11s/v8n/26n)
│   │       └── nanodet.py     # NanoDet-Plus-m
│   ├── exports/
│   │   ├── hailo.py           # ONNX → Hailo HEF bundle
│   │   └── hailo_shared_worker.py
│   └── reports/               # benchmark + cross-device reports
├── datasets/                  # built datasets per zone
├── runs/                      # training outputs (run.json + exports/)
├── hailo_bundles/             # Hailo HEF compile bundles
└── vendor/
    └── nanodet/               # vendored NanoDet source
```

## Quickstart

```bash
cd software/training
uv sync
uv run train --help
```

For camera/channel-balanced detector datasets, cap the dataset with diversity
sampling while keeping each Hive `source_role` represented:

```bash
uv run train build --zone c_channel --name v3_balanced --target-size 1500 --balance-source-role
```

You can also balance by the number of pieces in the frame. The default buckets
are `0,1,2,3,4,5,6,7,8,9-12,13+`:

```bash
uv run train build --zone c_channel --name v3_balanced --target-size 1500 --balance-source-role --balance-piece-count --keep-empty
```

To keep only high-confidence teacher samples, add a score threshold:

```bash
uv run train build --zone c_channel --name v3_balanced_098 --target-size 1500 --balance-source-role --balance-piece-count --min-detection-score 0.98
```

The score threshold only applies to positive samples with boxes; empty/negative
samples are still included when `--keep-empty` is set.

Use strict balancing when you want the build to fail instead of silently
underfilling a role that needs more samples:

```bash
uv run train build --zone c_channel --name v3_balanced --target-size 1500 --balance-source-role --strict-balance
```

During collection, run an incremental local Hive progress check from the Hive
backend environment. It keeps a per-sample cache and appends a history row each
time:

```bash
cd software/hive/backend
DATABASE_URL="postgresql://hive:hive_dev@127.0.0.1:5432/hive" ./.venv/bin/python scripts/sample_progress_check.py
```

The progress report includes a per-role bucket coverage score from 0-100. By
default, each role+piece-count bucket counts as complete once it has 50 accepted
samples; override with `--bucket-target`.
It also caches lightweight image metrics for QA (brightness, contrast, and
saturation buckets). Those image metrics are diagnostic only and are not used as
hard dataset-balancing criteria.

## Status

Scaffold only — CLI subcommands are stubs until each module is filled in.
