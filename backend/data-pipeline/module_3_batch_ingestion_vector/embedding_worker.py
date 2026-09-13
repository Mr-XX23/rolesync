from dataclasses import dataclass
from typing import Any, Optional
import math
import os
import random
import time

try:
    import requests
except ImportError:  # requests is available in the service image; guard for safety
    requests = None

from module_3_batch_ingestion_vector.chunker import TextNode

# Google Generative Language API (Gemini) embeddings endpoint.
_GEMINI_BASE = "https://generativelanguage.googleapis.com/v1beta"

# Worth another attempt: rate limiting and transient server-side faults.
# Anything else (400 bad request, 401/403 bad key, 404 wrong model) will fail
# identically forever, so retrying only delays the real error.
_RETRYABLE_STATUS = frozenset({408, 429, 500, 502, 503, 504})


class EmbeddingFailed(RuntimeError):
    """Real embeddings were configured but could not be produced.

    Raised rather than quietly substituting pseudo-vectors: the chunks would
    be dropped from the index while the document still reported success, so a
    single rate-limit response silently cost a batch of content. Raising hands
    the document to the ingestion queue, which retries it and finally
    dead-letters it where it can be seen and replayed.
    """


@dataclass
class EmbeddedChunk:
    node: TextNode
    vector: list[float]
    # True when the vector is the deterministic pseudo-embedding rather than a
    # real one. Callers must not treat these as searchable, and must not commit
    # their delta hashes, or a transient API failure would be recorded as a
    # successful index and could never be repaired.
    is_fallback: bool = False


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
      EMBEDDING_MAX_ATTEMPTS    default 4 attempts per batch (429/5xx only)
      EMBEDDING_BACKOFF_SECONDS default 2.0 base for exponential backoff
      EMBEDDING_MAX_BACKOFF_SECONDS default 60 ceiling for a single wait
    """

    def __init__(self, model_name: str = "gemini-embedding-001", dimension: int = 1536) -> None:
        # ``model_name`` is the human-facing engine label carried in the RAG
        # config (e.g. "RoleSync Vector Engine (1536-dim)"); the real API model
        # id is env-driven so it is never accidentally set to a UI label.
        self.model_name = model_name
        self.api_model = os.environ.get("EMBEDDING_MODEL", "gemini-embedding-001").strip()
        # Clamped to the same range the vector column is created with. Without
        # this a larger value silently produces embeddings the table rejects, and
        # every upsert would fall back to Mongo with no obvious cause.
        requested = int(os.environ.get("EMBEDDING_DIMENSIONS", str(dimension)))
        self.dimension = requested if 0 < requested <= 2000 else 1536
        if self.dimension != requested:
            print(f"[EmbeddingWorker] EMBEDDING_DIMENSIONS={requested} out of range (1-2000); using {self.dimension}.")
        self.api_key = os.environ.get("GEMINI_API_KEY", "").strip()
        self.task_type = os.environ.get("EMBEDDING_TASK_TYPE", "RETRIEVAL_DOCUMENT").strip()
        self.batch_size = max(1, int(os.environ.get("EMBEDDING_BATCH_SIZE", "100")))
        self.timeout = float(os.environ.get("EMBEDDING_TIMEOUT_SECONDS", "30"))
        self.max_attempts = max(1, int(os.environ.get("EMBEDDING_MAX_ATTEMPTS", "4")))
        self.backoff_seconds = float(os.environ.get("EMBEDDING_BACKOFF_SECONDS", "2"))
        self.max_backoff_seconds = float(os.environ.get("EMBEDDING_MAX_BACKOFF_SECONDS", "60"))

    # ---- public API -------------------------------------------------------
    def generate_embeddings(self, nodes: list[TextNode]) -> list[EmbeddedChunk]:
        if not nodes:
            return []

        use_real = bool(self.api_key) and requests is not None
        if not use_real:
            reason = "GEMINI_API_KEY not set" if not self.api_key else "requests unavailable"
            print(f"[EmbeddingWorker] {reason} — using deterministic pseudo-vectors (NOT semantic) for {len(nodes)} chunks.")
            return [
                EmbeddedChunk(node=n, vector=self._pseudo_vector(n.chunk_hash), is_fallback=True)
                for n in nodes
            ]

        print(f"[EmbeddingWorker] Generating embeddings for {len(nodes)} chunks via {self.api_model} (dim={self.dimension}, task={self.task_type})...")
        embedded: list[EmbeddedChunk] = []
        real_ok = 0
        for start in range(0, len(nodes), self.batch_size):
            batch = nodes[start:start + self.batch_size]
            vectors = self._embed_batch([n.text for n in batch])
            if vectors is None:
                # Previously this substituted pseudo-vectors, which the writer
                # then excluded - so the chunks vanished from the index while the
                # document still looked successfully ingested. Fail loudly so the
                # queue retries the document instead.
                raise EmbeddingFailed(
                    f"{self.api_model} could not embed {len(batch)} chunk(s) at offset {start} "
                    f"after {self.max_attempts} attempt(s)"
                )
            real_ok += len(batch)
            for node, vec in zip(batch, vectors):
                embedded.append(EmbeddedChunk(node=node, vector=vec, is_fallback=False))

        print(f"[EmbeddingWorker] Generated {len(embedded)} embeddings ({real_ok} real).")
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
        for attempt in range(1, self.max_attempts + 1):
            last = attempt >= self.max_attempts
            try:
                resp = requests.post(
                    url,
                    headers={"x-goog-api-key": self.api_key, "Content-Type": "application/json"},
                    json=payload,
                    timeout=self.timeout,
                )
                if resp.status_code == 200:
                    embeddings = resp.json().get("embeddings", [])
                    if len(embeddings) != len(texts):
                        # A short response would misalign vectors with chunks, so
                        # it is treated as a failure rather than a partial result.
                        print(f"[EmbeddingWorker] Gemini returned {len(embeddings)} embeddings for {len(texts)} inputs.")
                        return None
                    return [self._normalize([float(x) for x in (emb.get("values") or [])]) for emb in embeddings]

                retryable = resp.status_code in _RETRYABLE_STATUS
                print(
                    f"[EmbeddingWorker] Gemini embeddings HTTP {resp.status_code} "
                    f"(attempt {attempt}/{self.max_attempts}, retryable={retryable}): {resp.text[:300]}"
                )
                if not retryable or last:
                    return None
                self._wait_before_retry(attempt, resp.headers.get("Retry-After"))
            except Exception as err:
                # Timeouts and connection resets are transient by nature.
                print(f"[EmbeddingWorker] Gemini embeddings request error (attempt {attempt}/{self.max_attempts}): {err}")
                if last:
                    return None
                self._wait_before_retry(attempt, None)
        return None

    def _wait_before_retry(self, attempt: int, retry_after: Optional[str]) -> None:
        """Back off exponentially, but obey an explicit Retry-After when given."""
        delay = self.backoff_seconds * (2 ** (attempt - 1))
        if retry_after:
            try:
                delay = max(delay, float(retry_after))
            except (TypeError, ValueError):
                pass  # HTTP-date form: keep the computed backoff
        # Jitter so parallel workers do not retry in lockstep after a 429.
        delay = min(delay, self.max_backoff_seconds) * (0.5 + random.random() / 2)
        print(f"[EmbeddingWorker] Retrying in {delay:.1f}s.")
        time.sleep(delay)

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
