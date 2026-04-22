"""Detector implementations. Import triggers registry self-registration.

Hive-trained detectors are discovered dynamically by scanning
``blob/hive_detection_models/``. Discovery is a safe no-op when the
directory is absent (fresh clone / CI without model blobs).
"""

from __future__ import annotations

from . import hive_onnx  # noqa: F401

# Explicit discovery call — robust against missing models dir.
hive_onnx.discover_and_register_hive_detectors()


__all__ = ["hive_onnx"]
