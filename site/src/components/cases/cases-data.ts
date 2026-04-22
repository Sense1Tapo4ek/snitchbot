// Source of truth: docs/superpowers/specs/2026-04-19-landing-design.md §5.2
// and .superpowers/brainstorm/.../cases-block-v3.html
// TG bodies are verbatim against src/snitchbot/sidecar/pipeline/.../renderers/*.py.

export interface CaseEntry {
  key: string;
  label: string;
  kind: string;
  file: string;
  service: string;
  what: string;
  triggerHtml: string;
  code: string;
  tgHtml: string;
}

export const CASES: CaseEntry[] = [
  {
    key: "crash",
    label: "Crash",
    kind: "auto",
    file: "orders_api.py",
    service: "orders-api",
    what: "Uncaught exceptions — captured automatically.",
    triggerHtml: `<b>Zero user code</b> beyond <code>snitchbot.init()</code>. Hooks into <code>sys.excepthook</code>, <code>threading.excepthook</code>, and the asyncio exception handler. Works in main thread, worker threads, async tasks. Fork-safe.`,
    code: `import snitchbot

snitchbot.init("orders-api")

# Unhandled exceptions are captured automatically,
# including stack, thread, and origin.

async def list_orders(user_id: int) -> list:
    return await svc.fetch_all(user_id)

# Somewhere down the stack:
#   raise DatabaseConnectionError("refused to ...")
# -> snitchbot captures and sends the alert below.`,
    tgHtml: `<div class="tg-msg"><span class="accent">🔴</span> <b>crash</b> · orders-api · <code>a1b2c3</code> <span class="counter">× 2</span><br><b>DatabaseConnectionError</b>: connection refused to 10.0.0.5:5432<div style="margin-top:6px"><b>Details</b><div class="meta-table">first     14:18:42 UTC (24m ago)
last      14:42:10 UTC (just now)
pid       <b>101</b>
thread    MainThread
origin    sys_excepthook</div></div><div style="margin-top:6px"><b>Stack</b> <span style="color:#6a7b8a;font-size:11px">(top 3 user frames)</span><pre>app/db/pool.py:47 in acquire()
  conn = await self._pool.get()
app/services/orders.py:88 in fetch_all()
  return await db.fetch(q)
app/routes/orders.py:12 in list_orders()
  return await svc.fetch_all()</pre></div><div class="tg-btn-row"><span class="tg-btn">📋 full trace</span><span class="tg-btn">🔕 mute 1h</span></div><span class="tg-msg__time">14:42</span></div>`,
  },

  {
    key: "slow",
    label: "Slow call",
    kind: "decorator",
    file: "watch_slow_demo.py",
    service: "slow-demo",
    what: "Functions that crossed the threshold — sync or async.",
    triggerHtml: `Decorate with <code>@snitchbot.watch_slow(threshold_ms=...)</code>. Fast path untouched — the alert fires only when duration exceeds the threshold. Works for sync functions too.`,
    code: `import asyncio
import time
import snitchbot


@snitchbot.watch_slow(threshold_ms=100)
async def fetch_user_profile(user_id: int) -> dict:
    await asyncio.sleep(0.25)  # 250 ms > threshold
    return {"name": "Alice"}


@snitchbot.watch_slow(threshold_ms=500)
def generate_report() -> str:
    time.sleep(0.6)  # sync, also captured
    return "report-data"


async def main():
    snitchbot.init("slow-demo")
    await fetch_user_profile(42)
    generate_report()`,
    tgHtml: `<div class="tg-msg"><span style="color:#ffb15c">🟠</span> <b>slow call</b> · slow-demo · <code>ee48d4</code><br><b>__main__.fetch_user_profile</b> took <b>250 ms</b> (threshold 100 ms)<div style="margin-top:6px"><b>Details</b><div class="meta-table">time      12:57:18 UTC
pid       <b>1738</b>
is_async  true
location  watch_slow_demo.py:8</div></div><span class="tg-msg__time">12:57</span></div><div class="tg-msg"><span style="color:#ffb15c">🟠</span> <b>slow call</b> · slow-demo · <code>f9c2a1</code><br><b>__main__.generate_report</b> took <b>612 ms</b> (threshold 500 ms)<div style="margin-top:6px"><b>Details</b><div class="meta-table">time      12:57:20 UTC
pid       <b>1738</b>
is_async  false
location  watch_slow_demo.py:14</div></div><span class="tg-msg__time">12:57</span></div>`,
  },

  {
    key: "watchdog",
    label: "Watchdog",
    kind: "coroutine",
    file: "worker.py",
    service: "watchdog-demo",
    what: "Configurable coroutine. Measures event loop latency. Alerts past 500 ms by default.",
    triggerHtml: `A lightweight <b>pinger coroutine</b> updates a monotonic timestamp every 100 ms; a separate observer checks the gap. Any stall past <code>threshold_ms</code> is reported with every stuck task's stack. Multi-threshold severity: <code>threshold_ms</code> -> 🟠 warning, <code>error_threshold_ms</code> -> 🔴 error, <code>critical_threshold_ms</code> -> 🟣 critical. All defaults sensible — zero-config works, full-config unlocks the 3-tier escalation.`,
    code: `import snitchbot
from snitchbot import AnomalyConfig, WatchdogConfig

snitchbot.init("watchdog-demo")

# Zero-config: watchdog is on, threshold 500 ms,
# auto-escalates to error at 2 s, critical at 5 s.

# Full config with custom thresholds:
snitchbot.init(
    "watchdog-demo",
    anomaly=AnomalyConfig(
        watchdog=WatchdogConfig(
            threshold_ms=500,            # 🟠 warning
            error_threshold_ms=2000,      # 🔴 error
            critical_threshold_ms=5000,   # 🟣 critical
            escalation_window="1m",
            cooldown_sec=5,
        ),
    ),
)`,
    tgHtml: `<div class="tg-msg"><span style="color:#ffb15c">🟠</span> <b>watchdog</b> · watchdog-demo · <code>7c6497</code><br>Event loop blocked for <b>588 ms</b> (threshold 500 ms)<div style="margin-top:6px"><b>Details</b><div class="meta-table">time   11:25:10 UTC
pid    <b>1580</b>
loop   main</div></div><span class="tg-msg__time">11:25</span></div><div class="tg-msg"><span class="accent">🔴</span> <b>watchdog</b> · watchdog-demo · <code>7c6497</code> <span class="counter">× 2</span><br>Event loop blocked for <b>2 690 ms</b> (threshold 500 ms)<div style="margin-top:6px"><b>Details</b><div class="meta-table">first  11:25:10 UTC (40s ago)
last   11:25:20 UTC (just now)
pid    <b>1580</b>
loop   main</div></div><div class="tg-btn-row"><span class="tg-btn">📋 full trace</span></div><span class="tg-msg__time">11:25</span></div><div class="tg-msg"><span class="critical">🟣</span> <b>watchdog</b> · watchdog-demo · <code>732334</code><br>Event loop blocked for <b>5 699 ms</b> (threshold 500 ms)<div style="margin-top:6px"><b>Details</b><div class="meta-table">time   11:25:24 UTC
pid    <b>1580</b>
loop   main</div></div><div style="margin-top:6px"><b>Stuck tasks</b> (2)<pre>Innocent-Worker · background_task
  worker.py:55 in background_task()
Task-1 · main
  worker.py:97 in main()</pre></div><div class="tg-btn-row"><span class="tg-btn">📋 full trace</span></div><span class="tg-msg__time">11:25</span></div>`,
  },

  {
    key: "anomaly",
    label: "Anomaly",
    kind: "sidecar",
    file: "vitals_config.py",
    service: "anomaly-demo",
    what: "A richly-configurable vitals detector — RSS, CPU, FDs, threads.",
    triggerHtml: `Every metric gets three independent modes: <code>ceiling</code> (hard limit), <code>spike</code> (relative growth vs baseline), <code>drop</code> (relative decline). Windows and baselines are time-based (<code>"15s"</code>, <code>"1m"</code>, <code>"1h"</code>). The sidecar samples <code>psutil</code> every 5 s (tunable via <code>sample_interval_sec</code>). Turn any mode off by passing <code>None</code> — or skip the config entirely for sensible defaults.`,
    code: `import snitchbot
from snitchbot import (
    AnomalyConfig,
    RssAnomalyConfig,
    CpuAnomalyConfig,
    FdAnomalyConfig,
    ThreadAnomalyConfig,
)

snitchbot.init(
    "anomaly-demo",
    sample_interval_sec=5,
    anomaly=AnomalyConfig(
        rss=RssAnomalyConfig(
            duration="1m", baseline_duration="30m",
            max_mb=450,          # 🔴 ceiling
            spike_ratio=1.5,      # 🟠 +50% vs baseline
            min_spike_mb=50,      # and ≥ 50 MB absolute
        ),
        cpu=CpuAnomalyConfig(
            duration="2m", baseline_duration="20m",
            max_percent=90,       # 🔴 ceiling
            spike_ratio=2.5,       # 🟠 spike
            min_spike_delta=30,    # ≥ 30 pp
        ),
        fds=FdAnomalyConfig(
            max_fds=800,          # 🔴 ulimit guard
            spike_ratio=1.5,       # 🔴 fd leak
            drop_ratio=0.5,        # 🟠 pool collapse
        ),
        threads=ThreadAnomalyConfig(
            max_threads=100,
            spike_ratio=1.5,
        ),
    ),
)`,
    tgHtml: `<div class="tg-msg"><span style="color:#ffb15c">🟠</span> <b>anomaly</b> · anomaly-demo · <code>a7af9c</code> <span class="counter">× 2</span><br>RSS spike: <b>183 MB</b> (baseline 70 MB, <b class="accent">+160%</b>)<div style="margin-top:6px"><b>Details</b><div class="meta-table">time      11:17:40 UTC
pid       <b>1550</b>
type      rss_spike
window    1m
baseline  70 MB
current   183 MB</div></div><span class="tg-msg__time">11:17</span></div><div class="tg-msg"><span class="accent">🔴</span> <b>anomaly</b> · anomaly-demo · <code>c82b14</code><br>CPU ceiling: <b>94%</b> (limit 90%)<div style="margin-top:6px"><b>Details</b><div class="meta-table">time      11:21:02 UTC
pid       <b>1550</b>
type      cpu_ceiling
window    2m
baseline  18%
current   94%</div></div><span class="tg-msg__time">11:21</span></div><div class="tg-msg"><span class="accent">🔴</span> <b>anomaly</b> · anomaly-demo · <code>91e7da</code><br>FD leak: 40 -> <b>820</b> (+780)<div style="margin-top:6px"><b>Details</b><div class="meta-table">time      11:24:55 UTC
pid       <b>1550</b>
type      fds_spike
window    5m
baseline  40
current   820</div></div><span class="tg-msg__time">11:24</span></div><div class="tg-msg"><span style="color:#ffb15c">🟠</span> <b>anomaly</b> · anomaly-demo · <code>44c2fb</code><br>Thread spike: 8 -> <b>45</b> (+462%)<div style="margin-top:6px"><b>Details</b><div class="meta-table">time      11:28:11 UTC
pid       <b>1550</b>
type      threads_spike
window    1m
baseline  8
current   45</div></div><span class="tg-msg__time">11:28</span></div>`,
  },

  {
    key: "lifecycle",
    label: "Lifecycle",
    kind: "auto",
    file: "app.py",
    service: "orders-api",
    what: "Know when a service starts, stops, or dies.",
    triggerHtml: `Emitted <b>automatically</b> by <code>snitchbot.init()</code> and registered <code>atexit</code> / signal handlers. You see startup, clean exits, graceful shutdowns (<code>SIGTERM</code> / <code>SIGINT</code>), and crashes — with pid, role (worker / standalone), reason, and exit code. Multiworker-aware: gunicorn / uvicorn workers get their own role suffix.`,
    code: `import snitchbot

snitchbot.init("orders-api")

# ▶ lifecycle("startup", reason="init")  — sent immediately

# ...your service does its thing...

# On any of these paths, a shutdown event is emitted:
#  · Clean exit      -> reason="clean_exit", exit_code=0
#  · SIGTERM / SIGINT -> reason="sigterm" / "sigint"
#  · Uncaught crash   -> reason="crash" (+ traceback)
#  · Thread crash     -> reason="thread_crash"

# Nothing to call, nothing to decorate.`,
    tgHtml: `<div class="tg-msg"><span style="color:#5ab5ff">▶</span> <b>orders-api started</b><br><span class="sep">━━━━━━━━━━━━━━━━━━</span><div class="meta-table">pid        <b>101</b>
time       10:00:14 UTC</div><span class="tg-msg__time">10:00</span></div><div class="tg-msg"><span style="color:#8fa3b4">■</span> <b>orders-api stopped</b><br><span class="sep">━━━━━━━━━━━━━━━━━━</span><div class="meta-table">pid        <b>101</b>
reason     clean_exit
exit_code  0
time       10:42:55 UTC</div><span class="tg-msg__time">10:42</span></div><div class="tg-msg"><span style="color:#5ab5ff">▶</span> <b>orders-api (worker) started</b><br><span class="sep">━━━━━━━━━━━━━━━━━━</span><div class="meta-table">pid        <b>198</b>
time       11:01:02 UTC</div><span class="tg-msg__time">11:01</span></div><div class="tg-msg"><span style="color:#8fa3b4">■</span> <b>orders-api (worker) stopped</b><br><span class="sep">━━━━━━━━━━━━━━━━━━</span><div class="meta-table">pid        <b>198</b>
reason     sigterm
exit_code  0
time       11:30:41 UTC</div><span class="tg-msg__time">11:30</span></div><div class="tg-msg"><span class="accent">⚠</span> <b>orders-api crashed</b><br><span class="sep">━━━━━━━━━━━━━━━━━━</span><div class="meta-table">pid        <b>254</b>
reason     crash
time       13:02:18 UTC</div><span class="tg-msg__time">13:02</span></div>`,
  },

  {
    key: "notify",
    label: "Notify",
    kind: "manual",
    file: "checkout.py",
    service: "notify-demo",
    what: "Send anything — warnings, errors, business events.",
    triggerHtml: `Call <code>snitchbot.notify(text, severity, extras, exc_info)</code>. Severity drives the icon (🟠/🔴/🟣) and rate-limit bucket. <code>exc_info=True</code> attaches the current traceback.`,
    code: `import snitchbot

snitchbot.init("notify-demo")

# Warning with extras — renders as a meta-table
snitchbot.notify(
    "Starting checkout process",
    severity="warning",
    extras={"cart_size": 3, "user": "Alice"},
)

# Error with live traceback
try:
    _ = 1 / 0
except ZeroDivisionError:
    snitchbot.notify(
        "Division failed in payment calculator",
        severity="error",
        exc_info=True,
    )`,
    tgHtml: `<div class="tg-msg"><span style="color:#ffb15c">🟠</span> <b>notify</b> · notify-demo · <code>f966e3</code><br>Starting checkout process<div style="margin-top:6px"><b>Details</b><div class="meta-table">time      12:42:47 UTC
pid       <b>1718</b>
caller    checkout.py:6 in main()</div></div><div style="margin-top:6px"><b>Extras</b><div class="meta-table">cart_size   3
user        Alice</div></div><span class="tg-msg__time">12:42</span></div><div class="tg-msg"><span class="accent">🔴</span> <b>notify</b> · notify-demo · <code>2eec9c</code><br>Division failed in payment calculator<div style="margin-top:6px"><b>Details</b><div class="meta-table">time      12:52:35 UTC
pid       <b>1732</b>
caller    checkout.py:14 in main()</div></div><div style="margin-top:6px"><b>Exception</b>: ZeroDivisionError: division by zero<pre>Traceback (most recent call last):
  File "checkout.py", line 13, in main
    _ = 1 / 0
ZeroDivisionError: division by zero</pre></div><span class="tg-msg__time">12:52</span></div>`,
  },

  {
    key: "context",
    label: "Context",
    kind: "scope",
    file: "handler.py",
    service: "context-demo",
    what: "Attach trace_id + metadata to every alert in scope.",
    triggerHtml: `Wrap code in <code>with snitchbot.request_context(trace_id=..., **extras)</code>. <b>Everything</b> inside — <code>notify()</code>, <code>@watch_slow</code>, crash reports — inherits the context. Propagates across <code>await</code>, <code>create_task</code>, and nested calls. Frameworks (FastAPI / Flask / Litestar) set this automatically per request.`,
    code: `import asyncio
import snitchbot


@snitchbot.watch_slow(threshold_ms=100)
async def call_payment_api(amount: float) -> str:
    await asyncio.sleep(0.2)
    return "txn-12345"


async def handle_request(request_id: str, user_id: int):
    with snitchbot.request_context(
        trace_id=request_id,
        user_id=user_id,
        action="checkout",
    ):
        snitchbot.notify(
            "User started checkout",
            extras={"cart_size": 3},
        )
        await call_payment_api(99.99)  # inherits ctx`,
    tgHtml: `<div class="tg-msg"><span style="color:#ffb15c">🟠</span> <b>notify</b> · context-demo · <code>156afe</code><br>User started checkout<div style="margin-top:6px"><b>Details</b><div class="meta-table">time      12:53:41 UTC
pid       <b>1733</b>
caller    handler.py:15 in handle_request()</div></div><div style="margin-top:6px"><b>Extras</b><div class="meta-table">cart_size   3</div></div><div style="margin-top:6px"><b>Context</b><div class="meta-table">trace_id   req-abc-123
user_id    42
action     checkout</div></div><span class="tg-msg__time">12:53</span></div><div class="tg-msg"><span style="color:#ffb15c">🟠</span> <b>slow call</b> · context-demo · <code>ee48d4</code><br><b>__main__.call_payment_api</b> took <b>201 ms</b> (threshold 100 ms)<div style="margin-top:6px"><b>Details</b><div class="meta-table">time      12:57:18 UTC
pid       <b>1733</b>
is_async  true
location  handler.py:6</div></div><div style="margin-top:6px"><b>Context</b><div class="meta-table">trace_id   req-abc-123
user_id    42
action     checkout</div></div><span class="tg-msg__time">12:57</span></div>`,
  },

  {
    key: "logging",
    label: "Logging",
    kind: "stdlib · structlog",
    file: "app.py",
    service: "log-demo",
    what: "stdlib logging and structlog — both bridged to Telegram.",
    triggerHtml: `One line — <code>snitchbot.setup_logging()</code> — attaches a handler to Python's <code>logging</code>. WARNING+ records become notifications, keeping level, message, extras, and <code>exc_info</code>. For structlog, call <code>snitchbot.setup_structlog()</code> and add the returned processor to your chain. Inside a <code>request_context</code>, <code>trace_id</code> is attached automatically.`,
    code: `import logging
import snitchbot

snitchbot.init("log-demo")
snitchbot.setup_logging()  # WARNING+ -> Telegram

# Or, for structlog users:
# processor = snitchbot.setup_structlog()
# structlog.configure(processors=[..., processor])

logger = logging.getLogger("myapp")

# Extras become a meta-table in the alert
logger.warning(
    "Cache miss rate too high",
    extra={"miss_pct": 42},
)

# exc_info=True attaches the traceback
try:
    _ = 1 / 0
except ZeroDivisionError:
    logger.error("Calculation failed", exc_info=True)

# Inside request_context — trace_id attached automatically
with snitchbot.request_context(trace_id="req-abc-123"):
    logger.warning("Slow DB query in checkout")`,
    tgHtml: `<div class="tg-msg"><span style="color:#ffb15c">🟠</span> <b>log.warning</b> · log-demo · <code>c1b4e8</code><br>Cache miss rate too high<div style="margin-top:6px"><b>Details</b><div class="meta-table">time      14:02:11 UTC
pid       <b>2104</b>
caller    app.py:15 in &lt;module&gt;()</div></div><div style="margin-top:6px"><b>Extras</b><div class="meta-table">miss_pct    42
logger      myapp
level       WARNING</div></div><span class="tg-msg__time">14:02</span></div><div class="tg-msg"><span class="accent">🔴</span> <b>log.error</b> · log-demo · <code>d9a3f1</code><br>Calculation failed<div style="margin-top:6px"><b>Exception</b>: ZeroDivisionError: division by zero<pre>Traceback (most recent call last):
  File "app.py", line 23, in &lt;module&gt;
    _ = 1 / 0
ZeroDivisionError: division by zero</pre></div><span class="tg-msg__time">14:02</span></div><div class="tg-msg"><span style="color:#ffb15c">🟠</span> <b>log.warning</b> · log-demo · <code>7b2c8d</code><br>Slow DB query in checkout<div style="margin-top:6px"><b>Context</b><div class="meta-table">trace_id   req-abc-123</div></div><span class="tg-msg__time">14:02</span></div>`,
  },

  {
    key: "frameworks",
    label: "Frameworks",
    kind: "fastapi · flask · litestar",
    file: "main.py",
    service: "web-demo",
    what: "FastAPI, Flask, and Litestar — one-line integration each.",
    triggerHtml: `<code>install(app)</code> from the matching integration module. Middleware attaches per-request context (<code>http_method</code>, <code>path</code>, <code>client_ip</code>, <code>trace_id</code>). 5xx errors auto-captured with safe headers and query params. Response gets an <code>X-Snitchbot-Trace-Id</code> header. Logging bridge picks up the same context inside request scope.`,
    code: `import snitchbot

snitchbot.init("web-demo")
snitchbot.setup_logging()

# ── FastAPI ───────────────────────────────────
from fastapi import FastAPI
from snitchbot.integrations.fastapi import install

app = FastAPI()
install(app)

# ── Flask ─────────────────────────────────────
# from flask import Flask
# from snitchbot.integrations.flask import install
# app = Flask(__name__); install(app)

# ── Litestar ──────────────────────────────────
# from litestar import Litestar
# from snitchbot.integrations.litestar import install
# app = Litestar(route_handlers=[...]); install(app)


@app.post("/checkout")
async def checkout(cart_value: int = 100):
    snitchbot.notify("Large checkout",
                     extras={"cart_value": cart_value})
    return {"status": "processing"}


@app.get("/search")
async def search(query: str):
    raise ValueError("Unknown search backend")`,
    tgHtml: `<div class="tg-msg"><span style="color:#ffb15c">🟠</span> <b>notify</b> · web-demo · <code>5ec8a2</code><br>Large checkout<div style="margin-top:6px"><b>Details</b><div class="meta-table">time      15:12:04 UTC
pid       <b>2211</b>
caller    main.py:22 in checkout()</div></div><div style="margin-top:6px"><b>Extras</b><div class="meta-table">cart_value   500</div></div><div style="margin-top:6px"><b>Context</b><div class="meta-table">http_method  POST
path         /checkout
client_ip    10.0.0.14
trace_id     a3f7-b2c9</div></div><span class="tg-msg__time">15:12</span></div><div class="tg-msg"><span class="accent">🔴</span> <b>crash</b> · web-demo · <code>bb9d31</code><br><b>ValueError</b>: Unknown search backend<div style="margin-top:6px"><b>Details</b><div class="meta-table">time      15:13:22 UTC
pid       <b>2211</b>
origin    fastapi_middleware</div></div><div style="margin-top:6px"><b>Context</b><div class="meta-table">http_method  GET
path         /search
client_ip    10.0.0.14
trace_id     d2e8-c4a1
query        {"query":"test"}</div></div><div style="margin-top:6px"><b>Stack</b> <span style="color:#6a7b8a;font-size:11px">(top 2 user frames)</span><pre>main.py:28 in search()
  raise ValueError("Unknown search backend")</pre></div><div class="tg-btn-row"><span class="tg-btn">📋 full trace</span><span class="tg-btn">🔕 mute 1h</span></div><span class="tg-msg__time">15:13</span></div>`,
  },
];

if (CASES.length !== 9) {
  throw new Error(`cases-data.ts must have 9 entries — got ${CASES.length}`);
}
