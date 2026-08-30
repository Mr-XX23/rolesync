from typing import Any
from module_3_batch_ingestion_vector.chunker import TextNode

class VersionedHashDB:
    """Versioned Hash Database maintaining chunk MD5 hash fingerprints per doc_id."""

    def __init__(self) -> None:
        self._db: dict[str, dict[str, str]] = {}  # doc_id -> {chunk_id: chunk_hash}

    def get_chunk_hash(self, doc_id: str, chunk_id: str) -> str | None:
        return self._db.get(doc_id, {}).get(chunk_id)

    def set_chunk_hash(self, doc_id: str, chunk_id: str, chunk_hash: str) -> None:
        if doc_id not in self._db:
            self._db[doc_id] = {}
        self._db[doc_id][chunk_id] = chunk_hash

    def clear_document_hashes(self, doc_id: str) -> None:
        self._db.pop(doc_id, None)

class DeltaChecker:
    """Delta Hash Checker preventing redundant re-indexing of unmodified document chunks."""

    def __init__(self, hash_db: VersionedHashDB | None = None) -> None:
        self.hash_db = hash_db or VersionedHashDB()

    def filter_changed_chunks(self, nodes: list[TextNode]) -> tuple[list[TextNode], list[TextNode]]:
        new_or_modified: list[TextNode] = []
        unchanged: list[TextNode] = []

        for node in nodes:
            existing_hash = self.hash_db.get_chunk_hash(node.doc_id, node.chunk_id)
            if existing_hash != node.chunk_hash:
                new_or_modified.append(node)
            else:
                unchanged.append(node)

        print(f"[DeltaChecker] Evaluated {len(nodes)} chunks -> New/Modified: {len(new_or_modified)}, Unchanged Skipped: {len(unchanged)}")
        return new_or_modified, unchanged

    def commit_chunk_hashes(self, nodes: list[TextNode]) -> None:
        for node in nodes:
            self.hash_db.set_chunk_hash(node.doc_id, node.chunk_id, node.chunk_hash)
