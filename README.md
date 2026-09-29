# Webhook Inspector

A developer tool for capturing, inspecting, searching, replaying, and testing HTTP webhooks.

Point a third-party service (Stripe, Shopify, GitHub, WooCommerce, your own systems) at a generated
webhook URL, watch requests arrive live, inspect headers/query/body, then replay them — modified or
as-is — to any allowed target.

> Independent portfolio project. Not affiliated with any customer engagement. Deliberately scoped as
> a small, real, deployable developer tool — not a demo toy and not a SaaS platform.

## What It Does

1. **Create endpoint** — get an unguessable webhook URL (`/hook/<128-bit random id>`).
2. **Receive webhooks** — every request (method, headers, query, raw body, parsed JSON, timing,
   signature/auth verdicts) is persisted and answered with your configured response.
3. **Inspect** — searchable, paginated history with a syntax-highlighted, collapsible JSON viewer.
4. **Replay** — resend any captured request (optionally edited) to a target URL, guarded by
   SSRF protection. Every attempt is audited, including blocked ones.
5. **Test provider behavior** — configure the response status/body/content-type/delay your endpoint
   returns, and verify HMAC signatures before your real code sees the payload.
6. **Forget about cleanup** — endpoints have TTLs; a background worker deletes expired data.

## Features

- Unguessable endpoint URLs (cryptographically random public ids)
- Captures `GET/POST/PUT/PATCH/DELETE/OPTIONS/HEAD`; raw body is always preserved first — a JSON
  parse failure never loses data
- Request history with pagination, full-text search (body, headers, path, query) and date-range /
  method filters
- Live updates via Server-Sent Events (with polling fallback); page-hidden-aware
- Replay with editable target URL, method, headers and body (JSON-validated); per-request replay
  audit trail
- Generic HMAC signature verification (SHA-1/256/384/512, hex/base64, constant-time compare,
  provider-style `sha256=` prefixes tolerated) — secrets encrypted at rest, never returned by the API
- Optional per-endpoint ingest token (`X-Webhook-Token`, stored hashed)
- Bearer-token-protected management API with a uniform error envelope
- TTL + retention cleanup worker (graceful shutdown, idempotent, testable)
- Per-endpoint rolling history cap, body-size limit (413), single-instance rate limiting (429 with
  `Retry-After` / `X-RateLimit-*` headers)
- Configurable responses (status/body/content-type, 0–10 s delay) to test how senders react
- Dark/light mode, responsive layout, keyboard-friendly lists, confirm dialogs for destructive
  actions

## Screenshots

| Dashboard | Request detail (JSON body) |
| --- | --- |
| ![Dashboard](docs/screenshots/dashboard.png) | ![Request detail](docs/screenshots/request-detail-json.png) |

| Endpoint overview | Replay & audit trail | SSRF-blocked attempts | Signature verified |
| --- | --- | --- | --- |
| ![Endpoint](docs/screenshots/endpoint-detail.png) | ![Replay](docs/screenshots/replay-result.png) | ![SSRF audit](docs/screenshots/ssrf-blocked-audit.png) | ![Signature](docs/screenshots/request-signature-verified.png) |

## Architecture

```
React 18 + TypeScript + Vite (SPA)
        │  fetch (JSON envelope) + SSE (live updates)
        ▼
FastAPI (single uvicorn instance)
  ├─ api/routes        thin HTTP layer (bearer-token guarded management API, /hook ingest)
  ├─ services          ingest pipeline, replay + SSRF guard, signatures, rate limiter,
  │                    cleanup worker, SSE broker, crypto
  ├─ models/schemas    SQLAlchemy 2.x models, Pydantic v2 schemas
  └─ alembic           migrations
        ▼
PostgreSQL 16 (asyncpg; SQLite supported for tests/quick local runs)
```

