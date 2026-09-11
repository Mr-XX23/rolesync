# Sales Agent Engine

Async FastAPI + LangGraph microservice: an orchestrator and scoped sub-agents that pursue sales
tasks and long-running goals through gated tools, streaming their progress and pausing for human
approval before any real-world action.

- Architecture: [docs/architecture.md](docs/architecture.md)
- Build order: [docs/implementation-plan.md](docs/implementation-plan.md) (phases are built strictly in order)

## Status

| Phase | Scope | State |
|---|---|---|
| 0 | Skeleton, schema `agent`, identity, SSE channel, Tool Gate (tenant/scope/ACL/audit/approval), LangGraph Postgres checkpointer | done |
| 1 | One vertical slice: `send_email` via Composio, model router, orchestrator, approval pause/resume | next |
| 2–6 | Read tools, write tools + guardrails, context/memory, sub-agents, autonomy layer | — |

## Layout

```
app/
  api/            FastAPI routes (health, SSE stream, approvals) + identity dependencies
  engine/         runner (start / pause / resume), event emitter
  tools/          gate.py (the choke point), registry.py (definitions + per-agent SCOPES), executor
  autonomy/       policy envelope (EscalateAllPolicy until Phase 6)
  observability/  TracingClient (no-op until LangSmith is wired)
  db/             SQLAlchemy models, repositories, Alembic migrations (schema `agent`)
  platform/       adapters: LangGraph runtime, JWT verifier, workspace-service, Redis, Eureka
  config.py       settings (SALES_AGENT_* plus shared platform variables)
```

`app/` is a package so the plan's `platform/` folder can't shadow Python's standard `platform` module.

## Identity

The gateway does not verify tokens or inject identity headers, so the engine does:

1. The `access_token` cookie (or `Authorization: Bearer`) is verified with auth-service's RS256
   public key. The user is the `userId` claim (`sub` is a non-unique display name).
2. The tenant is `X-Tenant-Id`, a workspace UUID. The engine confirms membership with
   workspace-service (`GET /api/v1/workspaces`), cached for 60s and re-checked live before any
   denial.
3. The SSE endpoint can't receive custom headers (`EventSource`), so it takes the tenant from the
   session row and re-checks membership.

A logged-out token stays valid here until it expires (up to 60 min), because revocation lives only
inside auth-service.

## API (prefix `/api/v1/sales-agent`)

| Method | Path | |
|---|---|---|
| GET | `/health`, `/health/ready` | liveness, and readiness (database + Redis) |
| GET | `/sessions/{id}/events` | SSE: `{type, session_id, data, ts}` envelopes, resumable with `Last-Event-ID` |
| GET | `/approvals?status=PENDING` | the caller's pending actions |
| POST | `/approvals/{id}/decision` | `{"decision": "approve" \| "edit" \| "reject", "args"?, "note"?}` |

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
`/api/v1/sales-agent/**`.

## Tests

```bash
.venv/Scripts/python -m pytest
```

Integration tests use the local Postgres (database `rolesync-micro-sales-agent-test`) and Redis
db 15. They cover the gate end to end, durable pause/resume across a simulated process restart,
the approvals API and the SSE stream.
