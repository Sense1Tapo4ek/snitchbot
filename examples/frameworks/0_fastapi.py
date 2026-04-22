"""FastAPI Integration Demo.

Demonstrates snitchbot's FastAPI middleware:
    1. Auto-Context: every alert gets http_method, path, client_ip
    2. Crash Capture: 5xx errors include query params and safe headers
    3. Trace-ID: X-Snitchbot-Trace-Id injected in response headers
    4. Logging bridge: logger.warning() inside a request gets the context

Try these:
    curl http://localhost:8000/                     # check X-Snitchbot-Trace-Id header
    curl http://localhost:8000/checkout -X POST      # manual notify with context
    curl http://localhost:8000/search?query=test     # crash with query params
    curl http://localhost:8000/disk-check            # logging with context

Prerequisites:
    uv run uvicorn examples.frameworks.0_fastapi:app --reload
"""
import logging

from fastapi import FastAPI

import snitchbot
from snitchbot.integrations.fastapi import install

snitchbot.init("fastapi-demo")
snitchbot.setup_logging()

app = FastAPI()
install(app)

logger = logging.getLogger("fastapi-demo")


@app.get("/")
async def root():
    """Check response headers for X-Snitchbot-Trace-Id."""
    return {"status": "ok"}


@app.post("/checkout")
async def checkout(cart_value: int = 100):
    """notify() inherits the request context automatically."""
    snitchbot.notify(
        "Large checkout initiated",
        severity="warning",
        extras={"cart_value": cart_value},
    )
    return {"status": "processing"}


@app.get("/search")
async def search(query: str):
    """Crash demo. Alert will include query_params and safe headers."""
    _ = query  # used by FastAPI as query param
    raise ValueError("Unknown search backend")


@app.get("/disk-check")
async def disk_check():
    """Logging bridge demo. Warning log gets the request context."""
    logger.warning("Disk space running low", extra={"free_gb": 2.5})
    return {"status": "warning"}