In production the built SPA is served by FastAPI itself (single origin, no CORS). The rate limiter
and SSE broker are in-process, which is why the app runs a single worker — see
[Limitations](#limitations).

## Tech Stack

Python 3.12+, FastAPI, Pydantic v2, SQLAlchemy 2.x (async), Alembic, PostgreSQL, httpx,
React 18, TypeScript, Vite, Vitest, Playwright, Docker Compose, GitHub Actions.

## Quick Start (local development)

Prerequisites: Python 3.12+ (developed on 3.13), Node 20+ (developed on 24), and a
PostgreSQL server (or use SQLite for a quick look).

```bash
# 1. Backend
python -m venv .venv
.venv/Scripts/pip install -e "backend[dev]"        # Linux/macOS: .venv/bin/pip ...
cd backend
cp ../.env.example .env                            # then edit ADMIN_API_TOKEN / SECRET_KEY / DATABASE_URL
alembic upgrade head                               # create the schema
uvicorn app.main:app --port 8000                   # http://localhost:8000

# 2. Frontend (dev server with /api + /hook proxy)
cd ../frontend
npm install
npm run dev                                        # http://localhost:5173
```

Open the UI, paste your `ADMIN_API_TOKEN` in **Settings**, and create an endpoint.

SQLite shortcut (no infrastructure): set `DATABASE_URL=sqlite+aiosqlite:///./local.db` in
`backend/.env`. PostgreSQL remains the recommended/production database.

## Docker

```bash
cp .env.example .env      # set ADMIN_API_TOKEN and SECRET_KEY (required)
docker compose up -d --build
# app: http://localhost:8000  (migrations run automatically on start)
```

The compose stack is `app` (multi-stage image, non-root, healthcheck, serves the built SPA) +
`postgres:16` with a persistent volume.

For a **local demo** of the full loop (replay to the built-in mock receiver), overlay the demo file —
it enables the mock receiver and permits private-network replay targets, which you must never do on
a public deployment:

```bash
docker compose -f docker-compose.yml -f docker-compose.demo.yml up -d --build
```

> Docker files are provided but were **not executed in the development environment of this commit**
> (no Docker daemon available); they were kept consistent with the locally verified setup. The
> database layer itself (SQLAlchemy + Alembic + PostgreSQL 16) *was* verified locally against a real
> PostgreSQL server, and CI runs the whole suite against a PostgreSQL service.

## Configuration

| Variable | Default | Purpose |
| --- | --- | --- |
| `ADMIN_API_TOKEN` | — (required) | Bearer token for the management API |
| `SECRET_KEY` | — (required) | Encrypts per-endpoint signature secrets at rest |
| `DATABASE_URL` | postgres dsn | `postgresql+asyncpg://…` (or `sqlite+aiosqlite://…`) |
| `BASE_URL` | *(derive from request)* | Public base URL used in generated webhook URLs |
| `CORS_ORIGINS` | `http://localhost:5173` | Comma-separated allowed origins |
| `MAX_BODY_SIZE` | `1000000` | Ingest body cap (bytes) → 413 |
| `ALLOW_HTTP_REPLAY` | `false` | Allow `http://` replay targets (default https-only) |
| `REPLAY_ALLOW_PRIVATE_NETWORKS` | `false` | Allow replay to private/loopback IPs (demo only!) |
| `REPLAY_TIMEOUT_SECONDS` | `10` | Per-replay HTTP timeout |
| `RATE_LIMIT_REQUESTS` / `_WINDOW_SECONDS` | `120` / `60` | Single-instance ingest rate limit |
| `CLEANUP_INTERVAL_SECONDS` | `60` | Cleanup worker cadence |
| `CLEANUP_GRACE_HOURS` | `24` | Expired endpoints are deleted this long after expiry |
| `ENABLE_MOCK_RECEIVER` | `true` (dev) | Mounts `POST /mock/receiver` (dev/demo only) |
| `TRUST_PROXY_HEADERS` | `false` | Honor `X-Forwarded-For` (only behind a trusted proxy) |
| `APP_ENV` | `development` | `production` hides `/docs` |

## Creating a Webhook Endpoint

UI: **Dashboard → + New endpoint**. Or the API:

```bash
curl -X POST http://localhost:8000/api/endpoints \
  -H "Authorization: Bearer $ADMIN_API_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
        "name": "Stripe sandbox",
        "ttl_hours": 24,
        "max_requests": 100,
        "response_status": 200,
        "response_body": "{\"received\": true}",
        "replay_target_url": "https://your-service.example.com/webhooks"
      }'
```

The response contains the generated `webhook_url`:

```json
{"data": {"id": 1, "webhook_url": "http://localhost:8000/hook/YEy6l5A4N2k2WVAsajHyLw", ...}}
```

## Receiving Webhooks

Point your provider at the URL. Every method is captured; the raw body is stored before anything
else happens:

```bash
curl -X POST http://localhost:8000/hook/YEy6l5A4N2k2WVAsajHyLw \
  -H "Content-Type: application/json" \
  -H "X-Event-Type: order.created" \
  -d '{"order_id":12345,"amount":199.99}'
# → 200 {"received": true}
```

Malformed JSON is kept verbatim (`body_json` stays empty, `body_text`/`body_raw` intact) and
recorded with the response your endpoint configuration produces. Rejected attempts (expired →
`410 endpoint_expired`, disabled → `409 endpoint_disabled`, bad ingest token → `401`,
oversized → `413`, rate-limited → `429`) use the same JSON error envelope and — except rate
limits — are recorded in history so you can see what a sender actually sent.

## Request Inspection

The endpoint page lists requests (newest first) with live SSE updates. The detail view shows
Overview / Headers / Query / Body / Response / Replay. JSON bodies get a collapsible,
syntax-highlighted viewer; everything renders as text — webhook payloads are untrusted input and
are never interpreted as HTML. Sensitive-looking headers (`Authorization`, `Cookie`, `*token*`,
`*signature*`, …) are shown as `[REDACTED]` until you explicitly reveal them.

## Replay

From a request's **Replay** tab you can send a copy to the target URL (defaults to the endpoint's
configured `replay_target_url`), editing method/headers/body before sending. Invalid JSON blocks
sending. The original request is never modified; every attempt creates a replay record:

