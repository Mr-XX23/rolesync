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
| 3 | Write tools (calendar, Slack, Notion, documents + quotes saved to Drive or the knowledge base, catalog + stock) and guardrails (turn limits + loop detection, retry/timeout, circuit breaker, undo with approval, approval TTL, per-workspace budgets) | done |
| 4 | Context/memory | next |
| 5–6 | Sub-agents, autonomy layer | — |

## Layout

```
app/
  api/            chat, sessions, SSE stream, approvals, health + identity dependencies
  engine/         orchestrator (plan → act → compensate graph), runner (start / pause / resume / recovery /
                  approval expiry), events, run leases, workspace_record (outbox → workspace-service),
                  guardrails/ (turn limits + loop detection, saga compensation, tenant budgets)
  models/         router.py (complexity + failover), providers/ (gemini, openrouter), neutral types
  tools/          gate.py (the choke point), registry.py (definitions + per-agent SCOPES), executor.py
                  (timeout, retries, circuit breaker), adapters/, documents/ (rendering + Drive/KB storage)
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
   never need approval; a write such as `send_email` runs alone, shows the reviewer a preview (built by
   the tool, e.g. a quote's priced lines or a catalog change's before → after), emits
   `awaiting_approval` and pauses durably in the Postgres checkpoint. If a write doesn't go through,
   the rest of that step's calls are skipped so the model re-plans.
4. `POST /approvals/{id}/decision` (approve / edit / reject) resumes the run, in this or another
   process. The gate executes once (idempotency key), and records a saga step and an audit row.
5. If a write failed (or gave no answer, or its approval expired) after other actions of the same request
   succeeded, `compensate` proposes `undo_actions` for those actions: one approval card lists what would be
   undone and what can't be. Nothing is reversed unless the rep approves.
6. The session context, the action's task, sent emails, saved documents and quotes, and the final answer
   are written to `agent.workspace_outbox` and delivered to workspace-service, where they can be retrieved later.

A maintenance sweep resumes runs whose process died (RUNNING with no live lease) from their
checkpoint, and paused sessions whose approvals were decided but never resumed. A write whose
outcome is unknown (timeout, dropped connection) is reported as UNKNOWN and never retried.

## Tools

| Tool | Kind | Backed by |
|---|---|---|
| `send_email` | write (approval), can't be undone | Composio Gmail |
| `create_calendar_event` | write; undo deletes it (attendees get a cancellation) | Composio Google Calendar |
| `send_slack_message` | write; undo deletes the message | Composio Slack |
| `create_notion_page` | write; undo moves it to the trash | Composio Notion |
| `generate_document` | write: docx, pptx, xlsx, pdf or md; undo trashes / deletes the file | rendered in the engine; saved to Google Drive (Composio), else the workspace knowledge vault |
| `create_quote` | write: catalog prices, per-line discounts within each item's limit, totals, optional stock reservation; undo removes the file and releases stock | data-pipeline catalog + document storage as above |
| `create_catalog_item`, `update_catalog_item`, `retire_catalog_item` | write; undo retires / restores the replaced values / restores the status | data-pipeline catalog (never hard-deletes) |
| `set_stock`, `reserve_stock`, `release_stock` | write; undo restores the count / releases the reservation (a release can't be undone) | data-pipeline inventory |
| `undo_actions` | write: undo completed actions of the session, newest first (orchestrator only) | each tool's own undo handler |
| `search_emails`, `read_email_thread` | read | Composio Gmail |
| `list_calendar_events` | read | Composio Google Calendar |
| `search_slack_messages` | read | Composio Slack |
| `search_notion`, `read_notion_page` | read | Composio Notion |
| `search_knowledge_base`, `read_knowledge_document` | read | data-pipeline knowledge vault (keyword retrieval in the adapter) |
| `search_catalog`, `check_inventory` | read | data-pipeline catalog |
| `web_search` | read | Tavily pages + Google Search grounding (Gemini) |
| `research_prospect` | read | web search, condensed into a cited brief by the low-complexity route (OpenRouter) |

Connector tools are denied (not failed) when the user hasn't connected that app. Results carry
`sources` (web pages, message and page links, or links to what a write created), which the chat UI
shows under each step. Catalog writes and stock reservations are denied to workspace viewers. Every
executed write's result includes an `action_id`, which `undo_actions` takes.

## Guardrails

| Guardrail | Where | Behaviour |
|---|---|---|
| Timeout + retry | `tools/executor.py` | Every call has a timeout. Reads and undo steps retry quick transient failures (no answer, 5xx, 429) with exponential backoff, up to `SALES_AGENT_TOOL_READ_ATTEMPTS`; timeouts and writes are never retried. |
| Circuit breaker (per tool) | `tools/executor.py` | After `SALES_AGENT_CIRCUIT_BREAKER_FAILURES` consecutive transient failures a tool fails fast for a cool-down, then one probe call decides. Errors about the request (access, bad input) never trip it. |
| Turn limits + loop detection | `engine/guardrails/limits.py` | Model steps, tool calls and tokens per turn, and the same call with the same arguments more than `SALES_AGENT_MAX_IDENTICAL_TOOL_CALLS` times. A breach ends the turn **HALTED** with a `halted` event and an explanation; the session takes a new request. |
| Saga / compensation | `engine/guardrails/saga.py` | Handlers record how to reverse what they did; `undo_actions` reverses completed steps newest first after approval, each audited as `undo:<tool>` and marked COMPENSATED or COMPENSATION_FAILED. The automatic offer covers only the current request (`session.turn`). |
| Approval TTL | runner maintenance sweep | Approvals past `SALES_AGENT_APPROVAL_TTL_SECONDS` expire; the session resumes with EXPIRED and is offered an undo of what its request already did. |
| Per-workspace budgets | `api/chat.py`, `engine/guardrails/budgets.py` | Before a turn: concurrent runs per workspace, requests per user per minute, model tokens per workspace per UTC day (429 with a message). |

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
| POST | `/chat` | `{"message", "session_id"?, "time_zone"?}` → 202 `{session_id, status, events_url}` (429 over a workspace budget) |
| GET | `/sessions` | the caller's sessions in the workspace |
| GET | `/sessions/{id}` | transcript, open approvals, and `last_event_id` to subscribe after |
| GET | `/sessions/{id}/events` | SSE: `{type, session_id, data, ts}` envelopes; resume with `Last-Event-ID` or `?last_event_id=` |
| GET | `/approvals?status=PENDING` | the caller's pending actions |
| POST | `/approvals/{id}/decision` | `{"decision": "approve" \| "edit" \| "reject", "args"?, "note"?}` |
| GET | `/health`, `/health/ready` | liveness, and readiness (database + Redis) |

Event types: `user_message` (the prompt that started a turn), `step_started`, `token` (`reset: true`
= discard partial text after a model failover), `tool_call`, `tool_result` (with `sources` for
reads, links for writes), `awaiting_approval`, `approval_resolved` (also `EXPIRED` from the TTL worker),
`progress`, `done`, `halted` (a guardrail stopped the turn: `reason`, `message`, `final_answer`), `error`.

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
UNKNOWN outcomes and previews that reject arguments), approvals, the workspace outbox, and Phase 3's
"done when": a forced failure after an approved action offers an undo that compensates once approved
(and nothing when rejected), approval expiry, halts on loops and limits, undo of earlier requests by
`action_id`, and budgets. Unit tests cover every write tool's provider arguments and undo, document
rendering, quote pricing, retries and the circuit breaker. `--live` adds contract checks: Composio
accepts every argument the adapters send (reads, writes and undo steps), Gemini and the failover
models accept every tool schema, and grounding, Tavily and the low-complexity route answer.
