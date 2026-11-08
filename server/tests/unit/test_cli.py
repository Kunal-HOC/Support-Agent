from __future__ import annotations

import pytest

from server.cli import main
from testing_support import SETTING_KEYS


def test_startup_fails_listing_every_missing_key(capsys: pytest.CaptureFixture[str]) -> None:
    exit_code = main([])
    err = capsys.readouterr().err
    assert exit_code == 1
    assert f"Missing required settings: {', '.join(sorted(SETTING_KEYS))}" in err
    assert "Traceback" not in err
