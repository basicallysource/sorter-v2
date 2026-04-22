"""HTTP router for browsing and downloading Hive detection models.

The router is a thin facade over ``server.hive_models``: it handles target
resolution (never leaking API tokens), translates ``HiveError`` into sensible
HTTP responses, and exposes a small surface for the sorter UI to poll.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query

from server import hive_models as hive_models_service

HiveError = hive_models_service.HiveError


router = APIRouter(prefix="/api/hive", tags=["hive-models"])


def _public_target(target: dict) -> dict:
    """Strip the API token before returning a target to the client."""
    return {
        "id": target.get("id"),
        "name": target.get("name"),
        "url": target.get("url"),
    }


def _resolve_target_id(target_id: str | None) -> str:
    targets = hive_models_service.resolve_targets()
    if not targets:
        raise HTTPException(status_code=400, detail="no hive targets configured")
    if target_id is None or not target_id:
        return targets[0]["id"]
    for target in targets:
        if target["id"] == target_id:
            return target_id
    raise HTTPException(status_code=404, detail=f"unknown hive target: {target_id}")


def _hive_error_response(exc: HiveError) -> HTTPException:
    detail = str(exc) or "Hive request failed"
    return HTTPException(status_code=502, detail=detail)


# ---------------------------------------------------------------------------
# Targets
# ---------------------------------------------------------------------------


@router.get("/targets")
def list_targets() -> list[dict]:
    return [_public_target(target) for target in hive_models_service.resolve_targets()]


# ---------------------------------------------------------------------------
# Remote catalog
# ---------------------------------------------------------------------------


@router.get("/models")
def list_models(
    target_id: str | None = Query(default=None),
    scope: str | None = Query(default=None),
    runtime: str | None = Query(default=None),
    family: str | None = Query(default=None),
    q: str | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=30, ge=1, le=200),
) -> dict:
    resolved_target = _resolve_target_id(target_id)
    filters: dict[str, Any] = {"page": page, "page_size": page_size}
    if scope:
        filters["scope"] = scope
    if runtime:
        filters["runtime"] = runtime
    if family:
        filters["family"] = family
    if q:
        filters["q"] = q
    try:
        payload = hive_models_service.list_remote_models(resolved_target, **filters)
    except HiveError as exc:
        raise _hive_error_response(exc)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return {"target_id": resolved_target, **(payload if isinstance(payload, dict) else {})}


# NOTE: ``/models/installed`` must be declared before ``/models/{model_id}``
# so FastAPI's path matcher doesn't capture ``"installed"`` as a model id.
@router.get("/models/installed")
def list_installed() -> dict:
    return {"items": hive_models_service.list_installed_models()}


@router.get("/models/{model_id}")
def get_model(
    model_id: str,
    target_id: str | None = Query(default=None),
) -> dict:
    resolved_target = _resolve_target_id(target_id)
    try:
        detail = hive_models_service.get_remote_model(resolved_target, model_id)
    except HiveError as exc:
        raise _hive_error_response(exc)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))

    variants = detail.get("variants") if isinstance(detail, dict) else None
    variant_runtimes: list[str] = []
    if isinstance(variants, list):
        for variant in variants:
            if isinstance(variant, dict) and isinstance(variant.get("runtime"), str):
                variant_runtimes.append(variant["runtime"])

    recommended = hive_models_service.pick_runtime_for_this_machine(variant_runtimes)

    return {
        "target_id": resolved_target,
        **(detail if isinstance(detail, dict) else {}),
        "variant_runtimes": variant_runtimes,
        "recommended_runtime": recommended,
    }


# ---------------------------------------------------------------------------
# Downloads
# ---------------------------------------------------------------------------


@router.post("/models/{model_id}/download")
def download_model(
    model_id: str,
    target_id: str | None = Query(default=None),
    variant_runtime: str | None = Query(default=None),
) -> dict:
    resolved_target = _resolve_target_id(target_id)
    manager = hive_models_service.get_job_manager()
    job_id = manager.enqueue(resolved_target, model_id, variant_runtime)
    return {"job_id": job_id}


@router.get("/downloads")
def list_downloads() -> dict:
    manager = hive_models_service.get_job_manager()
    return {"jobs": manager.snapshot()}


# ---------------------------------------------------------------------------
# Installed models
# ---------------------------------------------------------------------------


@router.delete("/models/installed/{local_id}")
def delete_installed(local_id: str) -> dict:
    try:
        hive_models_service.remove_installed_model(local_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return {"ok": True}
