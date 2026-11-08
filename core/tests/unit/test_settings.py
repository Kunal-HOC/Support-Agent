from __future__ import annotations

from pathlib import Path

import pytest

from core.config import ConfigError, Settings, load_settings

ALL_KEYS = ["APP_ENV", "DATABASE_URL", "EMBEDDING_DIMENSION", "LOG_LEVEL"]
VALID_URL = "postgresql+psycopg://user:pass@localhost:5432/db"


def _set_env(monkeypatch: pytest.MonkeyPatch, **values: str) -> None:
    for key, value in values.items():
        monkeypatch.setenv(key, value)


def test_all_missing_keys_are_reported_at_once() -> None:
    with pytest.raises(ConfigError) as info:
        load_settings(env_file=None)
    assert info.value.missing == ALL_KEYS
    assert info.value.invalid == {}
    assert (
        "Missing required settings: APP_ENV, DATABASE_URL, EMBEDDING_DIMENSION, LOG_LEVEL"
        in str(info.value)
    )


def test_only_the_missing_keys_are_reported(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_env(monkeypatch, DATABASE_URL=VALID_URL)
    with pytest.raises(ConfigError) as info:
        load_settings(env_file=None)
    assert info.value.missing == ["APP_ENV", "EMBEDDING_DIMENSION", "LOG_LEVEL"]


def test_missing_and_invalid_are_reported_together(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_env(monkeypatch, APP_ENV="staging", LOG_LEVEL="info")
    with pytest.raises(ConfigError) as info:
        load_settings(env_file=None)
    assert info.value.missing == ["DATABASE_URL", "EMBEDDING_DIMENSION"]
    assert sorted(info.value.invalid) == ["APP_ENV", "LOG_LEVEL"]
    message = str(info.value)
    assert "Missing required settings: DATABASE_URL, EMBEDDING_DIMENSION" in message
    assert "APP_ENV:" in message and "LOG_LEVEL:" in message


@pytest.mark.parametrize("dimension", ["0", "2001", "-5", "abc", "7.5", ""])
def test_invalid_embedding_dimension(monkeypatch: pytest.MonkeyPatch, dimension: str) -> None:
    _set_env(
        monkeypatch,
        DATABASE_URL=VALID_URL,
        EMBEDDING_DIMENSION=dimension,
        APP_ENV="test",
        LOG_LEVEL="INFO",
    )
    with pytest.raises(ConfigError) as info:
        load_settings(env_file=None)
    assert list(info.value.invalid) == ["EMBEDDING_DIMENSION"]


def test_database_url_scheme_is_checked_without_leaking_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_env(
        monkeypatch,
        DATABASE_URL="postgresql://user:topsecret@localhost/db",
        EMBEDDING_DIMENSION="8",
        APP_ENV="test",
        LOG_LEVEL="INFO",
    )
    with pytest.raises(ConfigError) as info:
        load_settings(env_file=None)
    assert list(info.value.invalid) == ["DATABASE_URL"]
    assert "topsecret" not in str(info.value)


@pytest.mark.parametrize("app_env", ["development", "test", "production"])
@pytest.mark.parametrize("log_level", ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"])
def test_valid_settings_from_environment(
    monkeypatch: pytest.MonkeyPatch, app_env: str, log_level: str
) -> None:
    _set_env(
        monkeypatch,
        DATABASE_URL=VALID_URL,
        EMBEDDING_DIMENSION="2000",
        APP_ENV=app_env,
        LOG_LEVEL=log_level,
    )
    settings = load_settings(env_file=None)
    assert settings == Settings(
        _env_file=None,
        DATABASE_URL=VALID_URL,
        EMBEDDING_DIMENSION=2000,
        APP_ENV=app_env,  # type: ignore[arg-type]
        LOG_LEVEL=log_level,  # type: ignore[arg-type]
    )


def test_env_file_is_ignored_when_disabled() -> None:
    Path(".env").write_text("APP_ENV=test\n", encoding="utf-8")  # in tmp_path (autouse fixture)
    with pytest.raises(ConfigError) as info:
        load_settings(env_file=None)
    assert "APP_ENV" in info.value.missing


def test_env_file_is_read_when_given(tmp_path: Path) -> None:
    env_file = tmp_path / "settings.env"
    env_file.write_text(
        f"DATABASE_URL={VALID_URL}\nEMBEDDING_DIMENSION=8\nAPP_ENV=test\nLOG_LEVEL=INFO\n"
        "SOME_LATER_KEY=ignored\n",
        encoding="utf-8",
    )
    settings = load_settings(env_file=env_file)
    assert settings.EMBEDDING_DIMENSION == 8
