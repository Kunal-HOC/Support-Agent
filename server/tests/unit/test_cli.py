from __future__ import annotations

import pytest

from server.cli import main


def test_startup_fails_listing_every_missing_key(capsys: pytest.CaptureFixture[str]) -> None:
    exit_code = main([])
    err = capsys.readouterr().err
    assert exit_code == 1
    assert "Missing required settings: APP_ENV, DATABASE_URL, EMBEDDING_DIMENSION, LOG_LEVEL" in err
    assert "Traceback" not in err
