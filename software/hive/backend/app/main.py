from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from slowapi import Limiter
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address

from sqlalchemy import text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from app import background, roles
from app.config import settings
from app.deps import get_db
from app.errors import (
    APIError,
    api_error_handler,
    http_exception_handler,
    operational_error_handler,
    unhandled_exception_handler,
)
from app.logging_config import configure_app_logging
from app.middleware.request_timing import RequestTimingMiddleware
from app.rate_limiting import rate_limit_exceeded_handler
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
    jobs,
    leaderboard,
    link_models,
    machine_config_backups,
    machine_defaults,
    machine_lookup,
    machine_models,
    machine_parts,
    machine_sync,
    machines,
    model_defaults,
    models as models_router,
    piece_color_labels,
    agent,
    kits,
    profiles,
    records,
    public_catalog,
    public_stats,
    review,
    samples,
    stats,
    swatch_models,
    teacher,
    upload,
)

configure_app_logging()

limiter = Limiter(key_func=get_remote_address)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    # The background workers start here only in HIVE_ROLE=all; a web process
    # starts none (app.background, agent-docs/process-roles.md).
    if not roles.serves_requests():
        raise RuntimeError(
            "HIVE_ROLE=worker is the background worker process: run `python -m app.worker`, "
            "not the web app."
        )
    background.start()
    try:
        yield
    finally:
        background.stop()


app = FastAPI(title="Hive API", version="0.1.0", lifespan=lifespan)
app.state.limiter = limiter

app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.CORS_ORIGIN],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(RequestTimingMiddleware)  # added last, so outermost: app/middleware/request_timing.py

app.add_exception_handler(APIError, api_error_handler)
app.add_exception_handler(HTTPException, http_exception_handler)
app.add_exception_handler(OperationalError, operational_error_handler)
app.add_exception_handler(Exception, unhandled_exception_handler)
app.add_exception_handler(RateLimitExceeded, rate_limit_exceeded_handler)

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
app.include_router(kits.router)
app.include_router(records.router)
app.include_router(agent.router)
app.include_router(upload.router)
app.include_router(samples.router)
app.include_router(review.router)
app.include_router(stats.router)
app.include_router(models_router.router)
app.include_router(model_defaults.router)
app.include_router(machine_defaults.router)
app.include_router(machine_models.router)
app.include_router(machine_parts.router)
app.include_router(machine_parts.catalog_router)
app.include_router(piece_color_labels.router)
app.include_router(color_models.router)
app.include_router(color_predict.router)
app.include_router(public_stats.router)
app.include_router(public_catalog.router)
app.include_router(link_models.router)
app.include_router(swatch_models.router)
app.include_router(swatch_models.sample_router)
app.include_router(jobs.router)
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
