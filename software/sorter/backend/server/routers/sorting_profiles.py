"""Local machine endpoints for Hive-backed sorting profiles."""

from __future__ import annotations

import json
import os
import re
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from bin_contents import start_new_sorting_session
from local_state import get_hive_config, get_sorting_profile_sync_state, set_sorting_profile_sync_state
from server import shared_state
from server.hive_models import HiveClient, HiveError
from sorting_profile import profileSummary
from server.routers.bins import (
    clear_bin_category_assignments,
    _current_bin_categories,
    _apply_and_persist_bin_categories,
)

router = APIRouter()


class ApplySortingProfilePayload(BaseModel):
    target_id: str
    profile_id: str
    profile_name: str
    version_id: str
    version_number: int | None = None
    version_label: str | None = None
    # Legacy flag; still supported. ``preassign_mode`` is the new name and
    # carries richer semantics ("empty" vs. "rules").
    reset_bin_categories: bool = False
    # "empty"  → clear all bin category assignments (dynamic assignment).
    # "rules"  → walk the profile's rules in order and seed bin i with
    #            rule i's id.
    # ``None`` → do nothing to bin assignments.
    preassign_mode: str | None = None


def _load_targets() -> list[dict[str, Any]]:
    config = get_hive_config() or {}
    targets = config.get("targets")
    if not isinstance(targets, list):
        return []
    return [target for target in targets if isinstance(target, dict)]


def _get_target_or_404(target_id: str) -> dict[str, Any]:
    for target in _load_targets():
        if target.get("id") == target_id:
            return target
    raise HTTPException(status_code=404, detail="Hive target not found.")


def _target_client(target: dict[str, Any]) -> HiveClient:
    url = target.get("url")
    api_token = target.get("api_token")
    if not isinstance(url, str) or not url.strip():
        raise HTTPException(status_code=400, detail="Hive target URL is missing.")
    if not isinstance(api_token, str) or not api_token.strip():
        raise HTTPException(status_code=400, detail="Hive target token is missing.")
    return HiveClient(url.strip(), api_token.strip())


def _hive_http_error(exc: Exception) -> HTTPException:
    if isinstance(exc, HiveError):
        return HTTPException(status_code=exc.status_code, detail=str(exc))
    return HTTPException(status_code=502, detail=f"Hive could not be reached: {exc}")


def _target_meta(target: dict[str, Any]) -> dict[str, Any]:
    # Metadata only — no network. Shaped like a full library entry with empty
    # profiles so the UI can render target cards/skeletons before the Hive
    # fetch lands.
    return {
        "id": target.get("id"),
        "name": target.get("name") or target.get("url"),
        "url": target.get("url"),
        "enabled": bool(target.get("enabled", False)),
        "machine_id": target.get("machine_id"),
        "profiles": [],
        "assignment": None,
        "error": None,
    }


def _fetch_target_library(target: dict[str, Any]) -> dict[str, Any]:
    payload = _target_meta(target)
    if not payload["enabled"]:
        return payload
    try:
        body = _target_client(target).profile_library()
        payload["profiles"] = body.get("profiles", []) if isinstance(body, dict) else []
        payload["assignment"] = body.get("assignment") if isinstance(body, dict) else None
    except Exception as exc:
        payload["error"] = exc.detail if isinstance(exc, HTTPException) else str(exc)
    return payload


def _preassign_bins_from_rules(artifact: dict[str, Any]) -> int:
    """Seed bin category assignments from the artifact's rule order.

    Walks top-level non-disabled rules in order; each rule's id gets
    written to the next available bin (layer → section → bin). Rules
    keep their ordering from the artifact so the operator can plan
    physical placement ahead of time. Returns the number of bins that
    received an assignment.
    """
    rules = artifact.get("rules") if isinstance(artifact, dict) else None
    if not isinstance(rules, list):
        return 0
    rule_ids: list[str] = []
    for rule in rules:
        if not isinstance(rule, dict):
            continue
        if rule.get("disabled"):
            continue
        rid = rule.get("id")
        if isinstance(rid, str) and rid:
            rule_ids.append(rid)
    if not rule_ids:
        return 0

    categories = _current_bin_categories()
    assigned = 0
    for layer in categories:
        for section in layer:
            for bin_categories in section:
                if assigned >= len(rule_ids):
                    continue
                bin_categories.clear()
                bin_categories.append(rule_ids[assigned])
                assigned += 1
    # No MISC auto-reservation here — unmatched pieces fall through to the
    # bottom tray via distribution's passthrough branch, which the UI now
    # renders as a virtual bin. Reserving a real bin for MISC wastes a
    # physical slot.
    if assigned > 0:
        _apply_and_persist_bin_categories(categories)
    return assigned


