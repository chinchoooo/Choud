from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import auth, files, folders, health, search, uploads
from app.core.config import get_settings
from app.core.logging import configure_logging

settings = get_settings()
configure_logging(settings.backend_log_level)

app = FastAPI(title="Personal Cloud API", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health.router)
app.include_router(auth.router)
app.include_router(folders.router)
app.include_router(files.router)
app.include_router(search.router)
app.include_router(uploads.router)

# Routers for versions and shares are added as their respective phases
# land (see docs/architecture.md).
