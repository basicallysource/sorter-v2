import json
from typing import Any, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

import bin_layout_store
from local_state import get_sorting_profile_sync_state

router = APIRouter()


def _norm(snapshot: Any) -> str:
    return json.dumps(snapshot, sort_keys=True, default=str)


def _is_dirty(record: dict[str, Any]) -> bool:
    return _norm(record.get("layout")) != _norm(bin_layout_store.current_layout_snapshot())


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
    sync = get_sorting_profile_sync_state() or {}
    return (sync.get("profile_id") or sync.get("local_filename"), sync.get("source"))


@router.get("/api/bin-layouts")
def list_bin_layouts(profile_id: Optional[str] = None) -> dict[str, Any]:
    records = bin_layout_store.list_bin_layouts(profile_id)
    return {"ok": True, "layouts": [_record_out(r) for r in records]}


@router.get("/api/bin-layouts/active")
def active_bin_layout() -> dict[str, Any]:
    record = bin_layout_store.get_active_bin_layout_record()
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
    record = bin_layout_store.create_bin_layout(
        name=name,
        layout=bin_layout_store.current_layout_snapshot(),
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
    record = bin_layout_store.create_bin_layout(
        name=name,
        layout=payload.layout,
        profile_id=payload.profile_id,
        profile_source=payload.profile_source,
        make_active=payload.make_active,
    )
    return {"ok": True, "layout": _record_out(record)}


@router.post("/api/bin-layouts/{layout_id}/save")
def save_bin_layout(layout_id: str) -> dict[str, Any]:
    if bin_layout_store.get_bin_layout_record(layout_id) is None:
        raise HTTPException(status_code=404, detail="Unknown bin layout.")
    record = bin_layout_store.update_bin_layout(layout_id, layout=bin_layout_store.current_layout_snapshot())
    return {"ok": True, "layout": _record_out(record)}


class RenameBinLayoutPayload(BaseModel):
    name: str


@router.post("/api/bin-layouts/{layout_id}/rename")
def rename_bin_layout(layout_id: str, payload: RenameBinLayoutPayload) -> dict[str, Any]:
    if bin_layout_store.get_bin_layout_record(layout_id) is None:
        raise HTTPException(status_code=404, detail="Unknown bin layout.")
    name = (payload.name or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="name is required.")
    record = bin_layout_store.update_bin_layout(layout_id, name=name)
    return {"ok": True, "layout": _record_out(record)}


@router.delete("/api/bin-layouts/{layout_id}")
def delete_bin_layout(layout_id: str) -> dict[str, Any]:
    record = bin_layout_store.get_bin_layout_record(layout_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Unknown bin layout.")
    if record["is_active"]:
        raise HTTPException(status_code=400, detail="Cannot delete the active bin layout.")
    bin_layout_store.delete_bin_layout(layout_id)
    return {"ok": True}


@router.post("/api/bin-layouts/{layout_id}/apply")
def apply_bin_layout(layout_id: str) -> dict[str, Any]:
    record = bin_layout_store.get_bin_layout_record(layout_id)
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
    bin_layout_store.set_bin_layout({"layers": layers})
    if snapshot.get("bin_categories") is not None:
        bin_layout_store.set_bin_categories(snapshot["bin_categories"])
    if snapshot.get("not_in_inventory_bins") is not None:
        bin_layout_store.set_not_in_inventory_bins(snapshot["not_in_inventory_bins"])
    bin_layout_store.set_active_bin_layout(layout_id)
    return {
        "ok": True,
        "restart_required": True,
        "layout": _record_out(bin_layout_store.get_bin_layout_record(layout_id), dirty=False),
        "message": f"Switched to '{record['name']}'. Restart the backend to apply.",
    }
