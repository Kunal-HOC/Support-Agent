"""Pre-commit hook: block private data and document files from being committed.

Blocked (paths compared case-insensitively):
- ``.env`` and ``.env.*`` files at any depth, except ``.env.example``
- anything inside a ``data/``, ``uploads/`` or ``evals/private/`` directory at
  the repo root or directly under a package root (``core/``, ``server/``,
  ``agents/``, ``mcp/``, ``client/``), e.g. ``server/uploads/``
- ``.pdf .doc .docx .odt .rtf .pages`` files at any depth outside a
  ``tests/fixtures/`` directory

Usage: ``python scripts/check_forbidden_files.py <path> [<path> ...]``
Exits 1 and lists every blocked path if any are found.
"""

from __future__ import annotations

import sys
from collections.abc import Sequence
from pathlib import PurePosixPath

BLOCKED_DIRS: tuple[tuple[str, ...], ...] = (("data",), ("uploads",), ("evals", "private"))
PACKAGE_ROOTS = frozenset({"core", "server", "agents", "mcp", "client"})
DOCUMENT_EXTENSIONS = frozenset({".pdf", ".doc", ".docx", ".odt", ".rtf", ".pages"})
FIXTURES_DIR: tuple[str, ...] = ("tests", "fixtures")
ENV_EXAMPLE = ".env.example"


def _contains(parts: Sequence[str], sequence: Sequence[str]) -> bool:
    size = len(sequence)
    return any(tuple(parts[i : i + size]) == tuple(sequence) for i in range(len(parts) - size + 1))


def _starts_with(parts: Sequence[str], prefix: Sequence[str]) -> bool:
    return tuple(parts[: len(prefix)]) == tuple(prefix)


def _in_private_dir(directories: Sequence[str], blocked: Sequence[str]) -> bool:
    """True if ``blocked`` sits at the repo root or directly under a package root."""
    if _starts_with(directories, blocked):
        return True
    return (
        len(directories) > 0
        and directories[0] in PACKAGE_ROOTS
        and _starts_with(directories[1:], blocked)
    )


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
        if _in_private_dir(directories, blocked):
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
