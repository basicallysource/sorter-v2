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

## Status

Scaffold only — CLI subcommands are stubs until each module is filled in.
