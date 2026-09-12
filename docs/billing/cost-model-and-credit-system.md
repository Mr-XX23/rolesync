# Role-Sync — Platform Cost Model & Credit System Design

> Status: **Phase A deliverable (cost analysis)** — code-verified 2026-09-12. No billing code has been written yet.
> This document is the source of truth for the credit economics. Numbers here are derived from the
> actual wired code paths (four code audits) + current vendor pricing (Sept 2026), **not** from the
> aspirational `backend/data-pipeline/doc/arch.md` design.

---

## 0. How to read this (the single most important caveat)

There are **two cost regimes** and they differ by ~100×:

| Regime | What it means | Marginal AI cost |
|---|---|---|
| **Today (dev / free-tier)** | data-pipeline *chat*-LLM runs on OpenRouter `:free` models; the gatekeeper "semantic scorer" doesn't exist. **Embeddings are now REAL** (Gemini, PR #19). | **≈ $0/token for chat-LLM.** Real spend: **LlamaParse** per-page, **Gemini embeddings** per-document, and the **sales-agent-engine** on **Gemini 3.5 Flash** once its small free quota is exhausted. |
| **At scale (production, paid)** | Free tiers are rate-limited (OpenRouter free = 50 req/day; Gemini free quota is tiny) and cannot serve real traffic. Everything must move to paid models. | This is what the credit system must be priced against. |

**Do not price credits against "today ≈ $0."** Price them against the at-scale paid regime below.

### The one lever that dominates everything

The **sales agent turn is the platform's dominant cost**, and it currently runs on **`gemini-3.5-flash` ($1.50 in / $9.00 out per 1M)** by default (complexity defaults to HIGH). Re-routing routine planning to `gemini-2.5-flash` (5× cheaper) or `gemini-2.5-flash-lite` (~15–20× cheaper), capping output tokens, and cutting the Google-Search grounding surcharge is a **5–20× cost reduction on the dominant operation.** Decide the model/grounding strategy **before** finalizing credit prices — it changes "what $10 buys" from ~17 agent messages to ~100+.

---

## 1. Complete cost inventory

### 1.1 Variable costs (scale with user activity — the credit surface)

| Cost | Provider | Billing unit | Attributable to a user? | Wired today? |
|---|---|---|---|---|
| LLM reasoning (agent) | Gemini | tokens (in/out) | Yes (per turn) | **Yes, paid** (`gemini-3.5-flash`) |
| LLM web grounding | Gemini + Google Search | tokens + $/1k grounded prompts | Yes (per search) | **Yes, paid** (`gemini-2.5-flash`) |
| Web search | Tavily | $/search | Yes (per search) | Yes, paid |
| LLM classification / findability / query-expansion | OpenRouter | tokens | Yes (per doc/search) | Yes but **`:free` → $0** today |
| Embeddings (index-time) | Gemini | tokens | Yes (per doc) | **Yes, paid** (`gemini-embedding-001`, 1536-dim) |
| Embeddings (query-time) | Gemini | tokens | (per search) | **Not wired** — `embed_query()` has no callers |
| Document parsing/OCR | LlamaParse | **$/page** | Yes (per doc) | **Yes, paid** (default tier) |
| Tool actions (connectors) | Composio | **$/tool-execution** | Yes (per sync / per agent tool call) | Yes (reads in data-pipeline; **writes** in agent) |
| SMS OTP | Twilio | $/segment | Yes (onboarding) | Yes, paid |
| Avatar image storage | Cloudinary | storage + bandwidth | Yes (per avatar) | Yes (free tier covers early) |
| Tracing | LangSmith | $/trace | Indirectly (per LLM+tool call) | Yes (`LANGSMITH_TRACING=true`) |
| Transactional email | Gmail SMTP | ≈ free | Yes (onboarding) | Yes (≈ $0; ~500/day cap) |

### 1.2 Fixed costs (paid regardless of activity — allocate across active users, do NOT charge per-op)

The whole stack currently runs in one `docker-compose` (Postgres, MongoDB, Redis, Kafka+Zookeeper, config, eureka, gateway, auth, workspace, data-pipeline, sales-agent-engine). **No Neo4j, no S3, no managed Atlas** in reality. Estimated small-production footprint:

