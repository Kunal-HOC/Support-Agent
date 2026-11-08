"""Track the heading hierarchy while walking a document."""

from __future__ import annotations


class SectionTracker:
    """Keeps the current heading path: a new heading closes deeper or equal levels."""

    def __init__(self) -> None:
        self._stack: list[tuple[int, str]] = []

    def heading(self, level: int, title: str) -> None:
        while self._stack and self._stack[-1][0] >= level:
            self._stack.pop()
        self._stack.append((level, title.strip()))

    @property
    def path(self) -> tuple[str, ...]:
        return tuple(title for _, title in self._stack)
