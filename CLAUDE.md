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
├── anomalies/               # psutil vitals sampling + 4 anomaly detectors
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
- **Anomaly config v2**: unified 3-mode model per metric (ceiling/spike/drop) with time-based windows. Config classes: `RssAnomalyConfig`, `CpuAnomalyConfig`, `FdAnomalyConfig`, `ThreadAnomalyConfig`, `WatchdogConfig`. Old names (`RssSpikeConfig`, `MemoryAnomalyConfig`, etc.) are deprecated aliases. Variable-length vitals history deque sized from `max_history_seconds()`. Configurable `sample_interval_sec` (default 5s). ASCII charts via `/chart` command (asciichartpy)
- **Stats namespaces**: `_client_stats` (host) and `_sidecar_stats` (sidecar) are disjoint — no sharing
- **Config hash**: `blake2b(f"{token}\0{chat_id}", digest_size=6).hexdigest()` — single source in `shared/domain/services/config_hash_service.py`
- **DI**: manual wiring in `root/entrypoints/sidecar.py`; client side is singleton-module; no DI framework
- **Forum mode (F1–F8)**: when `chat_id` resolves to a forum supergroup AND the bot has `can_manage_topics`, the sidecar creates one topic per `service` and routes alerts/commands per-thread. Otherwise simple mode (current behaviour). Detection is one `getChat` + `getMe` + `getChatMember` call at sidecar startup. State persisted in `state_dir/topics-<config_hash>.json` (atomic rename, mirrors mute persistence). New `init()` kwargs: `forum: bool | "auto" = "auto"`, `topic_color: int | None = None`. Mute entries gain optional `service` for per-topic scoping.
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

### Forum-mode invariants (F1–F8)

| ID | Statement |
|---|---|
| F1 | Mode decided once at sidecar startup. `forum=True` or `forum="auto"` + `getChat.is_forum=true` ⇒ forum mode. Anything else ⇒ simple mode. |
| F2 | Topic mapping is `service: str -> message_thread_id: int`. Mapping is the truth; topic name is cosmetic. |
| F3 | Topic creation is idempotent: cache lookup first, only call `createForumTopic` on miss, persist atomically before sending. |
| F4 | Concurrent `register(service)` calls for same service produce exactly one `createForumTopic` API call (per-service `asyncio.Lock`). |
| F5 | `Bad Request: message thread not found` invalidates cache entry and triggers exactly one recreate retry per send. |
| F6 | Missing `can_manage_topics` ⇒ degrade to General topic + log one ERROR-level warning; never crash. |
| F7 | Inbound commands inside a topic scope to the resolved service. Commands in General (or where `message_thread_id` is None/1) keep global semantics. |
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
# open http://localhost:4321/telegram_analitics/
```

Production build:

```bash
cd site && pnpm build
# output: site/dist/
```

Deployment is automatic on push to `master` when `site/**` or
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