# Sales Agent Engine — Implementation Plan
 
> **Audience:** Claude Code, implementing a new microservice inside the existing RoleSync platform.
> **What this is:** The **Sales Agent Engine** — an agentic AI microservice that lets a user pursue sales goals (from a single task like "draft a follow-up" up to a month-long autonomous campaign like "sell 200 shirts this month") by reasoning over multiple steps, calling the whole system's tools, streaming its thinking live, and pausing for human approval before real-world actions. Everything tenant-isolated and audited.
> **What already exists (do NOT rebuild):** Composio connectors (Gmail/Calendar/Slack/Notion/Drive read+write), the knowledge-base retrieval/vector pipeline, the product/service catalog service, the Spring Cloud Gateway (JWT + tenant), Postgres, MongoDB, pgvector, Redis, Kafka. This engine **calls** those as tools.
 
---
 
## 0. Prime directives (read first — these govern every decision)
 
1. **This is a brain over existing hands.** The engine never re-implements Gmail, Slack, catalog, etc. It exposes what already exists as **tools** and reasons over them. New code is concentrated in: orchestration, the tool gate, model router, memory/context, guardrails, and the autonomy layer.
2. **Wrap every external dependency behind your own interface.** LangGraph, Gemini SDK, OpenRouter, Composio, LangSmith — each sits behind a thin adapter your code owns (`LLMProvider`, `TracingClient`, `ConnectorClient`, etc.). Business logic never imports a vendor type directly. This is non-negotiable: these APIs churn, and you must be able to swap one without a rewrite.
3. **One choke point for all tool calls.** Every tool call from every agent passes through the **Tool Gate**: tenant check → ACL → per-agent scope → audit → (approval if a write). Nothing bypasses it. This is what makes "the agent can touch the whole system" safe.
4. **Orchestrator-mediated, never peer-to-peer.** Sub-agents never call each other. The orchestrator delegates and collects results. One coordinator, one place to audit, no tangle.
5. **Never act on the real world without a gate.** Any write/send/schedule/charge/delete requires human approval (interactive mode) or must be inside the pre-approved autonomy envelope (autonomous mode). Reads are free.
6. **Build in strict phase order (§10).** The full architecture is the target, not the day-one build. Each phase must work before the next goes on top.
---
 
## 1. Tech stack (locked)
 
| Concern | Choice | Notes |
|---|---|---|
| Language | Python 3.11+ | matches platform |
| Web / API | FastAPI, **fully async** | separate service; async end-to-end (streaming + LangGraph) |
| Agent framework | **LangGraph** + Deep Agents patterns | durable execution, streaming, human-in-the-loop, subagents |
| Primary model | **Gemini** | complex reasoning: planning, negotiation, quote logic |
| Secondary model | **OpenRouter** | simple tasks + failover |
| Model selection | **Model Router** (new) | complexity hint + failover, one place |
| Streaming | **SSE** (Server-Sent Events) | server→client events; approvals via POST |
| Durable state / checkpoints | **Postgres** via `langgraph-checkpoint-postgres` | off-the-shelf pause/resume |
| Goals / memory / audit / traces | **Postgres** (schema `agent`) | structured, transactional |
| Wake queue | **Redis** (existing) | dedup, rate control, trigger-storm buffer |
| Event triggers | **Composio + Kafka** (existing) | subscribe, don't rebuild |
| Scheduler | **hand-rolled Postgres + Redis worker** | Temporal later only if needed |
| Tracing | **LangSmith** (behind an adapter) | swap to OTel later if cost/residency demands |
| Metrics / errors | **Grafana + Sentry** (existing) | |
 
> **Sync/async note:** this engine is async; the catalog service is sync. They are separate microservices communicating over HTTP/tools, so there is no sync/async conflict — do not share DB sessions or code between them.
 
---
 
## 2. Service layout
 
