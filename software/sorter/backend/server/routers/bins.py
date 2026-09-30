"""Bins: the bin grid, moving to a bin, category assignments, contents, snapshots and CSV export."""

from __future__ import annotations

import copy
import csv
import io
import json
import os
import time
from collections import Counter
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel

import machine_toml
from bin_contents import (
    clear_current_session_bins,
    get_bin_snapshot,
    get_bin_snapshot_pieces,
    get_current_bin_contents_snapshot,
    get_current_bin_contents_version,
    get_current_bin_pieces,
    get_distributed_part_keys_since,
    list_bin_snapshots,
)
from bin_layout_store import (
    get_bin_categories,
    get_not_in_inventory_bins,
    set_bin_categories,
    set_not_in_inventory_bins,
)
from irl.bin_layout import (
    getBinLayout,
    saveBinLayout,
    BinLayoutConfig,
    LayerConfig,
    extractCategories,
    applyCategories,
    layoutMatchesCategories,
    mkLayoutFromConfig,
    extractNotInInventory,
    applyNotInInventory,
    notInInventoryMatchesLayout,
)
from irl.parse_user_toml import DEFAULT_CHUTE_FIRST_BIN_CENTER, DEFAULT_CHUTE_PILLAR_WIDTH_DEG
from server import shared_state
from server.routers.chute import _chute_move, _chute_settings_from_config
from server.routers.steppers import _ensure_not_homing
from sorting_profile import MISC_CATEGORY, categoryResolver
from subsystems.distribution.chute import BinAddress
from toml_config import getBinAssignmentConfig, setBinAssignmentConfig

router = APIRouter()


def _clear_runtime_bin_contents(
    *,
    scope: str,
    layer_index: int | None = None,
    section_index: int | None = None,
    bin_index: int | None = None,
) -> None:
    collector = getattr(shared_state.gc_ref, "runtime_stats", None) if shared_state.gc_ref is not None else None
    if collector is None or not hasattr(collector, "clearBinContents"):
        return
    collector.clearBinContents(
        scope=scope,
        layer_index=layer_index,
        section_index=section_index,
        bin_index=bin_index,
    )


class MoveToBinPayload(BaseModel):
    layer_index: int
    section_index: int
    bin_index: int


class MoveToSectionPayload(BaseModel):
    section_index: int


class SectionEnabledPayload(BaseModel):
    # scope "section" -> one section in one layer (needs layer_index + section_index)
    # scope "column"  -> the same section index across every layer (needs section_index)
    # scope "all"     -> every section in every layer
    scope: str
    layer_index: Optional[int] = None
    section_index: Optional[int] = None
    enabled: bool


class BinScopePayload(BaseModel):
    scope: str
    layer_index: Optional[int] = None
    section_index: Optional[int] = None
    bin_index: Optional[int] = None


class ClearBinCategoriesPayload(BinScopePayload):
    pass


class ClearBinContentsPayload(BinScopePayload):
    pass


class AssignBinCategoriesPayload(BaseModel):
    layer_index: int
    section_index: int
    bin_index: int
    category_ids: List[str] = []


class NotInInventoryModePayload(BinScopePayload):
    # scope "bin" | "layer" | "all"; enabled toggles not-in-inventory mode.
    enabled: bool = True


class AutoAssignBinsPayload(BaseModel):
    overlap: bool = False
    window_days: float = 7.0


def _apply_live_section_enabled(config: "BinLayoutConfig") -> bool:
    # Mirror the persisted per-section on/off flags into the live runtime
    # distribution layout so toggles take effect without a backend restart,
    # exactly like _apply_live_storage_layer_enabled does for whole layers.
    active_irl = shared_state.getActiveIRL()
    if active_irl is None:
        return False
    distribution_layout = getattr(active_irl, "distribution_layout", None)
    runtime_layers = list(getattr(distribution_layout, "layers", [])) if distribution_layout is not None else []
    if len(runtime_layers) != len(config.layers):
        return False
    for runtime_layer, layer_config in zip(runtime_layers, config.layers):
        flags = layer_config.section_enabled or []
        runtime_sections = list(getattr(runtime_layer, "sections", []))
        for section_idx, runtime_section in enumerate(runtime_sections):
            enabled = flags[section_idx] if section_idx < len(flags) else True
            setattr(runtime_section, "enabled", bool(enabled))
    return True


def _runtime_distribution_layout() -> Any | None:
    irl = shared_state.getActiveIRL()
    if irl is None:
        return None
    return getattr(irl, "distribution_layout", None)


