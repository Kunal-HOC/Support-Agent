"""Pre-commit hook: block private data and document files from being committed.

Blocked (paths compared case-insensitively, at any depth):
- ``.env`` and ``.env.*`` files, except ``.env.example``
- anything inside a ``data/``, ``uploads/`` or ``evals/private/`` directory
- ``.pdf .doc .docx .odt .rtf .pages`` files outside a ``tests/fixtures/`` directory

Usage: ``python scripts/check_forbidden_files.py <path> [<path> ...]``
Exits 1 and lists every blocked path if any are found.
"""

from __future__ import annotations

import sys
from collections.abc import Sequence
from pathlib import PurePosixPath

BLOCKED_DIRS: tuple[tuple[str, ...], ...] = (("data",), ("uploads",), ("evals", "private"))
DOCUMENT_EXTENSIONS = frozenset({".pdf", ".doc", ".docx", ".odt", ".rtf", ".pages"})
FIXTURES_DIR: tuple[str, ...] = ("tests", "fixtures")
ENV_EXAMPLE = ".env.example"


def _contains(parts: Sequence[str], sequence: Sequence[str]) -> bool:
    size = len(sequence)
    return any(tuple(parts[i : i + size]) == tuple(sequence) for i in range(len(parts) - size + 1))


def reason_blocked(path: str) -> str | None:
    """Return why ``path`` must not be committed, or None if it is allowed."""
    pure = PurePosixPath(path.replace("\\", "/"))
    parts = [p.lower() for p in pure.parts]
    if not parts:
        return None
    name = parts[-1]
    directories = parts[:-1]

    if (name == ".env" or name.startswith(".env.")) and name != ENV_EXAMPLE:
        return "environment file"
    for blocked in BLOCKED_DIRS:
        if _contains(directories, blocked):
            return f"inside a private '{'/'.join(blocked)}/' directory"
    if pure.suffix.lower() in DOCUMENT_EXTENSIONS and not _contains(directories, FIXTURES_DIR):
        return "document file outside tests/fixtures/"
    return None


def main(argv: Sequence[str] | None = None) -> int:
    paths = list(sys.argv[1:] if argv is None else argv)
    blocked = [(p, r) for p in paths if (r := reason_blocked(p)) is not None]
    if not blocked:
        return 0
    print("Commit blocked: these files must not be committed:", file=sys.stderr)
    for path, reason in blocked:
        print(f"  - {path} ({reason})", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
