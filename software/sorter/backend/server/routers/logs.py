from __future__ import annotations

import glob
import os
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Query

from server import shared_state

router = APIRouter()

_MAX_READ_BYTES = 512_000

_LOG_SOURCES = [
    {
        "id": "machine-backend",
        "label": "Machine Backend",
        "description": "Current sorter runtime and backend process output.",
        "patterns": [
            "/tmp/sorter-client-main.log",
            "/tmp/sorter-client.log",
            "/tmp/sorter-client-backend.log",
            "/tmp/legosorter-machine-backend.log",
            "/tmp/legosorter-client-backend.log",
        ],
    },
    {
        "id": "machine-api",
        "label": "Machine API",
        "description": "Standalone API-only machine logs, if available.",
        "patterns": [
            "/tmp/sorter-client-api.log",
            "/tmp/legosorter-machine-api-only.log",
            "/tmp/legosorter-client-api.log",
        ],
    },
    {
        "id": "ui-frontend",
        "label": "UI Frontend",
        "description": "Svelte/Vite frontend output.",
        "patterns": ["/tmp/sorter-ui.log"],
    },
]


def _logger_file_path() -> Path | None:
    candidates: list[Path] = []

    gc = shared_state.gc_ref
    logger = getattr(gc, "logger", None) if gc is not None else None
    log_file = getattr(logger, "_log_file", None)
    log_name = getattr(log_file, "name", None)
    if isinstance(log_name, str) and log_name.strip():
        return Path(log_name).expanduser()
    return None

def _matched_paths(patterns: list[str]) -> list[Path]:
    candidates: list[Path] = []
    for pattern in patterns:
        for match in glob.glob(pattern):
            candidates.append(Path(match))

    deduped: list[Path] = []
    seen: set[str] = set()
    for path in candidates:
        try:
            resolved = str(path.expanduser().resolve())
        except OSError:
            continue
        if resolved in seen:
            continue
        seen.add(resolved)
        deduped.append(Path(resolved))
    return deduped


def _pick_latest_path(paths: list[Path]) -> Path | None:
    freshest: tuple[float, Path] | None = None
    for path in paths:
        if not path.exists() or not path.is_file():
            continue
        try:
            updated_at = path.stat().st_mtime
        except OSError:
            continue
        if freshest is None or updated_at > freshest[0]:
            freshest = (updated_at, path)
    return freshest[1] if freshest is not None else None


def _source_entry(spec: dict[str, Any]) -> dict[str, Any]:
    logger_path = _logger_file_path()
    paths = _matched_paths(list(spec["patterns"]))
    if spec["id"] == "machine-backend" and logger_path is not None:
        paths = [logger_path, *paths]

    selected_path = _pick_latest_path(paths)
    if selected_path is None:
        return {
            "id": spec["id"],
            "label": spec["label"],
            "description": spec["description"],
            "available": False,
            "path": None,
            "size_bytes": None,
            "updated_at": None,
        }

    stat = selected_path.stat()
    return {
        "id": spec["id"],
        "label": spec["label"],
        "description": spec["description"],
        "available": True,
        "path": str(selected_path),
        "size_bytes": stat.st_size,
        "updated_at": stat.st_mtime,
    }


def _available_sources() -> list[dict[str, Any]]:
    return [_source_entry(spec) for spec in _LOG_SOURCES]


def _resolve_source_or_404(source_id: str) -> dict[str, Any]:
    for source in _available_sources():
        if source["id"] == source_id:
            if not source["available"]:
                raise HTTPException(status_code=404, detail="Log source is not currently available.")
            return source
    raise HTTPException(status_code=404, detail="Log source not found.")


def _read_log_tail(path: Path, *, max_bytes: int, line_limit: int) -> str:
    try:
        with open(path, "rb") as handle:
            handle.seek(0, os.SEEK_END)
            size = handle.tell()
            read_size = min(size, max_bytes)
            handle.seek(size - read_size)
            raw = handle.read(read_size)
    except OSError as exc:
        raise HTTPException(status_code=500, detail=f"Failed to read log file: {exc}")

    text = raw.decode("utf-8", errors="replace")
    lines = text.splitlines()
    if len(lines) > line_limit:
        lines = lines[-line_limit:]
    return "\n".join(lines)


@router.get("/api/logs")
def list_logs() -> dict[str, Any]:
    return {"sources": _available_sources()}


@router.get("/api/logs/{source_id}")
def get_log_contents(
    source_id: str,
    lines: int = Query(default=400, ge=1, le=5000),
) -> dict[str, Any]:
    source = _resolve_source_or_404(source_id)
    path = Path(source["path"])
    content = _read_log_tail(path, max_bytes=_MAX_READ_BYTES, line_limit=lines)
    stat = path.stat()
    return {
        "id": source_id,
        "label": source["label"],
        "description": source["description"],
        "name": path.name,
        "path": str(path),
        "size_bytes": stat.st_size,
        "updated_at": stat.st_mtime,
        "content": content,
    }
