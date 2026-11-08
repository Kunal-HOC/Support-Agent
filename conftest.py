"""Shared pytest fixtures.

Settings are always injected by fixtures. Real ``.env`` files are never read:
the app-setting environment variables are cleared for every test, each test
runs in an empty temporary directory, and tests pass ``env_file=None``.
"""

from __future__ import annotations

import hashlib
import os
import shutil
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from core.config import Settings, load_settings
from testing_support import (
    SETTING_KEYS,
    TEST_DATABASE_URL_VAR,
    TIKTOKEN_FIXTURE,
    TIKTOKEN_URL,
    VALID_VALUES,
    MakeSettings,
)


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption(
        "--run-openai",
        action="store_true",
        help="Run tests marked 'openai', which call the real OpenAI API.",
    )


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    if config.getoption("--run-openai"):
        return
    skip = pytest.mark.skip(reason="calls the real OpenAI API; run with --run-openai")
    for item in items:
        if "openai" in item.keywords:
            item.add_marker(skip)


@pytest.fixture(autouse=True)
def _isolated_settings_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Iterator[None]:
    """Remove app settings from the environment and run in an empty directory."""
    for key in SETTING_KEYS:
        monkeypatch.delenv(key, raising=False)
    monkeypatch.chdir(tmp_path)
    yield


@pytest.fixture
def upload_dir(tmp_path: Path) -> Path:
    """An empty, writable UPLOAD_DIR outside the repository."""
    directory = tmp_path / "upload-store"
    directory.mkdir()
    return directory


@pytest.fixture
def make_settings(upload_dir: Path) -> MakeSettings:
    """Build valid ``Settings``; keyword overrides replace individual values."""

    def _make(**overrides: Any) -> Settings:
        values = {**VALID_VALUES, "UPLOAD_DIR": str(upload_dir), **overrides}
        return load_settings(env_file=None, **values)

    return _make


@pytest.fixture
def test_database_url() -> str:
    """URL of the sandbox Postgres + pgvector DB. DB tests fail if it is not set."""
    url = os.environ.get(TEST_DATABASE_URL_VAR)
    if not url:
        pytest.fail(f"{TEST_DATABASE_URL_VAR} must be set to run tests marked 'db'.")
    return url


@pytest.fixture
def tiktoken_cache(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Serve cl100k_base from the committed fixture file, with no download.

    tiktoken looks in TIKTOKEN_CACHE_DIR for a file named after the SHA-1 of the
    encoding's URL.
    """
    if not TIKTOKEN_FIXTURE.is_file():
        pytest.fail(
            f"Missing {TIKTOKEN_FIXTURE.relative_to(TIKTOKEN_FIXTURE.parents[4])}. "
            f"Download it from {TIKTOKEN_URL} and commit it."
        )
    cache_dir = tmp_path / "tiktoken-cache"
    cache_dir.mkdir()
    cache_name = hashlib.sha1(TIKTOKEN_URL.encode()).hexdigest()
    shutil.copyfile(TIKTOKEN_FIXTURE, cache_dir / cache_name)
    monkeypatch.setenv("TIKTOKEN_CACHE_DIR", str(cache_dir))
    return cache_dir
