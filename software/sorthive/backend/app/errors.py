from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse


class APIError(HTTPException):
    def __init__(self, status_code: int, error: str, code: str):
        self.error_message = error
        self.error_code = code
        super().__init__(status_code=status_code, detail=error)


async def api_error_handler(request: Request, exc: APIError) -> JSONResponse:
    return JSONResponse(
        status_code=exc.status_code,
        content={"ok": False, "error": exc.error_message, "code": exc.error_code},
    )


async def http_exception_handler(request: Request, exc: HTTPException) -> JSONResponse:
    return JSONResponse(
        status_code=exc.status_code,
        content={"ok": False, "error": exc.detail, "code": "HTTP_ERROR"},
    )
