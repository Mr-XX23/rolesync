# Data-Pipeline RAG — Architecture Conformance Audit

> Re-verified 2026-09-12 after the Module 1 rebuild, by an **independent code audit**
> plus an **end-to-end run through the live gateway**. Compares the design in
> [`backend/data-pipeline/doc/arch.md`](../../backend/data-pipeline/doc/arch.md)
> against what the code actually executes.
>
> Judged only by executing code. Docstrings and class names in this repo are in
> several places aspirational and were explicitly ignored.

## Verdict

The Module 1 happy path is now real and proven end to end: a document uploaded through
the gateway is scanned, parsed, gate-kept, chunked, embedded with Gemini, stored with its
raw bytes in MinIO, its text and lineage in Postgres, and is retrievable by semantic
search over a real HNSW index — then fully purged on delete. What remains unmet is
mostly *durability and operability* (real queues, observability, raw archive for
connectors), plus a security asymmetry between the two ingestion paths.

**Verified live (`e2e_module1.py`, through `localhost:8080`):** upload → `Indexed` →
content from `rag.document_content` → chunks from pgvector (dim 1536) → semantic search
hit at score 0.65 → raw download from MinIO → delete cascade. All green.

## Storage split (the current truth)

| Store | Holds |
|---|---|
| **Postgres** (`pgvector-db`, `rag` schema) | `vector_chunks` (chunk text + embedding + **HNSW**), `document_content` (parsed text), `documents` (lineage/status/ACL), `document_events` (audit), `chunk_hashes` (delta de-dup), `checkpoints` |
| **MinIO** | raw original bytes (**manual uploads only** — connectors keep the provider as source of truth) |
| **MongoDB** | `knowledge_documents` (vault registry), `raw_documents` (metadata + MinIO pointer), `knowledge_vault_configs`, and 15 connector-state collections |

## Status — arch.md Module 1

✅ implemented & wired · 🟡 partial · ❌ missing

| Component | Status | Notes |
|---|---|---|
| Sources: Uploads, Gmail, GDrive, Slack, Notion (+Calendar) | ✅ | Zoom/Outlook intentionally skipped |
| Composio create/update triggers | ✅ | |
| Composio **delete / ACL** events | ❌ | Providers do not emit them; reconciliation is the compensating mechanism |
| Security scanner on **manual** uploads (type, size, ClamAV hook) | ✅ | |
| Security scanner on **connector** payloads | ✅ | Inline payloads and attachments run the same size + malware policy as uploads |
| ClamAV actually scanning | 🟡 | Lazy-connects via `CLAMAV_HOST`; **no clamav service in compose**, so inert |
| MIME router / LlamaParse / ParserService | ✅ | |
| Raw store (S3-compatible, local fallback, legacy readable) | 🟡 | MinIO wired; **no versioning / object-lock / KMS**; connectors store no bytes |
| Canonical DB (Postgres, ACL snapshot, lineage) | ✅ | `rag.documents` + `rag.document_events` |
| Normalized text retained (both paths) | ✅ | `rag.document_content`; re-index no longer re-fetches from the provider |
| Memory gatekeeper on **both** paths | ✅ | Shared `GatekeeperEngine` singleton |
| Deletion handler / GDPR erasure | ✅ | Both paths cascade to text, chunks, hashes, stored object and registry row, and tombstone lineage |
| ACL sync | ✅ | Propagates to pgvector |
| Reconciliation sweeper | ✅ | Scheduled, **off by default**, HTTP-reachable, refuses deletion inference from incomplete listings, mass-delete ratio guard |
| Media queue / parking | 🟡 | Audio/video parked on both the generic route and the attachment path; the queue itself is still process-local and undrained |
| Transcription workers | ❌ (deliberate) | Explicit placeholder: `available()` False, `transcribe()` raises |
| Parse failure store | 🟡 | In-memory, one instance per `ParserService`, no endpoint reads it |
| Embeddings | ✅ | Real Gemini `gemini-embedding-001`; **not** OpenAI Batch (no 50% discount, no rate limiter) |
| Vector index (HNSW, pre-filter) | ✅ | `USING hnsw (embedding vector_cosine_ops)`; tenant + ACL applied in SQL |
| Durable queues (Redis/Celery) | ❌ | Still in-process `asyncio.Queue`; `celery[redis]` unused |
| Observability (Grafana/Sentry, queue depth, DLQ) | ❌ | None |

