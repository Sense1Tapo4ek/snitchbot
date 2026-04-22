"""Litestar integration — middleware with auto-context and crash reporting.

Usage::

    from litestar import Litestar
    import snitchbot
    from snitchbot.integrations.litestar import install

    snitchbot.init("my-service")
    app = Litestar(route_handlers=[...])
    install(app)

What install() does:
    1. Adds middleware that wraps every request in snitchbot.request_context
       with trace_id, http_method, http_path, client_ip.
    2. Injects X-Snitchbot-Trace-Id response header.
    3. On 5xx crash: captures query params + safe headers, sends alert.

Legacy usage (still works)::

    from snitchbot.integrations.litestar import exception_handler
    app = Litestar(exception_handlers={Exception: exception_handler})
"""
import uuid
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from litestar import Litestar, Request, Response

__all__ = ["install", "exception_handler"]

_SENSITIVE_HEADERS = frozenset({
    b"authorization", b"cookie", b"set-cookie",
    b"x-api-key", b"x-auth-token", b"proxy-authorization",
})


def install(app: "Litestar") -> None:
    """Register snitchbot middleware and exception handler on a Litestar app."""
    from litestar.middleware import DefineMiddleware

    app.middleware.insert(0, DefineMiddleware(_SnitchMiddleware))
    app.exception_handlers[Exception] = exception_handler


def exception_handler(request: "Request", exc: Exception) -> "Response":
    """Report 5xx crashes to snitchbot with request context."""
    from litestar import Response as LitestarResponse
    from litestar.exceptions import HTTPException

    import snitchbot

    if isinstance(exc, HTTPException) and exc.status_code < 500:
        raise exc

    scope = request.scope
    method = scope.get("method", "")
    path = scope.get("path", "")
    headers_raw = dict(scope.get("headers", []))
    client = scope.get("client")
    client_ip = (
        headers_raw.get(b"x-forwarded-for", b"").decode().split(",")[0].strip()
        or (client[0] if client else "unknown")
    )
    trace_id = headers_raw.get(
        b"x-snitchbot-trace-id", b"",
    ).decode() or f"req-{__import__('uuid').uuid4().hex[:8]}"

    safe_headers = {
        k.decode(): v.decode()
        for k, v in scope.get("headers", [])
        if k.lower() not in _SENSITIVE_HEADERS
    }
    query_string = scope.get("query_string", b"").decode()
    query_params = dict(
        pair.split("=", 1) for pair in query_string.split("&")
        if "=" in pair
    ) if query_string else {}

    # Set context so the alert includes trace_id and HTTP metadata
    with snitchbot.request_context(
        trace_id=trace_id,
        http_method=method,
        http_path=path,
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
    return LitestarResponse(
        content={"detail": "Internal server error"},
        status_code=500,
    )


class _SnitchMiddleware:
    """ASGI middleware for request context and trace ID injection."""

    def __init__(self, app) -> None:
        self.app = app

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        import snitchbot

        trace_id = f"req-{uuid.uuid4().hex[:8]}"
        method = scope.get("method", "")
        path = scope.get("path", "")
        headers = dict(scope.get("headers", []))
        client = scope.get("client")
        client_ip = (
            headers.get(b"x-forwarded-for", b"").decode().split(",")[0].strip()
            or (client[0] if client else "unknown")
        )

        # Inject trace_id into response headers
        _original_send = send

        async def _send_with_trace(message) -> None:
            if message["type"] == "http.response.start":
                headers = list(message.get("headers", []))
                headers.append(
                    (b"x-snitchbot-trace-id", trace_id.encode()),
                )
                message["headers"] = headers
            await _original_send(message)

        with snitchbot.request_context(
            trace_id=trace_id,
            http_method=method,
            http_path=path,
            client_ip=client_ip,
        ):
            await self.app(scope, receive, _send_with_trace)
