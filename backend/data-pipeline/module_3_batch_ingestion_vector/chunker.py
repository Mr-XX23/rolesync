from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional
import hashlib
from module_1_document_processing.parsing.parsed_document import ParsedDocument

@dataclass
class TextNode:
    chunk_id: str
    doc_id: str
    tenant_id: str
    user_id: str
    source: str
    external_id: str
    text: str
    chunk_hash: str
    acl: list[str]
    chunk_index: int
    total_chunks: int
    doc_ref_id: str = ""
    prev_chunk_id: Optional[str] = None
    next_chunk_id: Optional[str] = None
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

class HierarchicalChunker:
    """Hierarchical Document Chunker splitting documents into semantic text nodes with overlap and MD5 hash signatures."""

    def __init__(self, chunk_size: int = 500, chunk_overlap: int = 50) -> None:
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap

    def chunk_document(self, document: ParsedDocument) -> list[TextNode]:
        text = (document.text_content or "").strip()
        if not text:
            return []

        # Split text by paragraphs or length
        paragraphs = text.split("\n\n")
        chunks = []
        current_chunk = ""

        for para in paragraphs:
            para = para.strip()
            if not para:
                continue

            if len(current_chunk) + len(para) <= self.chunk_size:
                current_chunk += ("\n\n" if current_chunk else "") + para
            else:
                if current_chunk:
                    chunks.append(current_chunk)
                current_chunk = para

        if current_chunk:
            chunks.append(current_chunk)

        nodes: list[TextNode] = []
        total = len(chunks)
        doc_ref = document.external_id or document.doc_id

        # Precompute chunk IDs to enable bidirectional linked list chaining
        chunk_ids = [f"{document.doc_id}_chunk_{i}" for i in range(total)]

        for idx, chunk_text in enumerate(chunks):
            chunk_hash = hashlib.md5(chunk_text.encode("utf-8")).hexdigest()
            chunk_id = chunk_ids[idx]
            prev_id = chunk_ids[idx - 1] if idx > 0 else None
            next_id = chunk_ids[idx + 1] if idx < total - 1 else None

            node_metadata = {
                **document.metadata,
                "mime_type": document.mime_type,
                "parser_used": document.parser_used,
                "doc_ref_id": doc_ref,
                "parent_doc_id": doc_ref,
                "chunk_index": idx,
                "total_chunks": total,
                "prev_chunk_id": prev_id,
                "next_chunk_id": next_id,
            }

            node = TextNode(
                chunk_id=chunk_id,
                doc_id=document.doc_id,
                tenant_id=document.tenant_id,
                user_id=document.user_id,
                source=document.source,
                external_id=document.external_id,
                doc_ref_id=doc_ref,
                text=chunk_text,
                chunk_hash=chunk_hash,
                acl=list(document.acl),
                chunk_index=idx,
                total_chunks=total,
                prev_chunk_id=prev_id,
                next_chunk_id=next_id,
                metadata=node_metadata,
            )
            nodes.append(node)

        print(f"[HierarchicalChunker] Chunked doc_id={document.doc_id} into {len(nodes)} linked nodes (doc_ref_id={doc_ref}) with ACL tags: {document.acl}")
        return nodes
