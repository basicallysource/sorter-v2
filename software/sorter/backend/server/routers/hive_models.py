"""HTTP router for browsing and downloading Hive detection models.

The router is a thin facade over ``server.hive_models``: it handles target
resolution (never leaking API tokens), translates ``HiveError`` into sensible
HTTP responses, and exposes a small surface for the sorter UI to poll.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from server import hive_models as hive_models_service

HiveError = hive_models_service.HiveError


router = APIRouter(prefix="/api/hive", tags=["hive-models"])


# ---------------------------------------------------------------------------
# Active per-scope detection assignments
# ---------------------------------------------------------------------------

# Each slot: (toml_section, role_key_or_None, human_label, registry_scope, group)
#
# ``toml_section`` — what gets passed to ``getDetectionConfig`` /
# ``setDetectionConfig``.
# ``registry_scope`` — the ``vision.detection_registry.DetectionScope`` value
# used to check whether a model can serve this slot.
# ``group`` — coarse logical grouping (``c_channels`` | ``chamber`` |
# ``carousel``) the UI can collapse into a single line when every slot in the
# group runs the same model.
# NOTE: ``toml_section`` here is what the *live VisionManager* reads, not
# whatever the operator-facing label suggests. The C4 station in the
# ``classification_channel`` setup is wired pipeline-side as the carousel
# detection — so its persisted algorithm lives in ``[detection.carousel]``,
# never in a ``[detection.classification_channel]`` section (which would be
# dead config nobody picks up).
_ACTIVE_ASSIGNMENT_SLOTS: tuple[tuple[str, str | None, str, str, str], ...] = (
    ("classification", None, "Chamber", "classification", "chamber"),
    ("feeder", "c_channel_2", "C-Channel 2", "feeder", "c_channels"),
    ("feeder", "c_channel_3", "C-Channel 3", "feeder", "c_channels"),
    ("feeder", "carousel", "Carousel feed", "feeder", "carousel"),
    ("carousel", None, "Classification C-Channel (C4)", "carousel", "c_channels"),
    ("carousel", None, "Carousel detect", "carousel", "carousel"),
)


def _push_to_live_vision_manager(
    scope: str, role: str | None, algorithm_id: str
) -> None:
    """Update the running VisionManager so the next frame uses the new model.

    Without this, ``/activate`` only writes to ``machine_params.toml`` and the
    live pipeline keeps running with whatever was loaded at process start —
    which silently falls back to MOG2/heatmap_diff if the persisted algorithm
    couldn't be resolved at startup time.
    """
    from server import shared_state

    vision_manager = getattr(shared_state, "vision_manager", None)
    if vision_manager is None:
        return
    try:
        if scope == "feeder":
            setter = getattr(vision_manager, "setFeederDetectionAlgorithm", None)
            if setter is not None:
                if role is not None:
                    setter(algorithm_id, role)
                else:
                    setter(algorithm_id)
        elif scope == "carousel":
            setter = getattr(vision_manager, "setCarouselDetectionAlgorithm", None)
            if setter is not None:
                setter(algorithm_id)
        elif scope == "classification":
            setter = getattr(vision_manager, "setClassificationDetectionAlgorithm", None)
            if setter is not None:
                setter(algorithm_id)
    except Exception:  # pragma: no cover - defensive: TOML still got written
        import logging
        logging.getLogger(__name__).exception(
            "Failed to push %s/%s → %s to live VisionManager", scope, role, algorithm_id
        )


def _slots_for_setup(setup_key: str | None) -> tuple[tuple[str, str | None, str, str, str], ...]:
    """Filter the slot list to those that exist in the current machine setup.

    A ``classification_channel`` machine has no carousel and no chamber, so
    surfacing those rows would be misleading. A ``standard_carousel`` machine
    has no C4. ``manual_carousel`` keeps the same slot set as the standard
    setup minus the operator-managed feeder.
    """
    from machine_setup import get_machine_setup_definition

    setup = get_machine_setup_definition(setup_key)
    keep_chamber = setup.uses_classification_chamber
    keep_carousel = setup.uses_carousel_transport
    keep_c4 = setup.uses_classification_channel

    visible: list[tuple[str, str | None, str, str, str]] = []
    for slot in _ACTIVE_ASSIGNMENT_SLOTS:
        toml_section, role, _label, _scope, group = slot
        if toml_section == "classification" and not keep_chamber:
            continue
        if group == "carousel" and not keep_carousel:
            continue
        if toml_section == "classification_channel" and not keep_c4:
            continue
        # Drop the ``feeder.carousel`` role when carousel transport is gone:
        # in classification_channel mode no piece ever lands in that slot.
        if (
            toml_section == "feeder"
            and role == "carousel"
            and not keep_carousel
        ):
            continue
        visible.append(slot)
    return tuple(visible)


def _current_setup_key() -> str | None:
    try:
        from toml_config import _read_toml  # type: ignore[attr-defined]
    except Exception:
        return None
    try:
        cfg = _read_toml()
    except Exception:
        return None
    raw = cfg.get("machine_setup") if isinstance(cfg, dict) else None
    if isinstance(raw, dict):
        candidate = raw.get("type")
        if isinstance(candidate, str) and candidate.strip():
            return candidate.strip()
    return None


def _collect_active_assignments() -> list[dict[str, str | None]]:
    from toml_config import getDetectionConfig

    setup_key = _current_setup_key()
    items: list[dict[str, str | None]] = []
    for scope, role, label, registry_scope, group in _slots_for_setup(setup_key):
        cfg = getDetectionConfig(scope)
        if not isinstance(cfg, dict):
            algorithm = None
        elif role is not None:
            by_role = cfg.get("algorithm_by_role")
            algorithm = (
                by_role.get(role)
                if isinstance(by_role, dict) and isinstance(by_role.get(role), str)
                else cfg.get("algorithm")
            )
        else:
            algorithm = cfg.get("algorithm")
        items.append(
            {
                "scope": scope,
                "role": role,
                "label": label,
                "registry_scope": registry_scope,
                "group": group,
                "algorithm_id": algorithm if isinstance(algorithm, str) else None,
            }
        )
    return items


def _apply_active_assignments(algorithm_id: str, registry_scopes: set[str]) -> dict:
    """Write ``algorithm_id`` to every TOML slot whose registry_scope matches.

    Returns a summary describing which slots were touched and which were left
    alone (the model couldn't serve them).
    """
    from toml_config import getDetectionConfig, setDetectionConfig

    applied: list[str] = []
    skipped: list[str] = []
    by_scope_changes: dict[str, dict[str, dict]] = {}
    live_pushes: list[tuple[str, str | None, str]] = []

    for scope, role, label, registry_scope, _group in _slots_for_setup(_current_setup_key()):
        if registry_scope not in registry_scopes:
            skipped.append(label)
            continue
        scope_changes = by_scope_changes.setdefault(scope, {"set": {}})
        if role is None:
            scope_changes["set"]["algorithm"] = algorithm_id
        else:
            roles_map = scope_changes["set"].setdefault("algorithm_by_role", {})
            roles_map[role] = algorithm_id
        live_pushes.append((scope, role, algorithm_id))
        applied.append(label)

    for scope, changes in by_scope_changes.items():
        existing = getDetectionConfig(scope) or {}
        merged = dict(existing)
        for key, value in changes["set"].items():
            if key == "algorithm_by_role":
                current = (
                    merged.get("algorithm_by_role")
                    if isinstance(merged.get("algorithm_by_role"), dict)
                    else {}
                )
                merged["algorithm_by_role"] = {**current, **value}
            else:
                merged[key] = value
        setDetectionConfig(scope, merged)

    # Push to the live VisionManager *after* persistence so a crash here
    # still leaves the next process restart with the right config.
    for scope, role, algo in live_pushes:
        _push_to_live_vision_manager(scope, role, algo)

    return {"applied": applied, "skipped": skipped}


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
    purpose: str | None = Query(default=None),
    q: str | None = Query(default=None),
    include_experimental: bool = Query(default=False),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=30, ge=1, le=200),
) -> dict:
    filters: dict[str, Any] = {"page": page, "page_size": page_size}
    if include_experimental:
        filters["include_experimental"] = True
    if scope:
        filters["scope"] = scope
    if runtime:
        filters["runtime"] = runtime
    if family:
        filters["family"] = family
    if purpose:
        filters["purpose"] = purpose
    if q:
        filters["q"] = q

    # No target_id → aggregate across every enabled Hive so the UI can present
    # a single merged catalog and tag each row with its source Hive.
    if not target_id:
        return hive_models_service.list_remote_models_all(**filters)

    try:
        payload = hive_models_service.list_remote_models(target_id, **filters)
    except HiveError as exc:
        raise _hive_error_response(exc)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return {"target_id": target_id, **(payload if isinstance(payload, dict) else {})}


# NOTE: ``/models/installed`` must be declared before ``/models/{model_id}``
# so FastAPI's path matcher doesn't capture ``"installed"`` as a model id.
@router.get("/models/installed")
def list_installed() -> dict:
    from vision.detection_registry import detection_algorithm_definition

    items = hive_models_service.list_installed_models()
    # Tag each entry with the training scopes the registry knows it for, so the
    # Models UI can flag "not designed for this subsystem" when the operator
    # assigns a model to a slot outside its scope (still allowed — informational).
    for item in items:
        algo_id = f"{'bundled:' if item.get('bundled') else 'hive:'}{item.get('local_id')}"
        definition = detection_algorithm_definition(algo_id)
        item["registry_scopes"] = (
            sorted(definition.supported_scopes) if definition is not None else []
        )
    return {"items": items}


@router.get("/models/active-assignments")
def list_active_assignments() -> dict:
    """Which detection algorithm is currently bound to which scope/role.

    Reads from ``machine_params.toml`` and returns a flat list of
    ``{algorithm_id, scope, role, label}`` so the Models UI can show
    "this model is currently active for: ..." next to each installed entry.
    """
    return {"items": _collect_active_assignments()}


class ActivatePayload(BaseModel):
    algorithm_id: str
    # When ``scope`` is set, activate for EXACTLY that one subsystem slot (1:1
    # with the TOML, no fan-out, no scope gate). When omitted, fall back to the
    # legacy behavior of activating every slot the model's training scope claims.
    scope: str | None = None
    role: str | None = None


def _apply_active_assignment_to_slot(
    algorithm_id: str, target_scope: str, target_role: str | None
) -> dict:
    """Write ``algorithm_id`` to exactly ONE subsystem slot. 1:1 with the TOML,
    no fan-out and NO scope gate — a model may be assigned to a slot whose
    training scope it doesn't claim (perception loads any model by id; the UI
    surfaces a 'not designed for this' note). Pushes the live VisionManager and
    pokes perception to reconcile so the change applies without a restart."""
    from toml_config import getDetectionConfig, setDetectionConfig

    slot = None
    for s in _slots_for_setup(_current_setup_key()):
        if s[0] == target_scope and s[1] == target_role:
            slot = s
            break
    if slot is None:
        raise HTTPException(
            status_code=400,
            detail=f"no subsystem for scope={target_scope!r} role={target_role!r} in this setup",
        )
    scope, role, label, _registry_scope, _group = slot
    merged = dict(getDetectionConfig(scope) or {})
    if role is None:
        merged["algorithm"] = algorithm_id
    else:
        current = (
            merged.get("algorithm_by_role")
            if isinstance(merged.get("algorithm_by_role"), dict)
            else {}
        )
        merged["algorithm_by_role"] = {**current, role: algorithm_id}
    setDetectionConfig(scope, merged)
    _push_to_live_vision_manager(scope, role, algorithm_id)
    try:
        from server import shared_state

        ps = getattr(getattr(shared_state, "gc_ref", None), "perception_service", None)
        if ps is not None and hasattr(ps, "request_reconcile"):
            ps.request_reconcile()
    except Exception:
        pass
    return {"applied": [label], "skipped": []}


@router.post("/models/activate")
def activate_algorithm(payload: ActivatePayload) -> dict:
    """Activate ``algorithm_id`` for a subsystem.

    With ``scope`` set, writes exactly one subsystem slot — 1:1 with the TOML,
    no scope gate. Without it, the legacy behavior writes every slot the model's
    training scope claims.
    """
    from vision.detection_registry import detection_algorithm_definition, invalidate_registry

    # Defensive rescan: a model that was just downloaded won't be in the
    # cached registry until invalidation runs. The download worker also
    # invalidates, but if the activation request races ahead of that we'd
    # otherwise hand the user a confusing "unknown algorithm" error.
    invalidate_registry()

    definition = detection_algorithm_definition(payload.algorithm_id)
    if definition is None:
        raise HTTPException(
            status_code=404, detail=f"unknown algorithm: {payload.algorithm_id}"
        )
    if payload.scope is not None:
        summary = _apply_active_assignment_to_slot(
            payload.algorithm_id, payload.scope, payload.role
        )
    else:
        summary = _apply_active_assignments(
            payload.algorithm_id, set(definition.supported_scopes)
        )
    return {
        "algorithm_id": payload.algorithm_id,
        "label": definition.label,
        **summary,
        "items": _collect_active_assignments(),
    }


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
    """Queue downloads for this model.

    Without ``variant_runtime`` we enqueue **every deployable variant**
    (ONNX, NCNN, Hailo) in parallel — each into its own
    ``hive-<model_id>-<runtime>`` directory. Operators on a Mac get both the
    ONNX and NCNN exports so they can later choose between e.g. CoreML and
    Vulkan execution by activating the right variant. Pytorch is filtered
    out because the sorter cannot load it.

    Pass an explicit ``variant_runtime`` (``onnx``/``ncnn``/``hailo``) to
    queue exactly one variant.
    """
    resolved_target = _resolve_target_id(target_id)
    manager = hive_models_service.get_job_manager()
    if variant_runtime:
        job_id = manager.enqueue(resolved_target, model_id, variant_runtime)
        return {"job_id": job_id, "job_ids": [job_id]}
    job_ids = manager.enqueue_all_deployable_variants(resolved_target, model_id)
    return {"job_ids": job_ids, "job_id": job_ids[0] if job_ids else None}


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
