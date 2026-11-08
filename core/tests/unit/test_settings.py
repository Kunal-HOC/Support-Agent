from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from core.config import REPO_ROOT, ConfigError, load_settings
from testing_support import SETTING_KEYS, VALID_VALUES

ALL_KEYS = sorted(SETTING_KEYS)
VALID_URL = "postgresql+psycopg://user:pass@localhost:5432/db"


@pytest.fixture
def valid_env(monkeypatch: pytest.MonkeyPatch, upload_dir: Path) -> dict[str, str]:
    """Set every key to a valid value in the environment."""
    values = {key: str(value) for key, value in VALID_VALUES.items()}
    values["UPLOAD_DIR"] = str(upload_dir)
    for key, value in values.items():
        monkeypatch.setenv(key, value)
    return values


def _invalid_keys(**overrides: Any) -> list[str]:
    with pytest.raises(ConfigError) as info:
        load_settings(env_file=None, **overrides)
    assert info.value.missing == []
    return list(info.value.invalid)


def test_all_missing_keys_are_reported_at_once() -> None:
    with pytest.raises(ConfigError) as info:
        load_settings(env_file=None)
    assert info.value.missing == ALL_KEYS
    assert info.value.invalid == {}
    assert f"Missing required settings: {', '.join(ALL_KEYS)}" in str(info.value)


@pytest.mark.parametrize("absent", SETTING_KEYS)
def test_each_key_is_required(
    monkeypatch: pytest.MonkeyPatch, valid_env: dict[str, str], absent: str
) -> None:
    monkeypatch.delenv(absent)
    with pytest.raises(ConfigError) as info:
        load_settings(env_file=None)
    assert info.value.missing == [absent]


def test_missing_and_invalid_are_reported_together(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APP_ENV", "staging")
    monkeypatch.setenv("LOG_LEVEL", "info")
    with pytest.raises(ConfigError) as info:
        load_settings(env_file=None)
    assert info.value.missing == [k for k in ALL_KEYS if k not in {"APP_ENV", "LOG_LEVEL"}]
    assert sorted(info.value.invalid) == ["APP_ENV", "LOG_LEVEL"]
    message = str(info.value)
    assert "Missing required settings: CHUNKING_STRATEGY" in message
    assert "APP_ENV:" in message and "LOG_LEVEL:" in message


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("EMBEDDING_DIMENSION", "0"),
        ("EMBEDDING_DIMENSION", "2001"),
        ("EMBEDDING_DIMENSION", "abc"),
        ("EMBEDDING_DIMENSION", "7.5"),
        ("EMBEDDING_DIMENSION", ""),
        ("MAX_UPLOAD_BYTES", "0"),
        ("MAX_PAGES", "0"),
        ("SOP_CATEGORIES", ""),
        ("SOP_CATEGORIES", "IT,,HR"),
        ("SOP_CATEGORIES", "IT, IT"),
        ("EMBEDDING_PROVIDER", "voyage"),
        ("EMBEDDING_MODEL", ""),
        ("OPENAI_API_KEY", "  "),
        ("EMBEDDING_BATCH_SIZE", "0"),
        ("EMBEDDING_BATCH_SIZE", "2049"),
        ("CHUNKING_STRATEGY", "semantic"),
        ("CHUNK_MAX_TOKENS", "0"),
        ("CHUNK_OVERLAP_TOKENS", "-1"),
        ("CHUNK_OVERLAP_TOKENS", "200"),
        ("TOKENIZER_ENCODING", "not_an_encoding"),
        ("UPLOAD_DIR", "relative/path"),
    ],
)
def test_invalid_value_is_reported(
    monkeypatch: pytest.MonkeyPatch, valid_env: dict[str, str], key: str, value: str
) -> None:
    monkeypatch.setenv(key, value)
    assert _invalid_keys() == [key]


def test_overlap_must_be_less_than_max(
    monkeypatch: pytest.MonkeyPatch, valid_env: dict[str, str]
) -> None:
    monkeypatch.setenv("CHUNK_MAX_TOKENS", "50")
    monkeypatch.setenv("CHUNK_OVERLAP_TOKENS", "50")
    with pytest.raises(ConfigError) as info:
        load_settings(env_file=None)
    assert info.value.invalid == {"CHUNK_OVERLAP_TOKENS": "must be less than CHUNK_MAX_TOKENS"}


