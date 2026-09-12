# Data-Pipeline RAG — Architecture Conformance Audit

> Code-verified 2026-09-12. Compares the design in
> [`backend/data-pipeline/doc/arch.md`](../../backend/data-pipeline/doc/arch.md)
> ("FINAL — Enterprise Multimodal RAG Ingestion Pipeline (1M docs)") against what
> the code actually implements and runs.

## Verdict

The **shape** of the architecture is scaffolded end-to-end and the happy path runs.
After the 2026-09-12 fix, it produces **real Gemini embeddings + real cosine ranking**.
But nearly all of the *durable / scalable* backends the diagram specifies — Postgres
persistence, durable queues (Redis/Celery), S3 raw store, a vector index, observability —
are **in-memory stubs or not wired**. Treat the current pipeline as a working single-process
prototype, not the enterprise/1M-doc system the diagram describes.

## Two ingestion paths (not equal)

| Path | Route | Pipeline stages | Scanner? | Gatekeeper? |
|---|---|---|---|---|
| **Connector / webhook** | `QueueWorker._process_event` (started in `main.py`) | scan → canonical lineage → parse → gatekeeper → ingest → deletion/ACL | ✅ | ✅ |
| **Manual KB upload** | `knowledge_vault_routes` upload / ingest-url | parse → classify → ingest | ❌ | ❌ |

**Consequence:** user-uploaded files skip the malware/DLP scanner *and* the quality gatekeeper.
This is a security + quality gap (see remediation #3).

## Status legend
✅ real / as designed · 🟡 works but diverges (in-memory / different backend / partial) · ⚠️ wired on one path only · ❌ missing or not running

### Module 1 — Connectors & Raw Storage
| Component (arch.md) | Reality | Status |
|---|---|---|
| Sources: Uploads, Gmail, GDrive, Slack, Notion, Zoom | Uploads, Gmail, GDrive, Slack, Notion **+Calendar**; **no Zoom / Outlook** | 🟡 |
| Composio (OAuth vault; triggers create/update/**delete/ACL**) | reads wired (5 toolkits); create/disable/delete triggers exist; **delete/ACL events not real**; write actions only in the agent | 🟡 |
| Security Scanner (ClamAV + size limits) | wired in connector path (`clamd`, best-effort/optional); **not on manual uploads** | ⚠️ |
| Raw Store (**S3/GCS/R2**, immutable, versioned, KMS) | **Mongo `raw_documents` + local disk + base64** (`raw_document_store.py`); no S3/KMS/versioning | 🟡 |
| Canonical DB (**Postgres** documents, ACL snapshot + lineage) | **in-memory dict** (`canonical_store.py`) — lost on restart | 🟡 |
| MIME Router · LlamaParse (ParserService) · Parse Failure Store | wired, real (LlamaParse default per-page tier) | ✅ |
| Media Queue · Transcription (Whisper / Groq / Deepgram) | **not implemented** | ❌ |
| Deletion Handler · ACL Sync | wired on connector DELETE / ACL_CHANGE events | ⚠️ |
| Reconciliation Sweeper | **defined but never scheduled** (`reconciliation_sweeper.py`, tests only) | ❌ |

### Module 2 — Memory Gatekeeper
| Component | Reality | Status |
|---|---|---|
| Staging Queue (**Redis + BullMQ/Celery**, FIFO) | **in-process `asyncio.Queue`** (connector path only); not durable/distributed | 🟡 |
| Category Router · Lexical/Entropy Checker · Audit Logger | wired (heuristics: mime/keyword routing, Shannon entropy + density) | ✅ |
| **Semantic Scorer** (versioned utility models, log-only mode) | **not implemented** | ❌ |
| Rejected / Quarantine Store | present, in-memory | 🟡 |

### Module 3 — Batch Ingestion
| Component | Reality | Status |
|---|---|---|
| Ingestion Queue (**fair tenant scheduler**) | **no queue** — pipeline runs inline; no fairness/backpressure | ❌ |
| Batch Loader (**Postgres lease**, SELECT FOR UPDATE SKIP LOCKED, heartbeat) | **not implemented** | ❌ |
| Chunker (hierarchical parent/child) | paragraph packing by char size; overlap is dead code; not true parent/child | 🟡 |
| Delta Checker / **Versioned Hash DB (Postgres chunk_hashes)** | **in-memory + a fresh instance is created per upload** → cross-run dedup never fires | 🟡 |
| Embedding Workers (**OpenAI Batch API, 50% off**, token-aware limiter) | **real Gemini `gemini-embedding-001`** (2026-09-12 fix); synchronous, no batch discount, no rate limiter | 🟡↑ |
| Bulk Writer (idempotent upsert) | wired | ✅ |
| Checkpoint Store (**Postgres**) · DLQ | **in-memory** | 🟡 |
| MongoDB (**Atlas M30+, scalar quantization**) | self-hosted Mongo 7 community; no quantization | 🟡 |
| **Vector Index (HNSW, pre-filter)** | **no vector index** — brute-force cosine over ACL-filtered docs (`search_similarity`); scalar Mongo indexes only on tenant/doc | ❌ |

### Observability
| Component | Reality | Status |
|---|---|---|
| Grafana + Sentry (queue depth/age, throughput, DLQ) | **none** in data-pipeline (LangSmith exists, agent-only) | ❌ |

## The four gaps that matter most
1. **Almost all state is in-memory** — Canonical DB, Checkpoint Store, Versioned Hash DB, Rejected/Quarantine, DLQ, and the vector store's in-memory mirror. On restart it is gone. The arch's *checkpoint-resume*, *delta-dedup*, and *1M-doc* guarantees **do not currently hold**.
2. **No real queue/worker layer** — `celery[redis]` and `boto3` are in `requirements.txt` but **unused**; the only queue is an in-process `asyncio.Queue`. Single process, no horizontal scale, no durable backpressure or fair tenant scheduling.
3. **Manual uploads bypass the scanner + gatekeeper** — malware/DLP and quality checks only run on the connector path.
4. **No vector index** — self-hosted Mongo has no HNSW / `$vectorSearch`, so semantic search is brute-force. Fine at current volume; needs **pgvector or Atlas Vector Search** to scale (a future infra cost in the credit/cost model).

## Remediation backlog (priority order)
1. **Persist the Hash DB + Checkpoint Store to Postgres** so delta-dedup and resume actually work across restarts/uploads.
2. **Add the security scanner + gatekeeper to the manual upload path** (unify both paths through one pipeline).
3. **Real durable queue** (Redis/Celery — already a dependency) with a fair tenant scheduler + Postgres lease loader, replacing the in-process `asyncio.Queue`.
4. **Vector index** — move vectors to pgvector or Atlas Vector Search; keep the brute-force path as a fallback.
5. **Persist Canonical Store / Quarantine / Rejected / DLQ** to a real datastore.
6. Wire the **Reconciliation Sweeper** on a schedule; make Composio delete/ACL events real when available.
7. **Observability** (Sentry + metrics) for queue depth/age, throughput, DLQ.
8. Optional: transcription/media path, true hierarchical chunking, OpenAI Batch (or Gemini batch) embeddings for the 50% discount.

## Note on the 2026-09-12 embeddings fix
Before this fix, `embedding_worker.py` generated a **non-semantic pseudo-vector from the chunk hash** (only 10 of 1536 dims non-zero) and `search_similarity` **ignored the query vector entirely**. Both are now fixed: real Gemini embeddings (L2-normalized, config-driven model/dims, graceful pseudo fallback when no key) and real cosine ranking. This applies to **both** ingestion paths. See the PR for details.