def _atomic_write_json(path: str, data: dict[str, Any]) -> None:
    target_path = Path(path).expanduser().resolve()
    target_path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(dir=target_path.parent, suffix=".json.tmp")
    try:
        with os.fdopen(fd, "w") as handle:
            json.dump(data, handle, indent=2)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_path, target_path)
    except BaseException:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


# ─── Local (on-disk) sorting profiles ──────────────────────────────────────
# A properly-named library of saved profiles sitting next to local_state.sqlite.
# Each is a standard artifact JSON (same shape Hive emits). Writes are atomic
# (temp + fsync + rename) and reads open-and-close — nothing is held open, so a
# crash or OS hiccup can't leave a half-written or locked profile behind.


def _local_profiles_dir() -> Path:
    if shared_state.gc_ref is not None and getattr(shared_state.gc_ref, "local_profiles_dir", None):
        directory = Path(shared_state.gc_ref.local_profiles_dir)
    else:
        directory = Path(__file__).resolve().parents[2] / "sorting_profiles"
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def _safe_local_path(filename: str) -> Path:
    name = os.path.basename((filename or "").strip())
    if not name or name.startswith(".") or not name.endswith(".json"):
        raise HTTPException(status_code=400, detail="Invalid profile filename.")
    directory = _local_profiles_dir()
    resolved = (directory / name).resolve()
    if resolved.parent != directory.resolve():
        raise HTTPException(status_code=400, detail="Invalid profile filename.")
    return resolved


def _slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", (value or "").lower()).strip("-")
    return slug or "profile"


def _unique_local_path(base: str) -> Path:
    directory = _local_profiles_dir()
    stem = _slugify(base)
    candidate = directory / f"{stem}.json"
    counter = 2
    while candidate.exists():
        candidate = directory / f"{stem}-{counter}.json"
        counter += 1
    return candidate


def _profile_file_meta(path: Path) -> dict[str, Any]:
    data = profileSummary(path)
    return {
        "name": data.get("name"),
        "description": data.get("description"),
        "profile_type": data.get("profile_type"),
        "default_category_id": data.get("default_category_id"),
        "artifact_hash": data.get("artifact_hash"),
        "updated_at": data.get("updated_at"),
        "rule_count": len(data.get("rules", []) or []),
        "category_count": len(data.get("categories", {}) or {}),
        "part_count": data["part_count"],
    }


def _mtime_iso(path: Path) -> str | None:
    try:
        return datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc).isoformat()
    except OSError:
        return None


def _local_profile_entry_light(path: Path, active_filename: str | None) -> dict[str, Any]:
    # No parse — filename/stem/mtime only. Counts and the real name are filled
    # in lazily by GET /local/{filename}/meta so first paint never touches the
    # multi-MB file.
    return {
        "filename": path.name,
        "id": path.stem,
        "name": None,
        "description": None,
        "profile_type": None,
        "rule_count": None,
        "category_count": None,
        "part_count": None,
        "artifact_hash": None,
        "updated_at": _mtime_iso(path),
        "is_active": bool(active_filename and path.name == active_filename),
        "error": None,
    }


