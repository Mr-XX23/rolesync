import asyncio
import inspect
import os
from typing import Any, Awaitable, Callable
from module_1_document_processing.composio_connector.events.canonical_event import CanonicalEvent, EventType
from module_1_document_processing.security.security_scanner import SecurityScanner, ScanResult
from module_1_document_processing.pipeline.canonical_store import CanonicalStore
from module_1_document_processing.parsing.parser_service import ParserService
from module_1_document_processing.parsing.media_queue import MEDIA_PENDING
from module_1_document_processing.del_acl_and_reconc.deletion_handler import DeletionHandler
from module_1_document_processing.del_acl_and_reconc.acl_sync import ACLSyncService
from module_2_memory_gatekeeper.gatekeeper_engine import GatekeeperEngine
from module_3_batch_ingestion_vector.ingestion_pipeline import BatchIngestionPipeline
from module_1_document_processing.pipeline import ingestion_guards as guards
from module_1_document_processing.pipeline.durable_queue import DurableQueue, Job, ingest_queue
from module_1_document_processing.pipeline.job_payloads import (
    JOB_CONNECTOR_EVENT,
    discard_staged_bytes,
    event_to_payload,
    payload_to_event,
)

class QueueWorker:
    """Asynchronous Queue Worker for offloading incoming webhooks and backfill items to the staging, parsing, gatekeeper, ingestion, deletion & ACL sync pipeline."""

    def __init__(
        self,
        scanner: SecurityScanner | None = None,
        store: CanonicalStore | None = None,
        parser_service: ParserService | None = None,
        deletion_handler: DeletionHandler | None = None,
        acl_sync: ACLSyncService | None = None,
        gatekeeper_engine: GatekeeperEngine | None = None,
        ingestion_pipeline: BatchIngestionPipeline | None = None,
        queue: DurableQueue | None = None,
    ) -> None:
        # Shared singletons so the connector path and manual uploads enforce the
        # exact same scan and gatekeeper policy.
        self.scanner = scanner or guards.security_scanner
        self.store = store or CanonicalStore()
        self.parser_service = parser_service or ParserService()
        self.deletion_handler = deletion_handler or DeletionHandler(self.store)
        self.acl_sync = acl_sync or ACLSyncService(self.store)
        self.gatekeeper_engine = gatekeeper_engine or guards.gatekeeper_engine
        self.ingestion_pipeline = ingestion_pipeline or BatchIngestionPipeline()

        # Work is handed to a durable queue rather than an in-process one, so an
        # accepted job survives a restart of this service.
        self.queue = queue if queue is not None else ingest_queue
        self._handlers: dict[str, Callable[[dict[str, Any]], Any]] = {
            JOB_CONNECTOR_EVENT: self._handle_connector_event,
        }
        # Called when a job kind has exhausted its retries, so the owning module
        # can record the outcome instead of leaving a record stuck mid-flight.
        self._on_dead: dict[str, Callable[[dict[str, Any]], Any]] = {}
        self._worker_tasks: list[asyncio.Task] = []
        self._is_running = False

    def register_handler(
        self,
        kind: str,
        handler: Callable[[dict[str, Any]], Any],
        on_dead: Callable[[dict[str, Any]], Any] | None = None,
    ) -> None:
        """Route a job kind to a handler. Lets other modules (the knowledge vault
        upload path) put work on the same durable queue without importing it.

        `on_dead` runs once the queue gives up on a job, so a failure that is
        still being retried is not reported to the user as final.
        """
        self._handlers[kind] = handler
        if on_dead is not None:
            self._on_dead[kind] = on_dead

    async def start(self) -> None:
        if self._is_running:
            return
        self._is_running = True

        # Anything left in flight by a previous run goes back on the queue; this
        # is what stops a restart from stranding documents at "Parsing".
        reclaimed = await asyncio.to_thread(self.queue.reclaim_stale)

        workers = max(1, int(os.environ.get("INGEST_QUEUE_WORKERS", "1") or 1))
        for index in range(workers):
            self._worker_tasks.append(asyncio.create_task(self._worker_loop(index)))

        stats = await asyncio.to_thread(self.queue.stats)
        print(
            f"[QueueWorker] Staging queue worker started "
            f"(backend={stats.get('backend')}, workers={workers}, reclaimed={reclaimed}, pending={stats.get('pending')})."
        )
        if stats.get("backend") != "redis":
            print("[QueueWorker] WARNING: Redis unavailable - queued ingestion work will not survive a restart.")

    async def stop(self) -> None:
        if not self._is_running:
            return
        self._is_running = False
        for task in self._worker_tasks:
            task.cancel()
        for task in self._worker_tasks:
            try:
                await task
            except asyncio.CancelledError:
                pass
        self._worker_tasks.clear()
        print("[QueueWorker] Queue worker stopped.")

    async def enqueue(self, event: CanonicalEvent) -> Job:
        """Accept a connector event. Returns once the job is durably queued."""
        return await self.enqueue_job(JOB_CONNECTOR_EVENT, event_to_payload(event))

    async def enqueue_job(self, kind: str, payload: dict[str, Any]) -> Job:
        job = await asyncio.to_thread(self.queue.enqueue, kind, payload)
        print(f"[QueueWorker] Enqueued {kind} job_id={job.job_id}")
        return job

    async def _worker_loop(self, index: int = 0) -> None:
        while self._is_running:
            job: Job | None = None
            try:
                job = await asyncio.to_thread(self.queue.reserve, 1.0)
                if job is None:
                    # Nothing waiting: yield so an in-memory queue does not spin.
                    await asyncio.sleep(0.05)
                    continue
                await self._dispatch(job)
                await asyncio.to_thread(self.queue.ack, job)
            except asyncio.CancelledError:
                # Leave the job in flight: it is reclaimed and retried on restart.
                break
            except Exception as err:
                if job is None:
                    print(f"[QueueWorker] Worker {index} error: {err}")
                    await asyncio.sleep(0.5)
                    continue
                outcome = await asyncio.to_thread(self.queue.fail, job, str(err))
                print(
                    f"[QueueWorker] Job {job.job_id} ({job.kind}) failed on attempt "
                    f"{job.attempts}/{self.queue.max_attempts}: {err} -> {outcome}"
                )
                if outcome == "dead":
                    await self._notify_dead(job)

    async def _notify_dead(self, job: Job) -> None:
        callback = self._on_dead.get(job.kind)
        if callback is None:
            return
        try:
            result = callback(job.payload)
            if inspect.isawaitable(result):
                await result
        except Exception as err:
            # A failing callback must not take the worker loop down with it.
            print(f"[QueueWorker] on_dead callback failed for {job.job_id}: {err}")

    async def _dispatch(self, job: Job) -> None:
        handler = self._handlers.get(job.kind)
        if handler is None:
            raise RuntimeError(f"No handler registered for job kind '{job.kind}'")
        result = handler(job.payload)
        if inspect.isawaitable(result):
            await result

    async def _handle_connector_event(self, payload: dict[str, Any]) -> None:
        event = payload_to_event(payload)
        try:
            await self._process_event(event)
        finally:
            # The staged copy exists only to carry bytes through the queue.
            discard_staged_bytes(payload.get("staged_ref") or "")

    @staticmethod
    def _display_name(event: CanonicalEvent, doc_id: str) -> str:
        meta = event.metadata or {}
        for key in ("name", "title", "subject", "summary", "filename"):
            value = meta.get(key)
            if value:
                return str(value)[:200]
        return event.external_id or doc_id

    def _register_connector_document(
        self, event: CanonicalEvent, parsed_doc, chunks_written: int
    ) -> None:
        """Persist parsed text, classify, and add a vault registry row.

        Connector documents previously reached the vector store without any of
        this, so they were searchable by the agent yet absent from the Knowledge
        Vault, unclassified, and impossible to re-index without re-fetching from
        the provider (which costs Composio executions).

        Imported lazily to keep module import order independent of the routes.
        """
        try:
            from datetime import datetime, timezone

            from module_1_document_processing import knowledge_vault_routes as vault
            from module_1_document_processing.raw_document_store import raw_document_store

            doc_id = f"{event.tenant_id}:{event.source}:{event.external_id}"
            text_content = parsed_doc.text_content or ""
            if not text_content:
                return

            # chunks_written == 0 is ambiguous: either nothing was indexable, or
            # the delta check skipped chunks that are already indexed. Ask the
            # index which it is, so a re-sync of unchanged content is not
            # reported to the user as "Rejected".
            effective_chunks = chunks_written
            if effective_chunks <= 0:
                from module_3_batch_ingestion_vector.pgvector_index import pgvector_index

                effective_chunks = len(pgvector_index.list_chunks(doc_id) or [])

            name = self._display_name(event, doc_id)
            classification = vault.sales_classifier.classify(
                filename=name,
                mime_type=parsed_doc.mime_type or "text/plain",
                text_content=text_content,
            )

            # raw_bytes is None: the provider holds the original, we retain the text.
            raw_document_store.save_raw_document(
                doc_ref_id=doc_id,
                tenant_id=event.tenant_id,
                user_id=event.user_id,
                filename=name,
                mime_type=parsed_doc.mime_type or "text/plain",
                full_text_content=text_content,
                raw_bytes=None,
                category=classification.category,
                document_type=classification.category,
                target_competitor=classification.target_competitor,
                target_industry=classification.target_industry,
                sales_summary=classification.sales_summary,
                sales_tags=classification.sales_tags,
                total_chunks=effective_chunks,
                parser_used=parsed_doc.parser_used,
                parse_status=parsed_doc.parse_status,
                metadata=parsed_doc.metadata,
                source=event.source,
            )

            now = datetime.now(timezone.utc).isoformat()
            existing = vault._find_doc_record(doc_id) or {}
            record = {
                **existing,
                "doc_id": doc_id,
                "doc_ref_id": doc_id,
                "name": name,
                "type": (event.source or "CONNECTOR").upper(),
                "size_bytes": len(text_content),
                "chunks": effective_chunks,
                "status": "Indexed" if effective_chunks > 0 else "Rejected",
                "category": classification.category,
                "target_competitor": classification.target_competitor,
                "target_industry": classification.target_industry,
                "sales_summary": classification.sales_summary,
                "sales_tags": classification.sales_tags,
                "classifier_used": classification.classifier_used,
                "confidence_score": classification.confidence_score,
                "created_at": existing.get("created_at", now),
                "last_updated": now,
                "tenant_id": event.tenant_id,
                "user_id": event.user_id,
                "source": (event.source or "CONNECTOR").upper(),
                "has_raw_document": False,  # the provider holds the original
                "metadata": {
                    **(existing.get("metadata") or {}),
                    "category": classification.category,
                    "document_type": classification.category,
                    "parser_used": parsed_doc.parser_used,
                    "external_id": event.external_id,
                    "preview_snippet": text_content[:240].strip(),
                    "sales_classification": classification.to_dict(),
                },
            }
            vault._save_doc_record(record)
            print(f"[QueueWorker] Registered connector document {doc_id} ({classification.category}).")
        except Exception as err:
            # Registration is best-effort: never fail an otherwise good ingest.
            print(f"[QueueWorker] Could not register connector document: {err}")

    async def _process_event(self, event: CanonicalEvent) -> None:
        print(f"[QueueWorker] Processing event_id={event.event_id} type={event.event_type} from source={event.source}")
        doc_id = f"{event.tenant_id}:{event.source}:{event.external_id}"

        # 1. Security Scan & Sanitization
        scan_res: ScanResult = self.scanner.scan_and_sanitize_event(event)
        if not scan_res.is_safe:
            print(f"[QueueWorker] Security scan failed for event_id={event.event_id}: {scan_res.reason}")
            self.store.record_event(event, status="QUARANTINED")
            return

        sanitized_event = scan_res.event or event

        # Connector events can carry raw bytes inline (attachments, file payloads).
        # arch.md treats Composio output as untrusted input, so those bytes get the
        # same size and malware policy as an uploaded file rather than going
        # straight to the parser.
        inline_bytes = (sanitized_event.metadata or {}).get("raw_bytes")
        if isinstance(inline_bytes, (bytes, bytearray)) and inline_bytes:
            payload_scan = guards.security_scanner.scan_raw_bytes(bytes(inline_bytes))
            if not payload_scan.is_safe:
                print(f"[QueueWorker] Rejected payload for event_id={event.event_id}: {payload_scan.reason}")
                self.store.record_event(sanitized_event, status="QUARANTINED")
                return

        # Handle DELETION events
        if sanitized_event.event_type == EventType.DELETE:
            self.deletion_handler.process_deletion(sanitized_event)
            return

        # Handle ACL_CHANGE events
        if sanitized_event.event_type == EventType.ACL_CHANGE:
            self.acl_sync.process_acl_change(sanitized_event)
            return

        # 2. Stage Event Lineage
        self.store.record_event(sanitized_event, status="STAGED")

        # 3. Document Parsing (Supports SUCCESS and PARTIAL_SUCCESS with skipped oversized attachments)
        # Parsing, embedding and classification are synchronous and network-bound
        # (LlamaParse, Gemini, OpenRouter). Running them inline would block the
        # event loop - and therefore every other connector - for their duration.
        parsed_doc = await asyncio.to_thread(self.parser_service.parse_event, sanitized_event)

        # Audio/video is parked, not failed: the file is kept and can be replayed
        # once transcription is implemented.
        if parsed_doc.parse_status == MEDIA_PENDING:
            print(f"[QueueWorker] Media parked for doc_id={doc_id} (transcription not implemented).")
            self.store.record_event(sanitized_event, status="MEDIA_PENDING")
            return

        if parsed_doc.parse_status not in ("SUCCESS", "PARTIAL_SUCCESS"):
            print(f"[QueueWorker] Parsing failed for doc_id={doc_id}: status={parsed_doc.parse_status}")
            self.store.record_event(sanitized_event, status="PARSED_FAILED")
            return

        print(f"[QueueWorker] Parsed doc_id={doc_id} using '{parsed_doc.parser_used}' (Status: {parsed_doc.parse_status}, Content length: {len(parsed_doc.text_content)})")
        self.store.record_event(sanitized_event, status="PARSED_SUCCESS")

        # 4. Memory Gatekeeper Evaluation
        gk_decision = self.gatekeeper_engine.evaluate_document(parsed_doc)
        print(f"[QueueWorker] Gatekeeper evaluation for doc_id={doc_id}: Decision={gk_decision.decision}, Category={gk_decision.category.value}")

        if gk_decision.decision != "ACCEPTED":
            self.store.record_event(sanitized_event, status=f"GATEKEEPER_{gk_decision.decision}")
            return

        self.store.record_event(sanitized_event, status="GATEKEEPER_ACCEPTED")

        # Connector normalizers set provider-native ACLs (a mailbox owner's email,
        # a Slack sender id). Knowledge-vault search filters on the workspace and
        # caller identity, so without these markers connector documents are
        # indexed but unreachable - Gmail in particular was invisible to search.
        workspace_acl = [f"tenant:{sanitized_event.tenant_id}", f"user:{sanitized_event.user_id}"]
        for marker in workspace_acl:
            if marker not in parsed_doc.acl:
                parsed_doc.acl.append(marker)

        # 5. Module 3 Batch Ingestion Pipeline (Chunker -> Delta Hash -> Embedder -> VectorStore)
        vectors_written = await asyncio.to_thread(
            self.ingestion_pipeline.process_accepted_document, parsed_doc
        )
        print(f"[QueueWorker] Ingestion pipeline complete for doc_id={doc_id}: Upserted {vectors_written} vectors into VectorStore.")

        # 5b. Give connector documents the same treatment as manual uploads:
        # retain the parsed text, classify them, and register them in the vault
        # so they are not merely searchable-but-invisible.
        await asyncio.to_thread(
            self._register_connector_document, sanitized_event, parsed_doc, vectors_written
        )

        # 6. Mark Lineage Complete
        self.store.record_event(sanitized_event, status="VECTOR_STORE_INDEXED")
        print(f"[QueueWorker] Event event_id={event.event_id} completed full end-to-end pipeline! Final Status=VECTOR_STORE_INDEXED")
