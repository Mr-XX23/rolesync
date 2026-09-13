"""Staged bytes have to outlive a failure.

The bytes of an upload are written to the object store before the request is
answered, and the queued job carries only the reference. So the staged copy must
survive a failed attempt - a retry re-reads it, and a dead-lettered job cannot be
replayed without it. Discarding it in a `finally` would have turned the first
transient failure into a permanent one.
"""
import pytest

from module_1_document_processing import knowledge_vault_routes as kv


@pytest.fixture
def staged(monkeypatch):
    state = {"bytes": b"%PDF-1.7 pricing", "discarded": [], "records": {}}
    monkeypatch.setattr(kv, "load_staged_bytes", lambda ref: state["bytes"] if ref else None)
    monkeypatch.setattr(kv, "discard_staged_bytes", lambda ref: state["discarded"].append(ref))
    monkeypatch.setattr(kv, "_find_doc_record", lambda doc_id: state["records"].get(doc_id))
    monkeypatch.setattr(kv, "_save_doc_record", lambda record: state["records"].__setitem__(record["doc_id"], record))
    return state


def payload(**overrides) -> dict:
    base = {
        "doc_id": "doc_1", "tenant_id": "t1", "user_id": "u1", "filename": "pricing.pdf",
        "mime_type": "application/pdf", "source": "USER_UPLOAD", "staged_ref": "s3://bucket/t1/staging/doc_1",
    }
    base.update(overrides)
    return base


def test_a_successful_job_cleans_up_its_staged_copy(monkeypatch, staged):
    seen = {}
    monkeypatch.setattr(kv, "_process_document_background", lambda **kw: seen.update(kw))

    kv.process_document_job(payload())

    assert seen["doc_id"] == "doc_1"
    assert seen["raw_bytes"] == b"%PDF-1.7 pricing"
    assert staged["discarded"] == ["s3://bucket/t1/staging/doc_1"]


def test_a_failed_job_keeps_its_bytes_for_the_retry(monkeypatch, staged):
    def explode(**kw):
        raise RuntimeError("LlamaParse returned 500")

    monkeypatch.setattr(kv, "_process_document_background", explode)

    with pytest.raises(RuntimeError, match="LlamaParse"):
        kv.process_document_job(payload())

    assert staged["discarded"] == []  # the retry still needs them


def test_missing_bytes_fail_loudly(monkeypatch, staged):
    monkeypatch.setattr(kv, "load_staged_bytes", lambda ref: None)
    monkeypatch.setattr(kv, "_process_document_background", lambda **kw: None)

    with pytest.raises(RuntimeError, match="Staged bytes missing"):
        kv.process_document_job(payload())


# --- giving up ------------------------------------------------------------
def test_giving_up_marks_the_record_so_it_stops_saying_parsing(staged):
    staged["records"]["doc_1"] = {"doc_id": "doc_1", "status": "Parsing", "chunks": 0}

    kv.mark_document_failed(payload())

    record = staged["records"]["doc_1"]
    assert record["status"] == "Error"
    assert record["error_message"] == kv.guards.PROCESSING_FAILED_MESSAGE
    assert record["last_updated"]


def test_giving_up_keeps_the_bytes_so_the_job_stays_replayable(staged):
    staged["records"]["doc_1"] = {"doc_id": "doc_1", "status": "Parsing", "chunks": 0}

    kv.mark_document_failed(payload())

    assert staged["discarded"] == []


def test_giving_up_on_an_unknown_document_is_harmless(staged):
    kv.mark_document_failed(payload(doc_id="doc_gone"))  # must not raise

    assert staged["records"] == {}


# --- refusing work rather than promising it ------------------------------
class _Queue:
    def __init__(self, overloaded: bool, depth: int = 0, max_depth: int = 0):
        self._overloaded, self._depth, self.max_depth = overloaded, depth, max_depth

    def is_overloaded(self):
        return self._overloaded

    def depth(self):
        return self._depth


def test_a_deep_backlog_is_refused_with_a_retry_hint(monkeypatch):
    """Accepting here would keep answering "queued for parsing" for work that
    will not be reached for a long time, and grow the backlog without bound."""
    import fastapi

    monkeypatch.setattr(kv, "ingest_queue", _Queue(True, depth=500, max_depth=500))

    with pytest.raises(fastapi.HTTPException) as excinfo:
        kv._reject_if_backlogged()

    assert excinfo.value.status_code == 503
    assert excinfo.value.detail == kv.guards.QUEUE_FULL_MESSAGE
    assert excinfo.value.headers["Retry-After"] == "120"


def test_a_healthy_queue_accepts_work(monkeypatch):
    monkeypatch.setattr(kv, "ingest_queue", _Queue(False))

    kv._reject_if_backlogged()  # must not raise


def test_the_refusal_message_says_nothing_was_lost():
    """The queue is durable, so the user must not think an upload vanished."""
    assert "lost" in kv.guards.QUEUE_FULL_MESSAGE
    assert "try again" in kv.guards.QUEUE_FULL_MESSAGE.lower()