def _empty_categories_from_config() -> list[list[list[list[str]]]]:
    layout_config = getBinLayout()
    return [
        [[[] for _ in section] for section in layer.sections]
        for layer in layout_config.layers
    ]


def _current_bin_categories() -> list[list[list[list[str]]]]:
    runtime_layout = _runtime_distribution_layout()
    if runtime_layout is not None:
        return extractCategories(runtime_layout)

    saved = get_bin_categories()
    if saved is not None:
        layout_config = getBinLayout()
        reference_layout = mkLayoutFromConfig(layout_config)
        if layoutMatchesCategories(reference_layout, saved):
            return saved

    return _empty_categories_from_config()


def _apply_and_persist_bin_categories(categories: list[list[list[list[str]]]]) -> None:
    runtime_layout = _runtime_distribution_layout()
    if runtime_layout is not None and layoutMatchesCategories(runtime_layout, categories):
        applyCategories(runtime_layout, categories)
        set_bin_categories(extractCategories(runtime_layout))
        return

    set_bin_categories(categories)


def _empty_not_in_inventory_from_config() -> list[list[list[bool]]]:
    layout_config = getBinLayout()
    return [
        [[False for _ in section] for section in layer.sections]
        for layer in layout_config.layers
    ]


def _current_not_in_inventory() -> list[list[list[bool]]]:
    runtime_layout = _runtime_distribution_layout()
    if runtime_layout is not None:
        return extractNotInInventory(runtime_layout)

    saved = get_not_in_inventory_bins()
    if saved is not None:
        reference_layout = mkLayoutFromConfig(getBinLayout())
        if notInInventoryMatchesLayout(reference_layout, saved):
            return saved

    return _empty_not_in_inventory_from_config()


def _apply_and_persist_not_in_inventory(flags: list[list[list[bool]]]) -> None:
    runtime_layout = _runtime_distribution_layout()
    if runtime_layout is not None and notInInventoryMatchesLayout(runtime_layout, flags):
        applyNotInInventory(runtime_layout, flags)
        set_not_in_inventory_bins(extractNotInInventory(runtime_layout))
        return

    set_not_in_inventory_bins(flags)


def set_not_in_inventory_mode(
    *, scope: str, layer_index: int | None, section_index: int | None,
    bin_index: int | None, enabled: bool,
) -> dict[str, Any]:
    flags = _current_not_in_inventory()
    if scope == "all":
        for layer in flags:
            for section in layer:
                for i in range(len(section)):
                    section[i] = enabled
    elif scope == "layer":
        if layer_index is None or layer_index < 0 or layer_index >= len(flags):
            raise HTTPException(status_code=400, detail="Invalid layer index.")
        for section in flags[layer_index]:
            for i in range(len(section)):
                section[i] = enabled
    elif scope == "bin":
        if (
            layer_index is None or section_index is None or bin_index is None
            or layer_index < 0 or layer_index >= len(flags)
            or section_index < 0 or section_index >= len(flags[layer_index])
            or bin_index < 0 or bin_index >= len(flags[layer_index][section_index])
        ):
            raise HTTPException(status_code=400, detail="Invalid bin coordinates.")
        flags[layer_index][section_index][bin_index] = enabled
    else:
        raise HTTPException(status_code=400, detail="Unsupported scope.")
    _apply_and_persist_not_in_inventory(flags)
    total = sum(1 for layer in flags for section in layer for b in section if b)
    return {"ok": True, "scope": scope, "enabled": enabled, "not_in_inventory_bin_count": total}


