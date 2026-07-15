from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address

from app.config import settings
from app.errors import APIError, api_error_handler, http_exception_handler, unhandled_exception_handler
from app.routers import (
    admin,
    admin_parts,
    analytics,
    api_keys,
    auth,
    color_models,
    color_predict,
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
    public_stats,
    review,
    samples,
    sets,
    stats,
    teacher,
    upload,
)
from app.services.profile_catalog import get_existing_profile_catalog_service, get_profile_catalog_service
from app.services.condition_worker import get_condition_worker
from app.services.machine_stats import get_machine_stats_worker
from app.services.teacher_worker import get_teacher_worker

limiter = Limiter(key_func=get_remote_address)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    if settings.PROFILE_CATALOG_AUTO_SYNC_ENABLED and settings.REBRICKABLE_API_KEY:
        get_profile_catalog_service().start_auto_sync_loop()
    get_teacher_worker().start()
    get_condition_worker().start()
    get_machine_stats_worker().start()
    try:
        yield
    finally:
        get_teacher_worker().stop()
        get_condition_worker().stop()
        get_machine_stats_worker().stop()
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
app.include_router(analytics.router)
app.include_router(machines.router)
app.include_router(machine_config_backups.router)
app.include_router(machine_lookup.router)
app.include_router(installs.router)
app.include_router(machine_sync.router)
app.include_router(profiles.router)
app.include_router(upload.router)
app.include_router(samples.router)
app.include_router(review.router)
app.include_router(sets.router)
app.include_router(stats.router)
app.include_router(models_router.router)
app.include_router(machine_models.router)
app.include_router(machine_parts.router)
app.include_router(piece_color_labels.router)
app.include_router(color_models.router)
app.include_router(color_predict.router)
app.include_router(public_stats.router)
app.include_router(link_models.router)
app.include_router(api_keys.router)
app.include_router(teacher.router)
app.include_router(leaderboard.router)


@app.get("/api/health")
def health():
    return {"ok": True, "service": "hive-backend"}
