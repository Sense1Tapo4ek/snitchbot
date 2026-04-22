"""Flask Integration Demo.

Demonstrates snitchbot's Flask integration:
    1. Auto-Context: every alert gets http_method, path, client_ip
    2. Crash Capture: 5xx errors include query params and safe headers
    3. Trace-ID: X-Snitchbot-Trace-Id injected in response headers
    4. Logging bridge: logger.warning() inside a request gets the context

Try these:
    curl http://localhost:5000/
    curl http://localhost:5000/notify
    curl http://localhost:5000/crash
    curl http://localhost:5000/log-warning

Prerequisites:
    uv run flask --app examples.frameworks.2_flask:app run --reload
"""
import logging

from flask import Flask

import snitchbot
from snitchbot.integrations.flask import install

app = Flask(__name__)

snitchbot.init("flask-demo")
snitchbot.setup_logging()
install(app)

logger = logging.getLogger("flask-demo")


@app.route("/")
def root() -> dict:
    return {"status": "ok"}


@app.route("/notify")
def notify_example() -> dict:
    """notify() inherits the request context automatically."""
    snitchbot.notify("Flask health check", severity="warning")
    return {"sent": True}


@app.route("/crash")
def crash_endpoint() -> dict:
    """Crash demo. Alert includes query params and safe headers."""
    raise ValueError("Flask crash!")


@app.route("/log-warning")
def log_warning_example() -> dict:
    """Logging bridge demo. Warning log gets the request context."""
    logger.warning("Cache miss rate above threshold", extra={"miss_pct": 42})
    return {"logged": "warning"}