def auto_assign_bins(*, overlap: bool, window_days: float = 7.0) -> dict[str, Any]:
    # Rank the active profile's categories by how many recently-distributed
    # pieces hit them (re-mapped through the CURRENT profile, since the profile
    # may have changed), then fill bins biggest-first: bottom layers (the larger
    # bins) get the highest-volume categories. Not-in-inventory bins are left for
    # the parallel pool. With overlap, leftover categories share bins.
    gc = shared_state.gc_ref
    path = getattr(gc, "sorting_profile_path", None) if gc is not None else None
    if not path or not os.path.exists(path):
        raise HTTPException(status_code=400, detail="No active sorting profile to assign from.")
    with open(path) as handle:
        artifact = json.load(handle)
    resolve = categoryResolver(artifact)
    default_cat = str(artifact.get("default_category_id", MISC_CATEGORY))
    cat_meta = artifact.get("categories", {}) or {}

    keys = get_distributed_part_keys_since(time.time() - window_days * 86400.0)
    tally: Counter[str] = Counter()
    for part_id, color_id in keys:
        if not part_id:
            continue
        cat = resolve(part_id, color_id if color_id else "any_color")
        if cat and cat != MISC_CATEGORY and cat != default_cat:
            tally[cat] += 1
    ranked = [cat for cat, _ in tally.most_common()]

    flags = _current_not_in_inventory()
    current = _current_bin_categories()
    layout_config = getBinLayout()

    def _pool_targets(want_nii: bool) -> list[tuple[int, int, int]]:
        out: list[tuple[int, int, int]] = []
        for li, layer in enumerate(layout_config.layers):
            if not getattr(layer, "enabled", True):
                continue
            section_flags = layer.section_enabled or [True] * len(layer.sections)
            for si, section in enumerate(layer.sections):
                if si < len(section_flags) and not section_flags[si]:
                    continue
                for bi in range(len(section)):
                    if bool(flags[li][si][bi]) == want_nii:
                        out.append((li, si, bi))
        # Bottom layers first (they hold the larger bins), then section/bin order.
        out.sort(key=lambda t: (-t[0], t[1], t[2]))
        return out

    normal_targets = _pool_targets(False)
    nii_targets = _pool_targets(True)

    new_cats = [[[list(b) for b in sec] for sec in layer] for layer in current]
    for li, si, bi in normal_targets + nii_targets:
        new_cats[li][si][bi] = []

    def _assign_pool(targets: list[tuple[int, int, int]], pool: str) -> list[dict[str, Any]]:
        n = len(targets)
        out: list[dict[str, Any]] = []
        if n == 0 or not ranked:
            return out
        chosen = ranked if overlap else ranked[:n]
        for i, cat in enumerate(chosen):
            li, si, bi = targets[i % n]
            new_cats[li][si][bi].append(cat)
            out.append({
                "category_id": cat,
                "name": (cat_meta.get(cat) or {}).get("name", cat),
                "pieces": tally[cat],
                "bin": [li, si, bi],
                "pool": pool,
            })
        return out

    main_assignments = _assign_pool(normal_targets, "main")
    nii_assignments = _assign_pool(nii_targets, "not_in_inventory")
    _apply_and_persist_bin_categories(new_cats)
    assignments = main_assignments + nii_assignments
    return {
        "ok": True,
        "main_bins": len(normal_targets),
        "not_in_inventory_bins": len(nii_targets),
        "main_assigned": len(main_assignments),
        "not_in_inventory_assigned": len(nii_assignments),
        "categories_ranked": len(ranked),
        "total_pieces": sum(tally.values()),
        "overlap": overlap,
        "window_days": window_days,
        "assignments": assignments,
    }


def clear_bin_category_assignments(
    *,
    scope: str,
    layer_index: int | None = None,
    section_index: int | None = None,
    bin_index: int | None = None,
) -> dict[str, Any]:
    categories = _current_bin_categories()
    # Snapshot flushing records each bin's category assignment; grab it before
    # the in-place clears below wipe it.
    categories_before = copy.deepcopy(categories)

    if scope == "all":
        cleared_bins = 0
        for layer in categories:
            for section in layer:
                for category_ids in section:
                    if category_ids:
                        cleared_bins += 1
                    category_ids.clear()
        _apply_and_persist_bin_categories(categories)
        _clear_runtime_bin_contents(scope=scope)
        clear_current_session_bins(scope=scope, bin_categories=categories_before)
        return {
            "ok": True,
            "scope": scope,
            "cleared_bins": cleared_bins,
            "message": "Reset all bins and cleared their assignments.",
        }

    if layer_index is None or layer_index < 0 or layer_index >= len(categories):
        raise HTTPException(status_code=400, detail="Invalid layer index.")

    if scope == "layer":
        cleared_bins = 0
        for section in categories[layer_index]:
            for category_ids in section:
                if category_ids:
                    cleared_bins += 1
                category_ids.clear()
        _apply_and_persist_bin_categories(categories)
        _clear_runtime_bin_contents(scope=scope, layer_index=layer_index)
        clear_current_session_bins(scope=scope, layer_index=layer_index, bin_categories=categories_before)
        return {
            "ok": True,
            "scope": scope,
            "layer_index": layer_index,
            "cleared_bins": cleared_bins,
            "message": f"Reset all bins on layer {layer_index + 1} and cleared their assignments.",
        }

    if scope != "bin":
        raise HTTPException(status_code=400, detail="Unsupported clear scope.")

    if section_index is None or section_index < 0 or section_index >= len(categories[layer_index]):
        raise HTTPException(status_code=400, detail="Invalid section index.")
    if bin_index is None or bin_index < 0 or bin_index >= len(categories[layer_index][section_index]):
        raise HTTPException(status_code=400, detail="Invalid bin index.")

    had_categories = bool(categories[layer_index][section_index][bin_index])
    categories[layer_index][section_index][bin_index] = []
    _apply_and_persist_bin_categories(categories)
    _clear_runtime_bin_contents(
        scope=scope,
        layer_index=layer_index,
        section_index=section_index,
        bin_index=bin_index,
    )
    clear_current_session_bins(
        scope=scope,
        layer_index=layer_index,
        section_index=section_index,
        bin_index=bin_index,
        bin_categories=categories_before,
    )
    return {
        "ok": True,
        "scope": scope,
        "layer_index": layer_index,
        "section_index": section_index,
        "bin_index": bin_index,
        "cleared_bins": 1 if had_categories else 0,
        "message": f"Reset bin {bin_index + 1} on layer {layer_index + 1} and cleared its assignment.",
    }