```bash
curl -X POST http://localhost:8000/api/requests/3/replay \
  -H "Authorization: Bearer $ADMIN_API_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"target_url": "https://httpbin.org/post", "body_text": "{\"order_id\": 99999}"}'
```

```json
{"data": {"status": "success", "response_status": 200, "duration_ms": 1780,
          "target_url": "https://httpbin.org/post", "response_body_preview": "{ ... }"}}
```

Blocked or timed-out attempts are recorded with status `blocked`/`timeout` and an explanation —
the audit trail never loses a refused replay.

### Replay security (SSRF)

Replay is a deliberate outbound-request feature, so it is guarded in depth:

- `https://` only by default (`http://` behind `ALLOW_HTTP_REPLAY=true`); every other scheme
  (`file:`, `gopher:`, `ftp:`, …) is rejected
- `localhost`, `.local`, `.internal`, `.home.arpa` hostnames rejected
- IP literals and **all DNS-resolved addresses** checked against loopback, RFC1918, link-local
  (incl. cloud metadata `169.254.169.254`), CGNAT, reserved, multicast and unspecified ranges
- Redirects are followed manually and **every hop is re-validated**, so a public URL cannot 302
  into an internal address
- **IP pinning (DNS rebinding defence)**: after DNS validation, the TCP connection is pinned to a
  validated address via a custom httpcore network backend. The URL, `Host` header and TLS
  SNI/certificate verification keep using the original hostname, so a re-resolution between
  validation and connection cannot silently move the request to a private address
- Classic IP-obfuscation forms (decimal `2130706433`, hex `0x7f000001`, octal `0177.0.0.1`) and
  IPv4-mapped IPv6 (`::ffff:127.0.0.1`) are rejected before DNS is even consulted
- Response bodies are truncated to `REPLAY_MAX_RESPONSE_BYTES`

## Signature Verification

Configure per endpoint: header name, algorithm (`hmac-sha1/256/384/512`), encoding
(`hex`/`base64`) and secret. Verification runs over the **raw request bytes** (never a
re-serialized JSON document) with constant-time comparison. GitHub-style `sha256=<hex>` prefixes
are tolerated. Results are recorded per request: `verified`, `invalid`, `not_configured`, `error`.

```bash
BODY='{"payment":"confirmed"}'
SIG=$(python -c "import hmac,hashlib;print(hmac.new(b'whsec_demo', b'{\"payment\":\"confirmed\"}', hashlib.sha256).hexdigest())")
curl -X POST http://localhost:8000/hook/<public_id> \
  -H "Content-Type: application/json" -H "X-Signature: sha256=$SIG" -d "$BODY"
```

Verification failures are flagged, not dropped — this is a debugging tool; you decide what to do
with invalid senders. Secrets are encrypted at rest and never returned by the API.

## API Authentication

