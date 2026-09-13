"""Embedding failures must cost nothing silently.

A rate-limited or briefly unavailable embeddings API used to produce
pseudo-vectors for the whole batch. The writer then (correctly) refused to index
those, so up to EMBEDDING_BATCH_SIZE chunks disappeared while the document still
reported success. These tests pin the replacement: transient failures are
retried, permanent ones are not retried pointlessly, and an exhausted batch
raises so the document goes back on the queue instead of half-indexing.
"""
import pytest

from module_3_batch_ingestion_vector import embedding_worker as ew
from module_3_batch_ingestion_vector.chunker import TextNode
from module_3_batch_ingestion_vector.embedding_worker import EmbeddingFailed, EmbeddingWorker

DIM = 8


class FakeResponse:
    def __init__(self, status_code: int, payload=None, headers=None, text=""):
        self.status_code = status_code
        self._payload = payload or {}
        self.headers = headers or {}
        self.text = text or str(status_code)

    def json(self):
        return self._payload


class FakeRequests:
    """Replays a scripted sequence of responses and records the calls."""

    def __init__(self, responses):
        self._responses = list(responses)
        self.calls = 0

    def post(self, url, headers=None, json=None, timeout=None):
        self.calls += 1
        item = self._responses[min(self.calls - 1, len(self._responses) - 1)]
        if isinstance(item, Exception):
            raise item
        return item


def ok_response(count: int) -> FakeResponse:
    return FakeResponse(200, {"embeddings": [{"values": [0.5] * DIM} for _ in range(count)]})


@pytest.fixture
def no_sleep(monkeypatch):
    """Backoff must not actually slow the tests; record what was asked for."""
    waits: list[float] = []
    monkeypatch.setattr(ew.time, "sleep", lambda s: waits.append(s))
    return waits


@pytest.fixture
def worker(monkeypatch) -> EmbeddingWorker:
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    monkeypatch.setenv("EMBEDDING_DIMENSIONS", str(DIM))
    monkeypatch.setenv("EMBEDDING_MAX_ATTEMPTS", "3")
    monkeypatch.setenv("EMBEDDING_BACKOFF_SECONDS", "2")
    return EmbeddingWorker()


def nodes(count: int = 2) -> list[TextNode]:
    return [
        TextNode(
            chunk_id=f"doc_1_chunk_{i}", doc_id="doc_1", tenant_id="t1", user_id="u1",
            source="USER_UPLOAD", external_id="doc_1", text=f"chunk {i} text",
            chunk_hash=f"hash{i}", acl=["user:u1"], chunk_index=i, total_chunks=count,
        )
        for i in range(count)
    ]


# --- retrying the right things -------------------------------------------
def test_rate_limit_is_retried_and_then_succeeds(monkeypatch, worker, no_sleep):
    fake = FakeRequests([FakeResponse(429, text="quota"), ok_response(2)])
    monkeypatch.setattr(ew, "requests", fake)

    chunks = worker.generate_embeddings(nodes(2))

    assert fake.calls == 2
    assert len(chunks) == 2
    assert all(not c.is_fallback for c in chunks)
    assert len(no_sleep) == 1  # backed off once


@pytest.mark.parametrize("status", [429, 500, 502, 503, 504, 408])
def test_transient_statuses_are_retried(monkeypatch, worker, no_sleep, status):
    fake = FakeRequests([FakeResponse(status), ok_response(2)])
    monkeypatch.setattr(ew, "requests", fake)

    assert len(worker.generate_embeddings(nodes(2))) == 2
    assert fake.calls == 2


@pytest.mark.parametrize("status", [400, 401, 403, 404])
def test_permanent_errors_are_not_retried(monkeypatch, worker, no_sleep, status):
    """A bad key or model fails identically forever; retrying only hides it."""
    fake = FakeRequests([FakeResponse(status, text="bad request")])
    monkeypatch.setattr(ew, "requests", fake)

    with pytest.raises(EmbeddingFailed):
        worker.generate_embeddings(nodes(2))

    assert fake.calls == 1
    assert no_sleep == []


def test_network_errors_are_retried(monkeypatch, worker, no_sleep):
    fake = FakeRequests([TimeoutError("read timed out"), ok_response(2)])
    monkeypatch.setattr(ew, "requests", fake)

    assert len(worker.generate_embeddings(nodes(2))) == 2
    assert fake.calls == 2


