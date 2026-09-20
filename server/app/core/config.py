from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

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

    # C++ engine
    engine_host: str = "engine"
    engine_port: int = 9000
    engine_timeout_seconds: float = 5.0

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