The management API (`/api/*` except `/api/health`) requires `Authorization: Bearer $ADMIN_API_TOKEN`.
The frontend stores the token in the browser's local storage (Settings page). Webhook ingestion
(`/hook/*`) never requires login; endpoints can additionally require an `X-Webhook-Token` shared
secret (stored hashed). Tokens and secrets are never logged and never returned in responses.

## TTL and Data Retention

Endpoints expire after their TTL (1 h – 30 d or custom). Expired endpoints reject new requests with
`410` but keep history until `CLEANUP_GRACE_HOURS` past expiry, when the cleanup worker deletes
them (requests and replay records cascade). Per-endpoint `request_retention_hours` prunes old
requests individually, and `max_requests` keeps a rolling history window (oldest pruned).

## Security

- Webhook bodies are **untrusted input**: rendered as text/tokens in React (no
  `dangerouslySetInnerHTML`), stored and searched as parameterized SQL (SQLAlchemy, no string
  interpolation), never echoed into logs
- Management API bearer auth + optional ingest tokens, both constant-time compared, both
  absent from logs/responses
- Replay SSRF protection as described above (validated per hop, fail-closed on DNS ambiguity)
- Uniform error envelope; Python tracebacks never reach clients (unknown exceptions → generic
  `internal_error`, details only in server logs)
- CORS is an explicit allow-list; no cookies → no CSRF surface; SPA served same-origin in production
- Oversized bodies rejected by byte-stream cap (not just `Content-Length`)
- SQLite/PostgreSQL migrations via Alembic; no implicit production schema creation

## API Reference

Interactive docs at `/docs` (disabled in production). Summary:

| Method | Path | Purpose |
| --- | --- | --- |
| GET | `/api/health` | Liveness + database check (no auth) |
| GET/POST | `/api/endpoints` | List / create endpoints |
| GET/PATCH/DELETE | `/api/endpoints/{id}` | Manage one endpoint |
| GET | `/api/endpoints/{id}/requests` | History: `search`, `method`, `date_from`, `date_to`, `page`, `page_size` |
| DELETE | `/api/endpoints/{id}/requests` | Clear history |
| GET | `/api/requests/{id}` | Full request detail |
| DELETE | `/api/requests/{id}` | Delete one request |
| POST | `/api/requests/{id}/clone` | Draft for the replay editor |
| POST | `/api/requests/{id}/replay` | Execute a replay |
| GET | `/api/requests/{id}/replays` | Replay audit trail |
| GET | `/api/endpoints/{id}/events` | SSE stream of new requests |
| ANY | `/hook/{public_id}` | Webhook ingestion |
| POST/GET | `/mock/receiver[/requests]` | Dev/demo receiver (when enabled) |

All responses use a uniform envelope: `{"data": …}` on success,
`{"error": {"code": "…", "message": "…"}}` on failure.

## Testing

```bash
# Backend (deterministic: in-memory SQLite, mocked replay HTTP, fake DNS)
cd backend && ruff check . && pytest -q

# Backend against real PostgreSQL
TEST_DATABASE_URL=postgresql+asyncpg://webhook:webhook@localhost:5432/webhook_inspector_test pytest -q

# Frontend
cd frontend && npm test && npm run build

# E2E (requires a running stack; see .github/workflows/e2e.yml)
cd frontend && npx playwright test
```

The suite is 232 backend tests across 15 modules plus 41 frontend unit tests and a 3-scenario
Playwright E2E flow; the backend suite passes identically on in-memory SQLite **and** a real
PostgreSQL 16 server (all three were run locally). Focus: ingest fidelity (raw body
preservation, JSON parsing, oversized bodies, rejections), search/pagination, signature and token
verification, replay success/failure/timeout, the full SSRF block matrix (localhost, private ranges,
CGNAT, link-local/metadata, schemes, redirect bypasses, DNS-to-private), rate limiting, TTL cleanup,
migrations, error envelopes, and UI unit tests for the JSON viewer, header redaction and toasts.

## CI

GitHub Actions (`.github/workflows/ci.yml`) runs on push/PR:

- **backend**: ruff → `alembic upgrade head` → full pytest suite **against a PostgreSQL 16 service**
- **frontend**: vitest → `tsc --noEmit` + production build
- **e2e** (`.github/workflows/e2e.yml`): builds the Docker stack and drives the real UI with
  Playwright through the complete loop (create → webhook → inspect → modify → replay → verify)

