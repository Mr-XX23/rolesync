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

        # 2. Commit chunk fingerprints ONLY on success (arch.md: "write hash ONLY
        # on success"). A fingerprint recorded for a chunk that was never stored
        # makes the delta check skip it on every future run, so the chunk is lost
        # permanently and re-indexing cannot repair it. Chunks that fell back to a
        # pseudo-embedding are excluded for the same reason.
        indexable = [item.node for item in embedded_chunks if not getattr(item, "is_fallback", False)]
        durable = getattr(self.vector_store, "last_write_durable", True)
        if indexable and durable and written_count >= len(indexable):
            self.delta_checker.commit_chunk_hashes(indexable)
            print(f"[BulkWriter] Successfully wrote {written_count} vectors and committed hash DB state.")
        else:
            print(
                f"[BulkWriter] Persisted {written_count}/{len(indexable)} indexable chunks; "
                "delta hashes NOT committed so a re-index can repair this."
            )
        return written_count
