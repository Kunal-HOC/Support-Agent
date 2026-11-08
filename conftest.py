"""Shared pytest fixtures.

Settings are always injected by fixtures. Real ``.env`` files are never read:
the app-setting environment variables are cleared for every test, each test
runs in an empty temporary directory, and tests pass ``env_file=None``.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from core.config import Settings, load_settings
from testing_support import SETTING_KEYS, TEST_DATABASE_URL_VAR, VALID_VALUES, MakeSettings


@pytest.fixture(autouse=True)
def _isolated_settings_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Iterator[None]:
    """Remove app settings from the environment and run in an empty directory."""
    for key in SETTING_KEYS:
        monkeypatch.delenv(key, raising=False)
    monkeypatch.chdir(tmp_path)
    yield


@pytest.fixture
def make_settings() -> MakeSettings:
    """Build valid ``Settings``; keyword overrides replace individual values."""

    def _make(**overrides: Any) -> Settings:
        return load_settings(env_file=None, **{**VALID_VALUES, **overrides})

    return _make


@pytest.fixture
def test_database_url() -> str:
    """URL of the sandbox Postgres + pgvector DB. DB tests fail if it is not set."""
    url = os.environ.get(TEST_DATABASE_URL_VAR)
    if not url:
        pytest.fail(f"{TEST_DATABASE_URL_VAR} must be set to run tests marked 'db'.")
    return url
