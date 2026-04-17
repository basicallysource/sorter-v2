"""LEGO detection-model training hub."""

from pathlib import Path

PACKAGE_ROOT = Path(__file__).resolve().parent
TRAINING_ROOT = PACKAGE_ROOT.parent.parent
DATASETS_DIR = TRAINING_ROOT / "datasets"
RUNS_DIR = TRAINING_ROOT / "runs"
HAILO_BUNDLES_DIR = TRAINING_ROOT / "hailo_bundles"
VENDOR_DIR = TRAINING_ROOT / "vendor"
STAGING_DIR = TRAINING_ROOT / "staging"

__all__ = [
    "PACKAGE_ROOT",
    "TRAINING_ROOT",
    "DATASETS_DIR",
    "RUNS_DIR",
    "HAILO_BUNDLES_DIR",
    "VENDOR_DIR",
    "STAGING_DIR",
]
