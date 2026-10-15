import asyncio
import contextlib
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api import (
    auth,
    files,
    folders,
    health,
    library,
    media,
    search,
    sync,
    trash,
    uploads,
    versions,
)
from app.core.config import enforce_safe_settings, get_settings
from app.core.logging import configure_logging
from app.core.maintenance import maintenance_loop
from app.services.errors import QuotaError

settings = get_settings()
configure_logging(settings.backend_log_level)

enforce_safe_settings(settings)


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    """Starts the housekeeping loop with the app and stops it on shutdown."""
    task = None
    if settings.maintenance_interval_seconds > 0:
        task = asyncio.create_task(maintenance_loop(settings.maintenance_interval_seconds))
    try:
        yield
    finally:
        if task is not None:
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

# The shares router is added when its phase lands (see docs/architecture.md).
