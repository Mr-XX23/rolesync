import asyncio
import os
from typing import Callable, Awaitable
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

        self._queue: asyncio.Queue[CanonicalEvent] = asyncio.Queue()
        self._worker_task: asyncio.Task | None = None
        self._is_running = False

    async def start(self) -> None:
        if self._is_running:
            return
        self._is_running = True
        self._worker_task = asyncio.create_task(self._worker_loop())
        print("[QueueWorker] Asynchronous staging queue worker started.")

    async def stop(self) -> None:
        if not self._is_running:
            return
        self._is_running = False
        if self._worker_task:
            self._worker_task.cancel()
            try:
                await self._worker_task
            except asyncio.CancelledError:
                pass
        print("[QueueWorker] Queue worker stopped.")

    async def enqueue(self, event: CanonicalEvent) -> None:
        await self._queue.put(event)
        print(f"[QueueWorker] Enqueued event_id={event.event_id} (Queue size: {self._queue.qsize()})")

    async def _worker_loop(self) -> None:
        while self._is_running:
            try:
                event = await asyncio.wait_for(self._queue.get(), timeout=1.0)
                await self._process_event(event)
                self._queue.task_done()
            except asyncio.TimeoutError:
                continue
            except asyncio.CancelledError:
                break
            except Exception as err:
                print(f"[QueueWorker] Error processing queue item: {err}")

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
        parsed_doc = self.parser_service.parse_event(sanitized_event)

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

        # 5. Module 3 Batch Ingestion Pipeline (Chunker -> Delta Hash -> Embedder -> VectorStore)
        vectors_written = self.ingestion_pipeline.process_accepted_document(parsed_doc)
        print(f"[QueueWorker] Ingestion pipeline complete for doc_id={doc_id}: Upserted {vectors_written} vectors into VectorStore.")

        # 5b. Give connector documents the same treatment as manual uploads:
        # retain the parsed text, classify them, and register them in the vault
        # so they are not merely searchable-but-invisible.
        self._register_connector_document(sanitized_event, parsed_doc, vectors_written)

        # 6. Mark Lineage Complete
        self.store.record_event(sanitized_event, status="VECTOR_STORE_INDEXED")
        print(f"[QueueWorker] Event event_id={event.event_id} completed full end-to-end pipeline! Final Status=VECTOR_STORE_INDEXED")
