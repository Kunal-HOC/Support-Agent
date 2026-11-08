"""Logging setup driven by the LOG_LEVEL setting."""

from __future__ import annotations

import logging

from core.config import LogLevel

LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s: %(message)s"


def configure_logging(level: LogLevel) -> None:
    """Configure the root logger to write to stderr at ``level``."""
    logging.basicConfig(level=level, format=LOG_FORMAT, force=True)
