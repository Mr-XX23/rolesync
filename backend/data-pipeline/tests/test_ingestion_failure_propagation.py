"""A failed ingestion has to reach the queue, not stop at a log line.

The pipeline used to catch its own failures and push them to an in-memory
dead-letter list that nothing read - and which was rebuilt per document, so it
was discarded seconds later. The document was never retried, and the only trace
was a FAILED checkpoint. Now the failure propagates: the queue retries it, and
when it finally gives up the owning module is told so the record stops claiming
to be in progress.
"""
import asyncio

import pytest

from module_1_document_processing.pipeline.durable_queue import DurableQueue
from module_1_document_processing.pipeline.queue_worker import QueueWorker
from module_1_document_processing.parsing.parsed_document import ParsedDocument
from module_3_batch_ingestion_vector.chunker import TextNode
from module_3_batch_ingestion_vector.ingestion_pipeline import BatchIngestionPipeline
from tests.fake_redis import FakeRedis


def document() -> ParsedDocument:
    return ParsedDocument(
        doc_id="t1:USER_UPLOAD:doc_1", tenant_id="t1", user_id="u1", source="USER_UPLOAD",
        external_id="doc_1", acl=["user:u1"], mime_type="text/plain",
        text_content="Enterprise pricing tiers, discount bands and renewal terms for the quarter.",
    )


class StubChunker:
    def chunk_document(self, doc):
        return [
            TextNode(
                chunk_id="c0", doc_id=doc.doc_id, tenant_id=doc.tenant_id, user_id=doc.user_id,
                source=doc.source, external_id=doc.external_id, text="chunk", chunk_hash="h0",
                acl=list(doc.acl), chunk_index=0, total_chunks=1,
            )
        ]


class StubDelta:
    def filter_changed_chunks(self, nodes):
        return nodes, []


class ExplodingEmbedder:
    def generate_embeddings(self, nodes):
        raise RuntimeError("gemini-embedding-001 could not embed 1 chunk(s)")


class StubWriter:
    def __init__(self):
        self.vector_store = object()

    def write_embedded_chunks(self, chunks):
        return len(chunks)


# --- the pipeline ---------------------------------------------------------
def test_pipeline_reraises_so_the_document_can_be_retried():
    pipeline = BatchIngestionPipeline(
        chunker=StubChunker(), delta_checker=StubDelta(),
        embedding_worker=ExplodingEmbedder(), bulk_writer=StubWriter(),
    )

    with pytest.raises(RuntimeError, match="could not embed"):
        pipeline.process_document(document())


def test_pipeline_records_the_failed_checkpoint_before_raising():
    pipeline = BatchIngestionPipeline(
        chunker=StubChunker(), delta_checker=StubDelta(),
        embedding_worker=ExplodingEmbedder(), bulk_writer=StubWriter(),
    )

    with pytest.raises(RuntimeError):
        pipeline.process_document(document())

    checkpoint = pipeline.checkpoint_store.get_checkpoint("batch_t1:USER_UPLOAD:doc_1")
    assert checkpoint is not None
    assert checkpoint.status == "FAILED"


def test_a_successful_document_still_returns_its_count():
    pipeline = BatchIngestionPipeline(
        chunker=StubChunker(), delta_checker=StubDelta(),
        embedding_worker=type("E", (), {"generate_embeddings": lambda self, n: n})(),
        bulk_writer=StubWriter(),
    )

    assert pipeline.process_document(document()) == 1


# --- the queue's side of it ----------------------------------------------
def build_worker(queue: DurableQueue) -> QueueWorker:
    stub = object()
    return QueueWorker(
        scanner=stub, store=stub, parser_service=stub, deletion_handler=stub,
        acl_sync=stub, gatekeeper_engine=stub, ingestion_pipeline=stub, queue=queue,
    )


def drain(worker: QueueWorker, kind: str, payload: dict, seconds: float = 0.4):
    async def scenario():
        await worker.start()
        await worker.enqueue_job(kind, payload)
        await asyncio.sleep(seconds)
        await worker.stop()

    asyncio.run(scenario())


def test_the_owner_is_told_only_once_the_queue_gives_up():
    store = FakeRedis()
    queue = DurableQueue(name="t:fail", client=store, consumer_id="w1", max_attempts=1)
    worker = build_worker(queue)
    gave_up: list[dict] = []

    def explode(payload):
        raise RuntimeError("embedding service is down")

    worker.register_handler("doc", explode, on_dead=gave_up.append)
    drain(worker, "doc", {"doc_id": "doc_1", "tenant_id": "t1"})

    assert gave_up == [{"doc_id": "doc_1", "tenant_id": "t1"}]
    assert len(queue.dead_letters()) == 1