| Item | Lean (self-hosted VPS) | Managed cloud |
|---|---:|---:|
| Compute (5 JVM + 2 Python services) | $120 | $250 |
| Postgres | (on VM) | $60 |
| MongoDB | (on VM) | $60 |
| Kafka + Zookeeper | $30 | $150 |
| Redis | (on VM) | $25 |
| Object store (MinIO self-hosted → R2/S3 later) | (on VM) | $15 |
| Monitoring / logging | $10 | $30 |
| Composio platform (Pro) | $29 | $29 |
| LlamaParse / Tavily / LangSmith floors | $0–80 | $0–110 |
| Domain / SSL / backups | $12 | $30 |
| **Total fixed / month** | **~$210** | **~$700** |

**Baseline used in the calculator: ~$350/mo.** Fixed cost per user = $350 ÷ (active users): 50 users → $7.00; 200 → $1.75; 1,000 → $0.35. **Break-even ≈ 47–50 paying users** at a $10/mo package (75% gross margin).

---

## 2. Current provider pricing (config-driven — see §11.1; never hardcode)

All USD, Sept 2026. Sources verified via vendor/aggregator pages.

| Provider | Model / unit | Input | Output | Notes |
|---|---|---:|---:|---|
| Gemini | `gemini-3.5-flash` | $1.50 /1M | $9.00 /1M | current agent "complex" default |
| Gemini | `gemini-2.5-flash` | $0.30 /1M | $2.50 /1M | agent grounding model |
| Gemini | `gemini-2.5-flash-lite` | $0.10 /1M | $0.40 /1M | cheapest viable |
| Gemini | `gemini-3.6-flash` | $0.75 /1M | $3.75 /1M | promo thru Dec'26 (then $1.50/$7.50) |
| Gemini | `gemini-embedding-001` **(in use)** | $0.15 /1M | — | $0.075/1M via async Batch API — **not used**, code calls sync `batchEmbedContents` |
| Gemini | Gemini Embedding 2 (successor) | $0.20 /1M | — | migration ⇒ full corpus re-embed |
| Gemini | Google Search grounding (2.5) | $35 /1k prompts | — | 1,500/day free |
| Gemini | Google Search grounding (3.x) | $14 /1k prompts | — | 5,000/mo free — **cheaper, prefer** |
| OpenRouter | `:free` models | $0 | $0 | 50 req/day (1k after $10) — **not scalable** |
| OpenRouter | paid passthrough | list | list | +5.5% on credit top-ups only |
| LlamaParse | per page (default tier) | ~$0.00375 | — | fast $0.00125 · agentic $0.0125 · agentic+ $0.056; 10k credits/mo free |
| Composio | tool execution (overage) | $0.004 | — | 20k/mo free; Pro $29 = 50k; trigger events $1/1k |
| Tavily | basic search | $0.008 | — | 1k/mo free |
| Twilio | SMS segment (US A2P) | ~$0.0125 | — | + one-time A2P registration |

---

## 3. Per-operation cost model (at-scale, paid rates)

**Metered ops** (charge on *actual* tokens): agent turn, any LLM op.
**Flat ops** (charge per unit from config): doc parse (per page), classification (per doc), Composio (per execution), web search (per call).

| Operation | External services | Calls / unit | Avg cost | Max (P99+) cost | Notes |
|---|---|---|---:|---:|---|
| **Document parse** | LlamaParse | 1 job / doc; per page | **$0.030** (8 pg) | **$0.19** (50 pg) | text/csv/md parse free-local; **reindex re-parses (leak, §7)** |
| **Embedding (index-time)** | Gemini embeddings | 1 call / 100 chunks | **$0.0009** (8 pg) | **$0.006** (50 pg) | ≈ document token count (512-char chunks, **no overlap inflation**); **delta-checked** |
| **Document classification** | OpenRouter→(paid) | 2 / doc | **$0.002** | $0.005 | ≈$0 today (free tier); trivial at paid |
| **Reclassification** | OpenRouter→(paid) | 1 / call | **$0.002** | $0.03 | re-charges each call; reindex adds a re-parse |
| **AI catalog search** | OpenRouter→(paid) | 1 / search | **$0.0002** | $0.001 | KB search = $0 (keyword); expansion on by default |
| **Agent turn — simple** | Gemini 3.5F | ~2 LLM | **$0.039** | — | no tools |
| **Agent turn — typical** | Gemini 3.5F + Tavily + grounding | ~3 LLM + 1 search | **$0.114** | — | grounding surcharge $0.035 dominates the search |
| **Agent turn — heavy** | Gemini 3.5F ×N + searches | delegation | **$0.45** | — | 3 sub-agents × up to 6 steps |
| **Agent turn — worst case** | Gemini 3.5F + unmetered sub-ops | near caps | — | **$2–4** | uncapped output + unmetered sub-ops (§7) |
| **Web search (grounded)** | Gemini 2.5F + Google + Tavily | 1 | **$0.044** | $0.05 | $0.035 grounding + $0.008 Tavily |
| **Composio action** | Composio | 1 exec | **$0.004** | $0.004 | +the agent turn that drives it |
| **Connector sync (Gmail incremental)** | Composio | 1 exec | **$0.004** | $0.04 | historical backfill up to 10 pages |
| **Connector sync (GDrive)** | Composio | 1 + N files | **$0.004 + $0.004·N** | — | one DOWNLOAD per file — heaviest per-item |
| **Idle auto-sync polling** | Composio | ≥1 exec / tick | — | **$5.76–$86 / mo / connector** | 30m default → 48/day; 2m → 720/day (§7 risk) |
| **Memory save / recall** | — | 0 LLM | **$0** | $0 | keyword + DB only |