# --- giving up loudly -----------------------------------------------------
def test_exhausted_retries_raise_instead_of_dropping_chunks(monkeypatch, worker, no_sleep):
    """The core fix: no silent half-indexed document."""
    fake = FakeRequests([FakeResponse(429, text="quota exhausted")])
    monkeypatch.setattr(ew, "requests", fake)

    with pytest.raises(EmbeddingFailed) as excinfo:
        worker.generate_embeddings(nodes(2))

    assert fake.calls == 3  # EMBEDDING_MAX_ATTEMPTS
    assert "could not embed" in str(excinfo.value)


def test_a_short_response_is_a_failure_not_a_partial_result(monkeypatch, worker, no_sleep):
    """Fewer vectors than chunks would misalign them; that must never be written."""
    fake = FakeRequests([ok_response(1)])  # one vector for two chunks
    monkeypatch.setattr(ew, "requests", fake)

    with pytest.raises(EmbeddingFailed):
        worker.generate_embeddings(nodes(2))


def test_every_batch_must_succeed(monkeypatch, worker, no_sleep):
    monkeypatch.setenv("EMBEDDING_BATCH_SIZE", "2")
    batched = EmbeddingWorker()
    fake = FakeRequests([ok_response(2), FakeResponse(400, text="nope")])
    monkeypatch.setattr(ew, "requests", fake)

    with pytest.raises(EmbeddingFailed) as excinfo:
        batched.generate_embeddings(nodes(4))

    assert "offset 2" in str(excinfo.value)


# --- backoff behaviour ----------------------------------------------------
def test_backoff_grows_and_is_jittered(monkeypatch, worker, no_sleep):
    fake = FakeRequests([FakeResponse(503)])
    monkeypatch.setattr(ew, "requests", fake)

    with pytest.raises(EmbeddingFailed):
        worker.generate_embeddings(nodes(2))

    assert len(no_sleep) == 2
    # base 2s then 4s, each jittered into [50%, 100%] of the computed delay.
    assert 1.0 <= no_sleep[0] <= 2.0
    assert 2.0 <= no_sleep[1] <= 4.0


def test_retry_after_header_is_honoured(monkeypatch, worker, no_sleep):
    fake = FakeRequests([FakeResponse(429, headers={"Retry-After": "30"}), ok_response(2)])
    monkeypatch.setattr(ew, "requests", fake)

    worker.generate_embeddings(nodes(2))

    assert no_sleep[0] >= 15.0  # 30s, jitter never drops below half


def test_a_nonsense_retry_after_falls_back_to_backoff(monkeypatch, worker, no_sleep):
    fake = FakeRequests([FakeResponse(429, headers={"Retry-After": "Wed, 21 Oct 2026 07:28:00 GMT"}), ok_response(2)])
    monkeypatch.setattr(ew, "requests", fake)

    worker.generate_embeddings(nodes(2))

    assert 1.0 <= no_sleep[0] <= 2.0


def test_a_single_wait_is_capped(monkeypatch, no_sleep):
    monkeypatch.setenv("GEMINI_API_KEY", "k")
    monkeypatch.setenv("EMBEDDING_MAX_ATTEMPTS", "2")
    monkeypatch.setenv("EMBEDDING_MAX_BACKOFF_SECONDS", "5")
    capped = EmbeddingWorker()
    fake = FakeRequests([FakeResponse(429, headers={"Retry-After": "3600"}), ok_response(2)])
    monkeypatch.setattr(ew, "requests", fake)

    capped.generate_embeddings(nodes(2))

    assert no_sleep[0] <= 5.0


# --- the offline path stays usable ---------------------------------------
def test_without_an_api_key_it_still_degrades_quietly(monkeypatch, no_sleep):
    """Local and test runs have no key; that is a deliberate mode, not a failure."""
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    offline = EmbeddingWorker()

    chunks = offline.generate_embeddings(nodes(2))

    assert len(chunks) == 2
    assert all(c.is_fallback for c in chunks)  # flagged, so never indexed


def test_no_nodes_is_not_an_error(worker):
    assert worker.generate_embeddings([]) == []
