"""Local machine endpoints for Hive-backed sorting profiles."""

from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from blob_manager import getHiveConfig, getSortingProfileSyncState, setSortingProfileSyncState
from local_state import start_new_sorting_session
from server import shared_state
from server.routers.hardware import (
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
    config = getHiveConfig() or {}
    targets = config.get("targets")
    if not isinstance(targets, list):
        return []
    return [target for target in targets if isinstance(target, dict)]


def _get_target_or_404(target_id: str) -> dict[str, Any]:
    for target in _load_targets():
        if target.get("id") == target_id:
            return target
    raise HTTPException(status_code=404, detail="Hive target not found.")


def _target_session(target: dict[str, Any]) -> requests.Session:
    url = target.get("url")
    api_token = target.get("api_token")
    if not isinstance(url, str) or not url.strip():
        raise HTTPException(status_code=400, detail="Hive target URL is missing.")
    if not isinstance(api_token, str) or not api_token.strip():
        raise HTTPException(status_code=400, detail="Hive target token is missing.")
    session = requests.Session()
    session.headers["Authorization"] = f"Bearer {api_token.strip()}"
    session.headers["Content-Type"] = "application/json"
    return session


def _target_base_url(target: dict[str, Any]) -> str:
    url = target.get("url")
    if not isinstance(url, str) or not url.strip():
        raise HTTPException(status_code=400, detail="Hive target URL is missing.")
    return url.strip().rstrip("/")


def _safe_json(response: requests.Response) -> dict[str, Any]:
    try:
        data = response.json()
        return data if isinstance(data, dict) else {"data": data}
    except Exception:
        return {"error": response.text}


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


def _current_local_profile_status() -> dict[str, Any]:
    sync_state = getSortingProfileSyncState() or {}
    path = (
        shared_state.gc_ref.sorting_profile_path
        if shared_state.gc_ref is not None
        else os.environ.get("SORTING_PROFILE_PATH")
    )
    metadata: dict[str, Any] = {}
    if path and os.path.exists(path):
        try:
            with open(path, "r") as handle:
                data = json.load(handle)
            metadata = {
                "path": path,
                "name": data.get("name"),
                "description": data.get("description"),
                "artifact_hash": data.get("artifact_hash"),
                "default_category_id": data.get("default_category_id"),
                "category_count": len(data.get("categories", {}) or {}),
                "rule_count": len(data.get("rules", []) or []),
                "updated_at": data.get("updated_at"),
            }
        except Exception as exc:
            metadata = {"path": path, "error": str(exc)}
    return {
        "sync_state": sync_state,
        "local_profile": metadata,
    }


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


@router.get("/api/sorting-profiles/status")
def get_sorting_profile_status() -> dict[str, Any]:
    return _current_local_profile_status()


@router.get("/api/sorting-profiles/library")
def get_sorting_profile_library() -> dict[str, Any]:
    target_payloads: list[dict[str, Any]] = []
    for target in _load_targets():
        enabled = bool(target.get("enabled", False))
        payload: dict[str, Any] = {
            "id": target.get("id"),
            "name": target.get("name") or target.get("url"),
            "url": target.get("url"),
            "enabled": enabled,
            "machine_id": target.get("machine_id"),
            "profiles": [],
            "assignment": None,
            "error": None,
        }
        if not enabled:
            target_payloads.append(payload)
            continue
        try:
            session = _target_session(target)
            response = session.get(f"{_target_base_url(target)}/api/machine/profiles/library", timeout=20)
            if not response.ok:
                body = _safe_json(response)
                message = body.get("error") or body.get("detail") or f"HTTP {response.status_code}"
                raise RuntimeError(str(message))
            body = response.json()
            payload["profiles"] = body.get("profiles", []) if isinstance(body, dict) else []
            payload["assignment"] = body.get("assignment") if isinstance(body, dict) else None
        except Exception as exc:
            payload["error"] = str(exc)
        target_payloads.append(payload)
    return {
        "targets": target_payloads,
        **_current_local_profile_status(),
    }


@router.get("/api/sorting-profiles/targets/{target_id}/profiles/{profile_id}")
def get_sorting_profile_detail(
    target_id: str,
    profile_id: str,
    version_id: str | None = None,
) -> dict[str, Any]:
    target = _get_target_or_404(target_id)
    session = _target_session(target)
    response = session.get(
        f"{_target_base_url(target)}/api/machine/profiles/{profile_id}",
        params={"version_id": version_id} if version_id else None,
        timeout=20,
    )
    if not response.ok:
        body = _safe_json(response)
        message = body.get("error") or body.get("detail") or f"HTTP {response.status_code}"
        raise HTTPException(status_code=response.status_code, detail=str(message))
    data = response.json()
    return data if isinstance(data, dict) else {"data": data}


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
    session = _target_session(target)
    base_url = _target_base_url(target)

    if shared_state.gc_ref is None:
        raise HTTPException(status_code=500, detail="Global config not initialized.")

    # Normalize mode: legacy ``reset_bin_categories`` maps to "empty".
    mode = payload.preassign_mode
    if mode is None and payload.reset_bin_categories:
        mode = "empty"

    reset_result: dict[str, Any] | None = None
    if mode in ("empty", "rules"):
        reset_result = clear_bin_category_assignments(scope="all")

    assignment_response = session.put(
        f"{base_url}/api/machine/profile-assignment",
        json={
            "profile_id": payload.profile_id,
            "version_id": payload.version_id,
        },
        timeout=20,
    )
    if not assignment_response.ok:
        body = _safe_json(assignment_response)
        message = body.get("error") or body.get("detail") or f"HTTP {assignment_response.status_code}"
        raise HTTPException(status_code=assignment_response.status_code, detail=str(message))

    artifact_response = session.get(
        f"{base_url}/api/machine/profiles/versions/{payload.version_id}/artifact",
        timeout=30,
    )
    if not artifact_response.ok:
        body = _safe_json(artifact_response)
        message = body.get("error") or body.get("detail") or f"HTTP {artifact_response.status_code}"
        raise HTTPException(status_code=artifact_response.status_code, detail=str(message))

    artifact_body = artifact_response.json()
    artifact = artifact_body.get("artifact") if isinstance(artifact_body, dict) else None
    if not isinstance(artifact, dict):
        raise HTTPException(status_code=502, detail="Hive returned an invalid artifact payload.")

    artifact_hash = str(artifact.get("artifact_hash") or "")
    _atomic_write_json(shared_state.gc_ref.sorting_profile_path, artifact)
    reloaded = _reload_runtime_profile()

    preassigned_count = 0
    if mode == "rules":
        preassigned_count = _preassign_bins_from_rules(artifact)

    sync_state = {
        "target_id": payload.target_id,
        "target_name": target.get("name") or target.get("url"),
        "target_url": base_url,
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
        activation_response = session.post(
            f"{base_url}/api/machine/profile-activation",
            json={
                "version_id": payload.version_id,
                "artifact_hash": artifact_hash or None,
            },
            timeout=20,
        )
        if activation_response.ok:
            activation_data = activation_response.json()
            if isinstance(activation_data, dict):
                sync_state["activated_at"] = datetime.now(timezone.utc).isoformat()
                sync_state["assignment"] = activation_data
        else:
            body = _safe_json(activation_response)
            activation_error = str(body.get("error") or body.get("detail") or f"HTTP {activation_response.status_code}")
    except Exception as exc:
        activation_error = str(exc)

    if activation_error:
        sync_state["last_error"] = activation_error

    setSortingProfileSyncState(sync_state)
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
