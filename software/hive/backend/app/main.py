import logging
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.config import settings
from app.deps import get_db
from app.errors import APIError, api_error_handler, http_exception_handler, unhandled_exception_handler
from app.routers import (
    admin,
    admin_parts,
    ai_models,
    ai_usage,
    analytics,
    api_keys,
    auth,
    color_models,
    color_predict,
    control_data,
    devices,
    installs,
    leaderboard,
    link_models,
    machine_config_backups,
    machine_lookup,
    machine_models,
    machine_parts,
    machine_sync,
    machines,
    models as models_router,
    piece_color_labels,
    profiles,
    public_catalog,
    public_stats,
    review,
    samples,
    sets,
    set_instances,
    stats,
    teacher,
    upload,
)
from app.services.profile_catalog import get_existing_profile_catalog_service, get_profile_catalog_service
from app.services.candidate_matview import get_candidate_matview_worker
from app.services.condition_worker import get_condition_worker
from app.services.machine_stats import get_machine_stats_worker
from app.services.server_health import get_memory_log_worker, get_storage_stats_worker
from app.services.teacher_worker import get_teacher_worker

def _configure_app_logging() -> None:
    """Give the ``app`` logger somewhere to write.

    uvicorn configures its own loggers and deliberately leaves the root logger
    alone, so nothing in this package had a handler and all 50-odd logger calls
    under app/ went nowhere — including the five background workers announcing
    themselves at startup, and warnings like "color model has no usable classes"
    that were meant to be the first sign something was wrong. None of it has
    ever appeared in `docker logs`.

    Configured on the ``app`` logger rather than the root on purpose: root would
    also unmute botocore and friends, and this box does not need that volume.
    uvicorn's own loggers do not propagate, so its access lines are unaffected.
    """
    app_logger = logging.getLogger("app")
    app_logger.setLevel(logging.INFO)
    if not app_logger.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s [%(name)s] %(message)s"))
        app_logger.addHandler(handler)


_configure_app_logging()

limiter = Limiter(key_func=get_remote_address)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    if settings.PROFILE_CATALOG_AUTO_SYNC_ENABLED and settings.REBRICKABLE_API_KEY:
        get_profile_catalog_service().start_auto_sync_loop()
    get_teacher_worker().start()
    get_condition_worker().start()
    get_machine_stats_worker().start()
    get_storage_stats_worker().start()
    get_memory_log_worker().start()  # diagnostic, delete with the 2026-08 leak
    get_candidate_matview_worker().start()
    try:
        yield
    finally:
        get_candidate_matview_worker().stop()
        get_teacher_worker().stop()
        get_condition_worker().stop()
        get_machine_stats_worker().stop()
        get_storage_stats_worker().stop()
        get_memory_log_worker().stop()
        service = get_existing_profile_catalog_service()
        if service is not None:
            service.stop_auto_sync_loop()


app = FastAPI(title="Hive API", version="0.1.0", lifespan=lifespan)
app.state.limiter = limiter

app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.CORS_ORIGIN],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.add_exception_handler(APIError, api_error_handler)
app.add_exception_handler(HTTPException, http_exception_handler)
app.add_exception_handler(Exception, unhandled_exception_handler)
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

app.include_router(auth.router)
app.include_router(admin.router)
app.include_router(admin_parts.router)
app.include_router(control_data.router)
app.include_router(analytics.router)
app.include_router(machines.router)
app.include_router(machine_config_backups.router)
app.include_router(machine_lookup.router)
app.include_router(installs.router)
app.include_router(devices.router)
app.include_router(machine_sync.router)
app.include_router(profiles.router)
app.include_router(upload.router)
app.include_router(samples.router)
app.include_router(review.router)
app.include_router(sets.router)
app.include_router(set_instances.router)
app.include_router(stats.router)
app.include_router(models_router.router)
app.include_router(machine_models.router)
app.include_router(machine_parts.router)
app.include_router(machine_parts.catalog_router)
app.include_router(piece_color_labels.router)
app.include_router(color_models.router)
app.include_router(color_predict.router)
app.include_router(public_stats.router)
app.include_router(public_catalog.router)
app.include_router(link_models.router)
app.include_router(api_keys.router)
app.include_router(teacher.router)
app.include_router(leaderboard.router)
app.include_router(ai_models.router)
app.include_router(ai_usage.router)


@app.get("/api/health")
def health(db: Session = Depends(get_db)):
    # The round-trip is the point: a health check that touches nothing reports
    # a sick service as healthy. A dead DB raises (non-2xx); an exhausted pool
    # or starved worker hangs, which the caller's timeout turns into a failure.
    db.execute(text("SELECT 1"))
    return {"ok": True, "service": "hive-backend", "database": "ok"}