### 3.1 Agent-turn cost distribution (the operation that sets the price)

| Percentile | Scenario | Cost (3.5 Flash) | Cost (2.5 Flash) | Cost (2.5 Flash-Lite) |
|---|---|---:|---:|---:|
| P50 | typical, 1 search | $0.11 | $0.06 | $0.05 |
| P90 | busy, 1–2 searches | $0.30 | $0.12 | $0.08 |
| P95 | light delegation | $0.45 | $0.15 | $0.09 |
| P99 | heavy delegation + searches | $1.00 | $0.35 | $0.20 |
| Max | near hard caps, uncapped output | $2–4 | $0.8–1.5 | $0.4–0.8 |

> Because agent turns are **metered on actual tokens**, worst-case turns don't create a loss — the user is charged for what they consume. Protection needed is **preflight + hold**, a **per-turn credit ceiling**, and **output caps** (§6). The remaining P50→P99 spread (~10×) is why flat per-turn pricing would be a mistake.

> **Actual measured distributions:** LangSmith tracing is already on. Once there is real traffic, pull true P50/P90/P95/P99 token counts per operation from LangSmith and replace these code-derived estimates. Until then these are engineering estimates from the wired token budgets.

---

## 4. The credit unit (derived, not guessed)

**Derivation:**
1. Target **gross margin on variable cost = 80%** → our cost must be ≤ 20% of credit revenue.
2. Choose a clean base credit price: **1 credit = $0.01** (list).
3. Therefore **target cost-per-credit = $0.002** (20% of $0.01).
4. **Credits per op = ceil( our_cost × (1 + safety_buffer) / $0.002 )**, floor 1 for user-visible ops. Safety buffer default **15%**.

This makes the credit self-documenting: **1 credit ≈ $0.002 of our cost ≈ $0.01 of user value.**

### 4.1 Recommended credit cost per operation (at current paid models)

| Operation | Our cost | Credits (metered/flat) | User pays @ $0.01 |
|---|---:|---|---:|
| Document ingestion (parse+embed+classify), per page | $0.00386 | **2 / page** (flat) | $0.02/pg |
| — 8-page doc (parse $0.0300 + embed $0.0009 + classify $0.0006) | $0.0315 | **~19** | $0.19 |
| Reclassification | $0.002 | **1** (flat; +parse if reindex) | $0.01 |
| AI catalog / KB search | $0.0002 | **1** (flat floor) | $0.01 |
| Web search (grounded) | $0.044 | **~22** (metered) | $0.22 |
| Agent turn — typical | $0.114 | **~57** (metered on actual) | $0.57 |
| Agent turn — heavy | $0.45 | **~225** (metered) | $2.25 |
| Composio action | $0.004 | **2** (flat) | $0.02 |
| Memory op | $0 | **0 / free** | — |

> **Tension to resolve:** at the current model, a typical agent message costs the user ~57 credits (~$0.57). $10 (1,000 credits) ≈ **17 messages**. Cost-optimized (2.5 Flash-Lite planning + 3.x grounding), the same message is ~8–12 credits and $10 buys **~100 messages**. Same margin, 6× more product. **This is the pricing decision, not the credit value.**

---

## 5. Credit costs are metered on actual usage where possible

- **Token-metered ops (agent turn, LLM ops):** `credits = ceil( (Σ in·price_in + Σ out·price_out + grounding_fees + tool_fees) × (1+buffer) / cost_per_credit )`, computed from **actual** token counts recorded per call.
- **Unit-metered ops (parse/page, classify/doc, composio/exec, search/call):** flat `credits_per_unit` from the config table (§11.1), multiplied by the unit count.

