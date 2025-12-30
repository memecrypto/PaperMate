from urllib.parse import urlparse
from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response, JSONResponse
from app.core.config import get_settings

settings = get_settings()

SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}


class CSRFMiddleware(BaseHTTPMiddleware):
    """
    CSRF protection middleware that validates Origin/Referer headers
    for state-changing requests (POST, PUT, PATCH, DELETE).
    """

    async def dispatch(self, request: Request, call_next) -> Response:
        if request.method in SAFE_METHODS:
            return await call_next(request)

        origin = request.headers.get("origin")
        referer = request.headers.get("referer")

        if origin:
            if not self._is_allowed_origin(origin):
                return JSONResponse(
                    status_code=403,
                    content={"detail": "CSRF validation failed: invalid origin"}
                )
        elif referer:
            parsed = urlparse(referer)
            referer_origin = f"{parsed.scheme}://{parsed.netloc}"
            if not self._is_allowed_origin(referer_origin):
                return JSONResponse(
                    status_code=403,
                    content={"detail": "CSRF validation failed: invalid referer"}
                )
        else:
            has_auth_cookie = "access_token" in request.cookies
            if has_auth_cookie:
                return JSONResponse(
                    status_code=403,
                    content={"detail": "CSRF validation failed: missing origin/referer"}
                )

        return await call_next(request)

    def _is_allowed_origin(self, origin: str) -> bool:
        return origin in settings.allowed_origins