No external API keys are required in CI. **Both workflows currently pass on GitHub Actions**
(the first runs on the initial push failed — a vitest/Playwright file-collection conflict, flaky
timing assertions, and the new production-secret policy correctly rejecting the weak CI tokens —
all fixed and verified in 0.2.0).

## Project Structure

```
backend/
  app/
    api/routes/      endpoints, requests, replays, events (SSE), hook, mock, health
    services/        ingest, replay + SSRF, signature, rate limit, cleanup, events, crypto
    models.py        SQLAlchemy models (webhook_endpoints, webhook_requests, replay_records)
    schemas.py       Pydantic v2 API schemas
    config.py        pydantic-settings
    main.py          app factory, error envelope, CORS, SPA mounting
  alembic/           migration environment + initial schema
  tests/             pytest suite (13 modules)
frontend/
  src/
    api/             typed client (envelope unwrapping, token header) + types
    components/      JsonViewer, ReplayPanel, modals, badges, toasts, states
    pages/           Dashboard, Endpoint, RequestDetail, Settings
    hooks/           SSE (fetch-based) + polling fallback + localStorage
    lib/             format, json tokenizer, header redaction
  e2e/               Playwright end-to-end flow
docker-compose.yml   app + postgres:16 (healthcheck, volume)
docker-compose.demo.yml  local demo override (mock receiver + private replay)
```

## Limitations

Stated plainly:

- **Single instance**: the rate limiter and SSE broker are in-process; run one worker. Horizontal
  scaling needs a shared store (future work).
- **Rate limiting is per-endpoint + source IP within one process** — not a distributed limiter.
- **Replay DNS rebinding**: addressed in 0.2.0 — connections are pinned to validated IPs at the
  socket layer and every hop is re-validated (see *Replay security* above, with offline tests for
  the rebinding scenarios). Residual note: the pinning relies on httpcore's network-backend
  contract; it is verified by unit tests plus live HTTP/HTTPS replays, not by a formal security
  audit.
- **No multi-user accounts/billing/IAM** — one admin token protects the API. Deploy behind HTTPS on
  a trusted network; anyone with the token sees all captured data.
- **Webhook payloads are sensitive.** This is a debugging tool: don't point production traffic with
  real customer data at a public instance you don't control; self-host instead.
- **Replay sends real outbound HTTP requests** to targets you choose.
- **SQLite mode** is for tests/quick looks; PostgreSQL is the supported production database.
- The mock receiver is a development aid, not a production feature.

## Development

```bash
cd backend  && ruff check . && pytest -q          # lint + tests
cd frontend && npm run dev                        # Vite dev server (proxies to :8000)
```

Version is `0.2.0` (pre-1.0 by design). See the changelog below.

CI badge: ![CI](https://github.com/taozhihaoo/webhook-inspector/actions/workflows/ci.yml/badge.svg) ![E2E](https://github.com/taozhihaoo/webhook-inspector/actions/workflows/e2e.yml/badge.svg)

## Changelog

### 0.2.0 — Release hardening

- **Security**: replay connections are pinned to DNS-validated IPs (httpcore network backend),
  closing the DNS-rebinding gap; IP-obfuscation forms (decimal/hex/octal, IPv4-mapped IPv6) are
  rejected statically; production mode refuses weak/default/short `ADMIN_API_TOKEN` / `SECRET_KEY`
  (and identical values); SQL parameter logging is silenced unconditionally so stored headers can
  never leak through debug logs.
- **Reliability**: rate-limiter memory is now bounded under adversarial key rotation (sweep +
  hard eviction); oversized requests are rejected even without `Content-Length` (unit-tested);
  SSE streams unsubscribe on disconnect (unit-tested).
- **Verified for real**: the full Playwright E2E flow ran against a live stack (and caught a real
  transport bug in the pinning implementation, which was fixed); the backend suite (232 tests)
  passes on both SQLite and PostgreSQL 16; Alembic `upgrade → downgrade → upgrade` round trip and
  schema-vs-models consistency verified on PostgreSQL; layout checked at 1280/1440/1920/mobile
  widths with no horizontal overflow.
- **CI**: vitest no longer collects Playwright specs (the actual cause of the first frontend CI
  failure); timing-assertion flakiness fixed; E2E workflow writes a proper `.env` so compose
  commands (including failure diagnostics) work.

## License

[MIT](LICENSE)
