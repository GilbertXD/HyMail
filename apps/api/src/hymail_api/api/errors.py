import logging

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

logger = logging.getLogger(__name__)


class UnhandledErrorMiddleware(BaseHTTPMiddleware):
    """Turn an unhandled exception into an ordinary 500 response.

    Starlette's own ``ServerErrorMiddleware`` sits *outside* ``CORSMiddleware``,
    so the 500 it produces carries no CORS headers. A browser then rejects the
    response before JavaScript can read it and reports a bare
    "Failed to fetch" — hiding the actual error behind what looks like a
    network problem.

    Catching here instead means the response travels back out through
    ``CORSMiddleware``, arrives with proper headers, and the client sees a
    real 500 while the traceback goes to the server log.
    """

    async def dispatch(self, request: Request, call_next):
        try:
            return await call_next(request)
        except Exception:
            logger.exception(
                "unhandled error: %s %s",
                request.method,
                request.url.path,
            )
            return JSONResponse(
                {"detail": "internal server error"},
                status_code=500,
            )
