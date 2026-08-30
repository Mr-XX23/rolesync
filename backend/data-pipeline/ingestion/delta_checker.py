import hashlib
from typing import Any
from ingestion.chunker import ChunkNode

class VersionedHashDB:
    """Store for tracking chunk-level composite hashes."""

    def __init__(self) -> None:
        self._hashes: dict[str, str] = {}  # key: chunk_id, val: composite_hash

    def get_hash(self, chunk_id: str) -> str | None:
        return self._hashes.get(chunk_id)

    def write_hash(self, chunk_id: str, composite_hash: str) -> None:
        self._hashes[chunk_id] = composite_hash

    def remove_doc_hashes(self, doc_id: str) -> None:
        to_del = [cid for cid in self._hashes if cid.startswith(f"{doc_id}:")]
        for cid in to_del:
            del self._hashes[cid]


class DeltaChecker:
    """Delta Hash Checker verifying composite chunk hashes to eliminate redundant re-indexing."""

    def __init__(self, hash_db: VersionedHashDB | None = None) -> None:
        self.hash_db = hash_db or VersionedHashDB()

    def filter_changed_chunks(self, nodes: list[ChunkNode]) -> tuple[list[ChunkNode], list[ChunkNode]]:
        new_or_modified: list[ChunkNode] = []
        unchanged: list[ChunkNode] = []

        for node in nodes:
            current_hash = self.compute_chunk_hash(node)
            prior_hash = self.hash_db.get_hash(node.chunk_id)

            if prior_hash == current_hash:
                unchanged.append(node)
            else:
                new_or_modified.append(node)

        print(f"[DeltaChecker] Evaluated {len(nodes)} chunks -> New/Modified: {len(new_or_modified)}, Unchanged Skipped: {len(unchanged)}")
        return new_or_modified, unchanged

    def compute_chunk_hash(self, node: ChunkNode) -> str:
        payload = f"{node.doc_id}:{node.chunk_index}:{node.text}:{','.join(sorted(node.acl))}"
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def commit_chunk_hashes(self, nodes: list[ChunkNode]) -> None:
        for node in nodes:
            chash = self.compute_chunk_hash(node)
            self.hash_db.write_hash(node.chunk_id, chash)
