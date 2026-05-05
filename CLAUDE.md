# snitchbot — Project Context for Claude

> **Self-maintenance rule:** This file MUST be updated whenever the project
> structure, architecture, key decisions, or invariant map changes. After any
> refactor that moves files, adds contexts, or changes conventions — update
> the relevant sections here before closing the task.

This is a Python telemetry library (`snitchbot`) that sends crash reports, slow-call alerts, watchdog events, custom notifications, and anomaly alerts to Telegram from dev/staging/prod Python services.

## Architecture

- **Host client** (`src/snitchbot/client/`) — thin, never blocks, never crashes the host app
- **Sidecar process** (`src/snitchbot/sidecar/`) — detached subprocess, handles all I/O, Telegram, dedup, rate-limit, vitals
- **IPC** — AF_UNIX SOCK_DGRAM, msgpack-encoded events
- **Shared kernel** (`src/snitchbot/shared/`) — event model, error hierarchy, codec, scrubbing, constants, cross-context types
- **Integrations** (`src/snitchbot/integrations/`) — stdlib `logging` handler + `structlog` processor
- **Root composition** (`src/snitchbot/root/`) — entrypoint with manual wiring

### Sidecar Structure (S-DDD bounded contexts)

```
src/snitchbot/sidecar/
├── __main__.py              # thin delegate -> root/entrypoints/sidecar.py
├── session/                 # SidecarSession, idle watcher, graceful shutdown
├── muting/                  # MuteState, persistence, mute/unmute UCs + callbacks
├── anomalies/               # psutil vitals sampling + 6 anomaly detectors (rss, cpu, fds, threads, total_rss, total_cpu)
├── ingest/                  # IPC socket, recv loop, client registry, registration
├── telegram_io/             # TG gateway, long polling, routers, budgets
├── pipeline/                # dedup -> queue -> rate-limit -> render -> dispatch
├── interactive/             # /status /last /test queries, trace callback
└── live_message/            # pinned dashboard message
```

Each context internally follows `domain/ -> app/ -> ports/{driving,driven}/ -> adapters/{driving,driven}/`.

## Design Specs

All specs are in `docs/superpowers/specs/`. Read these before touching the relevant code:

| Topic | File |
|---|---|
| Sidecar architecture, IPC, discovery, handshake | `docs/superpowers/specs/2026-04-11-sidecar-architecture-design.md` |
| Public API (`init`, `notify`, `watch_slow`, `request_context`) | `docs/superpowers/specs/2026-04-11-public-api-design.md` |
| Event model, envelope, fingerprint, invariants E1–E10 | `docs/superpowers/specs/2026-04-11-event-model-design.md` |
| Alert rendering, HTML templates, truncation | `docs/superpowers/specs/2026-04-11-alert-rendering-design.md` |
| Interactive Telegram commands & inline buttons | `docs/superpowers/specs/2026-04-11-interactive-tg-design.md` |
| Dedup & rate-limit, invariants D1–D7, RL1–RL8 | `docs/superpowers/specs/2026-04-11-dedup-rate-limit-design.md` |
| Live message vitals + anomaly detection | `docs/superpowers/specs/2026-04-11-live-message-vitals-design.md` |
| Client internals: excepthooks, watchdog, fork safety, CI1–CI42 | `docs/superpowers/specs/2026-04-11-client-internals-design.md` |
| Secret scrubbing, denylist + regex patterns | `docs/superpowers/specs/2026-04-11-secret-scrubbing-design.md` |
| Logging integration (stdlib + structlog) | `docs/superpowers/specs/2026-04-11-logging-integration-design.md` |

## Implementation Plan

- `docs/superpowers/plans/2026-04-11-implementation-plan.md` — 15 phases, TDD-first
- `docs/superpowers/plans/2026-04-15-sidecar-s-ddd-bounded-contexts.md` — S-DDD migration plan (completed)

Current status: **S-DDD migration complete.** All 8 bounded contexts extracted, full typing (0 Any), code quality passes done.

## Key Decisions (update as resolved)