def assign_bin_categories(
    *,
    layer_index: int,
    section_index: int,
    bin_index: int,
    category_ids: list[str],
) -> dict[str, Any]:
    categories = _current_bin_categories()

    if layer_index < 0 or layer_index >= len(categories):
        raise HTTPException(status_code=400, detail="Invalid layer index.")
    if section_index < 0 or section_index >= len(categories[layer_index]):
        raise HTTPException(status_code=400, detail="Invalid section index.")
    if bin_index < 0 or bin_index >= len(categories[layer_index][section_index]):
        raise HTTPException(status_code=400, detail="Invalid bin index.")

    cleaned: list[str] = []
    for category_id in category_ids:
        if not isinstance(category_id, str):
            raise HTTPException(status_code=400, detail="category_ids must be strings.")
        category_id = category_id.strip()
        if not category_id or category_id in cleaned:
            continue
        # MISC is the virtual discard passthrough, never a physical bin.
        if category_id == MISC_CATEGORY:
            raise HTTPException(
                status_code=400,
                detail="Misc is the discard passthrough and cannot be assigned to a bin.",
            )
        cleaned.append(category_id)

    # A category lives in exactly one bin. Drop these category_ids from every
    # other bin first so a manual assignment moves the category here rather than
    # leaving a stale duplicate that the positioner would match first.
    target = (layer_index, section_index, bin_index)
    for li, layer in enumerate(categories):
        for si, section in enumerate(layer):
            for bi, existing in enumerate(section):
                if (li, si, bi) == target or not existing:
                    continue
                section[bi] = [c for c in existing if c not in cleaned]

    categories[layer_index][section_index][bin_index] = cleaned
    _apply_and_persist_bin_categories(categories)
    return {
        "ok": True,
        "layer_index": layer_index,
        "section_index": section_index,
        "bin_index": bin_index,
        "category_ids": cleaned,
        "message": (
            f"Assigned {len(cleaned)} categor{'y' if len(cleaned) == 1 else 'ies'} "
            f"to bin {bin_index + 1} on layer {layer_index + 1}."
        ),
    }


def clear_bin_contents(
    *,
    scope: str,
    layer_index: int | None = None,
    section_index: int | None = None,
    bin_index: int | None = None,
) -> dict[str, Any]:
    if scope == "all":
        _clear_runtime_bin_contents(scope=scope)
        cleared = clear_current_session_bins(scope=scope, bin_categories=_current_bin_categories())
        return {
            "ok": True,
            "scope": scope,
            "cleared_bins": int(cleared.get("cleared_bins", 0)),
            "snapshot_id": cleared.get("snapshot_id"),
            "message": "Emptied all bins without changing their assignments.",
        }

    categories = _current_bin_categories()
    if layer_index is None or layer_index < 0 or layer_index >= len(categories):
        raise HTTPException(status_code=400, detail="Invalid layer index.")

    if scope == "layer":
        _clear_runtime_bin_contents(scope=scope, layer_index=layer_index)
        cleared = clear_current_session_bins(scope=scope, layer_index=layer_index, bin_categories=categories)
        return {
            "ok": True,
            "scope": scope,
            "layer_index": layer_index,
            "cleared_bins": int(cleared.get("cleared_bins", 0)),
            "message": f"Emptied all bins on layer {layer_index + 1} without changing assignments.",
        }

    if scope != "bin":
        raise HTTPException(status_code=400, detail="Unsupported clear scope.")

    if section_index is None or section_index < 0 or section_index >= len(categories[layer_index]):
        raise HTTPException(status_code=400, detail="Invalid section index.")
    if bin_index is None or bin_index < 0 or bin_index >= len(categories[layer_index][section_index]):
        raise HTTPException(status_code=400, detail="Invalid bin index.")

    cleared = clear_current_session_bins(
        scope=scope,
        layer_index=layer_index,
        section_index=section_index,
        bin_index=bin_index,
        bin_categories=categories,
    )
    _clear_runtime_bin_contents(
        scope=scope,
        layer_index=layer_index,
        section_index=section_index,
        bin_index=bin_index,
    )
    return {
        "ok": True,
        "scope": scope,
        "layer_index": layer_index,
        "section_index": section_index,
        "bin_index": bin_index,
        "cleared_bins": int(cleared.get("cleared_bins", 0)),
        "message": f"Emptied bin {bin_index + 1} on layer {layer_index + 1} without changing its assignment.",
    }