def _local_profile_entry(
    path: Path, active_hash: str | None, active_filename: str | None
) -> dict[str, Any]:
    entry: dict[str, Any] = {
        "filename": path.name,
        "id": path.stem,
        "name": None,
        "description": None,
        "profile_type": None,
        "rule_count": None,
        "category_count": None,
        "part_count": None,
        "artifact_hash": None,
        "updated_at": None,
        "is_active": False,
        "error": None,
    }
    try:
        meta = _profile_file_meta(path)
    except Exception as exc:
        entry["error"] = str(exc)
        return entry
    artifact_hash = meta["artifact_hash"]
    entry.update(
        {
            "name": meta["name"] or path.stem,
            "description": meta["description"],
            "profile_type": meta["profile_type"],
            "rule_count": meta["rule_count"],
            "category_count": meta["category_count"],
            "part_count": meta["part_count"],
            "artifact_hash": artifact_hash,
        }
    )
    entry["updated_at"] = _mtime_iso(path)
    if active_filename and path.name == active_filename:
        entry["is_active"] = True
    elif artifact_hash and active_hash and artifact_hash == active_hash:
        entry["is_active"] = True
    return entry


def _list_local_profiles() -> list[dict[str, Any]]:
    sync_state = get_sorting_profile_sync_state() or {}
    active_filename = (
        sync_state.get("local_filename") if sync_state.get("source") == "local" else None
    )
    active_hash = sync_state.get("artifact_hash")
    return [
        _local_profile_entry(path, active_hash, active_filename)
        for path in sorted(_local_profiles_dir().glob("*.json"))
    ]


def _active_profile_path() -> str | None:
    return shared_state.gc_ref.sorting_profile_path if shared_state.gc_ref is not None else None


def _current_local_profile_status() -> dict[str, Any]:
    sync_state = get_sorting_profile_sync_state() or {}
    path = _active_profile_path()
    metadata: dict[str, Any] = {}
    if path and os.path.exists(path):
        try:
            meta = _profile_file_meta(Path(path))
            metadata = {
                "path": path,
                "name": meta["name"],
                "description": meta["description"],
                "artifact_hash": meta["artifact_hash"],
                "default_category_id": meta["default_category_id"],
                "category_count": meta["category_count"],
                "rule_count": meta["rule_count"],
                "updated_at": meta["updated_at"],
            }
        except Exception as exc:
            metadata = {"path": path, "error": str(exc)}
    return {
        "sync_state": sync_state,
        "local_profile": metadata,
    }


def _current_local_profile_status_light() -> dict[str, Any]:
    # No parse: name comes from sync_state; counts are omitted (the /profiles
    # page only needs the active name here, and even that is a rare fallback).
    sync_state = get_sorting_profile_sync_state() or {}
    path = _active_profile_path()
    metadata: dict[str, Any] = {}
    if path and os.path.exists(path):
        metadata = {
            "path": path,
            "name": sync_state.get("profile_name"),
            "artifact_hash": sync_state.get("artifact_hash"),
            "updated_at": _mtime_iso(Path(path)),
        }
    return {
        "sync_state": sync_state,
        "local_profile": metadata,
    }


def _list_local_profiles_light() -> list[dict[str, Any]]:
    sync_state = get_sorting_profile_sync_state() or {}
    active_filename = (
        sync_state.get("local_filename") if sync_state.get("source") == "local" else None
    )
    return [
        _local_profile_entry_light(path, active_filename)
        for path in sorted(_local_profiles_dir().glob("*.json"))
    ]


def _reload_runtime_profile() -> bool:
    controller = shared_state.controller_ref
    if controller is None or not hasattr(controller, "reloadSortingProfile"):
        return False
    controller.reloadSortingProfile()
    try:
        from server.set_progress_sync import getSetProgressSyncWorker

        getSetProgressSyncWorker().notify()
    except Exception:
        pass
    return True


@router.get("/api/sorting-profiles/library")
def get_sorting_profile_library() -> dict[str, Any]:
    # Bundled view (local + every target's Hive fetch, sequentially). Kept for
    # the sorting-profile dropdown. The /profiles page uses the split
    # /local + /targets/{id}/library endpoints so fast local data renders
    # before the slow per-target Hive calls resolve.
    return {
        "targets": [_fetch_target_library(target) for target in _load_targets()],
        "local_profiles": _list_local_profiles(),
        **_current_local_profile_status(),
    }


@router.get("/api/sorting-profiles/local")
def get_sorting_profile_local() -> dict[str, Any]:
    # Fast tier: target metadata, active sync state, and local-profile
    # filenames. No Hive network AND no multi-MB JSON parse — counts/names for
    # local profiles are filled in lazily via /local/{filename}/meta so this
    # returns in milliseconds and the page can skeleton everything at once.
    return {
        "targets": [_target_meta(target) for target in _load_targets()],
        "local_profiles": _list_local_profiles_light(),
        **_current_local_profile_status_light(),
    }


