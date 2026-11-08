"""Application settings.

Every setting is required and has no default. If any are missing or invalid,
``load_settings`` raises a single ``ConfigError`` that lists all of them.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

from pydantic import Field, ValidationError, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

AppEnv = Literal["development", "test", "production"]
LogLevel = Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]

DATABASE_URL_SCHEME = "postgresql+psycopg://"
# pgvector cannot build an HNSW index on a `vector` column above 2000 dimensions.
MAX_EMBEDDING_DIMENSION = 2000


class Settings(BaseSettings):
    """All settings used by M1. Later milestones add their own keys."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        frozen=True,
    )

    DATABASE_URL: str
    EMBEDDING_DIMENSION: int = Field(ge=1, le=MAX_EMBEDDING_DIMENSION)
    APP_ENV: AppEnv
    LOG_LEVEL: LogLevel

    @field_validator("DATABASE_URL")
    @classmethod
    def _check_database_url(cls, value: str) -> str:
        # The message deliberately does not echo the value: it may hold a password.
        if not value.startswith(DATABASE_URL_SCHEME):
            raise ValueError(f"must start with '{DATABASE_URL_SCHEME}'")
        return value


class ConfigError(Exception):
    """Raised when settings are missing or invalid. Lists every problem at once."""

    def __init__(self, missing: list[str], invalid: dict[str, str]) -> None:
        self.missing = sorted(missing)
        self.invalid = dict(sorted(invalid.items()))
        super().__init__(self._render())

    def _render(self) -> str:
        lines = ["Invalid configuration."]
        if self.missing:
            lines.append(f"Missing required settings: {', '.join(self.missing)}")
        if self.invalid:
            lines.append("Invalid settings:")
            lines.extend(f"  - {key}: {reason}" for key, reason in self.invalid.items())
        return "\n".join(lines)


def load_settings(env_file: Path | None = Path(".env"), **values: Any) -> Settings:
    """Build ``Settings`` from the environment (and ``env_file`` if it exists).

    Pass ``env_file=None`` to ignore any ``.env`` file; tests always do this.
    Keyword ``values`` take priority over the environment.
    """
    try:
        return Settings(_env_file=env_file, **values)
    except ValidationError as exc:
        raise _to_config_error(exc) from None


def _to_config_error(exc: ValidationError) -> ConfigError:
    missing: list[str] = []
    invalid: dict[str, str] = {}
    for error in exc.errors():
        key = str(error["loc"][0]) if error["loc"] else "<settings>"
        if error["type"] == "missing":
            missing.append(key)
        else:
            message = str(error["msg"]).removeprefix("Value error, ")
            invalid[key] = message
    return ConfigError(missing, invalid)