- **IPC transport**: AF_UNIX SOCK_DGRAM (not SEQPACKET — macOS incompatible)
- **Serialization**: msgpack (base dep); psutil + httpx are sidecar-only optional extras
- **Python**: ≥3.10, Linux primary, macOS supported
- **Stack extraction**: `sys._getframe(1)` (200 ns) not `inspect.stack()` (1–5 ms)
- **Fingerprint**: blake2b(digest_size=3) -> 6-char hex, computed sidecar-side
- **Dedup window**: 5 min, byte-cap 10 MB, entry-cap 10 000
- **Rate limit**: 30 tokens main bucket, critical bypass
- **Fork safety**: `os.register_at_fork(after_in_child=_after_fork_in_child)`
- **Anomaly config v2**: unified 3-mode model per metric (ceiling/spike/drop) with time-based windows. Config classes: `RssAnomalyConfig`, `CpuAnomalyConfig`, `FdAnomalyConfig`, `ThreadAnomalyConfig`, `WatchdogConfig`. Aggregate detectors `total_rss` and `total_cpu` (process + recursive children) are opt-in (`None` by default). Old names (`RssSpikeConfig`, `MemoryAnomalyConfig`, etc.) are deprecated aliases. Variable-length vitals history deque sized from `max_history_seconds()`. Configurable `sample_interval_sec` (default 5s). ASCII charts via `/chart` command (asciichartpy).
- **Subprocess discovery (V11)**: `PsutilVitalsSampler` calls `proc.children(recursive=True)` on every tick and accumulates child RSS/CPU into `VitalsSnapshot.total_rss_bytes`, `total_cpu_percent`, and `children_count`. Child access errors (`NoSuchProcess`, `AccessDenied`) are silently skipped. `total_rss` / `total_cpu` detectors use the same ceiling/spike/drop logic as their "own" counterparts but operate on aggregate values. `SidecarSession` tracks `app_total_rss_bytes`, `app_total_cpu_percent`, and `app_children_count` (sum across all non-dead clients). Live dashboard and `/status` show `own/total/children` per client row plus an Application total block. `/chart` supports `total_mem` and `total_cpu` metrics.
- **Stats namespaces**: `_client_stats` (host) and `_sidecar_stats` (sidecar) are disjoint — no sharing
- **Config hash**: `blake2b(f"{token}\0{chat_id}", digest_size=6).hexdigest()` — single source in `shared/domain/services/config_hash_service.py`
- **DI**: manual wiring in `root/entrypoints/sidecar.py`; client side is singleton-module; no DI framework
- **Per-service topics (F1–F8)**: when `chat_id` resolves to a forum supergroup AND the bot has `can_manage_topics`, the sidecar creates one topic per `service` and routes alerts/commands per-thread. Otherwise every message goes to the chat without a thread id. Detection is one `getChat` + `getMe` + `getChatMember` call at sidecar startup — there is no manual switch in `init()`. State persisted in `state_dir/topics-<config_hash>.json` (atomic rename, mirrors mute persistence). Topic colours are auto-derived deterministically from the service name. Mute entries gain optional `service` for per-topic scoping.
- **Bot-message separator (R1)**: every structured outgoing Telegram message (alerts, lifecycle, `/status`, `/last`, `/test`, `/chart`, `/export`, mute/unmute confirmations, live dashboard, trace, rate-limit) inserts exactly one `━━━━━━━━━━━━━━━━━━` (18 × U+2501) line between the header and the first content block. Single source of truth: `SEPARATOR` in `src/snitchbot/shared/constants.py`. Any new renderer MUST import from there — never inline the literal.

## S-DDD Layer Rules (apply strictly)

- `domain/` — pure Python stdlib only, no frameworks, no I/O
- `app/` — orchestration, no direct I/O, interfaces are Protocols in `app/interfaces/`
- `ports/driving/` — thin facades, may import own `app/` + `domain/`
- `ports/driven/` — implement Protocols from `app/interfaces/`, wrap infra exceptions into PortError
- `adapters/driving/` — controllers, import own `ports/driving/` only
- `adapters/driven/` — raw httpx, psutil, socket, filesystem
- **Cross-context:** siblings communicate only through `shared/` or Protocols (never direct domain imports)
- **`root/`** — composition layer, may import anything
- **`shared/`** — cross-cutting types (ClientState, VitalsSnapshot, RecentEvent, errors, constants)

## Testing Rules

- Unit: pure domain, **no mocks**
- Flow: app layer, `AsyncMock` on all interfaces
- Integration: real UNIX sockets / real psutil / real tmp filesystem / pytest-httpx for TG
- E2E: real client + real sidecar subprocess + mock TG HTTPS server
- Coverage: 80% minimum (`--fail-under=80`)
- Every spec invariant (E1–E10, P1–P8, D1–D7, etc.) maps to at least one test

