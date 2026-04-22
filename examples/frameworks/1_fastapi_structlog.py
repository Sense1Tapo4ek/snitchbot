"""FastAPI + Structlog Integration Demo.

Demonstrates how structlog and snitchbot's FastAPI middleware work together.
When you log an error with structlog, the snitchbot processor catches it,
merges the structlog kwargs with the FastAPI Auto-Context, and delivers a
perfectly enriched alert to Telegram.

Expected Telegram output:
    🔴 error · fastapi-structlog · e4f5a6
    Failed to process webhook
    Details
        time       2026-04-14 15:50:00 UTC
        pid        450888
        source     structlog
    Extras
        provider   stripe
        event_type charge.failed
    Context
        trace_id   req-1a2b3c4d
        extras     {'http_method': 'POST', 'http_path': '/webhook', 'client_ip': '127.0.0.1'}

Prerequisites:
    uv run uvicorn examples.integrations.fastapi.structlog_app:app --reload
"""
import structlog
from fastapi import FastAPI, Request
from structlog.processors import CallsiteParameter, CallsiteParameterAdder

import snitchbot
from snitchbot.integrations.fastapi import install

# 1. Initialize snitchbot
snitchbot.init("fastapi-structlog")

# 2. Configure structlog to use the snitchbot processor

structlog.configure(
    processors=[
        structlog.stdlib.add_log_level,
        CallsiteParameterAdder([
            CallsiteParameter.PATHNAME,
            CallsiteParameter.LINENO,
            CallsiteParameter.FUNC_NAME,
        ]),
        snitchbot.setup_structlog(),
        structlog.dev.ConsoleRenderer(),
    ],
)

app = FastAPI()

# 3. Install the magic middleware
install(app)

log = structlog.get_logger()


@app.post("/webhook")
async def handle_webhook(request: Request, provider: str = "stripe"):
    """Demonstrates structlog forwarding with FastAPI context."""

    # We log an error with structured context (provider, event_type).
    # The FastAPI middleware automatically provides the trace_id, HTTP method, and path.
    # The snitchbot bridge combines them and sends the alert.

    log.error(
        "Failed to process webhook",
        provider=provider,
        event_type="charge.failed"
    )

    return {"status": "logged"}


@app.get("/payment/{payment_id}")
async def check_payment(payment_id: str):
    """Demonstrates that normal logs are untouched, but warnings are forwarded."""

    # This stays in the console only
    log.info("Checking payment status", payment_id=payment_id)

    if payment_id == "000":
        # This goes to the console AND Telegram, with FastAPI context!
        log.warning("Suspicious payment ID detected", payment_id=payment_id, risk_score=99)

    return {"payment_id": payment_id, "status": "pending"}
