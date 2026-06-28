from __future__ import annotations

import json
import os
import re
import threading
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from global_config import GlobalConfig

# BrickStore/BrickStock inventory (.bsx) support. A .bsx is the XML export of a
# real BrickLink store's on-hand inventory. Each <Item> carries a BrickLink
# ItemID + ColorID + on-hand Qty. We use it as the *inverse* of a parts list:
# a classified piece (which Brickognize reports in the SAME BrickLink id space —
# see piece_metadata_db) is "not in inventory" when its (item_id, color_id) is
# absent from the active .bsx. The lookup is a live, in-memory set membership
# test; swapping the active .bsx changes routing with no profile recompile.
#
# Files live next to local_state.sqlite under bsx_files/: the raw "{slug}.bsx"
# plus a "{slug}.bsx.meta.json" sidecar with cheap-to-list metadata (so listing
# never reparses the multi-MB XML). The active selection is a single pointer
# file "active_bsx.json" in that dir — same self-contained pattern as the active
# sorting profile.

_ACTIVE_POINTER_NAME = "active_bsx.json"

_active: Optional["BsxInventory"] = None
_active_loaded = False
_lock = threading.Lock()


class BsxInventory:
    def __init__(
        self,
        *,
        filename: str,
        name: str,
        pairs: set[tuple[str, str]],
        item_ids: set[str],
        meta: dict[str, Any],
    ):
        self.filename = filename
        self.name = name
        self._pairs = pairs
        self._item_ids = item_ids
        self.meta = meta

    def isInInventory(self, part_id: Optional[str], color_id: Optional[str]) -> Optional[bool]:
        # None = undecidable (no part id); True/False = a real membership answer.
        # Exact (part, color) membership is the restock-precise semantics: a store
        # that stocks 3001 in black but not red genuinely lacks red 3001. When the
        # piece color is unknown ("any_color"), fall back to part-only membership.
        if not part_id:
            return None
        cid = str(color_id).strip() if color_id not in (None, "") else "any_color"
        if cid == "any_color":
            return part_id in self._item_ids
        return (part_id, cid) in self._pairs


