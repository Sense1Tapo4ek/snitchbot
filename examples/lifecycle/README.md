# Lifecycle Management

snitchbot automatically tracks your Python application's lifecycle and sends
notifications to Telegram.

## How It Works

```
Your App                              Sidecar (detached process)
────────                              ──────────────────────────
snitchbot.init("my-svc")
  -> spawns sidecar (if not running)
  -> IPC: startup event ──────────►  receives, renders, sends to TG
                                      ▶ my-svc started

[your code runs normally]

[exit path 1: clean exit]
  atexit hook fires
  -> IPC: shutdown(clean_exit) ───►  ■ my-svc stopped (clean_exit)

[exit path 2: crash]
  sys.excepthook fires
  -> IPC: crash event ───────────►  🔴 crash · my-svc · a1b2c3
  -> IPC: shutdown(crash) ───────►  ⚠ my-svc crashed

[exit path 3: SIGTERM/SIGINT]
  signal handler fires
  -> IPC: shutdown(sigterm) ─────►  ■ my-svc stopped (sigterm)

[exit path 4: SIGKILL / OOM]
  process killed instantly
  -> NO IPC sent                     sidecar detects dead PID
                                    after 10 s grace period:
                                      ⚠ my-svc killed
```

## Exit Reasons

| Reason | Trigger | Detection |
|--------|---------|-----------|
| `clean_exit` | Normal script end, `sys.exit(0)` | `atexit` hook |
| `crash` | Unhandled exception | `sys.excepthook` / `threading.excepthook` |
| `sigterm` | `kill <pid>`, Docker stop, K8s drain | `signal.signal(SIGTERM)` |
| `sigint` | Ctrl+C | `signal.signal(SIGINT)` |
| `killed` | `kill -9`, OOM killer | Goodbye protocol (sidecar-side) |

## Roles

The `role` parameter is a label that appears in lifecycle messages. It helps
distinguish processes in multi-worker deployments:

```python
snitchbot.init("orders-api", role="master")    # ▶ orders-api (master) started
snitchbot.init("orders-api", role="worker")    # ▶ orders-api (worker) started
snitchbot.init("cleanup-job")                  # ▶ cleanup-job started (no role shown)
```

Role is **purely informational** — it does not change any sidecar behavior
(dedup, rate limiting, muting, idle timeout all work identically for every role).

| Role | When to use |
|------|-------------|
| `standalone` | Default. Single-process scripts, CLI tools. Not shown in messages. |
| `master` | Gunicorn/uvicorn master, multiprocessing parent. |
| `worker` | Gunicorn/uvicorn worker, multiprocessing child. |
| any string | Custom role: `"celery-beat"`, `"scheduler"`, `"worker-0"`. Shown as-is. |

### Fork Safety

When a process forks (e.g. gunicorn pre-fork), snitchbot automatically re-inits
in the child via `os.register_at_fork`. The child gets its own PID, its own
startup event, and independent lifecycle tracking. The `role` from `init()` is
preserved across forks.

## Multi-Process Support

Multiple processes can connect to the same sidecar simultaneously:

- **Same service + token + chat_id** -> same sidecar (shared UNIX socket)
- Each process registers with its own PID and role
- Lifecycle events fire independently per PID
- `/status` command shows all connected processes with their roles

Example with 4 processes:

```
▶ orders-api (master) started         pid 1001
▶ orders-api (worker) started         pid 1002
▶ orders-api (worker) started         pid 1003
▶ orders-api (worker) started         pid 1004
⚠ orders-api (worker) killed          pid 1002  (OOM killed)
■ orders-api (worker) stopped         pid 1003  (SIGTERM from K8s drain)
■ orders-api (worker) stopped         pid 1004  (clean exit)
■ orders-api (master) stopped         pid 1001  (clean exit)
```

If one worker dies, only that worker's event fires — others are unaffected.
The sidecar stays alive as long as at least one PID is registered (or within
the 30-second idle timeout after the last PID disappears).

## Goodbye Protocol

When a process dies without sending a shutdown event (SIGKILL, OOM), the sidecar
detects it automatically:

1. Sidecar polls registered PIDs every 5 seconds via `os.kill(pid, 0)`
2. Dead PID found -> start 10-second grace period
3. During grace: if the shutdown IPC arrives (race condition), mark as received
4. After grace: re-check shutdown flag. If still not received -> emit `killed`
5. Event rendered with `reason: killed` and the process role

The grace period prevents false `killed` events when SIGTERM handler sends the
shutdown IPC but the process dies before the sidecar processes it.

## Running Examples

```bash
# Set up credentials
cp .env.example .env
# Edit .env with your SNITCHBOT_TOKEN and SNITCHBOT_CHAT_ID

# Run any example
uv run examples/lifecycle/clean_exit.py
uv run examples/lifecycle/crash.py
uv run examples/lifecycle/sigterm.py
uv run examples/lifecycle/sigkill.py          # also covers OOM kill
uv run examples/lifecycle/multiworker.py
uv run examples/lifecycle/thread_crash.py
```
