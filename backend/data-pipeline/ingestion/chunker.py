from dataclasses import dataclass, field
from typing import Any
from parsing.parsed_document import ParsedDocument

try:
    from llama_index.core.node_parser import SentenceSplitter
except ImportError:
    SentenceSplitter = None

@dataclass
class ChunkNode:
    chunk_id: str
    doc_id: str
    chunk_index: int
    text: str
    tenant_id: str
    user_id: str
    source: str
    acl: list[str]
    metadata: dict[str, Any] = field(default_factory=dict)

class HierarchicalChunker:
    """Hierarchical chunker attaching tenant_id, source, and acl[] tags to every chunk."""

    def __init__(self, chunk_size: int = 512, chunk_overlap: int = 64) -> None:
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap
        self.splitter = None
        if SentenceSplitter is not None:
            try:
                self.splitter = SentenceSplitter(chunk_size=chunk_size, chunk_overlap=chunk_overlap)
            except Exception as e:
                print(f"[HierarchicalChunker] LlamaIndex splitter init notice: {e}")

    def chunk_document(self, document: ParsedDocument) -> list[ChunkNode]:
        text = document.text_content or ""
        if not text.strip():
            return []

        text_chunks = []
        if self.splitter is not None:
            try:
                text_chunks = self.splitter.split_text(text)
            except Exception as err:
                print(f"[HierarchicalChunker] LlamaIndex splitter error: {err}. Using local fallback chunker.")
                text_chunks = self._fallback_split(text)
        else:
            text_chunks = self._fallback_split(text)

        nodes = []
        for index, chunk_text in enumerate(text_chunks):
            chunk_id = f"{document.doc_id}:chunk_{index}"
            node = ChunkNode(
                chunk_id=chunk_id,
                doc_id=document.doc_id,
                chunk_index=index,
                text=chunk_text,
                tenant_id=document.tenant_id,
                user_id=document.user_id,
                source=document.source,
                acl=list(document.acl),
                metadata={
                    **document.metadata,
                    "mime_type": document.mime_type,
                    "chunk_index": index,
                    "total_chunks": len(text_chunks),
                },
            )
            nodes.append(node)

        print(f"[HierarchicalChunker] Chunked doc_id={document.doc_id} into {len(nodes)} nodes with ACL tags: {document.acl}")
        return nodes

    def _fallback_split(self, text: str) -> list[str]:
        words = text.split()
        chunks = []
        current = []
        current_len = 0

        for word in words:
            current.append(word)
            current_len += len(word) + 1
            if current_len >= self.chunk_size:
                chunks.append(" ".join(current))
                current = []
                current_len = 0

        if current:
            chunks.append(" ".join(current))

        return chunks if chunks else [text]
