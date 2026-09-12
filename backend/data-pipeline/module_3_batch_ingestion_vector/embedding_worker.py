from dataclasses import dataclass
from typing import Any, Optional
import os
import math

try:
    import requests
except ImportError:  # requests is available in the service image; guard for safety
    requests = None

from module_3_batch_ingestion_vector.chunker import TextNode

# Google Generative Language API (Gemini) embeddings endpoint.
_GEMINI_BASE = "https://generativelanguage.googleapis.com/v1beta"


@dataclass
class EmbeddedChunk:
    node: TextNode
    vector: list[float]


class EmbeddingWorker:
    """Batch embedding worker.

    Generates REAL semantic vectors via the Gemini embeddings API
    (``gemini-embedding-001`` by default). Only when no ``GEMINI_API_KEY`` is
    configured, ``requests`` is unavailable, or an API call fails does it fall
    back to a deterministic (non-semantic) pseudo-vector, so ingestion degrades
    gracefully instead of hard-failing.

    Config (env, all optional):
      GEMINI_API_KEY            API key (required for real embeddings)
      EMBEDDING_MODEL           default "gemini-embedding-001"
      EMBEDDING_DIMENSIONS      default 1536 (Matryoshka truncation, 128-3072)
      EMBEDDING_TASK_TYPE       default "RETRIEVAL_DOCUMENT" (use RETRIEVAL_QUERY for queries)
      EMBEDDING_BATCH_SIZE      default 100 requests per batchEmbedContents call
      EMBEDDING_TIMEOUT_SECONDS default 30
    """

    def __init__(self, model_name: str = "gemini-embedding-001", dimension: int = 1536) -> None:
        # ``model_name`` is the human-facing engine label carried in the RAG
        # config (e.g. "RoleSync Vector Engine (1536-dim)"); the real API model
        # id is env-driven so it is never accidentally set to a UI label.
        self.model_name = model_name
        self.api_model = os.environ.get("EMBEDDING_MODEL", "gemini-embedding-001").strip()
        self.dimension = int(os.environ.get("EMBEDDING_DIMENSIONS", str(dimension)))
        self.api_key = os.environ.get("GEMINI_API_KEY", "").strip()
        self.task_type = os.environ.get("EMBEDDING_TASK_TYPE", "RETRIEVAL_DOCUMENT").strip()
        self.batch_size = max(1, int(os.environ.get("EMBEDDING_BATCH_SIZE", "100")))
        self.timeout = float(os.environ.get("EMBEDDING_TIMEOUT_SECONDS", "30"))

    # ---- public API -------------------------------------------------------
    def generate_embeddings(self, nodes: list[TextNode]) -> list[EmbeddedChunk]:
        if not nodes:
            return []

        use_real = bool(self.api_key) and requests is not None
        if not use_real:
            reason = "GEMINI_API_KEY not set" if not self.api_key else "requests unavailable"
            print(f"[EmbeddingWorker] {reason} — using deterministic pseudo-vectors (NOT semantic) for {len(nodes)} chunks.")
            return [EmbeddedChunk(node=n, vector=self._pseudo_vector(n.chunk_hash)) for n in nodes]

        print(f"[EmbeddingWorker] Generating embeddings for {len(nodes)} chunks via {self.api_model} (dim={self.dimension}, task={self.task_type})...")
        embedded: list[EmbeddedChunk] = []
        real_ok = 0
        for start in range(0, len(nodes), self.batch_size):
            batch = nodes[start:start + self.batch_size]
            vectors = self._embed_batch([n.text for n in batch])
            if vectors is None:
                print(f"[EmbeddingWorker] Batch at offset {start} failed — pseudo-vector fallback for {len(batch)} chunks.")
                vectors = [self._pseudo_vector(n.chunk_hash) for n in batch]
            else:
                real_ok += len(batch)
            for node, vec in zip(batch, vectors):
                embedded.append(EmbeddedChunk(node=node, vector=vec))

        print(f"[EmbeddingWorker] Generated {len(embedded)} embeddings ({real_ok} real, {len(embedded) - real_ok} fallback).")
        return embedded

    def embed_query(self, text: str) -> Optional[list[float]]:
        """Embed a single query string (RETRIEVAL_QUERY). Returns None if the
        API key/dependency is missing or the call fails."""
        if not text or not self.api_key or requests is None:
            return None
        vecs = self._embed_batch([text], task_type="RETRIEVAL_QUERY")
        return vecs[0] if vecs else None

    # ---- internals --------------------------------------------------------
    def _embed_batch(self, texts: list[str], task_type: Optional[str] = None) -> Optional[list[list[float]]]:
        url = f"{_GEMINI_BASE}/models/{self.api_model}:batchEmbedContents"
        payload = {
            "requests": [
                {
                    "model": f"models/{self.api_model}",
                    "content": {"parts": [{"text": (t or " ")[:8000]}]},
                    "task_type": task_type or self.task_type,
                    "output_dimensionality": self.dimension,
                }
                for t in texts
            ]
        }
        try:
            resp = requests.post(
                url,
                headers={"x-goog-api-key": self.api_key, "Content-Type": "application/json"},
                json=payload,
                timeout=self.timeout,
            )
            if resp.status_code != 200:
                print(f"[EmbeddingWorker] Gemini embeddings HTTP {resp.status_code}: {resp.text[:300]}")
                return None
            embeddings = resp.json().get("embeddings", [])
            if len(embeddings) != len(texts):
                print(f"[EmbeddingWorker] Gemini returned {len(embeddings)} embeddings for {len(texts)} inputs.")
                return None
            return [self._normalize([float(x) for x in (emb.get("values") or [])]) for emb in embeddings]
        except Exception as err:
            print(f"[EmbeddingWorker] Gemini embeddings request error: {err}")
            return None

    @staticmethod
    def _normalize(vec: list[float]) -> list[float]:
        # gemini-embedding-001 is pre-normalized only at 3072 dims; truncated
        # (Matryoshka) outputs must be L2-normalized for cosine similarity.
        norm = math.sqrt(sum(v * v for v in vec))
        return [v / norm for v in vec] if norm > 0 else vec

    def _pseudo_vector(self, chunk_hash: str) -> list[float]:
        # Deterministic, NON-semantic fallback (legacy behaviour). Used only when
        # no API key is configured or the embeddings API is unreachable.
        dummy = [0.0] * self.dimension
        hash_val = sum(ord(c) for c in chunk_hash)
        for i in range(min(10, self.dimension)):
            dummy[i] = ((hash_val + i) % 100) / 100.0
        return dummy
