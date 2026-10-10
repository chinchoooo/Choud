import logging
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict

# Placeholders that appear in .env.example / old defaults. Running production
# with any of these means the secret is public (it is in the repository).
_INSECURE_SECRET_PREFIXES = ("changeme", "dev-only")
MIN_SECRET_LENGTH = 32


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # "production" turns the insecure-secret check below into a hard failure
    # (docker-compose.yml sets it; docker-compose.dev.yml sets "development").
    environment: str = "development"

    # PostgreSQL
    postgres_user: str = "cloud"
    postgres_password: str = "changeme"
    postgres_db: str = "personal_cloud"
    postgres_host: str = "postgres"
    postgres_port: int = 5432

    # Backend
    backend_host: str = "0.0.0.0"
    backend_port: int = 8000
    backend_log_level: str = "info"
    jwt_secret: str = "changeme-generate-a-long-random-string"
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 15
    refresh_token_expire_days: int = 7

    # Storage
    storage_root: str = "/data/cloud"
    default_storage_quota_bytes: int = 10 * 1024**3  # 10 GiB

    # Chunked uploads (Phase 5)
    upload_session_expire_hours: int = 24

    # Housekeeping loop inside the backend (app/core/maintenance.py). Seconds
    # between runs; 0 disables it.
    maintenance_interval_seconds: int = 3600

    # Auth endpoint rate limiting (app/core/rate_limit.py).
    rate_limit_enabled: bool = True

    # C++ engine
    engine_host: str = "engine"
    engine_port: int = 9000
    # Quick control calls (health, exists, delete, abandon).
    engine_timeout_seconds: float = 5.0
    # Calls that read or write whole files (hash, put, get, chunk write,
    # finalize). Hashing and reassembling a multi-GB upload takes far longer
    # than 5 s; a short timeout would turn a healthy engine into a spurious 502
    # after the work was already done.
    engine_data_timeout_seconds: float = 1800.0

    def insecure_settings(self) -> list[str]:
        """Human-readable problems that make these settings unsafe to deploy."""
        problems = []
        if self.jwt_secret.startswith(_INSECURE_SECRET_PREFIXES) or (
            len(self.jwt_secret) < MIN_SECRET_LENGTH
        ):
            problems.append(
                f"JWT_SECRET is a placeholder or shorter than {MIN_SECRET_LENGTH} characters"
            )
        if self.postgres_password.startswith(_INSECURE_SECRET_PREFIXES):
            problems.append("POSTGRES_PASSWORD is a placeholder")
        return problems

    @property
    def database_url(self) -> str:
        return (
            f"postgresql+psycopg2://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )

    @property
    def engine_base_url(self) -> str:
        return f"http://{self.engine_host}:{self.engine_port}"


@lru_cache
def get_settings() -> Settings:
    return Settings()


def enforce_safe_settings(settings: Settings) -> None:
    """Refuses to start in production with placeholder secrets.

    Anywhere else (development, tests) it only logs a warning, so a fresh
    clone still runs without any setup.
    """
    problems = settings.insecure_settings()
    if not problems:
        return
    message = "insecure configuration: " + "; ".join(problems)
    if settings.environment == "production":
        raise RuntimeError(f"{message}. Run scripts/setup.sh to generate real secrets.")
    logging.getLogger(__name__).warning(
        "%s (allowed because ENVIRONMENT=%s)", message, settings.environment
    )
