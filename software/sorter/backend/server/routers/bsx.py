"""Local machine endpoints for BrickStore (.bsx) inventory files.

A .bsx is a real BrickLink store's on-hand inventory export. One can be active at
a time; a sorting profile with an inventory_routing block routes pieces NOT in the
active inventory to a chosen bin. See bsx_inventory.py for the storage/lookup.
"""

from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, HTTPException, Request

import bsx_inventory
from server import shared_state

router = APIRouter()


def _gc():
    gc = shared_state.gc_ref
    if gc is None:
        raise HTTPException(status_code=503, detail="Backend not ready.")
    return gc


@router.get("/api/bsx")
def list_bsx() -> dict[str, Any]:
    gc = _gc()
    return {
        "files": bsx_inventory.listBsxFiles(gc),
        "active_filename": bsx_inventory.getActiveBsxFilename(gc),
    }


# Raw-body upload (not multipart): the .bsx XML is POSTed as the request body with
# the display name in the ?name= query param. Avoids a python-multipart dependency.
@router.post("/api/bsx/upload")
async def upload_bsx(request: Request, name: Optional[str] = None) -> dict[str, Any]:
    gc = _gc()
    content = await request.body()
    if not content:
        raise HTTPException(status_code=400, detail="Empty file.")
    display_name = (name or "").strip() or "inventory"
    try:
        entry = bsx_inventory.saveBsxUpload(gc, display_name=display_name, content=content)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Could not parse .bsx: {exc}")
    return entry


@router.post("/api/bsx/activate")
def activate_bsx(payload: dict[str, Any]) -> dict[str, Any]:
    gc = _gc()
    filename = payload.get("filename")
    if not isinstance(filename, str) or not filename:
        raise HTTPException(status_code=400, detail="filename is required.")
    try:
        bsx_inventory.setActiveBsx(gc, filename)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Inventory file not found.")
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {
        "active_filename": bsx_inventory.getActiveBsxFilename(gc),
        "files": bsx_inventory.listBsxFiles(gc),
    }


@router.post("/api/bsx/deactivate")
def deactivate_bsx() -> dict[str, Any]:
    gc = _gc()
    bsx_inventory.setActiveBsx(gc, None)
    return {
        "active_filename": bsx_inventory.getActiveBsxFilename(gc),
        "files": bsx_inventory.listBsxFiles(gc),
    }


@router.delete("/api/bsx/{filename}")
def delete_bsx(filename: str) -> dict[str, Any]:
    gc = _gc()
    try:
        bsx_inventory.deleteBsx(gc, filename)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {
        "active_filename": bsx_inventory.getActiveBsxFilename(gc),
        "files": bsx_inventory.listBsxFiles(gc),
    }
