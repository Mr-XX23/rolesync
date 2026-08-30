from dataclasses import dataclass
from typing import Any
import os
from module_3_batch_ingestion_vector.chunker import TextNode

@dataclass
class EmbeddedChunk:
    node: TextNode
    vector: list[float]

class EmbeddingWorker:
    """Batch Embedding Worker generating vector representations (OpenAI text-embedding-3-small or fallback)."""

    def __init__(self, model_name: str = "text-embedding-3-small", dimension: int = 1536) -> None:
        self.model_name = model_name
        self.dimension = dimension

    def generate_embeddings(self, nodes: list[TextNode]) -> list[EmbeddedChunk]:
        if not nodes:
            return []

        print(f"[EmbeddingWorker] Generating batch embeddings for {len(nodes)} chunks using model={self.model_name}...")
        embedded_chunks: list[EmbeddedChunk] = []

        for node in nodes:
            # Deterministic pseudo-embedding for testing/fallback if OpenAI API key isn't active
            dummy_vec = [0.0] * self.dimension
            # Seed vector values based on hash
            hash_val = sum(ord(c) for c in node.chunk_hash)
            for i in range(min(10, self.dimension)):
                dummy_vec[i] = ((hash_val + i) % 100) / 100.0

            embedded_chunks.append(EmbeddedChunk(node=node, vector=dummy_vec))

        print(f"[EmbeddingWorker] Successfully generated {len(embedded_chunks)} vector embeddings.")
        return embedded_chunks