@router.get("/api/sorting-profiles/local/{filename}/meta")
def get_local_profile_meta(filename: str) -> dict[str, Any]:
    # Lazy per-card metadata (name, counts) for a local profile. Parses the file
    # once and caches by mtime, so the 10s poll and re-renders are free.
    path = _safe_local_path(filename)
    if not path.exists():
        raise HTTPException(status_code=404, detail="Local profile not found.")
    try:
        meta = _profile_file_meta(path)
    except Exception as exc:
        return {"filename": path.name, "error": str(exc)}
    return {
        "filename": path.name,
        "name": meta["name"] or path.stem,
        "description": meta["description"],
        "profile_type": meta["profile_type"],
        "rule_count": meta["rule_count"],
        "category_count": meta["category_count"],
        "part_count": meta["part_count"],
        "artifact_hash": meta["artifact_hash"],
    }


@router.get("/api/sorting-profiles/targets/{target_id}/library")
def get_sorting_profile_target_library(target_id: str) -> dict[str, Any]:
    # Single target's Hive fetch. The page calls one of these per enabled
    # target in parallel so a slow/erroring target doesn't block the others.
    return _fetch_target_library(_get_target_or_404(target_id))


@router.get("/api/sorting-profiles/targets/{target_id}/profiles/{profile_id}")
def get_sorting_profile_detail(
    target_id: str,
    profile_id: str,
    version_id: str | None = None,
) -> dict[str, Any]:
    client = _target_client(_get_target_or_404(target_id))
    try:
        data = client.profile_detail(profile_id, version_id)
    except Exception as exc:
        raise _hive_http_error(exc) from exc
    return data if isinstance(data, dict) else {"data": data}


@router.get("/api/sorting-profiles/route")
def route_piece(
    part_id: str,
    color_id: str | None = None,
    confidence: float | None = None,
    color_confidence: float | None = None,
    price: float | None = None,
) -> dict[str, Any]:
    """Where a piece would go under the profile this machine runs now, kit
    counts included: its bin's category and name. Nothing moves. Rules on the
    piece itself read `confidence` and `color_confidence` (0 to 100, 100 when
    left out) and `price` (unknown when left out)."""
    controller = shared_state.controller_ref
    profile = getattr(getattr(controller, "coordinator", None), "sorting_profile", None)
    path = _active_profile_path()
    if profile is None:
        if not path or not os.path.exists(path):
            raise HTTPException(status_code=404, detail="No sorting profile is active.")
        from sorting_profile import JsonSortingProfile

        profile = JsonSortingProfile(shared_state.gc_ref)
    observed = {
        "confidence": 100.0 if confidence is None else confidence,
        "color_confidence": 100.0 if color_confidence is None else color_confidence,
        "piece_price": price,
    }
    category_id = profile.getCategoryIdForPart(
        part_id.strip(), (color_id or "").strip() or "any_color", piece=observed
    )
    categories: dict[str, Any] = {}
    if path and os.path.exists(path):
        try:
            categories = profileSummary(path).get("categories") or {}
        except (OSError, ValueError):
            categories = {}
    meta = categories.get(category_id) if isinstance(categories.get(category_id), dict) else {}
    return {
        "part_id": part_id,
        "color_id": color_id,
        "category_id": category_id,
        "category_name": meta.get("name") or category_id,
        "bin": meta,
    }


@router.post("/api/sorting-profiles/reload")
def reload_sorting_profile() -> dict[str, Any]:
    return {
        "ok": True,
        "reloaded": _reload_runtime_profile(),
        **_current_local_profile_status(),
    }