@router.get("/api/bins/layout")
def get_bins_layout() -> Dict[str, Any]:
    """Return the full bin grid: layers → sections → bins, with chute angles."""
    layout_config = getBinLayout()
    config = machine_toml.read()
    chute_cfg = _chute_settings_from_config(config)
    first_bin_center = float(chute_cfg.get("first_bin_center", DEFAULT_CHUTE_FIRST_BIN_CENTER))
    pillar_width_deg = float(chute_cfg.get("pillar_width_deg", DEFAULT_CHUTE_PILLAR_WIDTH_DEG))
    usable_per_section = 60.0 - pillar_width_deg

    layers_out = []
    for layer_idx, layer in enumerate(layout_config.layers):
        sections = layer.sections
        bins_flat = []
        global_bin = 0
        for section_idx, section_bins in enumerate(sections):
            num_bins = len(section_bins)
            bin_width = usable_per_section / num_bins if num_bins else 0
            for bin_idx, bin_size in enumerate(section_bins):
                angle = first_bin_center + section_idx * 60 + bin_idx * bin_width
                bins_flat.append({
                    "section_index": section_idx,
                    "bin_index": bin_idx,
                    "global_index": global_bin,
                    "size": bin_size,
                    "angle": round(angle, 2),
                })
                global_bin += 1
        max_per_bin = getattr(layer, "max_pieces_per_bin", None)
        max_dimension = getattr(layer, "max_dimension_mm", None)
        section_enabled = list(getattr(layer, "section_enabled", None) or [True] * len(sections))
        if len(section_enabled) < len(sections):
            section_enabled += [True] * (len(sections) - len(section_enabled))
        layers_out.append({
            "layer_index": layer_idx,
            "enabled": layer.enabled,
            "section_count": len(sections),
            "section_enabled": section_enabled,
            "bin_count": global_bin,
            "max_pieces_per_bin": max_per_bin if isinstance(max_per_bin, int) and max_per_bin > 0 else None,
            "max_dimension_mm": (
                float(max_dimension)
                if isinstance(max_dimension, (int, float)) and not isinstance(max_dimension, bool) and max_dimension > 0
                else None
            ),
            "bins": bins_flat,
        })

    # Overlay category assignments from live layout if available
    current_angle = None
    active_layer = None
    runtime_overlay_applied = False
    if shared_state.controller_ref is not None and hasattr(shared_state.controller_ref, "irl"):
        chute = getattr(shared_state.controller_ref.irl, "chute", None)
        if chute is not None:
            try:
                current_angle = round(float(chute.current_angle), 2)
            except Exception:
                pass
        servos = list(getattr(shared_state.controller_ref.irl, "servos", []))
        for i, servo in enumerate(servos):
            try:
                if hasattr(servo, "isOpen") and servo.isOpen():
                    active_layer = i
                    break
            except Exception:
                pass

        # Read category assignments from the live distribution layout
        dist_layout = getattr(shared_state.controller_ref.irl, "distribution_layout", None)
        if dist_layout is not None:
            runtime_layers = list(getattr(dist_layout, "layers", []))
            for layer_out in layers_out:
                li = layer_out["layer_index"]
                if li < len(runtime_layers):
                    runtime_overlay_applied = True
                    rt_layer = runtime_layers[li]
                    rt_sections = list(rt_layer.sections)
                    for bin_out in layer_out["bins"]:
                        si = bin_out["section_index"]
                        bi = bin_out["bin_index"]
                        if si < len(rt_sections) and bi < len(rt_sections[si].bins):
                            bin_out["category_ids"] = list(rt_sections[si].bins[bi].category_ids)

    if not runtime_overlay_applied:
        saved_categories = get_bin_categories()
        reference_layout = mkLayoutFromConfig(layout_config)
        if saved_categories is not None and layoutMatchesCategories(reference_layout, saved_categories):
            for layer_out in layers_out:
                li = layer_out["layer_index"]
                for bin_out in layer_out["bins"]:
                    si = bin_out["section_index"]
                    bi = bin_out["bin_index"]
                    bin_out["category_ids"] = list(saved_categories[li][si][bi])

    # Ensure every bin has category_ids even if live layout wasn't available
    for layer_out in layers_out:
        for bin_out in layer_out["bins"]:
            bin_out.setdefault("category_ids", [])

    # Overlay not-in-inventory mode flags (parallel bin pool).
    nii_flags = _current_not_in_inventory()
    for layer_out in layers_out:
        li = layer_out["layer_index"]
        for bin_out in layer_out["bins"]:
            si = bin_out["section_index"]
            bi = bin_out["bin_index"]
            try:
                bin_out["not_in_inventory"] = bool(nii_flags[li][si][bi])
            except (IndexError, TypeError):
                bin_out["not_in_inventory"] = False

    return {
        "ok": True,
        "layers": layers_out,
        "current_angle": current_angle,
        "active_layer": active_layer,
    }


