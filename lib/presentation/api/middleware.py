from __future__ import annotations

import time

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from lib.core.logs import get_logger

logger = get_logger(__name__)


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    """Logs every HTTP request/response, generically (issue #40's system-wide follow-up to
    #38): individual routes already log the specific thing they did (a job created, a flow
    step run, ...), this covers what the individual routes don't bother repeating: which
    request came in, how long it took, and what it returned, for every route, present or
    future, without needing a matching log call added to each one by hand. A WebSocket
    connection (/logs/stream) never reaches here, ASGI routes it around HTTP middleware
    entirely, so there's no risk of this logging about itself."""

    async def dispatch(self, request: Request, call_next) -> Response:
        started_at = time.monotonic()
        logger.debug("--> %s %s", request.method, request.url.path)
        try:
            response = await call_next(request)
        except Exception:
            duration_ms = (time.monotonic() - started_at) * 1000
            logger.exception("%s %s raised an unhandled exception after %.0fms", request.method, request.url.path, duration_ms)
            raise
        duration_ms = (time.monotonic() - started_at) * 1000
        logger.info("<-- %s %s %s (%.0fms)", request.method, request.url.path, response.status_code, duration_ms)
        return response