```
sales-agent-engine/
├── api/                      # FastAPI routes
│   ├── chat.py               # single-task prompt + SSE stream
│   ├── goals.py              # create/list/cancel long-running goals
│   ├── approvals.py          # approve/edit/reject pending actions
│   └── stream.py             # SSE event channel
├── engine/                   # the reactive core (LangGraph)
│   ├── orchestrator.py       # planner graph, sole coordinator
│   ├── subagents/            # research, outreach, quote (scoped)
│   ├── guardrails/           # limits, circuit breaker, retry/timeout, saga
│   └── events.py             # event emitter → SSE
├── models/                   # model router
│   ├── router.py             # complexity + failover
│   └── providers/            # gemini_provider.py, openrouter_provider.py (behind LLMProvider)
├── tools/                    # tool layer
│   ├── gate.py               # THE choke point (tenant+ACL+scope+audit+approval)
│   ├── registry.py           # tool definitions + per-agent scope map
│   └── adapters/             # composio_tool.py, catalog_tool.py, kb_tool.py, docgen_tool.py, ...
├── context/                  # shared context + memory
│   ├── manager.py            # compress/summarize/offload; the ONLY memory surface
│   ├── locks.py              # state lock + versioning
│   └── stores.py             # conversation / rep / deal memory
├── autonomy/                 # long-running goals
│   ├── goal_manager.py       # persistent goal object + progress
│   ├── scheduler.py          # time-based wakes (Postgres job table + worker)
│   ├── triggers.py           # event-based wakes (Kafka/Composio subscription)
│   ├── wake_queue.py         # Redis, idempotent, rate-controlled
│   └── policy.py             # autonomy envelope (act-alone vs escalate)
├── observability/
│   └── tracing.py            # LangSmith behind TracingClient adapter
├── db/                       # SQLAlchemy async models + Alembic migrations (schema `agent`)
├── platform/                 # adapters to existing services (wrap vendors here)
└── config.py                 # env, tenant budgets, model routing rules
```
 
---
 
## 3. Data model (Postgres, schema `agent`, async SQLAlchemy + Alembic)
 
All tables carry `tenant_id` and filter on it from the authenticated context. UUID PKs, `created_at`/`updated_at`.
 
### 3.1 `agent.session` — one interactive run or one wake
```
id, tenant_id, user_id, goal_id (nullable),
mode        text CHECK (mode IN ('INTERACTIVE','AUTONOMOUS')),
status      text CHECK (status IN ('RUNNING','AWAITING_APPROVAL','DONE','FAILED','HALTED')),
checkpoint_ref text,   -- LangGraph checkpoint id
started_at, ended_at
```
 
### 3.2 `agent.goal` — the persistent long-running objective
```
id, tenant_id, user_id,
title            text,           -- "sell 200 shirts this month"
target           jsonb,          -- {metric:'units_sold', value:200}
progress         jsonb,          -- {units_sold:34}
deadline         timestamptz,
strategy         jsonb,          -- current plan (re-assessed each wake)
priority         int,
status           text CHECK (status IN ('ACTIVE','PAUSED','MET','EXPIRED','CANCELLED','ESCALATED')),
-- guardrails on the goal itself:
budget           jsonb,          -- {max_emails, max_spend, max_discount_pct}
spent            jsonb,          -- running totals to enforce budget
terminal_reason  text
```
 
### 3.3 `agent.scheduled_wake` — hand-rolled scheduler jobs
```
id, tenant_id, goal_id,
fire_at      timestamptz,
kind         text,              -- 'FOLLOW_UP','PACING_CHECK','DEADLINE'
idempotency_key text UNIQUE,    -- prevents double-fire (see §7)
status       text CHECK (status IN ('PENDING','FIRED','SKIPPED','FAILED'))
```
 
### 3.4 `agent.wake_log` — every wake, for idempotency + audit
```
id, tenant_id, goal_id, source text ('SCHEDULE','TRIGGER'),
idempotency_key text UNIQUE, fired_at, session_id
```
 
