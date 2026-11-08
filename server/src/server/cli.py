"""`support-agent` command: load settings, then start the server."""

from __future__ import annotations

import argparse
import sys

import uvicorn

from core.config import ConfigError, load_settings
from server.main import create_app


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="support-agent", description="Run the Support Agent API.")
    parser.add_argument("--host", default="127.0.0.1", help="Bind address (uvicorn default).")
    parser.add_argument("--port", type=int, default=8000, help="Port (uvicorn default).")
    args = parser.parse_args(argv)

    try:
        settings = load_settings()
    except ConfigError as exc:
        print(exc, file=sys.stderr)
        return 1

    uvicorn.run(create_app(settings), host=args.host, port=args.port, log_config=None)
    return 0


def run() -> None:
    """Console-script entry point."""
    sys.exit(main())


if __name__ == "__main__":
    run()
