import logging

from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse

logger = logging.getLogger(__name__)


class APIError(HTTPException):
    def __init__(self, status_code: int, error: str, code: str, details: object | None = None):
        self.error_message = error
        self.error_code = code
        # Everything wrong at once (each rule's problem, say), for a client
        # that fixes them all before trying again.
        self.error_details = details
        super().__init__(status_code=status_code, detail=error)


async def api_error_handler(request: Request, exc: APIError) -> JSONResponse:
    content: dict[str, object] = {"ok": False, "error": exc.error_message, "code": exc.error_code}
    if exc.error_details is not None:
        content["details"] = exc.error_details
    return JSONResponse(status_code=exc.status_code, content=content)


async def http_exception_handler(request: Request, exc: HTTPException) -> JSONResponse:
    return JSONResponse(
        status_code=exc.status_code,
        content={"ok": False, "error": exc.detail, "code": "HTTP_ERROR"},
    )


# Postgres's SQLSTATE for a statement it cancelled: what a request's
# statement_timeout (app.deps.get_db) raises when it runs out.
_QUERY_CANCELED = "57014"


def is_statement_timeout(exc: BaseException) -> bool:
    return getattr(getattr(exc, "orig", None), "pgcode", None) == _QUERY_CANCELED


async def operational_error_handler(request: Request, exc: Exception) -> JSONResponse:
    """A request that ran out of statement time is a 503 the client can tell
    apart from a crash; every other database error is a 500 as before."""
    if not is_statement_timeout(exc):
        return await unhandled_exception_handler(request, exc)
    limit_ms = getattr(request.state, "statement_timeout_ms", None)
    logger.warning(
        "Statement timeout (%s ms) on %s %s",
        limit_ms if limit_ms is not None else "?",
        request.method,
        request.url.path,
    )
    return JSONResponse(
        status_code=503,
        content={
            "ok": False,
            "error": "This took longer than a request may, so the server stopped it. Try again, or narrow it down.",
            "code": "STATEMENT_TIMEOUT",
        },
    )


async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    logger.exception(
        "Unhandled API exception on %s %s",
        request.method,
        request.url.path,
        exc_info=exc,
    )
    return JSONResponse(
        status_code=500,
        content={"ok": False, "error": "Internal server error", "code": "INTERNAL_SERVER_ERROR"},
    )
