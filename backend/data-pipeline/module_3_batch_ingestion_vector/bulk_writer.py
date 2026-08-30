from typing import Any
from module_3_batch_ingestion_vector.vector_store import VectorStore
from module_3_batch_ingestion_vector.delta_checker import DeltaChecker

class BulkWriter:
    """Idempotent Bulk Writer for transactional vector store writes & Hash DB state commits."""

    def __init__(
        self,
        vector_store: VectorStore | None = None,
        delta_checker: DeltaChecker | None = None,
    ) -> None:
        self.vector_store = vector_store or VectorStore()
        self.delta_checker = delta_checker or DeltaChecker()

    def write_embedded_chunks(self, embedded_chunks: list[Any]) -> int:
        if not embedded_chunks:
            return 0

        print(f"[BulkWriter] Executing idempotent bulk write for {len(embedded_chunks)} embedded chunks...")

        # 1. Write vectors to VectorStore
        written_count = self.vector_store.upsert_vectors(embedded_chunks)

        # 2. Commit chunk MD5 hash fingerprints to Delta Hash DB
        nodes = [item.node for item in embedded_chunks]
        self.delta_checker.commit_chunk_hashes(nodes)

        print(f"[BulkWriter] Successfully wrote {written_count} vectors and committed hash DB state.")
        return written_count
