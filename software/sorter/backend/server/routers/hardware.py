"""The hardware config overview, and the storage layer settings."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

import machine_toml
from irl.bin_layout import (
    getBinLayout,
    saveBinLayout,
    BinLayoutConfig,
    LayerConfig,
    calibratedAnglesForLayer,
    channelIdForLayer,
    _LAYER_MAX_DIMENSION_DEFAULTS_MM,
)
from server import shared_state
from server.routers.chute import _chute_settings_from_config
from server.routers.servos import _servo_hardware_issues, _servo_settings_from_config

router = APIRouter()


class StorageLayerPayload(BaseModel):
    bin_count: int
    enabled: bool = True
    servo_open_angle: Optional[int] = None
    servo_closed_angle: Optional[int] = None
    max_pieces_per_bin: Optional[int] = None
    max_dimension_mm: Optional[float] = None


class StorageLayerSettingsPayload(BaseModel):
    layer_bin_counts: List[int] = []
    layers: List[StorageLayerPayload] = []


ALLOWED_STORAGE_LAYER_BIN_COUNTS = [6, 12, 18, 30]
DEFAULT_STORAGE_LAYER_SECTION_COUNT = 6


def _storage_layer_settings_from_layout(layout: Any) -> Dict[str, Any]:
    layers: List[Dict[str, Any]] = []
    for index, layer in enumerate(getattr(layout, "layers", []), start=1):
        sections = getattr(layer, "sections", [])
        bin_count = sum(len(section) for section in sections)
        section_count = len(sections) or DEFAULT_STORAGE_LAYER_SECTION_COUNT
        enabled = bool(getattr(layer, "enabled", True))

        bin_size = "medium"
        for section in sections:
            for value in section:
                if isinstance(value, str) and value:
                    bin_size = value
                    break
            if bin_size != "medium":
                break

        layer_entry: Dict[str, Any] = {
            "index": index,
            "bin_count": bin_count,
            "section_count": section_count,
            "bin_size": bin_size,
            "enabled": enabled,
        }
        # Calibration is sourced from the per-channel store (resolved via the
        # layer's servo_channel_id), not the layer's deprecated angle fields.
        servo_open, servo_closed = calibratedAnglesForLayer(layout, index - 1)
        max_per_bin = getattr(layer, "max_pieces_per_bin", None)
        max_dimension = getattr(layer, "max_dimension_mm", None)
        open_value = servo_open if isinstance(servo_open, int) else None
        closed_value = servo_closed if isinstance(servo_closed, int) else None
        layer_entry["servo_channel_id"] = channelIdForLayer(layout, index - 1)
        layer_entry["servo_open_angle"] = open_value
        layer_entry["servo_closed_angle"] = closed_value
        layer_entry["calibrated"] = open_value is not None and closed_value is not None
        layer_entry["max_pieces_per_bin"] = max_per_bin if isinstance(max_per_bin, int) and max_per_bin > 0 else None
        layer_entry["max_dimension_mm"] = (
            float(max_dimension)
            if isinstance(max_dimension, (int, float)) and not isinstance(max_dimension, bool) and max_dimension > 0
            else None
        )
        layers.append(layer_entry)

    return {
        "allowed_bin_counts": ALLOWED_STORAGE_LAYER_BIN_COUNTS,
        # Per-bin-count default oversize limit, so the UI can auto-fill the
        # field when the operator changes a layer's bin count.
        "max_dimension_defaults": {str(k): v for k, v in _LAYER_MAX_DIMENSION_DEFAULTS_MM.items()},
        "layers": layers,
    }


def _attach_live_servo_current_angles(layers: List[Dict[str, Any]]) -> None:
    """Fill in each layer's ``servo_current_angle`` from the live servo's
    internally-tracked angle (PCA path). None when there is no live hardware
    or the servo has not been moved since boot."""
    for layer in layers:
        layer.setdefault("servo_current_angle", None)
    active_irl = shared_state.getActiveIRL()
    if active_irl is None:
        return
    servos = list(getattr(active_irl, "servos", []))
    for index, layer in enumerate(layers):
        if index >= len(servos):
            continue
        angle = getattr(servos[index], "angle", None)
        layer["servo_current_angle"] = angle if isinstance(angle, int) else None


def _apply_live_storage_layer_enabled(layers: List[Dict[str, Any]]) -> bool:
    active_irl = shared_state.getActiveIRL()
    if active_irl is None:
        return False

    distribution_layout = getattr(active_irl, "distribution_layout", None)
    runtime_layers = list(getattr(distribution_layout, "layers", [])) if distribution_layout is not None else []
    if len(runtime_layers) != len(layers):
        return False

    for runtime_layer, layer in zip(runtime_layers, layers):
        setattr(runtime_layer, "enabled", bool(layer.get("enabled", True)))
        max_per_bin = layer.get("max_pieces_per_bin")
        setattr(
            runtime_layer,
            "max_pieces_per_bin",
            max_per_bin if isinstance(max_per_bin, int) and max_per_bin > 0 else None,
        )
        max_dimension = layer.get("max_dimension_mm")
        setattr(
            runtime_layer,
            "max_dimension_mm",
            float(max_dimension)
            if isinstance(max_dimension, (int, float)) and not isinstance(max_dimension, bool) and max_dimension > 0
            else None,
        )
    return True


@router.get("/api/hardware-config")
def get_hardware_config() -> Dict[str, Any]:
    config = machine_toml.read()
    layout = getBinLayout()
    storage_layers = _storage_layer_settings_from_layout(layout)
    _attach_live_servo_current_angles(storage_layers["layers"])
    return {
        "storage_layers": storage_layers,
        "servo": _servo_settings_from_config(config),
        "chute": _chute_settings_from_config(config),
        "issues": _servo_hardware_issues(),
    }


@router.post("/api/hardware-config/storage-layers")
def save_storage_layer_hardware_config(
    payload: StorageLayerSettingsPayload,
) -> Dict[str, Any]:
    layout = getBinLayout()
    current = _storage_layer_settings_from_layout(layout)
    requested_layers = list(payload.layers)
    if requested_layers:
        layer_updates = [
            {
                "bin_count": int(layer.bin_count),
                "enabled": bool(layer.enabled),
                "servo_open_angle": layer.servo_open_angle,
                "servo_closed_angle": layer.servo_closed_angle,
                "max_pieces_per_bin": layer.max_pieces_per_bin,
                "max_dimension_mm": layer.max_dimension_mm,
            }
            for layer in requested_layers
        ]
    else:
        layer_updates = [
            {
                "bin_count": int(count),
                "enabled": bool(layer.get("enabled", True)),
                "servo_open_angle": layer.get("servo_open_angle"),
                "servo_closed_angle": layer.get("servo_closed_angle"),
                "max_pieces_per_bin": layer.get("max_pieces_per_bin"),
                "max_dimension_mm": layer.get("max_dimension_mm"),
            }
            for count, layer in zip(payload.layer_bin_counts, current["layers"])
        ]

    new_layer_configs: List[LayerConfig] = []
    layout_changed = len(layer_updates) != len(current["layers"])
    enabled_changed = False
    default_section_count = int(current["layers"][0]["section_count"]) if current["layers"] else DEFAULT_STORAGE_LAYER_SECTION_COUNT
    default_bin_size = current["layers"][0]["bin_size"] if current["layers"] else "medium"

    for i, layer_update in enumerate(layer_updates):
        count = int(layer_update["bin_count"])
        enabled = bool(layer_update["enabled"])
        if count not in ALLOWED_STORAGE_LAYER_BIN_COUNTS:
            raise HTTPException(
                status_code=400,
                detail=f"Each layer bin count must be one of {ALLOWED_STORAGE_LAYER_BIN_COUNTS}.",
            )

        cur_layer = current["layers"][i] if i < len(current["layers"]) else None
        section_count = int(cur_layer["section_count"]) if cur_layer else default_section_count
        if section_count <= 0 or count % section_count != 0:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"Layer {i + 1} cannot be configured to {count} bins "
                    f"with {section_count} sections."
                ),
            )

        bins_per_section = count // section_count
        bin_size = cur_layer["bin_size"] if cur_layer else default_bin_size
        sections = [[bin_size] * bins_per_section for _ in range(section_count)]

        # Preserve existing servo calibration when the payload omits it. A bin-count
        # or enabled-flag change must NEVER null the angles — that silently wiped the
        # layer-door calibration before (only recoverable from a config backup). To
        # intentionally clear an angle, use /api/hardware-config/servo/layers/{i}/clear.
        prior_layer = layout.layers[i] if i < len(layout.layers) else None
        servo_open = layer_update.get("servo_open_angle")
        if not isinstance(servo_open, int):
            servo_open = prior_layer.servo_open_angle if prior_layer else None
        servo_closed = layer_update.get("servo_closed_angle")
        if not isinstance(servo_closed, int):
            servo_closed = prior_layer.servo_closed_angle if prior_layer else None
        max_per_bin = layer_update.get("max_pieces_per_bin")
        max_per_bin_value = max_per_bin if isinstance(max_per_bin, int) and max_per_bin > 0 else None
        max_dim = layer_update.get("max_dimension_mm")
        max_dim_value = (
            float(max_dim)
            if isinstance(max_dim, (int, float)) and not isinstance(max_dim, bool) and max_dim > 0
            else None
        )

        # Section count is preserved across this rebuild, so carry the existing
        # per-section on/off flags through rather than resetting them to all-on.
        prior_flags = layout.layers[i].section_enabled if i < len(layout.layers) else None
        prior_section_enabled = list(prior_flags) if prior_flags is not None else None

        new_layer_configs.append(LayerConfig(
            sections=sections,
            enabled=enabled,
            servo_open_angle=servo_open if isinstance(servo_open, int) else None,
            servo_closed_angle=servo_closed if isinstance(servo_closed, int) else None,
            # Carry the layer's servo channel reference through a rebuild (calibration
            # itself lives per-channel and is untouched here).
            servo_channel_id=prior_layer.servo_channel_id if prior_layer else None,
            max_pieces_per_bin=max_per_bin_value,
            max_dimension_mm=max_dim_value,
            section_enabled=prior_section_enabled,
        ))
        if cur_layer:
            layout_changed = layout_changed or count != int(cur_layer["bin_count"])
            enabled_changed = enabled_changed or enabled != bool(cur_layer.get("enabled", True))
            if max_per_bin_value != cur_layer.get("max_pieces_per_bin"):
                enabled_changed = True
            if max_dim_value != cur_layer.get("max_dimension_mm"):
                enabled_changed = True
        else:
            layout_changed = True

    if not layout_changed and not enabled_changed:
        return {
            "ok": True,
            "settings": current,
            "applied_live": False,
            "restart_required": False,
            "message": "Storage layer layout unchanged.",
        }

    try:
        saveBinLayout(BinLayoutConfig(layers=new_layer_configs))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to write bin layout: {e}")

    saved_layout = getBinLayout()
    saved_settings = _storage_layer_settings_from_layout(saved_layout)
    applied_live = False
    restart_required = layout_changed
    if enabled_changed and not layout_changed:
        applied_live = _apply_live_storage_layer_enabled(saved_settings["layers"])

    return {
        "ok": True,
        "settings": saved_settings,
        "applied_live": applied_live,
        "restart_required": restart_required,
        "message": (
            "Storage layer status saved and applied live."
            if applied_live
            else (
                "Storage layer status saved."
                if enabled_changed and not layout_changed
                else "Storage layer layout saved. Restart backend to apply layer changes."
            )
        ),
    }
