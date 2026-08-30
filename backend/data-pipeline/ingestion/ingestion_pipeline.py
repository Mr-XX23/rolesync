from parsing.parsed_document import ParsedDocument
from ingestion.chunker import HierarchicalChunker
from ingestion.delta_checker import DeltaChecker
from ingestion.embedding_worker import EmbeddingWorker
from ingestion.vector_store import VectorStore
from ingestion.bulk_writer import BulkWriter
from ingestion.checkpoint_store import CheckpointStore
from ingestion.dlq import DeadLetterQueue

class BatchIngestionPipeline:
    """Facade orchestrating Module 3 Batch Ingestion Pipeline."""

    def __init__(
        self,
        chunker: HierarchicalChunker | None = None,
        delta_checker: DeltaChecker | None = None,
        embedding_worker: EmbeddingWorker | None = None,
        vector_store: VectorStore | None = None,
        bulk_writer: BulkWriter | None = None,
        checkpoint_store: CheckpointStore | None = None,
        dlq: DeadLetterQueue | None = None,
    ) -> None:
        self.chunker = chunker or HierarchicalChunker()
        self.delta_checker = delta_checker or DeltaChecker()
        self.embedding_worker = embedding_worker or EmbeddingWorker()
        self.vector_store = vector_store or VectorStore()
        self.bulk_writer = bulk_writer or BulkWriter(self.vector_store, self.delta_checker)
        self.checkpoint_store = checkpoint_store or CheckpointStore()
        self.dlq = dlq or DeadLetterQueue()

    def process_accepted_document(self, document: ParsedDocument) -> int:
        batch_id = f"batch_{document.doc_id}"
        print(f"[BatchIngestionPipeline] Starting batch ingestion for doc_id={document.doc_id}...")

        # 1. Chunker -> Generate hierarchical nodes with tenant_id & acl[]
        nodes = self.chunker.chunk_document(document)
        if not nodes:
            print(f"[BatchIngestionPipeline] Document doc_id={document.doc_id} contains empty text. Skipped chunking.")
            return 0

        # Checkpoint: PENDING -> PROCESSING
        self.checkpoint_store.create_checkpoint(batch_id, document.doc_id, document.tenant_id, chunks_count=len(nodes))
        self.checkpoint_store.update_status(batch_id, "PROCESSING")

        try:
            # 2. Delta Hash Checker -> Skip unchanged chunks
            new_or_modified, unchanged = self.delta_checker.filter_changed_chunks(nodes)

            if not new_or_modified:
                print(f"[BatchIngestionPipeline] All {len(nodes)} chunks unchanged. Skipped re-indexing.")
                self.checkpoint_store.update_status(batch_id, "DONE")
                return 0

            # 3. Embedding Workers -> Batch embedding generation
            embedded_chunks = self.embedding_worker.generate_embeddings(new_or_modified)

            # 4. Bulk Writer -> Idempotent vector store write & hash commit
            written_count = self.bulk_writer.write_embedded_chunks(embedded_chunks)

            # Checkpoint: DONE
            self.checkpoint_store.update_status(batch_id, "DONE")
            print(f"[BatchIngestionPipeline] Successfully completed batch ingestion for doc_id={document.doc_id}! Written={written_count}")
            return written_count

        except Exception as err:
            print(f"[BatchIngestionPipeline] Error processing doc_id={document.doc_id}: {err}")
            self.checkpoint_store.update_status(batch_id, "FAILED")
            self.dlq.push_failure(doc_id=document.doc_id, tenant_id=document.tenant_id, reason=str(err), failed_chunks=nodes)
            raise err
