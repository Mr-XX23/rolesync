# Sales Agent Engine

Async FastAPI + LangGraph microservice: an orchestrator and scoped sub-agents that pursue sales
tasks and long-running goals through gated tools, streaming their progress and pausing for human
approval before any real-world action.

- Architecture: [docs/architecture.md](docs/architecture.md) (read its "As built" section first)
- Build order: [docs/implementation-plan.md](docs/implementation-plan.md) (phases are built strictly in order)

## Status

| Phase | Scope | State |
|---|---|---|
| 0 | Skeleton, schema `agent`, identity, SSE channel, Tool Gate (tenant/scope/ACL/audit/approval), LangGraph Postgres checkpointer | done |
| 1 | Vertical slice: chat → orchestrator (model router: Gemini, OpenRouter failover) → `send_email` via Composio → approval pause/resume → audit; workspace records; chat UI | done |
| 2 | Read tools: knowledge base, catalog, Gmail/Calendar/Slack/Notion reads, web search (Gemini grounding + Tavily), prospect research; reads run in parallel; sources in the UI | done |
| 3 | Remaining write tools + guardrails (limits, retry/timeout, circuit breaker, saga, approval TTL) | next |
| 4–6 | Context/memory, sub-agents, autonomy layer | — |

## Layout

```
app/
  api/            chat, sessions, SSE stream, approvals, health + identity dependencies
  engine/         orchestrator (plan → act graph), runner (start / pause / resume / recovery),
                  events, run leases, workspace_record (outbox → workspace-service)
  models/         router.py (complexity + failover), providers/ (gemini, openrouter), neutral types
  tools/          gate.py (the choke point), registry.py (definitions + per-agent SCOPES), adapters/
  autonomy/       policy envelope (EscalateAllPolicy until Phase 6)
  observability/  TracingClient: LangSmith or no-op
  db/             SQLAlchemy models, repositories, Alembic migrations (schema `agent`)
  platform/       adapters: LangGraph, Composio, data-pipeline (knowledge vault + catalog), Tavily,
                  JWT verifier, workspace-service, Redis, Eureka
  config.py       settings, model routing rules, budgets
```

`app/` is a package so the plan's `platform/` folder can't shadow Python's standard `platform` module.

## How a chat turn runs

1. `POST /chat` creates (or continues) a session and starts a background run.
2. `plan` asks the model router for the next step. Complex work goes to Gemini, with OpenRouter as
   failover; tokens stream to `GET /sessions/{id}/events`.
3. `act` runs tool calls through the gate: reads the model asked for together run in parallel and
   never need approval; a write such as `send_email` runs alone, creates a pending action, emits
   `awaiting_approval` and pauses durably in the Postgres checkpoint.
4. `POST /approvals/{id}/decision` (approve / edit / reject) resumes the run, in this or another
   process. The gate executes once (idempotency key), and records a saga step and an audit row.
5. The session context, the action's task, the sent email and the final answer are written to
   `agent.workspace_outbox` and delivered to workspace-service, where they can be retrieved later.

A maintenance sweep resumes runs whose process died (RUNNING with no live lease) from their
checkpoint, and paused sessions whose approvals were decided but never resumed. A write whose
outcome is unknown (timeout, dropped connection) is reported as UNKNOWN and never retried.

## Tools

| Tool | Kind | Backed by |
|---|---|---|
| `send_email` | write (approval) | Composio Gmail |
| `search_emails`, `read_email_thread` | read | Composio Gmail |
| `list_calendar_events` | read | Composio Google Calendar |
| `search_slack_messages` | read | Composio Slack |
| `search_notion`, `read_notion_page` | read | Composio Notion |
| `search_knowledge_base`, `read_knowledge_document` | read | data-pipeline knowledge vault (keyword retrieval in the adapter) |
| `search_catalog`, `check_inventory` | read | data-pipeline catalog |
| `web_search` | read | Tavily pages + Google Search grounding (Gemini) |
| `research_prospect` | read | web search, condensed into a cited brief by the low-complexity route (OpenRouter) |

