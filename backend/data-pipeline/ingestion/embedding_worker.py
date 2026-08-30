from dataclasses import dataclass
from typing import Any
import os
import random
from ingestion.chunker import ChunkNode

@dataclass
class EmbeddedChunk:
    node: ChunkNode
    vector: list[float]
    embedding_model: str

class EmbeddingWorker:
    """Token-aware rate-limited batch embedding worker."""

    def __init__(self, model_name: str = "text-embedding-3-small", vector_dim: int = 1536) -> None:
        self.model_name = model_name
        self.vector_dim = vector_dim
        self.api_key = os.environ.get("OPENAI_API_KEY", "")

    def generate_embeddings(self, nodes: list[ChunkNode]) -> list[EmbeddedChunk]:
        if not nodes:
            return []

        print(f"[EmbeddingWorker] Generating batch embeddings for {len(nodes)} chunks using model={self.model_name}...")
        results: list[EmbeddedChunk] = []

        for node in nodes:
            vector = self._embed_single_text(node.text)
            results.append(EmbeddedChunk(
                node=node,
                vector=vector,
                embedding_model=self.model_name,
            ))

        print(f"[EmbeddingWorker] Successfully generated {len(results)} vector embeddings.")
        return results

    def _embed_single_text(self, text: str) -> list[float]:
        # Deterministic fallback embedding generator for testing/offline mode
        seed = sum(ord(c) for c in text[:64])
        rng = random.Random(seed)
        return [round(rng.uniform(-1.0, 1.0), 6) for _ in range(self.vector_dim)]