### 3.5 `agent.memory` — versioned shared memory
```
id, tenant_id,
scope        text CHECK (scope IN ('CONVERSATION','REP','DEAL','ACCOUNT')),
scope_key    text,              -- session_id / user_id / deal_id
content      jsonb,
version      int,               -- optimistic locking (§ context manager)
updated_at
UNIQUE (tenant_id, scope, scope_key, version)
```
 
### 3.6 `agent.pending_action` — the human-in-the-loop queue
```
id, tenant_id, session_id,
tool         text, args jsonb,  -- the action awaiting approval
preview      jsonb,             -- human-readable draft (email body, discount, recipients)
status       text CHECK (status IN ('PENDING','APPROVED','EDITED','REJECTED','EXPIRED')),
expires_at   timestamptz,       -- TTL (§ approval timeout)
resolved_by, resolved_at
```
 
### 3.7 `agent.audit` — every executed action (compliance)
```
id, tenant_id, session_id, agent text, tool text, args jsonb,
result_summary text, at timestamptz
```
 
### 3.8 `agent.saga_step` — side-effect log for compensation
```
id, tenant_id, session_id, step_no int,
action text, undo_action jsonb,  -- how to reverse it
status text CHECK (status IN ('DONE','COMPENSATED')), ref_id
```
 
> Full execution **traces** (reasoning, tool timings, model choices) go to **LangSmith** via the tracing adapter — distinct from `agent.audit` (which records *actions* for compliance). Traces are for debugging/replay; audit is for "what did the agent do."
 
---
 
## 4. The Tool Gate (`tools/gate.py`) — the single most important component
 
Every tool call routes through one function. No exceptions.
 
```python
async def call_tool(ctx: AgentContext, agent_name: str, tool: str, args: dict) -> ToolResult:
    # 1. Tenant + user resolved from ctx (from JWT upstream) — NEVER from args
    # 2. Per-agent scope check: is `agent_name` allowed to call `tool`?
    #    (research=READ-only; outreach=SEND; quote=CATALOG) — registry.SCOPES
    # 3. ACL check: does this tenant/user have access to the target resource?
    # 4. If tool is a WRITE:
    #      - INTERACTIVE mode  -> create agent.pending_action, emit 'awaiting_approval',
    #                             pause (LangGraph interrupt). Resume on approval.
    #      - AUTONOMOUS mode    -> ask autonomy.policy: inside envelope? act : escalate.
    #      - record agent.saga_step (with undo_action) BEFORE executing.
    # 5. Execute via RetryTimeout wrapper (per-tool retry/backoff/timeout).
    # 6. Write agent.audit row.
    # 7. Return result.
```
 
**Rules:**
- Reads never require approval. Writes always do (interactive) or must be inside the envelope (autonomous).
- The `agent_name → allowed tools` scope map lives in `tools/registry.py`. A research agent that tries to call `send_email` is rejected here, not trusted.
- Saga step recorded **before** the side-effect, so a later failure can compensate.
- Idempotency: if the same action (same idempotency key) was already executed, skip and return the prior result.
---
 
## 5. Model Router (`models/router.py`)
 
```python
async def get_completion(task: TaskSpec) -> Completion:
    # task.complexity: 'high' | 'low'  (caller-provided hint; default 'high' when unsure)
    provider = GEMINI if task.complexity == 'high' else OPENROUTER
    try:
        return await provider.complete(task)   # provider behind LLMProvider interface
    except (RateLimited, ProviderError):
        if provider is GEMINI:
            return await OPENROUTER.complete(task)   # failover
        raise
```
 
- Both providers implement one `LLMProvider` interface (`complete`, `stream`). Swapping either = one file.
- Every agent asks the router for a brain; no agent calls Gemini/OpenRouter directly.
- Routing rules (which complexity → which model/model-id) live in `config.py`, not scattered.
---
 
## 6. Shared Context + Memory (`context/manager.py`)
 