@router.get("/api/bins/settings")
def get_bins_settings() -> Dict[str, Any]:
    return {"ok": True, **getBinAssignmentConfig()}


@router.post("/api/bins/settings")
def set_bins_settings(payload: Dict[str, Any]) -> Dict[str, Any]:
    merged = setBinAssignmentConfig(payload or {})
    return {"ok": True, **merged}


@router.post("/api/bins/move-to")
def move_to_bin(payload: MoveToBinPayload) -> Dict[str, Any]:
    """Move chute to a specific bin and open the correct layer servo."""
    if shared_state.controller_ref is None or not hasattr(shared_state.controller_ref, "irl"):
        raise HTTPException(status_code=503, detail="Hardware controller not initialized.")

    irl = shared_state.controller_ref.irl
    chute = getattr(irl, "chute", None)
    if chute is None:
        raise HTTPException(status_code=503, detail="Chute subsystem not available.")

    servos = list(getattr(irl, "servos", []))
    if payload.layer_index < 0 or payload.layer_index >= len(servos):
        raise HTTPException(status_code=400, detail=f"Invalid layer index {payload.layer_index}.")

    address = BinAddress(
        layer_index=payload.layer_index,
        section_index=payload.section_index,
        bin_index=payload.bin_index,
    )

    target_angle = chute.getAngleForBin(address)
    if target_angle is None:
        raise HTTPException(status_code=400, detail="Bin is unreachable (angle out of range).")

    # Close all servos first, then open the target layer
    for i, servo in enumerate(servos):
        try:
            if hasattr(servo, "isOpen") and servo.isOpen():
                servo.close()
        except Exception:
            pass

    estimated_ms = _chute_move(chute.moveToBin, address)

    # Open the target layer servo
    target_servo = servos[payload.layer_index]
    try:
        if hasattr(target_servo, "open"):
            target_servo.open()
    except Exception:
        pass

    return {
        "ok": True,
        "target_angle": round(target_angle, 2),
        "estimated_ms": estimated_ms,
        "layer_index": payload.layer_index,
        "section_index": payload.section_index,
        "bin_index": payload.bin_index,
    }


@router.post("/api/bins/move-to-section")
def move_to_section(payload: MoveToSectionPayload) -> Dict[str, Any]:
    """Point the chute at the center of a section without opening any servo."""
    _ensure_not_homing("point at a section")
    if shared_state.controller_ref is None or not hasattr(shared_state.controller_ref, "irl"):
        raise HTTPException(status_code=503, detail="Hardware controller not initialized.")
    chute = getattr(shared_state.controller_ref.irl, "chute", None)
    if chute is None:
        raise HTTPException(status_code=503, detail="Chute subsystem not available.")
    if payload.section_index < 0:
        raise HTTPException(status_code=400, detail="section_index must be >= 0.")

    # bins_in_section=1, bin_index=0 -> the midpoint of the section's usable arc.
    target_angle = chute.angleForVirtualBin(payload.section_index, 0, 1)
    if target_angle is None:
        raise HTTPException(status_code=400, detail="Section is unreachable (angle out of range).")

    estimated_ms = _chute_move(chute.moveToAngle, target_angle)

    return {
        "ok": True,
        "target_angle": round(target_angle, 2),
        "estimated_ms": estimated_ms,
        "section_index": payload.section_index,
    }


