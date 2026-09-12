"""Integrity rules that keep a failed index from becoming permanent data loss.

Two failure modes these pin down, both found by live testing rather than by the
unit suite:
  * a chunk fingerprint committed for a chunk that was never stored makes the
    delta check skip it forever, so re-indexing can never repair it;
  * a pseudo-embedding written into the search index silently degrades retrieval
    with no error anywhere.
"""
from module_1_document_processing.del_acl_and_reconc.live_source_lister import (
    SOURCE_ALIASES,
    SWEEPABLE_SOURCES,
    LiveSourceLister,
    UNSWEEPABLE_REASON,
)
from module_3_batch_ingestion_vector.bulk_writer import BulkWriter
from module_3_batch_ingestion_vector.chunker import TextNode
from module_3_batch_ingestion_vector.delta_checker import DeltaChecker, VersionedHashDB
from module_3_batch_ingestion_vector.embedding_worker import EmbeddedChunk, EmbeddingWorker


def _node(i: int) -> TextNode:
    return TextNode(chunk_id=f"c{i}", doc_id="docX", tenant_id="t1", user_id="u1",
                    source="upload", external_id="e1", text=f"chunk {i}",
                    chunk_hash=f"hash{i}", acl=["u1"], chunk_index=i, total_chunks=2)


class _VectorStoreStub:
    """Stands in for VectorStore, reporting how many records it persisted."""

    def __init__(self, persisted: int, durable: bool = True) -> None:
        self.persisted = persisted
        self.last_write_durable = durable

    def upsert_vectors(self, embedded_chunks):
        return self.persisted


def _writer(persisted: int, durable: bool = True):
    hash_db = VersionedHashDB(use_db=False)
    checker = DeltaChecker(hash_db)
    writer = BulkWriter(vector_store=_VectorStoreStub(persisted, durable), delta_checker=checker)
    return writer, hash_db


# ---- delta hashes are only committed on success -------------------------
def test_hashes_committed_when_everything_persisted():
    writer, hash_db = _writer(persisted=2)
    writer.write_embedded_chunks([EmbeddedChunk(node=_node(i), vector=[0.1]) for i in range(2)])
    assert hash_db.get_chunk_hash("docX", "c0") == "hash0"
    assert hash_db.get_chunk_hash("docX", "c1") == "hash1"


def test_hashes_not_committed_when_nothing_persisted():
    writer, hash_db = _writer(persisted=0)
    writer.write_embedded_chunks([EmbeddedChunk(node=_node(i), vector=[0.1]) for i in range(2)])
    # Skipping the commit is what allows a later re-index to repair the document.
    assert hash_db.get_chunk_hash("docX", "c0") is None


def test_hashes_not_committed_on_partial_write():
    writer, hash_db = _writer(persisted=1)
    writer.write_embedded_chunks([EmbeddedChunk(node=_node(i), vector=[0.1]) for i in range(2)])
    assert hash_db.get_chunk_hash("docX", "c0") is None
    assert hash_db.get_chunk_hash("docX", "c1") is None


def test_hashes_not_committed_when_no_durable_store_took_the_write():
    """Chunks that only live in-process must stay repairable by a re-index."""
    writer, hash_db = _writer(persisted=2, durable=False)
    writer.write_embedded_chunks([EmbeddedChunk(node=_node(i), vector=[0.1]) for i in range(2)])
    assert hash_db.get_chunk_hash("docX", "c0") is None


def test_fallback_chunks_never_get_a_committed_hash():
    writer, hash_db = _writer(persisted=1)
    writer.write_embedded_chunks([
        EmbeddedChunk(node=_node(0), vector=[0.1], is_fallback=False),
        EmbeddedChunk(node=_node(1), vector=[0.1], is_fallback=True),
    ])
    # One real chunk, one persisted -> the real one commits, the fallback does not.
    assert hash_db.get_chunk_hash("docX", "c0") == "hash0"
    assert hash_db.get_chunk_hash("docX", "c1") is None


# ---- fallback embeddings are flagged ------------------------------------
def test_missing_api_key_produces_flagged_fallback_embeddings(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "")
    chunks = EmbeddingWorker().generate_embeddings([_node(0), _node(1)])
    assert len(chunks) == 2
    assert all(chunk.is_fallback for chunk in chunks), "pseudo-embeddings must be flagged"


def test_embedded_chunk_defaults_to_real():
    assert EmbeddedChunk(node=_node(0), vector=[0.1]).is_fallback is False


# ---- reconciliation source keys match what is stored --------------------
def test_calendar_is_keyed_by_its_stored_source_value():
    # Calendar documents are persisted with source="google_calendar"; keying the
    # sweeper "calendar" made every calendar sweep match zero documents.
    assert "google_calendar" in SWEEPABLE_SOURCES
    assert "calendar" not in SWEEPABLE_SOURCES
    assert SOURCE_ALIASES["calendar"] == "google_calendar"


def test_colloquial_calendar_name_is_still_accepted():
    listing = LiveSourceLister(composio_client=None).list_source("calendar", "u1")
    # It should attempt the calendar listing, not reject the source outright.
    assert listing.reason != UNSWEEPABLE_REASON


def test_unbounded_sources_remain_unsweepable():
    for source in ("gmail", "slack"):
        listing = LiveSourceLister(composio_client=None).list_source(source, "u1")
        assert listing.reason == UNSWEEPABLE_REASON