- **The only surface agents use for shared state.** Sub-agents never read/write memory directly; they go through the manager (keeps one controlled, lockable, auditable surface).
- **Compression / summarization / offload:** before context exceeds a token budget, the manager summarizes older turns and offloads large tool results to storage, passing a reference instead (prevents context explosion).
- **Locking + versioning:** writes use optimistic concurrency on `agent.memory.version` (read version → write version+1; conflict → re-read + merge). Prevents concurrent-write corruption from two sub-agents or two of the user's requests.
---
 
## 7. Autonomy layer (`autonomy/`) — long-running goals
 
**Loop:** goal set → agent acts → sleeps → scheduler/trigger wakes it → re-assess against goal → act → … until terminal condition.
 
- **`goal_manager.py`** — owns the persistent `agent.goal`. On each wake, the orchestrator reads current goal+progress and **re-assesses the strategy against reality** (never blindly runs the day-1 plan). Enforces goal budget caps and terminal conditions (target met / deadline passed / cancelled → hard stop; no zombie goals).
- **`scheduler.py`** — Postgres `scheduled_wake` table + a Redis worker that polls for `fire_at <= now()` and enqueues wakes. Every wake carries an **idempotency_key**; a wake already in `agent.wake_log` is skipped (no double-fire).
- **`triggers.py`** — subscribes to existing Kafka/Composio events (reply, order, stock-out) and enqueues event wakes (also idempotency-keyed).
- **`wake_queue.py`** — Redis queue that dedupes and **rate-controls** wakes so a reply-storm (200 replies at once) doesn't spawn 200 parallel runs — it throttles and batches.
- **`policy.py` — the autonomy envelope (critical safety):** defines what the agent may do **alone** vs. what **escalates to a human even mid-campaign**.
  - Inside envelope (act alone): follow-up to an existing contact, log activity, update progress, pull data.
  - Outside envelope (pause → human): new discount / discount beyond `max_discount`, contacting a net-new list, any irreversible action, anything that would exceed the goal budget.
  - Escalation path: if the goal can't be met within the rules (e.g. behind target and would need to break the discount cap), set goal `status=ESCALATED`, notify the human, do **not** self-authorize breaking a rule.
---
 
## 8. Guardrails (`engine/guardrails/`)
 
- **Limits:** max steps, max recursion/delegation depth, max cost per run — checked before each step.
- **Circuit breaker:** trips on loop detection / limit breach → halts the run cleanly (`status=HALTED`), emits an event, never silently spins.
- **Retry + timeout:** per tool call (exponential backoff; bounded). One dead tool degrades, doesn't crash the run.
- **Saga / compensation:** on mid-plan failure, walk `agent.saga_step` in reverse and run each `undo_action`.
- **Approval TTL:** `pending_action.expires_at`; a worker expires stale approvals and triggers compensation so runs don't hang forever.
- **Per-tenant budgets** (`config.py` + gateway): rate, cost, concurrency, session isolation — enforced before a run/goal starts.
---
 
## 9. Streaming + approval (`api/stream.py`, `api/approvals.py`)
 
- **SSE event envelope** (server → client). Emit at every meaningful step so the UI shows live "thinking":
```json
{ "type": "step_started|token|tool_call|tool_result|awaiting_approval|progress|done|error",
  "session_id": "...", "data": { ... }, "ts": "..." }
```
- **Approval flow:** on a write in interactive mode, emit `awaiting_approval` with the `pending_action` preview → LangGraph interrupt (durable pause) → user POSTs approve/edit/reject to `api/approvals.py` → resume from checkpoint. Edited actions run the edited args.
- Client→server (approvals, new prompts) are normal POSTs; only the event stream is SSE.
---
 
## 10. Build order (STRICT — do not skip ahead)
 
Each phase must be demonstrably working before the next. This de-risks the hard parts first.
 