@router.post("/api/bins/sections/enabled")
def set_section_enabled(payload: SectionEnabledPayload) -> Dict[str, Any]:
    """Enable/disable sections: a single section, a whole column (same section
    index across every layer), or every section on the machine."""
    if payload.scope not in {"section", "column", "all"}:
        raise HTTPException(status_code=400, detail="scope must be 'section', 'column' or 'all'.")

    layout = getBinLayout()
    enabled = bool(payload.enabled)
    changed = 0

    def _set_layer_section(layer: LayerConfig, section_index: int) -> None:
        nonlocal changed
        flags = list(layer.section_enabled or [True] * len(layer.sections))
        if 0 <= section_index < len(flags) and flags[section_index] != enabled:
            flags[section_index] = enabled
            layer.section_enabled = flags
            changed += 1

    if payload.scope == "section":
        if payload.layer_index is None or payload.section_index is None:
            raise HTTPException(status_code=400, detail="section scope needs layer_index and section_index.")
        if payload.layer_index < 0 or payload.layer_index >= len(layout.layers):
            raise HTTPException(status_code=404, detail=f"Unknown layer {payload.layer_index}.")
        _set_layer_section(layout.layers[payload.layer_index], payload.section_index)
    elif payload.scope == "column":
        if payload.section_index is None:
            raise HTTPException(status_code=400, detail="column scope needs section_index.")
        for layer in layout.layers:
            _set_layer_section(layer, payload.section_index)
    else:  # all
        for layer in layout.layers:
            for section_index in range(len(layer.sections)):
                _set_layer_section(layer, section_index)

    if changed:
        try:
            saveBinLayout(layout)
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Failed to persist section state: {e}")

    applied_live = _apply_live_section_enabled(layout)
    return {
        "ok": True,
        "scope": payload.scope,
        "enabled": enabled,
        "changed": changed,
        "applied_live": applied_live,
        "layout": get_bins_layout(),
    }


@router.post("/api/bins/categories/clear")
def clear_bins_categories(payload: ClearBinCategoriesPayload) -> Dict[str, Any]:
    return clear_bin_category_assignments(
        scope=payload.scope,
        layer_index=payload.layer_index,
        section_index=payload.section_index,
        bin_index=payload.bin_index,
    )


@router.post("/api/bins/categories/assign")
def assign_bins_categories(payload: AssignBinCategoriesPayload) -> Dict[str, Any]:
    return assign_bin_categories(
        layer_index=payload.layer_index,
        section_index=payload.section_index,
        bin_index=payload.bin_index,
        category_ids=payload.category_ids,
    )


@router.post("/api/bins/auto-assign")
def auto_assign_bins_route(payload: AutoAssignBinsPayload) -> Dict[str, Any]:
    return auto_assign_bins(overlap=payload.overlap, window_days=payload.window_days)


@router.post("/api/bins/not-in-inventory/set")
def set_bins_not_in_inventory(payload: NotInInventoryModePayload) -> Dict[str, Any]:
    return set_not_in_inventory_mode(
        scope=payload.scope,
        layer_index=payload.layer_index,
        section_index=payload.section_index,
        bin_index=payload.bin_index,
        enabled=payload.enabled,
    )


@router.post("/api/bins/contents/clear")
def clear_bins_contents(payload: ClearBinContentsPayload) -> Dict[str, Any]:
    return clear_bin_contents(
        scope=payload.scope,
        layer_index=payload.layer_index,
        section_index=payload.section_index,
        bin_index=payload.bin_index,
    )


@router.post("/api/bins/reset/layer/{layer_index}")
def reset_bins_layer(layer_index: int) -> Dict[str, Any]:
    # Full reset of one layer: drop its category assignments and empty its bins
    # in a single server-side call, then hand back the fresh layout + contents so
    # the UI can update without slow follow-up round-trips.
    result = clear_bin_category_assignments(scope="layer", layer_index=layer_index)
    result["layout"] = get_bins_layout()
    result["bins"] = get_bin_contents().get("bins", [])
    return result


@router.post("/api/bins/reset/machine")
def reset_bins_machine() -> Dict[str, Any]:
    # Full machine reset: drop every assignment and empty every bin in one call,
    # returning the fresh layout + (now empty) contents.
    result = clear_bin_category_assignments(scope="all")
    result["layout"] = get_bins_layout()
    result["bins"] = get_bin_contents().get("bins", [])
    return result


_PIECE_CSV_COLUMNS = [
    "bl_part_id",
    "bl_color_id",
    "color_name",
    "category_id_in_profile",
    "profile_id",
    "profile_name",
    "classification_status",
    "created_at",
    "classified_at",
    "distributed_at",
    "layer_index",
    "section_index",
    "bin_index",
    "bin_epoch",
    "piece_uuid",
    "brickognize_preview_url",
]