@router.post("/api/sorting-profiles/apply")
def apply_sorting_profile(payload: ApplySortingProfilePayload) -> dict[str, Any]:
    target = _get_target_or_404(payload.target_id)
    client = _target_client(target)

    if shared_state.gc_ref is None:
        raise HTTPException(status_code=500, detail="Global config not initialized.")

    # Normalize mode: legacy ``reset_bin_categories`` maps to "empty".
    mode = payload.preassign_mode
    if mode is None and payload.reset_bin_categories:
        mode = "empty"

    reset_result: dict[str, Any] | None = None
    if mode in ("empty", "rules"):
        reset_result = clear_bin_category_assignments(scope="all")

    try:
        client.assign_profile(payload.profile_id, payload.version_id)
        artifact = client.profile_artifact(payload.version_id)
    except Exception as exc:
        raise _hive_http_error(exc) from exc

    artifact_hash = str(artifact.get("artifact_hash") or "")
    _atomic_write_json(shared_state.gc_ref.sorting_profile_path, artifact)
    reloaded = _reload_runtime_profile()

    preassigned_count = 0
    if mode == "rules":
        preassigned_count = _preassign_bins_from_rules(artifact)

    sync_state = {
        "source": "hive",
        "local_filename": None,
        "target_id": payload.target_id,
        "target_name": target.get("name") or target.get("url"),
        "target_url": client.api_url,
        "profile_id": payload.profile_id,
        "profile_name": payload.profile_name,
        "version_id": payload.version_id,
        "version_number": payload.version_number,
        "version_label": payload.version_label,
        "artifact_hash": artifact_hash or None,
        "applied_at": datetime.now(timezone.utc).isoformat(),
        "last_error": None,
    }

    activation_error: str | None = None
    try:
        activation_data = client.report_profile_activation(payload.version_id, artifact_hash or None)
        if isinstance(activation_data, dict):
            sync_state["activated_at"] = datetime.now(timezone.utc).isoformat()
            sync_state["assignment"] = activation_data
    except Exception as exc:
        activation_error = str(exc)

    if activation_error:
        sync_state["last_error"] = activation_error

    set_sorting_profile_sync_state(sync_state)
    start_new_sorting_session(reason="profile_activated")
    try:
        from server.set_progress_sync import getSetProgressSyncWorker

        getSetProgressSyncWorker().notify()
    except Exception:
        pass

    status = _current_local_profile_status()
    shared_state.publishSortingProfileStatus(status)
    return {
        "ok": True,
        "reloaded": reloaded,
        "bin_categories_reset": bool(reset_result),
        "bin_categories_reset_message": reset_result.get("message") if isinstance(reset_result, dict) else None,
        "preassigned_count": preassigned_count,
        "activation_error": activation_error,
        **status,
    }


def apply_first_default_profile_if_none() -> dict[str, Any] | None:
    """A sorter with no profile yet starts on its Hive's first default
    profile (BrickLink categories), so it sorts sensibly as soon as it is set
    up. Does nothing when a profile is active, or no Hive has defaults."""
    gc = shared_state.gc_ref
    if gc is None or os.path.exists(gc.sorting_profile_path):
        return None
    for target in _load_targets():
        if not target.get("enabled"):
            continue
        library = _fetch_target_library(target)
        defaults = sorted(
            (
                profile
                for profile in library.get("profiles") or []
                if isinstance(profile, dict)
                and profile.get("is_default")
                and isinstance(profile.get("latest_published_version"), dict)
            ),
            key=lambda profile: profile.get("default_rank") or 1_000_000,
        )
        if not defaults:
            continue
        profile = defaults[0]
        version = profile["latest_published_version"]
        gc.logger.info(f"Sorting profile: none active; starting on {profile.get('name')!r} from {target.get('name')}")
        return apply_sorting_profile(
            ApplySortingProfilePayload(
                target_id=str(target["id"]),
                profile_id=str(profile["id"]),
                profile_name=str(profile.get("name") or "Default"),
                version_id=str(version["id"]),
                version_number=version.get("version_number"),
                version_label=version.get("label"),
            )
        )
    return None


def start_first_default_profile_if_none() -> None:
    """The same, off the request path (it downloads from Hive)."""
    import threading

    def run() -> None:
        try:
            apply_first_default_profile_if_none()
        except Exception as exc:
            if shared_state.gc_ref is not None:
                shared_state.gc_ref.logger.warning(f"Sorting profile: could not start on a default: {exc}")

    threading.Thread(target=run, name="default-profile", daemon=True).start()