def test_upload_dir_inside_repo_is_refused(
    monkeypatch: pytest.MonkeyPatch, valid_env: dict[str, str]
) -> None:
    assert REPO_ROOT is not None
    monkeypatch.setenv("UPLOAD_DIR", str(REPO_ROOT / "server"))
    with pytest.raises(ConfigError) as info:
        load_settings(env_file=None)
    assert info.value.invalid == {"UPLOAD_DIR": "must be outside the repository"}


def test_upload_dir_must_exist(
    monkeypatch: pytest.MonkeyPatch, valid_env: dict[str, str], tmp_path: Path
) -> None:
    monkeypatch.setenv("UPLOAD_DIR", str(tmp_path / "missing"))
    with pytest.raises(ConfigError) as info:
        load_settings(env_file=None)
    assert info.value.invalid == {"UPLOAD_DIR": "must be an existing directory"}


def test_upload_dir_must_be_writable(
    monkeypatch: pytest.MonkeyPatch, valid_env: dict[str, str], upload_dir: Path
) -> None:
    monkeypatch.setattr("core.config._is_writable", lambda _path: False)
    with pytest.raises(ConfigError) as info:
        load_settings(env_file=None)
    assert info.value.invalid == {"UPLOAD_DIR": "must be writable"}


def test_database_url_scheme_is_checked_without_leaking_it(
    monkeypatch: pytest.MonkeyPatch, valid_env: dict[str, str]
) -> None:
    monkeypatch.setenv("DATABASE_URL", "postgresql://user:topsecret@localhost/db")
    with pytest.raises(ConfigError) as info:
        load_settings(env_file=None)
    assert list(info.value.invalid) == ["DATABASE_URL"]
    assert "topsecret" not in str(info.value)


def test_api_key_is_never_shown(valid_env: dict[str, str]) -> None:
    settings = load_settings(env_file=None)
    assert "sk-test-not-a-real-key" not in repr(settings)
    assert settings.OPENAI_API_KEY.get_secret_value() == "sk-test-not-a-real-key"


@pytest.mark.parametrize("app_env", ["development", "test", "production"])
@pytest.mark.parametrize("log_level", ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"])
def test_valid_settings_from_environment(
    monkeypatch: pytest.MonkeyPatch, valid_env: dict[str, str], app_env: str, log_level: str
) -> None:
    monkeypatch.setenv("APP_ENV", app_env)
    monkeypatch.setenv("LOG_LEVEL", log_level)
    settings = load_settings(env_file=None)
    assert app_env == settings.APP_ENV
    assert log_level == settings.LOG_LEVEL
    assert settings.SOP_CATEGORIES == ("Facilities", "IT", "HR")
    assert Path(valid_env["UPLOAD_DIR"]).resolve() == settings.UPLOAD_DIR


def test_categories_are_trimmed(monkeypatch: pytest.MonkeyPatch, valid_env: dict[str, str]) -> None:
    monkeypatch.setenv("SOP_CATEGORIES", " IT , Customer Care ")
    assert load_settings(env_file=None).SOP_CATEGORIES == ("IT", "Customer Care")


def test_env_file_is_ignored_when_disabled() -> None:
    Path(".env").write_text("APP_ENV=test\n", encoding="utf-8")  # in tmp_path (autouse fixture)
    with pytest.raises(ConfigError) as info:
        load_settings(env_file=None)
    assert "APP_ENV" in info.value.missing


def test_env_file_is_read_when_given(tmp_path: Path, upload_dir: Path) -> None:
    lines = [f"{key}={value}" for key, value in VALID_VALUES.items()]
    lines += [f"UPLOAD_DIR={upload_dir}", "SOME_LATER_KEY=ignored"]
    env_file = tmp_path / "settings.env"
    env_file.write_text("\n".join(lines) + "\n", encoding="utf-8")
    settings = load_settings(env_file=env_file)
    assert settings.EMBEDDING_DIMENSION == 8