def _pieces_to_csv(pieces: list[dict[str, Any]], *, extra_columns: dict[str, Any] | None = None) -> str:
    buffer = io.StringIO()
    columns = _PIECE_CSV_COLUMNS + list(extra_columns.keys() if extra_columns else [])
    writer = csv.DictWriter(buffer, fieldnames=columns, extrasaction="ignore")
    writer.writeheader()
    for piece in pieces:
        row = {
            "bl_part_id": piece.get("part_id"),
            "bl_color_id": piece.get("color_id"),
            "color_name": piece.get("color_name"),
            "category_id_in_profile": piece.get("category_id"),
            "profile_id": piece.get("profile_id"),
            "profile_name": piece.get("profile_name"),
            "classification_status": piece.get("classification_status"),
            "created_at": piece.get("created_at"),
            "classified_at": piece.get("classified_at"),
            "distributed_at": piece.get("distributed_at"),
            "layer_index": piece.get("layer_index"),
            "section_index": piece.get("section_index"),
            "bin_index": piece.get("bin_index"),
            "bin_epoch": piece.get("bin_epoch"),
            "piece_uuid": piece.get("piece_uuid"),
            "brickognize_preview_url": piece.get("brickognize_preview_url"),
        }
        if extra_columns:
            row.update(extra_columns)
        writer.writerow(row)
    return buffer.getvalue()


def _csv_response(content: str, filename: str) -> Response:
    return Response(
        content=content,
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/api/bins/snapshots")
def get_bin_snapshots() -> Dict[str, Any]:
    return {"snapshots": list_bin_snapshots()}


@router.get("/api/bins/snapshots/{snapshot_id}")
def get_bin_snapshot_detail(snapshot_id: str, include_images: bool = False) -> Dict[str, Any]:
    snapshot = get_bin_snapshot(snapshot_id)
    if snapshot is None:
        raise HTTPException(status_code=404, detail="Unknown snapshot.")
    if not include_images:
        for layer in snapshot.get("layers", []):
            for item in layer.get("items", []):
                for field in _BIN_ITEM_IMAGE_FIELDS:
                    item.pop(field, None)
    return snapshot


@router.get("/api/bins/snapshots/{snapshot_id}/export.csv")
def export_bin_snapshot_csv(snapshot_id: str) -> Response:
    pieces = get_bin_snapshot_pieces(snapshot_id)
    if pieces is None:
        raise HTTPException(status_code=404, detail="Unknown snapshot.")
    content = _pieces_to_csv(pieces, extra_columns={"snapshot_id": snapshot_id})
    return _csv_response(content, f"bin-snapshot-{snapshot_id[:8]}.csv")


@router.get("/api/bins/contents/version")
def get_bin_contents_version() -> Dict[str, Any]:
    # Cheap change token so the UI can poll frequently without pulling the full
    # contents payload each tick; fetch /api/bins/contents only when this changes.
    return {"version": get_current_bin_contents_version()}


@router.get("/api/bins/contents/export.csv")
def export_current_bin_contents_csv() -> Response:
    content = _pieces_to_csv(get_current_bin_pieces())
    return _csv_response(content, "bin-contents-current.csv")


_BIN_ITEM_IMAGE_FIELDS = ("thumbnail", "top_image", "bottom_image")


def _strip_bin_content_images(payload: dict[str, Any]) -> dict[str, Any]:
    # Inline base64 images blow the polled contents payload up to ~8MB, which
    # saturated a deployed machine's uplink. brickognize_preview_url (a plain
    # URL) stays; callers that truly need pixels pass include_images=true.
    bins = payload.get("bins")
    if not isinstance(bins, list):
        return payload
    for bin_entry in bins:
        if not isinstance(bin_entry, dict):
            continue
        for list_key in ("items", "recent_pieces"):
            entries = bin_entry.get(list_key)
            if not isinstance(entries, list):
                continue
            for entry in entries:
                if isinstance(entry, dict):
                    for field in _BIN_ITEM_IMAGE_FIELDS:
                        entry.pop(field, None)
    return payload


@router.get("/api/bins/contents")
def get_bin_contents(include_images: bool = False) -> Dict[str, Any]:
    persisted = get_current_bin_contents_snapshot()
    result: Dict[str, Any] | None = None
    if persisted.get("bins"):
        result = persisted
    else:
        collector = getattr(shared_state.gc_ref, "runtime_stats", None) if shared_state.gc_ref is not None else None
        if collector is None or not hasattr(collector, "binContentsSnapshot"):
            result = persisted
        else:
            try:
                snapshot = collector.binContentsSnapshot()
                result = snapshot if isinstance(snapshot, dict) else persisted
            except Exception as exc:
                raise HTTPException(status_code=500, detail=f"Failed to build bin contents: {exc}")
    return result if include_images else _strip_bin_content_images(result)
