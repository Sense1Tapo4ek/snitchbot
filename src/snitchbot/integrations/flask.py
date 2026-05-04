"""Flask integration — hooks with auto-context and crash reporting.

Usage::

    from flask import Flask
    import snitchbot
    from snitchbot.integrations.flask import install

    app = Flask(__name__)
    snitchbot.init("my-service")
    install(app)

What install() does:
    1. before_request: sets snitchbot.request_context with trace_id,
       http_method, http_path, client_ip.
    2. after_request: injects X-Snitchbot-Trace-Id response header.
    3. On 5xx crash: captures query params + safe headers, sends alert.
"""
import threading
import uuid
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from flask import Flask

__all__ = ["init_app", "install"]

_init_lock = threading.Lock()
_inited = False


def init_app(app: "Flask", *, service: str, **init_kwargs: Any) -> None:
    """Initialize snitchbot once per worker process on first request.

    Use this from a Flask application factory so every gunicorn / uwsgi
    worker registers separately (each prefork worker has its own
    module-level ``_inited`` flag because globals are per-process).

    Example::

        from snitchbot.integrations.flask import init_app, install

        def create_app():
            app = Flask(__name__)
            init_app(app, service="orders-api", role="web")
            install(app)
            return app
    """
    import snitchbot

    @app.before_request
    def _ensure_init() -> None:
        global _inited
        if _inited:
            return
        with _init_lock:
            if _inited:
                return
            snitchbot.init(service, **init_kwargs)
            _inited = True

_SENSITIVE_HEADERS = frozenset({
    "authorization", "cookie", "set-cookie",
    "x-api-key", "x-auth-token", "proxy-authorization",
})


def install(app: "Flask") -> None:
    """Register snitchbot hooks and error handler on a Flask app."""
    import snitchbot

    @app.before_request
    def _before():
        from flask import g, request

        trace_id = f"req-{uuid.uuid4().hex[:8]}"
        client_ip = (
            request.headers.get("X-Forwarded-For", "").split(",")[0].strip()
            or request.remote_addr
            or "unknown"
        )

        ctx = snitchbot.request_context(
            trace_id=trace_id,
            http_method=request.method,
            http_path=request.path,
            client_ip=client_ip,
        )
        g._snitchbot_ctx = ctx
        g._snitchbot_trace_id = trace_id
        ctx.__enter__()

    @app.teardown_request
    def _teardown(exc):
        from flask import g

        ctx = getattr(g, "_snitchbot_ctx", None)
        if ctx is not None:
            ctx.__exit__(None, None, None)

    @app.after_request
    def _after(response):
        from flask import g

        trace_id = getattr(g, "_snitchbot_trace_id", None)
        if trace_id:
            response.headers["X-Snitchbot-Trace-Id"] = trace_id
        return response

    from werkzeug.exceptions import HTTPException

    @app.errorhandler(Exception)
    def _crash_handler(exc: Exception):
        if isinstance(exc, HTTPException) and exc.code is not None and exc.code < 500:
            raise exc

        from flask import g, request

        client_ip = (
            request.headers.get("X-Forwarded-For", "").split(",")[0].strip()
            or request.remote_addr
            or "unknown"
        )
        trace_id = getattr(
            g, "_snitchbot_trace_id", None,
        ) or f"req-{uuid.uuid4().hex[:8]}"

        safe_headers = {
            k: v for k, v in request.headers
            if k.lower() not in _SENSITIVE_HEADERS
        }
        query_params = dict(request.args)

        # Re-enter context (teardown may have cleared it)
        with snitchbot.request_context(
            trace_id=trace_id,
            http_method=request.method,
            http_path=request.path,
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
        from flask import jsonify
        return jsonify(detail="Internal server error"), 500