## Invariant Map (phase -> invariant)

Keep updated as phases complete:

| Phase | Invariants validated |
|---|---|
| 0 | — (scaffolding only) |
| 1 | E1, E2, E3, E4, E7, D2, D7, S1–S12 |
| 2 | I1, I3, I5 |
| … | … |
| F | F1, F2, F3, F4, F5, F6, F7, F8 |

### Rendering invariants (R1)

| ID | Statement |
|---|---|
| R1 | Every structured outgoing Telegram message uses `SEPARATOR` (`"━" * 18`, from `src/snitchbot/shared/constants.py`) as a single divider line immediately after the header and before the first content block. No additional separators between inner sections. Callback answers (toast) and markup-only edits are exempt. |

### Vitals-sampling invariants (V1–V11)

| ID | Statement |
|---|---|
| V1 | Non-FD metrics (`rss_bytes`, `cpu_percent`, `threads`) are sampled on every tick (default 5 s). |
| V2 | Vitals history is stored in a `deque` with `maxlen=60` (5-minute sliding window at 5 s intervals). |
| V3 | `psutil.Process` object is constructed once per client and cached in `ClientState.psutil_process`. |
| V4 | PID reuse is detected via `psutil_create_time` mismatch against `Process.create_time()`; mismatch raises `NoSuchProcess`. |
| V5 | An error on one client does not break the sampling loop for remaining clients. |
| V6 | `NoSuchProcess` on the parent process marks the client `vitals_status='dead'`. |
| V7 | `AccessDenied` on the whole process marks the client `vitals_status='unavailable'`. |
| V8 | `AccessDenied` on `num_fds()` only sets `fds=None` without changing client status. |
| V9 | FDs are sampled every `VITALS_FDS_SAMPLE_SEC` (15 s), not every tick. |
| V10 | `sleep_remaining` returns `max(0, VITALS_SAMPLE_SEC - elapsed)` to prevent drift. |
| V11 | Child-process access errors (`NoSuchProcess`, `AccessDenied`) during recursive enumeration are silently skipped; they must never break sampling of the parent or other clients. |

### Anomaly invariants (A1)

| ID | Statement |
|---|---|
| A1 | Anomaly detection runs after successful sampling. If conditions are met, `_enqueue_anomaly` is called with the anomaly result before the tick ends. |

### Live-message invariants (LM1–LM8)

| ID | Statement |
|---|---|
| LM1 | One live dashboard message per service (per topic in forum mode). `send_message` is never called again once `message_id` is stored. |
| LM2 | `LIVE_MESSAGE_TICK_SEC` constant equals 10 seconds. |
| LM3 | `edit_message_text` is called only when rendered content differs from the previous tick; identical content is a no-op. |
| LM4 | Rendered content is truncated to Telegram's 4096-character limit before sending. |
| LM5 | No live message is created while no clients have vitals; first message is sent on the first tick with at least one client having `latest_vitals`. |
| LM6 | On graceful shutdown, the live message is edited with 🔴 and "stopped" text. |
| LM7 | A fresh sidecar session (no `message_id`) creates a new live message on its first tick with clients. |
| LM8 | Client `vitals_status` transitions are reflected in rendering: `'stale'` appends a `(stale)` suffix to the client row; `'unavailable'` and `'dead'` statuses are handled by the workflow. |

### Forum-mode invariants (F1–F8)

| ID | Statement |
|---|---|
| F1 | Capability decided once at sidecar startup via `getChat` + `getMe` + `getChatMember`. `getChat.is_forum=true` AND `can_manage_topics=true` ⇒ per-service topics active. Anything else ⇒ all messages go to the chat without a thread id. No manual switch is exposed. |
| F2 | Topic mapping is `service: str -> message_thread_id: int`. Mapping is the truth; topic name is cosmetic. |
| F3 | Topic creation is idempotent: cache lookup first, only call `createForumTopic` on miss, persist atomically before sending. |
| F4 | Concurrent `register(service)` calls for same service produce exactly one `createForumTopic` API call (per-service `asyncio.Lock`). |
| F5 | `Bad Request: message thread not found` invalidates cache entry and triggers exactly one recreate retry per send. |
| F6 | Chat is a forum but bot lacks `can_manage_topics` ⇒ all messages go to the chat without a thread id; one INFO-level log line at startup; never crash. Same fallback if `getChat`/`getMe`/`getChatMember` fail (logged at WARNING). |
| F7 | Inbound commands inside a topic scope to the resolved service, and the bot replies inside the same topic. Commands in General (or where `message_thread_id` is None/1) keep global semantics. |
| F8 | Live message dashboards in forum mode are per-topic; pin failure is logged and skipped, never propagated. |

