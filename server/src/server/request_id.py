"""Request id handling and the last-resort error boundary.

``RequestIdMiddleware`` is a pure ASGI middleware that:
- reuses a safe incoming ``X-Request-ID`` or generates a UUID4,
- adds ``X-Request-ID`` to every response,
- turns any unhandled exception into an ``internal_error`` response and logs
  the traceback on the server only.
"""

from __future__ import annotations

import logging
import re
import uuid
from contextvars import ContextVar

from starlette.datastructures import Headers, MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

logger = logging.getLogger(__name__)

REQUEST_ID_HEADER = "X-Request-ID"
# Incoming ids are reused only if they look safe to echo and log.
_SAFE_REQUEST_ID = re.compile(r"^[A-Za-z0-9._-]{1,128}$")

_request_id: ContextVar[str] = ContextVar("request_id", default="")


def get_request_id() -> str:
    return _request_id.get()


def _choose_request_id(incoming: str | None) -> str:
    if incoming and _SAFE_REQUEST_ID.fullmatch(incoming):
        return incoming
    return str(uuid.uuid4())


class RequestIdMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        request_id = _choose_request_id(Headers(scope=scope).get(REQUEST_ID_HEADER))
        token = _request_id.set(request_id)
        response_started = False

        async def send_with_request_id(message: Message) -> None:
            nonlocal response_started
            if message["type"] == "http.response.start":
                response_started = True
                headers = MutableHeaders(scope=message)
                headers[REQUEST_ID_HEADER] = request_id
            await send(message)

        try:
            await self.app(scope, receive, send_with_request_id)
        except Exception:
            logger.exception("Unhandled error (request_id=%s)", request_id)
            if response_started:
                raise
            # Imported here to avoid a circular import with server.errors.
            from server.errors import internal_error_response

            await internal_error_response()(scope, receive, send_with_request_id)
        finally:
            _request_id.reset(token)
