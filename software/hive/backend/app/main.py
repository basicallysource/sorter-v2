from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address

from app.config import settings
from app.errors import APIError, api_error_handler, http_exception_handler
from app.routers import admin, auth, machines, profiles, review, samples, sets, stats, upload
from app.services.profile_catalog import get_existing_profile_catalog_service, get_profile_catalog_service

limiter = Limiter(key_func=get_remote_address)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    if settings.PROFILE_CATALOG_AUTO_SYNC_ENABLED and settings.REBRICKABLE_API_KEY:
        get_profile_catalog_service().start_auto_sync_loop()
    try:
        yield
    finally:
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
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

app.include_router(auth.router)
app.include_router(admin.router)
app.include_router(machines.router)
app.include_router(profiles.router)
app.include_router(upload.router)
app.include_router(samples.router)
app.include_router(review.router)
app.include_router(sets.router)
app.include_router(stats.router)


@app.get("/api/health")
def health():
    return {"ok": True, "service": "hive-backend"}