**Phase 0 — Skeleton + the gate.**
FastAPI async service, LangGraph installed with the Postgres checkpointer, SSE channel with the event envelope, and the **Tool Gate empty but wired** (tenant+ACL+scope+audit+approval pathway). Nothing reasons yet. *Done when:* a stub tool call flows through the gate, gets audited, and an event streams to a test client.
 
**Phase 1 — One vertical slice: single tool, streaming, approval.**
Wire exactly one write tool (`send_email` via Composio). Prompt → orchestrator (Gemini via model router) plans → streams "drafting" → gate creates `pending_action` → pauses → user approves → resumes → sends → audits. *Done when:* the full interactive loop works end-to-end for one tool, including durable pause/resume.
 
**Phase 2 — Read tools (no approval).**
Knowledge-base search, catalog query, Gmail/Calendar/Slack/Notion read, web search, prospect research. Model router routing (simple→OpenRouter) active. *Done when:* the agent can research and answer a multi-source question, streaming its steps.
 
**Phase 3 — Remaining write tools + guardrails.**
Calendar create, Slack send, Notion write, Drive store (+ "if full → save to KB"), doc generation (docx/pptx/xlsx/md/pdf), catalog CRUD, quote/proposal — all through the gate. Add Limits, RetryTimeout, Circuit breaker, Saga, Approval TTL. *Done when:* every write is gated+approved+audited, and a forced tool failure compensates cleanly.
 
**Phase 4 — Context + memory.**
Context manager (compress/summarize/offload), state lock + versioning, conversation/rep/deal memory. *Done when:* a long multi-step run stays within token budget and two concurrent writes don't corrupt memory.
 
**Phase 5 — Multi-agent.**
Research / outreach / quote sub-agents via Deep Agents patterns, orchestrator-mediated (result-only back to planner), each with its permission scope enforced at the gate. *Done when:* the orchestrator delegates a real task across sub-agents and no sub-agent can exceed its scope.
 
**Phase 6 — Autonomy layer.**
Goal manager, hand-rolled scheduler, trigger subscription, wake queue (idempotent + rate-controlled), autonomy policy envelope, goal budgets + terminal conditions + escalation. *Done when:* "sell N this month" runs across multiple scheduled/triggered wakes, re-assesses each wake, respects the envelope, updates progress, and hard-stops on target/deadline.
 
**Cross-cutting (add incrementally from Phase 1):** LangSmith tracing behind the adapter, Grafana metrics, Sentry errors, per-tenant budgets.
 
---
 
## 11. Acceptance criteria (the whole engine)
 
- Every tool call passes through the gate; no path reaches a tool otherwise. A research agent calling a write tool is rejected.
- Reads never prompt for approval; writes always do in interactive mode, or obey the envelope in autonomous mode.
- Interactive: agent pauses on a write, survives a process restart (durable checkpoint), and resumes correctly on approval.
- A forced mid-plan failure runs compensation and leaves no partial side-effects.
- Two providers: complex tasks hit Gemini, simple hit OpenRouter, and Gemini failure fails over to OpenRouter with no run failure.
- Long goal: a scheduled wake and a duplicate wake with the same idempotency key result in exactly one execution.
- Autonomous panic case: when hitting the target would require exceeding `max_discount`, the agent escalates to a human instead of self-authorizing.
- Terminal conditions fire: goal hard-stops on target met or deadline passed; no zombie goals keep running.
- Full tenant isolation: no session, memory, goal, or tool result crosses tenants.
- Every executed action has an `agent.audit` row; every run has a LangSmith trace.
---
 
## 12. Explicitly out of scope for v1
 
- Temporal (revisit only if the hand-rolled scheduler's crash/exactly-once handling gets painful).
- OpenTelemetry tracing (LangSmith for now; the adapter makes switching cheap).
- Autonomous money movement / charging (quotes and payment links only; money moves through a human-confirmed step — separate future work).
- Peer-to-peer agent communication (orchestrator-mediated only).
- Fully autonomous writes with no envelope (the envelope is mandatory).
 