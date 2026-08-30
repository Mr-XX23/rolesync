import asyncio
import os
from typing import Callable, Awaitable
from connectors.events.canonical_event import CanonicalEvent, EventType
from pipeline.security_scanner import SecurityScanner, ScanResult
from pipeline.canonical_store import CanonicalStore
from parsing.parser_service import ParserService
from connectors.deletion_handler import DeletionHandler
from connectors.acl_sync import ACLSyncService
from gatekeeper.gatekeeper_engine import GatekeeperEngine
from ingestion.ingestion_pipeline import BatchIngestionPipeline

class QueueWorker:
    """Asynchronous Queue Worker for offloading incoming webhooks to the staging, parsing, gatekeeper, ingestion, deletion & ACL sync pipeline."""

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
        self.scanner = scanner or SecurityScanner()
        self.store = store or CanonicalStore()
        self.parser_service = parser_service or ParserService()
        self.deletion_handler = deletion_handler or DeletionHandler(self.store)
        self.acl_sync = acl_sync or ACLSyncService(self.store)
        self.gatekeeper_engine = gatekeeper_engine or GatekeeperEngine()
        self.ingestion_pipeline = ingestion_pipeline or BatchIngestionPipeline()
        self.queue: asyncio.Queue[CanonicalEvent] = asyncio.Queue()
        self._worker_task: asyncio.Task | None = None
        self._is_running = False

    async def start(self) -> None:
        if self._is_running:
            return
        self._is_running = True
        self._worker_task = asyncio.create_task(self._process_loop())
        print("[QueueWorker] Asynchronous staging queue worker started.")

    async def stop(self) -> None:
        self._is_running = False
        if self._worker_task:
            self._worker_task.cancel()
            try:
                await self._worker_task
            except asyncio.CancelledError:
                pass
        print("[QueueWorker] Queue worker stopped.")

    async def enqueue(self, event: CanonicalEvent) -> bool:
        await self.queue.put(event)
        print(f"[QueueWorker] Enqueued event_id={event.event_id} (Queue size: {self.queue.qsize()})")
        return True

    async def _process_loop(self) -> None:
        while self._is_running:
            try:
                event = await self.queue.get()
                await self._process_event(event)
                self.queue.task_done()
            except asyncio.CancelledError:
                break
            except Exception as e:
                print(f"[QueueWorker] Processing error: {e}")

    async def _process_event(self, event: CanonicalEvent) -> None:
        print(f"[QueueWorker] Processing event_id={event.event_id} type={event.event_type} from source={event.source}")
        
        # 1. Security Scan & Sanitization
        scan_res: ScanResult = self.scanner.scan_and_sanitize_event(event)
        if not scan_res.is_safe:
            print(f"[QueueWorker] Security scan failed for event_id={event.event_id}: {scan_res.reason}")
            self.store.record_event(event, status="REJECTED_SECURITY")
            return

        # 2. Event Type Dispatching
        if event.event_type == EventType.DELETE:
            self.deletion_handler.process_deletion(event)
            return

        elif event.event_type == EventType.ACL_CHANGE:
            self.acl_sync.process_acl_change(event)
            return

        # 3. CREATE / UPDATE -> Document Parsing Layer
        parsed_doc = self.parser_service.parse_event(event)
        print(f"[QueueWorker] Parsed doc_id={parsed_doc.doc_id} using '{parsed_doc.parser_used}' (Status: {parsed_doc.parse_status}, Content length: {len(parsed_doc.text_content)})")

        if parsed_doc.parse_status != "SUCCESS":
            self.store.record_event(event, status="PARSE_FAILED")
            return

        # 4. Memory Gatekeeper Evaluation (Category Routing & Entropy Quality Filter)
        decision = self.gatekeeper_engine.evaluate_document(parsed_doc)
        print(f"[QueueWorker] Gatekeeper evaluation for doc_id={parsed_doc.doc_id}: Decision={decision.decision}, Category={decision.category.value}")

        if decision.decision != "ACCEPTED":
            self.store.record_event(event, status="GATEKEEPER_REJECTED")
            return

        # 5. Module 3: Batch Ingestion Pipeline (Chunker -> Delta Checker -> Embedding Worker -> Bulk Writer -> Vector Store)
        written_count = self.ingestion_pipeline.process_accepted_document(parsed_doc)
        print(f"[QueueWorker] Ingestion pipeline complete for doc_id={parsed_doc.doc_id}: Upserted {written_count} vectors into VectorStore.")

        self.store.record_event(event, status="VECTOR_STORE_INDEXED")
        print(f"[QueueWorker] Event event_id={event.event_id} completed full end-to-end pipeline! Final Status=VECTOR_STORE_INDEXED")