## P0 defects found and fixed (2026-09-12)

Found by independent audit + live E2E; all failed *quietly*, which is why the unit suite missed them.

1. **Calendar reconciliation was dead code.** Events are stored as `source="google_calendar"`; the sweeper keyed `"calendar"`, so every sweep spent Composio executions and checked zero documents.
2. **Delta fingerprints were committed even when the write never reached a durable store** — making a failed index *permanent*, because the delta check then skipped those chunks forever and re-indexing could not repair them. (`arch.md`: "write hash ONLY on success".)
3. **A transient embedding failure silently wrote pseudo-vectors into the search index.** Embeddings now carry `is_fallback`, are excluded from the index and from search, and never commit hashes — so they stay repairable.
4. **Connector documents were unreachable by search.** Normalizers set provider-native ACLs (mailbox owner email, Slack sender id) while search filters on workspace/caller identity; Gmail content was indexed but invisible. Workspace markers are now added at ingest.
5. **`data-pipeline` had no dependency on `pgvector-db`**, so starting first latched the process into in-memory mode for its entire lifetime, with only a `print` to show for it.
6. Earlier the same day: **deleting a document left its chunk fingerprints behind**, so re-uploading the same file indexed it with 0 chunks and no error.

## P1 + P2 closed (2026-09-12, `75fb1f3`)

- **Connector input is now scanned.** Inline event payloads and every attachment run the same size + malware policy as an uploaded file, and media attachments are parked rather than decoded.
- **Two fabrication paths removed.** An unparseable attachment returned a `"placeholder"` string with status SUCCESS, and a document with nothing extractable was turned into a filler sentence — both were chunked, embedded and served as search results. Both now report a parse failure with empty text. This mattered because `gdrive_sync_manager` ignores the returned status and used the text directly.
- **Connector erasure cascades** to `rag.document_content`, the stored original and the registry row, not just the vectors.
- **Legacy chunks are findable again**: an empty pgvector result now falls through to the legacy scan instead of being treated as a definitive no-match.
- **Hygiene**: chunks leave the in-process mirror once pgvector owns them (bounded memory, worker-independent reads); parsing/embedding/classification moved off the event loop; `EMBEDDING_DIMENSIONS` clamped to the column's range; real vector backend reported instead of a hardcoded label; `requests` declared; RAG fallback URL built from env rather than hardcoded credentials.
- **The live pgvector SQL now has automated coverage** — 9 integration tests (ordering, tenant + ACL isolation, fallback exclusion, listing, deletion, ACL update) that run against a real database via `RAG_PERSISTENCE=on`, and skip otherwise.

## Remaining gaps

| Gap | Priority | Note |
|---|---|---|
| Durable queues (Redis/Celery) | High for scale | Still in-process `asyncio.Queue`; `celery[redis]` declared but unused |
| Observability (Grafana/Sentry, queue depth, DLQ) | High for operability | None |
| Raw archive for connector bytes | Medium | Provider remains source of truth; normalized text *is* retained, so re-index no longer re-fetches |
| Object versioning / lock / KMS on the raw store | Medium | MinIO holds plain objects |
| Parse failure store | Medium | In-memory, one instance per `ParserService`, no endpoint reads it |
| Transcription | Deliberate placeholder | Media parked; `MediaJobQueue` is process-local and not drained |
| ClamAV daemon | Medium | Scanner wired and lazy-connecting, but no `clamav` service in compose, so malware scanning is inert |
| Real Composio delete/ACL triggers | Low (compensated) | Reconciliation is the detector; off by default |
| Zoom / Outlook sources | Skipped by decision | |
| `gatekeeper_message` QUARANTINED branch | Cosmetic | `GatekeeperEngine` only returns ACCEPTED / REJECTED_LEXICAL |

## Local infrastructure (gitignored — recreate on any other machine)

- **MinIO** — `quay.io/minio/minio` (Docker Hub's `minio/minio` refuses anonymous pulls), console `:9001`, configured via `RAW_STORE_*`.
- **pgvector-db** — `pgvector/pgvector:pg16` on host `:5433`, holding the **RAG database only**. The main `postgres` is alpine with no pgvector build and no alpine pgvector image exists; migrating it would have required a dump/restore of every production database, so it was deliberately left untouched. Consolidate at deploy time.
- `PYTHONUNBUFFERED=1` on data-pipeline (its logs were otherwise invisible).
