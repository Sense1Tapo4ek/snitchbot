"""Litestar Integration Demo.

Demonstrates snitchbot's Litestar integration:
    1. Auto-Context: every alert gets http_method, path, client_ip
    2. Crash Capture: 5xx errors include query params and safe headers
    3. Trace-ID: X-Snitchbot-Trace-Id injected in response headers
    4. Watchdog: time.sleep() blocks the loop and triggers a watchdog alert

Try these:
    curl http://localhost:8000/
    curl http://localhost:8000/notify
    curl http://localhost:8000/crash
    curl http://localhost:8000/slow

Prerequisites:
    LITESTAR_APP=examples.frameworks.3_litestar:app uv run litestar run --reload
"""
import logging

from litestar import Litestar, get

import snitchbot
from snitchbot.integrations.litestar import install

snitchbot.init("litestar-demo")
snitchbot.setup_logging()

logger = logging.getLogger("litestar-demo")


@get("/")
async def root() -> dict:
    return {"status": "ok"}


@get("/notify")
async def notify_example() -> dict:
    """notify() inherits the request context automatically."""
    snitchbot.notify("Litestar health check", severity="warning")
    return {"sent": True}


@get("/crash")
async def crash_endpoint() -> dict:
    """Crash demo. Alert includes query params and safe headers."""
    raise ValueError("Litestar crash!")


@get("/slow")
async def slow_endpoint() -> dict:
    """Watchdog demo. Blocks event loop — triggers watchdog alert."""
    import time
    time.sleep(1)  # blocks the loop — watchdog will fire
    return {"status": "done"}


app = Litestar(route_handlers=[
    root, notify_example, crash_endpoint, slow_endpoint,
])
install(app)
