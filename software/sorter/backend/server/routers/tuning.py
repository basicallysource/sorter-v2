"""Tuning endpoints for runtime-adjustable parameters."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException

from toml_config import (
    getClassificationChannelRev01Config,
    setClassificationChannelRev01Config,
    getGoToAngleConfig,
    setGoToAngleConfig,
    getActiveTrackerType,
    setActiveTrackerType,
    getTrackerConfig,
    setTrackerConfig,
    getPulsePerceptionConfig,
    setPulsePerceptionConfig,
    getConstantMovementConfig,
    setConstantMovementConfig,
    getClassificationProviders,
    setClassificationProviders,
    getLinkMatchingConfig,
    setLinkMatchingConfig,
)
from classification.providers import COLOR_PROVIDER_SPECS, MOLD_PROVIDER_SPECS
from subsystems.classification_channel.simple_state_machine_rev01.rev01_config import FIELD_META
from subsystems.feeder.go_to_angle.config import FIELD_META as GO_TO_ANGLE_FIELD_META
from subsystems.feeder.pulse_perception.config import FIELD_META as PULSE_PERCEPTION_FIELD_META
from subsystems.feeder.constant_movement.config import FIELD_META as CONSTANT_MOVEMENT_FIELD_META
from perception.tracker_config import TRACKER_SPECS

router = APIRouter()


@router.get("/api/tuning/classification-channel-rev01")
def get_cc_rev01_config() -> dict[str, Any]:
    return {
        "config": getClassificationChannelRev01Config(),
        "fields": FIELD_META,
    }


@router.post("/api/tuning/classification-channel-rev01")
def set_cc_rev01_config(body: dict[str, Any]) -> dict[str, Any]:
    try:
        updated = setClassificationChannelRev01Config(body)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"config": updated}


@router.get("/api/tuning/feeder-go-to-angle")
def get_go_to_angle_config() -> dict[str, Any]:
    return {
        "config": getGoToAngleConfig(),
        "fields": GO_TO_ANGLE_FIELD_META,
    }


@router.post("/api/tuning/feeder-go-to-angle")
def set_go_to_angle_config(body: dict[str, Any]) -> dict[str, Any]:
    try:
        updated = setGoToAngleConfig(body)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"config": updated}


@router.get("/api/tuning/feeder-pulse-perception")
def get_pulse_perception_config() -> dict[str, Any]:
    return {
        "config": getPulsePerceptionConfig(),
        "fields": PULSE_PERCEPTION_FIELD_META,
    }


@router.post("/api/tuning/feeder-pulse-perception")
def set_pulse_perception_config(body: dict[str, Any]) -> dict[str, Any]:
    try:
        updated = setPulsePerceptionConfig(body)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"config": updated}


@router.get("/api/tuning/feeder-pulse-perception/autotune")
def get_pulse_perception_autotune_status() -> dict[str, Any]:
    from subsystems.feeder.pulse_perception.autotune import getAutoTuner

    try:
        return getAutoTuner().status()
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc))


@router.post("/api/tuning/feeder-pulse-perception/autotune/start")
def start_pulse_perception_autotune(body: dict[str, Any] | None = None) -> dict[str, Any]:
    from subsystems.feeder.pulse_perception.autotune import getAutoTuner

    try:
        return getAutoTuner().start(body or {})
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc))


@router.post("/api/tuning/feeder-pulse-perception/autotune/stop")
def stop_pulse_perception_autotune(body: dict[str, Any] | None = None) -> dict[str, Any]:
    from subsystems.feeder.pulse_perception.autotune import getAutoTuner

    apply = (body or {}).get("apply", "baseline")
    if apply not in ("baseline", "best", "keep"):
        raise HTTPException(status_code=400, detail="apply must be baseline, best, or keep")
    try:
        return getAutoTuner().stop(apply)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc))


@router.get("/api/tuning/feeder-pulse-perception/autotune/runs")
def list_pulse_perception_autotune_runs(limit: int = 50) -> dict[str, Any]:
    import local_state

    return {"runs": local_state.listFeederAutotuneRuns(limit=limit)}


@router.get("/api/tuning/feeder-pulse-perception/autotune/runs/{run_id}")
def get_pulse_perception_autotune_run(run_id: str) -> dict[str, Any]:
    import local_state

    run = local_state.getFeederAutotuneRun(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="run not found")
    return {"run": run, "trials": local_state.listFeederAutotuneTrials(run_id)}


@router.post("/api/tuning/feeder-pulse-perception/autotune/apply-best")
def apply_pulse_perception_autotune_best(body: dict[str, Any] | None = None) -> dict[str, Any]:
    import local_state

    run_id = (body or {}).get("run_id")
    if not isinstance(run_id, str) or not run_id:
        runs = local_state.listFeederAutotuneRuns(limit=1)
        if not runs:
            raise HTTPException(status_code=404, detail="no auto-tune runs found")
        run_id = runs[0]["id"]
    run = local_state.getFeederAutotuneRun(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="run not found")
    best_trial_id = run.get("best_trial_id")
    if best_trial_id is None:
        raise HTTPException(status_code=404, detail="run has no best trial yet")
    trial = local_state.getFeederAutotuneTrial(int(best_trial_id))
    if trial is None or not trial.get("params_json"):
        raise HTTPException(status_code=404, detail="best trial not found")
    updated = setPulsePerceptionConfig(trial["params_json"])
    return {"config": updated, "applied_trial": trial}


@router.get("/api/tuning/feeder-constant-movement")
def get_constant_movement_config() -> dict[str, Any]:
    return {
        "config": getConstantMovementConfig(),
        "fields": CONSTANT_MOVEMENT_FIELD_META,
    }


@router.post("/api/tuning/feeder-constant-movement")
def set_constant_movement_config(body: dict[str, Any]) -> dict[str, Any]:
    try:
        updated = setConstantMovementConfig(body)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"config": updated}


@router.get("/api/tuning/classification-providers")
def get_classification_providers() -> dict[str, Any]:
    active = getClassificationProviders()
    return {
        "active": active,
        "color_providers": [
            {"id": s.id, "label": s.label, "description": s.description}
            for s in COLOR_PROVIDER_SPECS.values()
        ],
        "mold_providers": [
            {"id": s.id, "label": s.label, "description": s.description}
            for s in MOLD_PROVIDER_SPECS.values()
        ],
    }


@router.post("/api/tuning/classification-providers")
def set_classification_providers(body: dict[str, Any]) -> dict[str, Any]:
    try:
        if "color_provider" in body and body["color_provider"] not in COLOR_PROVIDER_SPECS:
            raise ValueError(f"unknown color provider: {body['color_provider']}")
        if "mold_provider" in body and body["mold_provider"] not in MOLD_PROVIDER_SPECS:
            raise ValueError(f"unknown mold provider: {body['mold_provider']}")
        setClassificationProviders(body)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return get_classification_providers()


@router.get("/api/tuning/object-tracker")
def get_object_tracker_config() -> dict[str, Any]:
    # All trackers up front so the UI can switch between them client-side; the
    # active one is flagged separately.
    return {
        "active_type": getActiveTrackerType(),
        "trackers": [
            {
                "type": t,
                "label": spec.label,
                "description": spec.description,
                "fields": spec.field_meta,
                "config": getTrackerConfig(t),
            }
            for t, spec in TRACKER_SPECS.items()
        ],
    }


@router.post("/api/tuning/object-tracker")
def set_object_tracker_config(body: dict[str, Any]) -> dict[str, Any]:
    # Body may carry {type, config} to save one tracker's params and/or
    # {active_type} to switch the active tracker. The page sends both on Save.
    cfg_type = body.get("type")
    config = body.get("config")
    active_type = body.get("active_type")
    try:
        if cfg_type is not None and isinstance(config, dict):
            if cfg_type not in TRACKER_SPECS:
                raise ValueError(f"unknown tracker type: {cfg_type}")
            setTrackerConfig(cfg_type, config)
        if active_type is not None:
            if active_type not in TRACKER_SPECS:
                raise ValueError(f"unknown tracker type: {active_type}")
            setActiveTrackerType(active_type)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return get_object_tracker_config()


@router.get("/api/tuning/link-matching")
def get_link_matching() -> dict[str, Any]:
    import link_matcher
    import server.hive_models as hive_models

    installed = [
        {
            "local_id": e.get("local_id"),
            "name": e.get("name"),
            "model_id": e.get("model_id"),
            "downloaded_at": e.get("downloaded_at"),
        }
        for e in hive_models.list_installed_models()
        if e.get("purpose") == hive_models.PURPOSE_PIECE_LINK
    ]
    return {
        "config": getLinkMatchingConfig(),
        "installed": installed,
        "meta_features": link_matcher.META_FEATURES,
    }


@router.post("/api/tuning/link-matching")
def set_link_matching(body: dict[str, Any]) -> dict[str, Any]:
    import link_matcher

    try:
        updated = setLinkMatchingConfig(body)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    # Drop cached sessions so switching models (or re-enabling after a failed
    # load) takes effect without a restart.
    link_matcher.invalidateCache()
    return {"config": updated}
