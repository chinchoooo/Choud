import asyncio
import contextlib
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api import (
    admin,
    archive,
    auth,
    files,
    folders,
    health,
    insights,
    instance,
    invites,
    library,
    media,
    public_shares,
    rewind,
    search,
    shares,
    sync,
    trash,
    two_factor,
    uploads,
    versions,
)
from app.core.config import enforce_safe_settings, get_settings
from app.core.logging import configure_logging
from app.core.maintenance import index_loop, maintenance_loop, thumbnail_loop
from app.services.errors import PayloadTooLargeError, QuotaError

settings = get_settings()
configure_logging(settings.backend_log_level)

enforce_safe_settings(settings)


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    """Starts the housekeeping loop with the app and stops it on shutdown."""
    tasks = []
    if settings.maintenance_interval_seconds > 0:
        tasks.append(asyncio.create_task(maintenance_loop(settings.maintenance_interval_seconds)))
    if settings.index_interval_seconds > 0:
        tasks.append(asyncio.create_task(index_loop(settings.index_interval_seconds)))
    if settings.thumb_interval_seconds > 0:
        tasks.append(asyncio.create_task(thumbnail_loop(settings.thumb_interval_seconds)))
    try:
        yield
    finally:
        for task in tasks:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task


app = FastAPI(title="Personal Cloud API", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(QuotaError)
async def quota_exceeded(_: Request, exc: QuotaError) -> JSONResponse:
    """Every upload path (plain, chunked, sync) shares this one 413."""
    return JSONResponse(status_code=413, content={"detail": str(exc)})


@app.exception_handler(PayloadTooLargeError)
async def payload_too_large(_: Request, exc: PayloadTooLargeError) -> JSONResponse:
    return JSONResponse(status_code=413, content={"detail": str(exc)})


app.include_router(health.router)
app.include_router(auth.router)
app.include_router(folders.router)
app.include_router(files.router)
app.include_router(search.router)
app.include_router(uploads.router)
app.include_router(versions.router)
app.include_router(sync.router)
app.include_router(trash.router)
app.include_router(media.router)
app.include_router(library.router)
app.include_router(shares.router)
app.include_router(instance.router)
app.include_router(invites.router)
app.include_router(rewind.router)
app.include_router(insights.router)
app.include_router(admin.router)
app.include_router(archive.router)
app.include_router(two_factor.router)
app.include_router(public_shares.router)

# The shares router is added when its phase lands (see docs/architecture.md).