def _bsxDir(gc: GlobalConfig) -> Path:
    directory = Path(getattr(gc, "bsx_files_dir", None) or (Path(__file__).resolve().parent / "bsx_files"))
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def slugifyBsxName(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", (value or "").lower()).strip("-")
    return slug or "inventory"


def _safeBsxPath(gc: GlobalConfig, filename: str) -> Path:
    name = os.path.basename((filename or "").strip())
    if not name or name.startswith(".") or not name.endswith(".bsx"):
        raise ValueError("invalid bsx filename")
    directory = _bsxDir(gc)
    resolved = (directory / name).resolve()
    if resolved.parent != directory.resolve():
        raise ValueError("invalid bsx filename")
    return resolved


def _uniqueBsxPath(gc: GlobalConfig, display_name: str) -> Path:
    directory = _bsxDir(gc)
    stem = slugifyBsxName(display_name)
    candidate = directory / f"{stem}.bsx"
    counter = 2
    while candidate.exists():
        candidate = directory / f"{stem}-{counter}.bsx"
        counter += 1
    return candidate


def _parseBsx(content: bytes) -> tuple[set[tuple[str, str]], set[str], dict[str, Any]]:
    root = ET.fromstring(content)
    pairs: set[tuple[str, str]] = set()
    item_ids: set[str] = set()
    type_counts: dict[str, int] = {}
    n_lots = 0
    for item in root.iter("Item"):
        item_id = (item.findtext("ItemID") or "").strip()
        if not item_id:
            continue
        color_id = (item.findtext("ColorID") or "").strip() or "0"
        item_type = (item.findtext("ItemTypeID") or "?").strip() or "?"
        n_lots += 1
        type_counts[item_type] = type_counts.get(item_type, 0) + 1
        item_ids.add(item_id)
        pairs.add((item_id, color_id))
    meta = {
        "num_lots": n_lots,
        "num_unique_items": len(item_ids),
        "num_unique_pairs": len(pairs),
        "num_parts": type_counts.get("P", 0),
        "item_type_counts": type_counts,
    }
    return pairs, item_ids, meta


def _metaSidecarPath(bsx_path: Path) -> Path:
    return bsx_path.with_suffix(".bsx.meta.json")


def saveBsxUpload(gc: GlobalConfig, *, display_name: str, content: bytes) -> dict[str, Any]:
    # Validate by parsing before anything touches disk: a bad upload should fail
    # loudly here, not silently install an unusable inventory.
    _, _, parsed_meta = _parseBsx(content)
    path = _uniqueBsxPath(gc, display_name)
    path.write_bytes(content)
    meta = {
        "filename": path.name,
        "name": display_name.strip() or path.stem,
        "uploaded_at": datetime.now(timezone.utc).isoformat(),
        **parsed_meta,
    }
    _metaSidecarPath(path).write_text(json.dumps(meta, indent=2))
    return _entryFor(gc, path)


def _entryFor(gc: GlobalConfig, path: Path) -> dict[str, Any]:
    active_filename = getActiveBsxFilename(gc)
    entry: dict[str, Any] = {
        "filename": path.name,
        "name": path.stem,
        "uploaded_at": None,
        "num_lots": None,
        "num_parts": None,
        "num_unique_items": None,
        "item_type_counts": None,
        "is_active": path.name == active_filename,
        "error": None,
    }
    sidecar = _metaSidecarPath(path)
    if sidecar.exists():
        try:
            meta = json.loads(sidecar.read_text())
            entry.update(
                {
                    "name": meta.get("name") or path.stem,
                    "uploaded_at": meta.get("uploaded_at"),
                    "num_lots": meta.get("num_lots"),
                    "num_parts": meta.get("num_parts"),
                    "num_unique_items": meta.get("num_unique_items"),
                    "item_type_counts": meta.get("item_type_counts"),
                }
            )
        except Exception as exc:
            entry["error"] = str(exc)
    if entry["uploaded_at"] is None:
        try:
            entry["uploaded_at"] = datetime.fromtimestamp(
                path.stat().st_mtime, tz=timezone.utc
            ).isoformat()
        except OSError:
            pass
    return entry


def listBsxFiles(gc: GlobalConfig) -> list[dict[str, Any]]:
    return [_entryFor(gc, path) for path in sorted(_bsxDir(gc).glob("*.bsx"))]


def deleteBsx(gc: GlobalConfig, filename: str) -> None:
    path = _safeBsxPath(gc, filename)
    if getActiveBsxFilename(gc) == path.name:
        setActiveBsx(gc, None)
    for target in (path, _metaSidecarPath(path)):
        try:
            target.unlink()
        except FileNotFoundError:
            pass


def _activePointerPath(gc: GlobalConfig) -> Path:
    return _bsxDir(gc) / _ACTIVE_POINTER_NAME


def getActiveBsxFilename(gc: GlobalConfig) -> Optional[str]:
    pointer = _activePointerPath(gc)
    if not pointer.exists():
        return None
    try:
        data = json.loads(pointer.read_text())
    except Exception:
        return None
    name = data.get("filename") if isinstance(data, dict) else None
    return name if isinstance(name, str) and name else None


def setActiveBsx(gc: GlobalConfig, filename: Optional[str]) -> None:
    pointer = _activePointerPath(gc)
    if filename is None:
        try:
            pointer.unlink()
        except FileNotFoundError:
            pass
    else:
        path = _safeBsxPath(gc, filename)
        if not path.exists():
            raise FileNotFoundError(filename)
        pointer.write_text(
            json.dumps(
                {"filename": path.name, "activated_at": datetime.now(timezone.utc).isoformat()},
                indent=2,
            )
        )
    reloadActiveBsxInventory(gc)


def _buildActive(gc: GlobalConfig) -> Optional["BsxInventory"]:
    filename = getActiveBsxFilename(gc)
    if not filename:
        return None
    try:
        path = _safeBsxPath(gc, filename)
        content = path.read_bytes()
    except Exception as exc:
        gc.logger.warn(f"active bsx unreadable ({filename}): {exc}")
        return None
    try:
        pairs, item_ids, parsed_meta = _parseBsx(content)
    except Exception as exc:
        gc.logger.warn(f"active bsx parse failed ({filename}): {exc}")
        return None
    name = path.stem
    sidecar = _metaSidecarPath(path)
    if sidecar.exists():
        try:
            name = json.loads(sidecar.read_text()).get("name") or name
        except Exception:
            pass
    gc.logger.info(
        f"bsx inventory active: {filename} "
        f"({parsed_meta['num_unique_pairs']} part+color, {parsed_meta['num_unique_items']} items)"
    )
    return BsxInventory(filename=filename, name=name, pairs=pairs, item_ids=item_ids, meta=parsed_meta)


def reloadActiveBsxInventory(gc: GlobalConfig) -> Optional["BsxInventory"]:
    global _active, _active_loaded
    with _lock:
        _active = _buildActive(gc)
        _active_loaded = True
        return _active


def getActiveBsxInventory(gc: GlobalConfig) -> Optional["BsxInventory"]:
    global _active, _active_loaded
    with _lock:
        if _active_loaded:
            return _active
    return reloadActiveBsxInventory(gc)
