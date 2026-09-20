import os

from fastapi import APIRouter, Response

from app.core.config import get_settings
from app.core.database import check_database_connection
from app.services.engine_client import get_engine_client

router = APIRouter(prefix="/api", tags=["health"])

settings = get_settings()


def check_database() -> bool:
    return check_database_connection()


def check_engine() -> bool:
    return get_engine_client().check_health()


def check_storage() -> bool:
    try:
        os.makedirs(settings.storage_root, exist_ok=True)
        return os.access(settings.storage_root, os.W_OK)
    except OSError:
        return False


@router.get("/health")
def health(response: Response) -> dict[str, str]:
    components = {
        "database": check_database(),
        "engine": check_engine(),
        "storage": check_storage(),
    }
    healthy = all(components.values())

    response.status_code = 200 if healthy else 503

    return {
        "status": "healthy" if healthy else "unhealthy",
        **{name: "healthy" if ok else "unhealthy" for name, ok in components.items()},
    }
