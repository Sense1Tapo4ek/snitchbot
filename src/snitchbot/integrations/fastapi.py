"""FastAPI integration — middleware with auto-context and crash reporting.

Usage::

    from fastapi import FastAPI
    import snitchbot
    from snitchbot.integrations.fastapi import install

    app = FastAPI()
    snitchbot.init("my-service")
    install(app)

What install() does:
    1. Wraps every request in snitchbot.request_context with trace_id,
       http_method, http_path, client_ip.
    2. Injects X-Snitchbot-Trace-Id response header.
    3. On 5xx crash: captures query params + safe headers, sends alert.
"""
import uuid
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from fastapi import FastAPI

__all__ = ["install"]

_SENSITIVE_HEADERS = frozenset({
    "authorization", "cookie", "set-cookie",
    "x-api-key", "x-auth-token", "proxy-authorization",
})


def install(app: "FastAPI") -> None:
    """Register snitchbot middleware and exception handler on a FastAPI app."""
    from starlette.middleware.base import BaseHTTPMiddleware
    from starlette.requests import Request
    from starlette.responses import Response

    import snitchbot

    class _SnitchMiddleware(BaseHTTPMiddleware):
        async def dispatch(self, request: Request, call_next) -> Response:
            trace_id = f"req-{uuid.uuid4().hex[:8]}"
            client_ip = (
                request.headers.get("x-forwarded-for", "").split(",")[0].strip()
                or (request.client.host if request.client else "unknown")
            )

            with snitchbot.request_context(
                trace_id=trace_id,
                http_method=request.method,
                http_path=request.url.path,
                client_ip=client_ip,
            ):
                response = await call_next(request)
                response.headers["X-Snitchbot-Trace-Id"] = trace_id
                return response

    app.add_middleware(_SnitchMiddleware)

    from fastapi import HTTPException
    from fastapi import Request as FastAPIRequest
    from fastapi.responses import JSONResponse

    @app.exception_handler(Exception)
    async def _crash_handler(request: FastAPIRequest, exc: Exception):
        if isinstance(exc, HTTPException) and exc.status_code < 500:
            raise exc

        client_ip = (
            request.headers.get("x-forwarded-for", "").split(",")[0].strip()
            or (request.client.host if request.client else "unknown")
        )
        trace_id = request.headers.get(
            "x-snitchbot-trace-id",
        ) or f"req-{uuid.uuid4().hex[:8]}"

        safe_headers = {
            k: v for k, v in request.headers.items()
            if k.lower() not in _SENSITIVE_HEADERS
        }
        query_params = dict(request.query_params)

        with snitchbot.request_context(
            trace_id=trace_id,
            http_method=request.method,
            http_path=request.url.path,
            client_ip=client_ip,
        ):
            snitchbot.notify(
                f"{type(exc).__name__}: {exc}",
                severity="critical",
                exc_info=exc,
                source="exception",
                extras={
                    "query_params": query_params,
                    "headers": safe_headers,
                },
            )
        return JSONResponse(
            status_code=500,
            content={"detail": "Internal server error"},
        )