Flow per metered operation:
```
preflight estimate (estimate_task_tokens + config)
   → check balance ≥ estimate         (else: block, prompt to buy)
   → place HOLD (reserve estimate)     (ledger: pending)
   → run operation, record actual tokens/units per call
   → settle: charge actual, release hold difference   (ledger: consume)
```

---

## 6. Overspend / abuse safeguards (+ metering gaps that MUST be fixed first)

**Guards to implement:**
- **Preflight estimation + insufficient-credit block** (wire the already-present `estimate_task_tokens()` in `sales-agent-engine/app/context/manager.py`).
- **Per-turn max credit ceiling** → maps onto existing `max_tokens_per_turn` / `TurnLimits`; halt the turn when exceeded.
- **Per-operation max token budget** (cap `max_output_tokens` — currently unset/uncapped on planner + sub-agent calls).
- **Hold/reserve** so concurrent turns can't double-spend a balance.
- **Idempotent charging** (idempotency key per operation → no double-charge on retry).

**Metering gaps found in the audit (fix before charging real credits, or we mis-bill / lose money):**
1. **Uncapped output** on planner + sub-agent calls (`orchestrator.py`) — set `max_output_tokens`.
2. **Unmetered sub-operations** — grounded web answer, prospect brief, and conversation summarization call the model directly and **never record tokens** to the budget (they bypass both the per-turn cap and the tenant budget). Route them through the same token recorder.
3. **Preflight is a cap-check, not a cost estimate** — `admit_turn` gates on cumulative daily tokens but doesn't estimate the incoming turn, so one turn can overshoot.
4. **data-pipeline chat-LLM is unmetered** (fine at $0 on free tier; must be metered when moved to paid).

---

## 7. Cost leaks & correctness bugs found (spend control)

| # | Issue | File | Impact | Fix |
|---|---|---|---|---|
| 1 | **Reindex re-parses via LlamaParse** from raw bytes even though parsed text is already stored | `knowledge_vault_routes.py:1041` | Duplicate per-page charge on every reindex (**embedding** is now protected by the Postgres delta check; **parsing is not**) | Reuse stored `raw_document_store` text; only re-parse if bytes changed |
| 2 | Errored/0-chunk re-upload re-parses | `knowledge_vault_routes.py:600` | Duplicate parse charge | Content-hash cache of parse result |
| 3 | **Idle auto-sync polling** bills even with zero new items | `*_sync_manager.py` | $5.76–$86 /mo /connector | Charge credits per sync run, and/or cap min interval, and/or bill polling separately |
| 4 | Classification default model slugs may not exist on OpenRouter (e.g. `google/gemma-4-31b-it:free`) → 404 → silent heuristic fallback | `sales_classifier.py:150,273` | Classification silently degraded (also masks cost) | Validate slugs against OpenRouter model list |
| 5 | **Hardcoded Composio API key fallback** in source | `composio_client.py:38` | Security (committed secret) | Remove literal; require env; **rotate key** |
| 6 | **Pseudo-vector silent fallback** — on missing key/API failure the worker writes non-semantic hash vectors into the live index | `embedding_worker.py:60-75` | Search quality silently craters **and** cost silently drops to $0, masking the outage. Mixed real/fake vectors in one index is worse than none | Route failed chunks to the DLQ / mark the doc degraded instead of writing fake vectors; alert |
| 7 | **Async Batch API unused** — sync `batchEmbedContents` pays $0.15/M | `embedding_worker.py:_embed_batch` | 2× the batch rate on an already-async ingestion path | Move ingestion embeddings to the Batch API ($0.075/M) — a straight 50% cut |
| 8 | Legacy embedding model in use (`gemini-embedding-001`) | `embedding_worker.py:46` | Successor is Embedding 2; migrating ⇒ re-embed whole corpus (~$9 per 10k docs) | Keep `EMBEDDING_MODEL` env-driven (already is); budget a migration |

---

## 8. Credit ledger (append-only, balance derived)

```
credit_transactions
------------------------------------------------
transaction_id      uuid  pk
account_id          uuid  (workspace_id — credits are workspace-scoped, like catalog/KB)
type                enum  purchase | grant | consume | refund | adjust | hold | hold_release
credits_delta       bigint  (+/-)
balance_after       bigint  (materialized running balance for the account)
operation           text    (e.g. agent_turn, doc_parse, composio_action) — null for purchases
reference_id        text    (session_id / doc_id / payment_id)
actual_cost_usd     numeric (what it actually cost us — for margin analytics)
provider            text    (gemini | openrouter | llamaparse | composio | tavily)
model               text
tokens_in           bigint
tokens_out          bigint
units               numeric (pages / executions / searches)
idempotency_key     text    unique
created_at          timestamptz
```
- Balance = last `balance_after` per account, reconcilable as `Σ credits_delta`.
- **Holds**: a `hold` row reserves credits at preflight; on settle, a `consume` for the actual + a `hold_release` for the remainder (or the hold is converted). Available balance = balance − open holds.

