import json
from typing import Any, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

import local_state as ls

router = APIRouter()


# A saved bin layout is a snapshot of the live state keys (geometry + enabled +
# layer->channel ref + bin categories + not-in-inventory flags) — NO servo angles
# (those are per-channel/machine-level). Built from RAW local_state so it matches
# the migration-seeded record exactly (else the active record reads as dirty).
def _snapshot_from_state() -> dict[str, Any]:
    bin_layout = ls.get_bin_layout() or {}
    layers = []
    for layer in bin_layout.get("layers", []):
        if not isinstance(layer, dict):
            continue
        layers.append({
            "sections": layer.get("sections"),
            "enabled": layer.get("enabled", True),
            "servo_channel_id": layer.get("servo_channel_id"),
            "max_pieces_per_bin": layer.get("max_pieces_per_bin"),
            "max_dimension_mm": layer.get("max_dimension_mm"),
            "section_enabled": layer.get("section_enabled"),
        })
    return {
        "layers": layers,
        "bin_categories": ls.get_bin_categories(),
        "not_in_inventory_bins": ls.get_not_in_inventory_bins(),
    }


def _norm(snapshot: Any) -> str:
    return json.dumps(snapshot, sort_keys=True, default=str)


def _is_dirty(record: dict[str, Any]) -> bool:
    return _norm(record.get("layout")) != _norm(_snapshot_from_state())


def _record_out(record: dict[str, Any], dirty: Optional[bool] = None) -> dict[str, Any]:
    if dirty is None:
        dirty = _is_dirty(record) if record.get("is_active") else False
    return {
        "id": record["id"],
        "name": record["name"],
        "profile_id": record["profile_id"],
        "profile_source": record["profile_source"],
        "created_at": record["created_at"],
        "updated_at": record["updated_at"],
        "is_active": bool(record["is_active"]),
        "dirty": dirty,
    }


def _current_profile() -> tuple[Optional[str], Optional[str]]:
    sync = ls.get_sorting_profile_sync_state() or {}
    return (sync.get("profile_id") or sync.get("local_filename"), sync.get("source"))


@router.get("/api/bin-layouts")
def list_bin_layouts(profile_id: Optional[str] = None) -> dict[str, Any]:
    records = ls.list_bin_layouts(profile_id)
    return {"ok": True, "layouts": [_record_out(r) for r in records]}


@router.get("/api/bin-layouts/active")
def active_bin_layout() -> dict[str, Any]:
    record = ls.get_active_bin_layout_record()
    if record is None:
        return {"ok": True, "active": None}
    return {"ok": True, "active": _record_out(record, dirty=_is_dirty(record))}


class CreateBinLayoutPayload(BaseModel):
    name: str
    profile_id: Optional[str] = None
    profile_source: Optional[str] = None
    make_active: bool = True


@router.post("/api/bin-layouts")
def create_bin_layout(payload: CreateBinLayoutPayload) -> dict[str, Any]:
    name = (payload.name or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="name is required.")
    profile_id, profile_source = payload.profile_id, payload.profile_source
    if profile_id is None:
        profile_id, profile_source = _current_profile()
    record = ls.create_bin_layout(
        name=name,
        layout=_snapshot_from_state(),
        profile_id=profile_id,
        profile_source=profile_source,
        make_active=payload.make_active,
    )
    return {"ok": True, "layout": _record_out(record)}


class ImportBinLayoutPayload(BaseModel):
    name: str
    layout: dict[str, Any]
    profile_id: Optional[str] = None
    profile_source: Optional[str] = None
    make_active: bool = False


@router.post("/api/bin-layouts/import")
def import_bin_layout(payload: ImportBinLayoutPayload) -> dict[str, Any]:
    name = (payload.name or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="name is required.")
    if not isinstance(payload.layout, dict) or not isinstance(payload.layout.get("layers"), list):
        raise HTTPException(status_code=400, detail="layout must contain a layers list.")
    record = ls.create_bin_layout(
        name=name,
        layout=payload.layout,
        profile_id=payload.profile_id,
        profile_source=payload.profile_source,
        make_active=payload.make_active,
    )
    return {"ok": True, "layout": _record_out(record)}


@router.post("/api/bin-layouts/{layout_id}/save")
def save_bin_layout(layout_id: str) -> dict[str, Any]:
    if ls.get_bin_layout_record(layout_id) is None:
        raise HTTPException(status_code=404, detail="Unknown bin layout.")
    record = ls.update_bin_layout(layout_id, layout=_snapshot_from_state())
    return {"ok": True, "layout": _record_out(record)}


class RenameBinLayoutPayload(BaseModel):
    name: str


@router.post("/api/bin-layouts/{layout_id}/rename")
def rename_bin_layout(layout_id: str, payload: RenameBinLayoutPayload) -> dict[str, Any]:
    if ls.get_bin_layout_record(layout_id) is None:
        raise HTTPException(status_code=404, detail="Unknown bin layout.")
    name = (payload.name or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="name is required.")
    record = ls.update_bin_layout(layout_id, name=name)
    return {"ok": True, "layout": _record_out(record)}


@router.delete("/api/bin-layouts/{layout_id}")
def delete_bin_layout(layout_id: str) -> dict[str, Any]:
    record = ls.get_bin_layout_record(layout_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Unknown bin layout.")
    if record["is_active"]:
        raise HTTPException(status_code=400, detail="Cannot delete the active bin layout.")
    ls.delete_bin_layout(layout_id)
    return {"ok": True}


@router.post("/api/bin-layouts/{layout_id}/apply")
def apply_bin_layout(layout_id: str) -> dict[str, Any]:
    record = ls.get_bin_layout_record(layout_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Unknown bin layout.")
    snapshot = record.get("layout") or {}
    layers = snapshot.get("layers")
    if not isinstance(layers, list) or not layers:
        raise HTTPException(status_code=400, detail="This bin layout has no layers.")
    # Persist the snapshot to the live state keys, then mark it active. Geometry and
    # assignments take full effect on the next backend restart (boot rebuilds the
    # runtime layout and re-applies the saved categories/NII). Servo calibration is
    # per-channel and untouched.
    ls.set_bin_layout({"layers": layers})
    if snapshot.get("bin_categories") is not None:
        ls.set_bin_categories(snapshot["bin_categories"])
    if snapshot.get("not_in_inventory_bins") is not None:
        ls.set_not_in_inventory_bins(snapshot["not_in_inventory_bins"])
    ls.set_active_bin_layout(layout_id)
    return {
        "ok": True,
        "restart_required": True,
        "layout": _record_out(ls.get_bin_layout_record(layout_id), dirty=False),
        "message": f"Switched to '{record['name']}'. Restart the backend to apply.",
    }
