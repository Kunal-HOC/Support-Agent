"""Application settings.

Every setting is required and has no default. If any are missing or invalid,
``load_settings`` raises a single ``ConfigError`` that lists all of them.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path
from typing import Annotated, Any, Literal, Self

import tiktoken
from pydantic import Field, SecretStr, ValidationError, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

AppEnv = Literal["development", "test", "production"]
LogLevel = Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]
EmbeddingProvider = Literal["openai"]
ChunkingStrategy = Literal["heading", "fixed"]

DATABASE_URL_SCHEME = "postgresql+psycopg://"
# pgvector cannot build an HNSW index on a `vector` column above 2000 dimensions.
MAX_EMBEDDING_DIMENSION = 2000
# OpenAI accepts at most 2048 inputs per embeddings request.
MAX_EMBEDDING_BATCH_SIZE = 2048


def find_repo_root(start: Path) -> Path | None:
    """Return the nearest ancestor of ``start`` that contains a ``.git`` entry."""
    for candidate in (start, *start.parents):
        if (candidate / ".git").exists():
            return candidate
    return None


REPO_ROOT = find_repo_root(Path(__file__).resolve().parent)


class Settings(BaseSettings):
    """All settings used by M1. Later milestones add their own keys."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        frozen=True,
    )

    # M1
    DATABASE_URL: str
    EMBEDDING_DIMENSION: int = Field(ge=1, le=MAX_EMBEDDING_DIMENSION)
    APP_ENV: AppEnv
    LOG_LEVEL: LogLevel

    # M2: uploads
    UPLOAD_DIR: Path
    MAX_UPLOAD_BYTES: int = Field(ge=1)
    MAX_PAGES: int = Field(ge=1)
    SOP_CATEGORIES: Annotated[tuple[str, ...], NoDecode]

    # M2: embeddings
    EMBEDDING_PROVIDER: EmbeddingProvider
    EMBEDDING_MODEL: str = Field(min_length=1)
    OPENAI_API_KEY: SecretStr
    EMBEDDING_BATCH_SIZE: int = Field(ge=1, le=MAX_EMBEDDING_BATCH_SIZE)

    # M2: chunking
    CHUNKING_STRATEGY: ChunkingStrategy
    CHUNK_MAX_TOKENS: int = Field(ge=1)
    CHUNK_OVERLAP_TOKENS: int = Field(ge=0)
    TOKENIZER_ENCODING: str

    @field_validator("DATABASE_URL")
    @classmethod
    def _check_database_url(cls, value: str) -> str:
        # The message deliberately does not echo the value: it may hold a password.
        if not value.startswith(DATABASE_URL_SCHEME):
            raise ValueError(f"must start with '{DATABASE_URL_SCHEME}'")
        return value

    @field_validator("UPLOAD_DIR")
    @classmethod
    def _check_upload_dir(cls, value: Path) -> Path:
        if not value.is_absolute():
            raise ValueError("must be an absolute path")
        resolved = value.resolve()
        if REPO_ROOT is not None and resolved.is_relative_to(REPO_ROOT):
            raise ValueError("must be outside the repository")
        if not resolved.is_dir():
            raise ValueError("must be an existing directory")
        if not _is_writable(resolved):
            raise ValueError("must be writable")
        return resolved

    @field_validator("SOP_CATEGORIES", mode="before")
    @classmethod
    def _split_categories(cls, value: object) -> object:
        if isinstance(value, str):
            return tuple(part.strip() for part in value.split(","))
        return value

    @field_validator("SOP_CATEGORIES")
    @classmethod
    def _check_categories(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        cleaned = tuple(item.strip() for item in value)
        if not cleaned or any(not item for item in cleaned):
            raise ValueError("must be a comma-separated list of non-empty names")
        if len(set(cleaned)) != len(cleaned):
            raise ValueError("must not contain duplicates")
        return cleaned

    @field_validator("OPENAI_API_KEY")
    @classmethod
    def _check_api_key(cls, value: SecretStr) -> SecretStr:
        if not value.get_secret_value().strip():
            raise ValueError("must not be empty")
        return value

    @field_validator("TOKENIZER_ENCODING")
    @classmethod
    def _check_encoding(cls, value: str) -> str:
        names = tiktoken.list_encoding_names()
        if value not in names:
            raise ValueError(f"must be one of: {', '.join(sorted(names))}")
        return value

    @model_validator(mode="after")
    def _check_overlap(self) -> Self:
        if self.CHUNK_OVERLAP_TOKENS >= self.CHUNK_MAX_TOKENS:
            raise ValueError("must be less than CHUNK_MAX_TOKENS")
        return self


def _is_writable(directory: Path) -> bool:
    if not os.access(directory, os.W_OK):
        return False
    try:
        with tempfile.NamedTemporaryFile(dir=directory, prefix=".write-check-"):
            pass
    except OSError:
        return False
    return True


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
        # The only model-level (cross-field) check is the chunk overlap rule.
        key = str(error["loc"][0]) if error["loc"] else "CHUNK_OVERLAP_TOKENS"
        if error["type"] == "missing":
            missing.append(key)
        else:
            message = str(error["msg"]).removeprefix("Value error, ")
            invalid[key] = message
    return ConfigError(missing, invalid)