## Documentation sync (MANDATORY)

Any commit that changes `src/snitchbot/**/*.py` in a way that touches the
public surface MUST also update the docs at `site/src/content/docs/`:

1. **Add a symbol to `snitchbot.__all__`** -> create
   `site/src/content/docs/api/<kebab-name>.mdx` with frontmatter matching
   the Zod schema in `site/src/content/config.ts`.
2. **Remove a symbol from `snitchbot.__all__`** -> delete its MDX page.
3. **Change a public signature or semantic** -> update the matching MDX
   (signature block + parameter table + example).
4. **Change integration behaviour** (fastapi / flask / litestar) ->
   update the matching guide under `site/src/content/docs/guide/`.

Verify locally before pushing:

```bash
uv run scripts/check-docs-coverage.py
cd site && pnpm build
```

CI runs the same check and blocks deploy on mismatch.

Deprecated aliases (`RssSpikeConfig`, `CpuSustainedConfig`,
`FdLeakConfig`, `ThreadGrowthConfig`) are intentionally NOT documented.



## Website

The marketing / docs landing page lives in `site/` and deploys to
GitHub Pages via `.github/workflows/pages.yml`.

Local preview:

```bash
cd site
pnpm install
pnpm dev
# open http://localhost:4321/snitchbot/
```

Production build:

```bash
cd site && pnpm build
# output: site/dist/
```

Deployment is automatic on push to `main` when `site/**` or
`.github/workflows/pages.yml` changes. First-time setup requires
enabling **Pages -> Source: GitHub Actions** in the repo settings.

Assets (favicon, OG image, Apple touch icon) are regenerated with
`node site/scripts/generate-icons.mjs` from `site/public/favicon.svg`.

Fonts are self-hosted via `@fontsource/*` packages (Latin subsets only,
~115 KB over the wire). Noto Serif JP for the 見 kanji is deferred to
a future iteration — current fallback is system serif.

Lighthouse audits should be run locally (desktop + mobile preset). The
production bundles gzip to ≈ 4.8 KB JS and ≈ 23.8 KB CSS, well within
the design spec's budgets.

## Release process (PyPI)

Release pipeline lives in `.github/workflows/publish.yml` and uses
**PyPI Trusted Publishing (OIDC)** — no API tokens, no secrets in repo.

### One-time setup (already done, do not repeat)

1. PyPI account for `Sense1Tapo4ek` with 2FA enabled.
2. **Pending trusted publisher** added at
   https://pypi.org/manage/account/publishing/ with:
   - PyPI project name: `snitchbot`
   - Owner: `Sense1Tapo4ek`
   - Repository: `snitchbot`
   - Workflow name: `publish.yml`
   - Environment name: `pypi`
3. GitHub repo: **Settings -> Environments -> New environment `pypi`**
   (optionally add required reviewers / branch protection for the tag ref).

### How to cut a release

1. Bump version in `pyproject.toml` (single source of truth).
2. Commit on `main`: `chore: release vX.Y.Z`.
3. Tag and push:
   ```bash
   git tag vX.Y.Z
   git push origin vX.Y.Z
   ```
4. Workflow `publish.yml` runs automatically:
   - verifies tag matches `pyproject.toml` version (hard-fail otherwise),
   - `uv build` -> sdist + wheel,
   - `pypa/gh-action-pypi-publish` uploads to PyPI via OIDC.
5. After success, create a GitHub Release on the tag with changelog
   (via `gh release create vX.Y.Z --generate-notes` or the web UI).

### Invariants

- Tag MUST be `v<pyproject.version>` — workflow rejects a mismatch.
- Never publish from a branch other than `main`; Trusted Publisher config
  only trusts `publish.yml` on this repo.
- Never hard-code PyPI tokens in `.github/`, `secrets`, or local shells;
  OIDC is the only supported path.
- Bump `version` BEFORE tagging, in the same commit as any final changes.