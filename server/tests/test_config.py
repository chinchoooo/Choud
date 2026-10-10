"""Production refuses placeholder secrets; development only warns."""

import logging

import pytest

from app.core.config import MIN_SECRET_LENGTH, Settings, enforce_safe_settings

STRONG_SECRET = "x" * MIN_SECRET_LENGTH
STRONG_PASSWORD = "a-real-database-password"


def _settings(**overrides) -> Settings:
    base = {
        "environment": "production",
        "jwt_secret": STRONG_SECRET,
        "postgres_password": STRONG_PASSWORD,
    }
    return Settings(_env_file=None, **{**base, **overrides})


def test_strong_secrets_pass_in_production() -> None:
    enforce_safe_settings(_settings())


@pytest.mark.parametrize(
    "overrides, expected",
    [
        ({"jwt_secret": "changeme-generate-a-long-random-string"}, "JWT_SECRET"),
        ({"jwt_secret": "dev-only-insecure-jwt-secret-do-not-deploy"}, "JWT_SECRET"),
        ({"jwt_secret": "short"}, "JWT_SECRET"),
        ({"postgres_password": "changeme"}, "POSTGRES_PASSWORD"),
        ({"postgres_password": "dev-only-password"}, "POSTGRES_PASSWORD"),
    ],
)
def test_production_refuses_placeholder_secrets(overrides, expected) -> None:
    with pytest.raises(RuntimeError, match=expected):
        enforce_safe_settings(_settings(**overrides))


def test_production_error_lists_every_problem() -> None:
    settings = _settings(jwt_secret="changeme", postgres_password="changeme")

    with pytest.raises(RuntimeError) as excinfo:
        enforce_safe_settings(settings)

    assert "JWT_SECRET" in str(excinfo.value)
    assert "POSTGRES_PASSWORD" in str(excinfo.value)


def test_development_only_warns(caplog: pytest.LogCaptureFixture) -> None:
    settings = _settings(environment="development", jwt_secret="changeme")

    with caplog.at_level(logging.WARNING):
        enforce_safe_settings(settings)  # must not raise

    assert "insecure configuration" in caplog.text


def test_environment_defaults_to_development() -> None:
    assert Settings(_env_file=None).environment == "development"
