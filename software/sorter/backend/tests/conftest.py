"""Shared test fixtures for the sorter backend.

The bundled-models directory ``software/sorter/backend/bundled_models/`` ships
real model artifacts via git LFS. Tests that exercise the model registry or
``list_installed_models()`` need to start from a clean slate, otherwise the
real bundled entries leak into assertions about counts/contents.

This autouse fixture redirects both module-level constants to an empty tmp
dir for every test. Tests that specifically want to exercise the bundled flow
can re-monkeypatch with their own seeded directory.
"""

from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def _isolate_bundled_models_dir(tmp_path_factory: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch) -> Path:
    empty_root = tmp_path_factory.mktemp("bundled-models-empty")
    try:
        from vision import detection_registry as registry
    except Exception:
        registry = None
    try:
        from server import hive_models as hive_models_service
    except Exception:
        hive_models_service = None

    if registry is not None:
        monkeypatch.setattr(registry, "BUNDLED_MODELS_DIR", empty_root)
        registry.invalidate_registry()
    if hive_models_service is not None:
        monkeypatch.setattr(hive_models_service, "BUNDLED_MODELS_DIR", empty_root)

    yield empty_root

    if registry is not None:
        registry.invalidate_registry()
