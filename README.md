# snitchbot

[![PyPI version](https://img.shields.io/pypi/v/snitchbot.svg)](https://pypi.org/project/snitchbot/)
[![Python versions](https://img.shields.io/pypi/pyversions/snitchbot.svg)](https://pypi.org/project/snitchbot/)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![Docs](https://img.shields.io/badge/docs-sense1tapo4ek.github.io-ec4c2a.svg)](https://sense1tapo4ek.github.io/snitchbot/)
[![CI](https://github.com/Sense1Tapo4ek/snitchbot/actions/workflows/pages.yml/badge.svg)](https://github.com/Sense1Tapo4ek/snitchbot/actions/workflows/pages.yml)

Telegram telemetry for Python services. Crash reports, slow-call alerts, watchdog events, custom notifications, and anomaly detection — delivered to your Telegram chat.

**Docs:** https://sense1tapo4ek.github.io/snitchbot/

## Features

- **Crash reporting** — uncaught exceptions in sync, threading, and asyncio
- **Slow-call monitoring** — `@watch_slow(threshold_ms=1000)` decorator
- **Watchdog** — event loop block detection with severity escalation
- **Custom notifications** — `notify("deploy complete", severity="warning")`
- **Request context** — trace IDs and tags propagated across async boundaries
- **Anomaly detection** — RSS spikes, CPU sustained, FD leaks, thread growth
- **Interactive Telegram** — /status, /last, /test, /mute, /unmute commands
- **Live dashboard** — auto-updating message with service vitals
- **Secret scrubbing** — API keys, tokens, passwords never reach Telegram
- **Logging bridges** — stdlib `logging` handler + `structlog` processor

## Architecture

Thin host client + detached sidecar process. The client never blocks your app — events are sent via AF_UNIX SOCK_DGRAM to the sidecar, which handles dedup, rate limiting, and Telegram delivery.

## Installation

```bash
uv add snitchbot
```

With example frameworks (FastAPI, Litestar, Flask):
```bash
uv add snitchbot[examples]
```

## Quick Start

### 1. Get a Telegram bot token

Talk to [@BotFather](https://t.me/BotFather), create a bot, copy the token.

### 2. Get your chat ID

Add the bot to a group or start a DM, then use [@userinfobot](https://t.me/userinfobot) or the Telegram API to find the chat ID.

### 3. Configure

```bash
cp .env.example .env
# Edit .env — set SNITCHBOT_TOKEN and SNITCHBOT_CHAT_ID
```

### 4. Add to your app

```python
import snitchbot

# Reads SNITCHBOT_TOKEN and SNITCHBOT_CHAT_ID from env / .env file
snitchbot.init("my-service")

# Or pass explicitly:
# snitchbot.init("my-service", token="...", chat_id="...")

# That's it. Crashes are now reported automatically.

# Optional: custom notifications
snitchbot.notify("Deploy complete", severity="warning")

# Optional: slow-call monitoring
@snitchbot.watch_slow(threshold_ms=1000)
async def process_order(order_id: str):
    ...

# Optional: request context
with snitchbot.request_context(trace_id="req-abc", user_id="42"):
    snitchbot.notify("Processing started")
```

## Running Examples

### Prerequisites

```bash
# Clone and install
git clone https://github.com/Sense1Tapo4ek/snitchbot.git
cd snitchbot
uv sync --extra dev --extra examples

# Configure
cp .env.example .env
# Edit .env with your bot token and chat ID
```

### FastAPI

```bash
uv run uvicorn examples.fastapi_app:app --reload
```

Then visit:
- http://localhost:8000/ — health check
- http://localhost:8000/notify — sends a custom notification
- http://localhost:8000/slow — triggers slow-call alert (200ms > 100ms threshold)
- http://localhost:8000/crash — triggers crash report
- http://localhost:8000/context — demonstrates request context

### Litestar

```bash
uv run litestar run --app examples.litestar_app:app --reload
```

### Flask

```bash
uv run flask --app examples.flask_app run --reload
```

## Testing

```bash
# Run all tests (no Telegram token required)
uv run pytest

# Run only unit tests
uv run pytest tests/shared/unit tests/client/unit tests/sidecar/unit

# Run framework integration tests
uv run pytest tests/e2e/test_framework_integration.py -v
```

## Python Support

- Python >= 3.10
- Linux (primary), macOS (supported)
- Works with: FastAPI, Litestar, Flask, Django, Celery, Gunicorn, uvicorn, uvloop

## License

MIT

---