class ApplyLocalSortingProfilePayload(BaseModel):
    filename: str
    reset_bin_categories: bool = False
    preassign_mode: str | None = None


class UploadLocalSortingProfilePayload(BaseModel):
    artifact: dict[str, Any]
    name: str | None = None


def _is_profile_artifact(artifact: Any) -> bool:
    return isinstance(artifact, dict) and (
        isinstance(artifact.get("program"), dict) or "part_to_category" in artifact
    )


def _load_local_artifact(path: Path) -> dict[str, Any]:
    try:
        with open(path, "r") as handle:
            artifact = json.load(handle)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail=f"Profile file is corrupt: {exc}")
    if not _is_profile_artifact(artifact):
        raise HTTPException(
            status_code=400,
            detail="Profile is not a valid sorting profile (it has neither a program nor a part map).",
        )
    return artifact


@router.post("/api/sorting-profiles/local/apply")
def apply_local_sorting_profile(payload: ApplyLocalSortingProfilePayload) -> dict[str, Any]:
    if shared_state.gc_ref is None:
        raise HTTPException(status_code=500, detail="Global config not initialized.")

    path = _safe_local_path(payload.filename)
    if not path.exists():
        raise HTTPException(status_code=404, detail="Local profile not found.")
    artifact = _load_local_artifact(path)

    mode = payload.preassign_mode
    if mode is None and payload.reset_bin_categories:
        mode = "empty"
    reset_result: dict[str, Any] | None = None
    if mode in ("empty", "rules"):
        reset_result = clear_bin_category_assignments(scope="all")

    _atomic_write_json(shared_state.gc_ref.sorting_profile_path, artifact)
    reloaded = _reload_runtime_profile()

    preassigned_count = 0
    if mode == "rules":
        preassigned_count = _preassign_bins_from_rules(artifact)

    name = str(artifact.get("name") or path.stem)
    now = datetime.now(timezone.utc).isoformat()
    sync_state = {
        "source": "local",
        "local_filename": path.name,
        "target_id": None,
        "target_name": "Local",
        "target_url": None,
        "profile_id": None,
        "profile_name": name,
        "version_id": None,
        "version_number": None,
        "version_label": None,
        "artifact_hash": str(artifact.get("artifact_hash") or "") or None,
        "applied_at": now,
        "activated_at": now,
        "last_error": None,
    }
    set_sorting_profile_sync_state(sync_state)
    start_new_sorting_session(reason="profile_activated")
    try:
        from server.set_progress_sync import getSetProgressSyncWorker

        getSetProgressSyncWorker().notify()
    except Exception:
        pass

    status = _current_local_profile_status()
    shared_state.publishSortingProfileStatus(status)
    return {
        "ok": True,
        "reloaded": reloaded,
        "bin_categories_reset": bool(reset_result),
        "bin_categories_reset_message": reset_result.get("message") if isinstance(reset_result, dict) else None,
        "preassigned_count": preassigned_count,
        "local_profiles": _list_local_profiles(),
        **status,
    }


@router.post("/api/sorting-profiles/local/upload")
def upload_local_sorting_profile(payload: UploadLocalSortingProfilePayload) -> dict[str, Any]:
    artifact = payload.artifact
    if not _is_profile_artifact(artifact):
        raise HTTPException(
            status_code=400,
            detail="Uploaded JSON is not a valid sorting profile (it has neither a program nor a part map).",
        )
    name = (payload.name or "").strip()
    if name:
        artifact = {**artifact, "name": name}
    base = name or str(artifact.get("name") or artifact.get("id") or "profile")
    dest = _unique_local_path(base)
    _atomic_write_json(str(dest), artifact)
    return {
        "ok": True,
        "profile": _local_profile_entry(dest, None, None),
        "local_profiles": _list_local_profiles(),
    }


@router.delete("/api/sorting-profiles/local/{filename}")
def delete_local_sorting_profile(filename: str) -> dict[str, Any]:
    path = _safe_local_path(filename)
    if path.exists():
        try:
            path.unlink()
        except OSError as exc:
            raise HTTPException(status_code=500, detail=f"Could not delete profile: {exc}")
    return {"ok": True, "local_profiles": _list_local_profiles()}