Connector reads are denied (not failed) when the user hasn't connected that app. Read results carry
`sources` (web pages, message and page links), which the chat UI shows under each step.

## Identity

The gateway verifies the access token and injects `X-User-Id`, but this port can also be reached
directly, so the engine verifies the token itself:

1. The `access_token` cookie (or `Authorization: Bearer`) is verified with auth-service's RS256
   keys (JWKS, or the mounted PEM as fallback). The user is the `userId` claim (`sub` is a
   non-unique display name).
2. The tenant is `X-Tenant-Id`, a workspace UUID. The engine confirms membership with
   workspace-service (`GET /api/v1/workspaces`), cached for 60s and re-checked live before any
   denial.
3. The SSE endpoint can't receive custom headers (`EventSource`), so it takes the tenant from the
   session row and re-checks membership.

Sessions and approvals are private to the user who started them. A logged-out token stays valid
here until it expires (up to 60 min), because revocation lives only inside auth-service.

## API (prefix `/api/v1/sales-agent`)

| Method | Path | |
|---|---|---|
| POST | `/chat` | `{"message", "session_id"?}` → 202 `{session_id, status, events_url}` (429 over the workspace run budget) |
| GET | `/sessions` | the caller's sessions in the workspace |
| GET | `/sessions/{id}` | transcript, open approvals, and `last_event_id` to subscribe after |
| GET | `/sessions/{id}/events` | SSE: `{type, session_id, data, ts}` envelopes; resume with `Last-Event-ID` or `?last_event_id=` |
| GET | `/approvals?status=PENDING` | the caller's pending actions |
| POST | `/approvals/{id}/decision` | `{"decision": "approve" \| "edit" \| "reject", "args"?, "note"?}` |
| GET | `/health`, `/health/ready` | liveness, and readiness (database + Redis) |

Event types: `user_message` (the prompt that started a turn), `step_started`, `token` (`reset: true`
= discard partial text after a model failover), `tool_call`, `tool_result` (with `sources` for
reads), `awaiting_approval`, `approval_resolved`, `progress`, `done`, `error`.

## Configuration

Models, budgets, Composio version pins, workspace sync and identity keys are listed in
[.env.example](.env.example). Defaults fit the free tiers: `gemini-3.5-flash` for complex work (Pro
needs a billed Gemini project) and free NVIDIA Nemotron models on OpenRouter. With
`LANGSMITH_TRACING=true`, every session run, LLM call and tool call is traced to `LANGSMITH_PROJECT`.

## Running

The local stack (Postgres, Redis, workspace-service, ...) comes from `backend/docker-compose.yml`.

```bash
python -m venv .venv && .venv/Scripts/pip install -r requirements-dev.txt
.venv/Scripts/alembic upgrade head
.venv/Scripts/python -m app            # http://localhost:8084/api/v1/sales-agent/docs
```

Use `python -m app` rather than `uvicorn` directly on Windows: psycopg's async mode (the LangGraph
checkpointer) needs a selector event loop, which that entrypoint sets up.

Docker: `docker compose up -d --build sales-agent-engine` (runs migrations, registers with Eureka).
The gateway reads routes at startup, so restart `gateway-service` once to pick up
`/api/v1/sales-agent/**`. The chat UI is at `/salesman/sales-agent` in the frontend.

## Tests

```bash
.venv/Scripts/python -m pytest            # unit + integration (local Postgres + Redis)
.venv/Scripts/python -m pytest --live     # also call real Gemini / OpenRouter / Composio (nothing is sent)
```

Integration tests use the local Postgres (database `rolesync-micro-sales-agent-test`) and Redis
db 15, with scripted models, fake Composio, data-pipeline, Tavily and workspace-service. They cover
the Phase 1 loop and a multi-source research turn over HTTP + SSE, parallel reads, durable
pause/resume across a restart, crash and lease-loss recovery, model failover, the gate (including
UNKNOWN outcomes), approvals, and the workspace outbox. `--live` adds contract checks: Composio
accepts every argument the adapters send, Gemini and the failover models accept every tool schema,
and grounding, Tavily and the low-complexity route answer.