def test_a_document_still_being_retried_is_not_reported_as_failed():
    """The reason for the hook: a transient failure must not surface as final."""
    store = FakeRedis()
    queue = DurableQueue(name="t:fail", client=store, consumer_id="w1", max_attempts=5, backoff_seconds=60)
    worker = build_worker(queue)
    gave_up: list[dict] = []

    worker.register_handler("doc", lambda p: (_ for _ in ()).throw(RuntimeError("flaky")), on_dead=gave_up.append)
    drain(worker, "doc", {"doc_id": "doc_1", "tenant_id": "t1"})

    assert gave_up == []                       # still has attempts left
    assert store.zcard(queue.retry_key) == 1   # waiting to be retried
    assert queue.dead_letters() == []


def test_a_broken_callback_does_not_stop_the_worker():
    store = FakeRedis()
    queue = DurableQueue(name="t:fail", client=store, consumer_id="w1", max_attempts=1)
    worker = build_worker(queue)
    done: list[str] = []

    worker.register_handler("bad", lambda p: (_ for _ in ()).throw(RuntimeError("x")),
                            on_dead=lambda p: (_ for _ in ()).throw(RuntimeError("callback broke")))
    worker.register_handler("good", lambda p: done.append(p["doc_id"]))

    async def scenario():
        await worker.start()
        await worker.enqueue_job("bad", {"doc_id": "doc_bad", "tenant_id": "t1"})
        await asyncio.sleep(0.3)
        await worker.enqueue_job("good", {"doc_id": "doc_good", "tenant_id": "t1"})
        await asyncio.sleep(0.3)
        await worker.stop()

    asyncio.run(scenario())

    assert done == ["doc_good"]  # the loop kept running


def test_handlers_without_a_callback_are_unaffected():
    store = FakeRedis()
    queue = DurableQueue(name="t:fail", client=store, consumer_id="w1", max_attempts=1)
    worker = build_worker(queue)

    worker.register_handler("doc", lambda p: (_ for _ in ()).throw(RuntimeError("boom")))
    drain(worker, "doc", {"doc_id": "doc_1", "tenant_id": "t1"})

    assert len(queue.dead_letters()) == 1  # dead-lettered, no callback needed


# --- the worker must not freeze the service ------------------------------
def test_a_blocking_handler_does_not_stall_the_event_loop():
    """Ingestion handlers are ordinary blocking functions: they call LlamaParse,
    the classifier and the embeddings API, and sleep between embedding retries.
    Running one on the event loop would freeze every other request, the health
    check and the Eureka heartbeat for the whole document."""
    import time

    store = FakeRedis()
    queue = DurableQueue(name="t:block", client=store, consumer_id="w1", max_attempts=1)
    worker = build_worker(queue)
    worker.register_handler("slow", lambda payload: time.sleep(0.5))

    ticks = 0

    async def scenario():
        nonlocal ticks
        await worker.start()
        await worker.enqueue_job("slow", {"doc_id": "doc_1", "tenant_id": "t1"})
        deadline = asyncio.get_event_loop().time() + 0.6
        while asyncio.get_event_loop().time() < deadline:
            await asyncio.sleep(0.02)
            ticks += 1
        await worker.stop()

    asyncio.run(scenario())

    # ~30 ticks if the loop kept running; a handful if it was blocked.
    assert ticks > 15, f"event loop stalled during the handler ({ticks} ticks)"


def test_a_blocking_on_dead_callback_also_stays_off_the_loop():
    import time

    store = FakeRedis()
    queue = DurableQueue(name="t:block", client=store, consumer_id="w1", max_attempts=1)
    worker = build_worker(queue)
    called: list[str] = []

    worker.register_handler(
        "doc",
        lambda p: (_ for _ in ()).throw(RuntimeError("boom")),
        on_dead=lambda p: (time.sleep(0.3), called.append(p["doc_id"]))[1],
    )

    ticks = 0

    async def scenario():
        nonlocal ticks
        await worker.start()
        await worker.enqueue_job("doc", {"doc_id": "doc_1", "tenant_id": "t1"})
        deadline = asyncio.get_event_loop().time() + 0.5
        while asyncio.get_event_loop().time() < deadline:
            await asyncio.sleep(0.02)
            ticks += 1
        await worker.stop()

    asyncio.run(scenario())

    assert called == ["doc_1"]
    assert ticks > 12, f"event loop stalled during on_dead ({ticks} ticks)"
