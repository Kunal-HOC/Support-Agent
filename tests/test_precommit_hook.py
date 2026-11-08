from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path
from types import ModuleType

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "scripts" / "check_forbidden_files.py"


def _load_hook() -> ModuleType:
    spec = importlib.util.spec_from_file_location("check_forbidden_files", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


hook = _load_hook()


@pytest.mark.parametrize(
    "path",
    [
        ".env",
        "server/.env",
        ".env.local",
        ".ENV",
        "data/notes.txt",
        "data/sub/file.csv",
        "server/data/x.json",
        "uploads/file.txt",
        "server/uploads/a.bin",
        "evals/private/cases.jsonl",
        "core/evals/private/a.txt",
        "DATA/notes.txt",
        "docs/manual.pdf",
        "manual.PDF",
        "a.doc",
        "a.docx",
        "a.odt",
        "a.rtf",
        "a.pages",
        "fixtures/a.pdf",
        "tests/a.pdf",
        "core\\docs\\guide.docx",
    ],
)
def test_blocked(path: str) -> None:
    assert hook.reason_blocked(path) is not None


@pytest.mark.parametrize(
    "path",
    [
        ".env.example",
        "server/.env.example",
        "README.md",
        "core/src/core/config.py",
        "evals/public/cases.jsonl",
        "metadata/x.txt",
        "src/database/x.py",
        "tests/fixtures/sample.pdf",
        "core/tests/fixtures/sub/sample.DOCX",
        "server/tests/fixtures/a.rtf",
        "notes.txt",
    ],
)
def test_allowed(path: str) -> None:
    assert hook.reason_blocked(path) is None


def test_main_lists_every_blocked_path(capsys: pytest.CaptureFixture[str]) -> None:
    exit_code = hook.main(["data/a.txt", "README.md", "x.pdf"])
    err = capsys.readouterr().err
    assert exit_code == 1
    assert "data/a.txt" in err
    assert "x.pdf" in err
    assert "README.md" not in err


def test_main_passes_clean_paths() -> None:
    assert hook.main(["README.md", "core/src/core/db.py"]) == 0


def test_script_runs_as_command() -> None:
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "uploads/a.txt"], capture_output=True, text=True
    )
    assert result.returncode == 1
    assert "uploads/a.txt" in result.stderr
