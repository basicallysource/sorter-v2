"""Shared test fixtures for the sorter backend.

Installed detection models live in ``backend/blob/hive_detection_models/``,
which on a developer machine holds whatever that machine has downloaded. Tests
that exercise the model registry or ``list_installed_models()`` must not see
those, so this autouse fixture points both module-level constants at an empty
tmp dir for every test. Tests that want models seed their own directory and
re-monkeypatch.
"""

from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def _isolate_installed_models_dir(tmp_path_factory: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch) -> Path:
    empty_root = tmp_path_factory.mktemp("installed-models-empty")
    try:
        from vision import detection_registry as registry
    except Exception:
        registry = None
    try:
        from server import hive_models as hive_models_service
    except Exception:
        hive_models_service = None

    if registry is not None:
        monkeypatch.setattr(registry, "MODELS_DIR", empty_root)
        registry.invalidate_registry()
    if hive_models_service is not None:
        monkeypatch.setattr(hive_models_service, "LOCAL_MODELS_DIR", empty_root)

    yield empty_root

    if registry is not None:
        registry.invalidate_registry()