## 9. Usage records (analytics / reconciliation)

One row per billable call (finer-grained than the ledger; the ledger may bundle a turn's many calls into one `consume`):
```
usage_events(user_id, account_id, operation, provider, model,
             input_tokens, output_tokens, units, actual_cost_usd,
             credits_charged, request_id, session_id, created_at)
```
Feeds: real P50–P99 distributions, per-feature margin, "which features are loss-making," billing-dispute debugging.

---

## 10. Money ↔ credits separation (Billing Service)

```
User pays (Stripe / eSewa)
   → Payment succeeds  → payment_intents / invoices  (money domain)
   → Credit purchase   → credit_transactions +N       (credit domain)
User uses a feature
   → Preflight + hold → run → settle → credit_transactions −actual
   → usage_events + actual_cost_usd recorded (margin domain)
```
- **Billing Service** (new; already in the HLD: *Task Orchestration → Billing : Check Credits*) owns payments, plans, invoices, the ledger, and the credit-check/hold/settle API.
- Services call `POST /billing/credits/preflight` (estimate+hold) and `POST /billing/credits/settle` (actual). Money and credits are **decoupled** — operations never touch the payment domain directly.

---

## 11. Profitability & packages

### 11.1 Config-driven pricing (never hardcode — spec §14)
```
provider_rates(provider, model, input_price_per_1m, output_price_per_1m,
               request_fee, page_fee, effective_from, effective_until)
operation_costs(operation, unit, credits_per_unit, max_credits,
                metered boolean, effective_from, effective_until)
credit_config(credit_list_price_usd, target_cost_per_credit_usd,
              target_margin, safety_buffer, effective_from)
```
Historical cost is computed from the rate row valid at `usage_events.created_at`.

### 11.2 Recommended packages

| Package | Credits | Price | $/credit | Discount | Gross margin* |
|---|---:|---:|---:|---:|---:|
| Starter | 1,000 | $10 | $0.0100 | — | 80% |
| Growth | 5,000 | $45 | $0.0090 | 10% | 78% |
| Pro | 20,000 | $160 | $0.0080 | 20% | 75% |
| Business | 100,000 | $700 | $0.0070 | 30% | 71% |

\* at target cost-per-credit $0.002, before payment fees (~3–4%) and fixed-cost allocation. Margin stays **≥70% even at the deepest volume discount** — this validates the $0.01 base credit price.

### 11.3 Profitability by usage level (per active user / month, blended $0.008/credit sell, $0.002 cost)
| Level | Credits/mo | Revenue | Variable cost | Gross | Notes |
|---|---:|---:|---:|---:|---|
| Low | 500 | $4.0 | $1.0 | $3.0 | below fixed break-even alone |
| Average | 2,000 | $16 | $4.0 | $12 | healthy |
| High | 10,000 | $80 | $20 | $60 | |
| Very high | 50,000 | $400 | $100 | $300 | |
| Worst-case (heavy agent) | metered | metered | metered | ~75% | protected by metering + caps |

---

## 12. Build plan (Phase B — after economics sign-off)

1. **Fix metering gaps & leaks** (§6, §7) — output caps, meter sub-ops, cache parse, verify slugs, rotate/remove Composio key.
2. **Billing Service** (new Spring Boot service, `billing-db`): payments (Stripe + eSewa), plans, invoices.
3. **Credit ledger + holds** (in Billing Service): schema §8, idempotent charge/hold/settle API.
4. **Pricing config** (§11.1) + seed from §2 rates.
5. **Preflight + settle integration**: sales-agent-engine (wire `estimate_task_tokens`, per-turn credit ceiling), data-pipeline (parse/classify/search + connector syncs), Composio actions.
6. **Usage tracking** (§9) + **cost/margin analytics** dashboard.
7. **Scenario tests** (low/avg/high/worst) + **launch packages**.

**Highest-leverage optimization to decide alongside:** agent model routing (3.5 Flash → 2.5 Flash / Flash-Lite for routine planning) + grounding strategy (3.x grounding $14/1k vs 2.5 $35/1k; or Tavily-only). 5–20× on the dominant cost.
