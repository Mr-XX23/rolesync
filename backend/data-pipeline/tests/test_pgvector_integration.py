"""Integration tests that exercise the real pgvector SQL.

The rest of the suite pins RAG_PERSISTENCE=off, so none of this SQL was covered
automatically - which is why several defects in it only surfaced under live
testing. These run against an actual pgvector database when one is pointed at:

    RAG_PERSISTENCE=on \
    RAG_DATABASE_URL=postgresql://<user>:<pass>@localhost:5433/rolesync-micro-rag \
    python -m pytest tests/test_pgvector_integration.py

They skip cleanly otherwise.
"""
import os
import uuid

import pytest

_DISABLED = os.environ.get("RAG_PERSISTENCE", "off").strip().lower() in {
    "", "0", "off", "false", "disabled",
}
pytestmark = pytest.mark.skipif(_DISABLED, reason="needs a live pgvector database (RAG_PERSISTENCE=on)")


@pytest.fixture(scope="module")
def index():
    from rag.database import init_rag_db
    from rag.state import set_persistence_available

    if not init_rag_db():
        pytest.skip("RAG database unavailable")
    set_persistence_available(True)

    from module_3_batch_ingestion_vector.pgvector_index import pgvector_index

    if not pgvector_index.available():
        pytest.skip("pgvector extension unavailable")
    return pgvector_index


@pytest.fixture
def tenant(index):
    name = f"itest_{uuid.uuid4().hex[:10]}"
    yield name
    index._delete("tenant_id = :tenant_id", {"tenant_id": name})


class _Rec:
    """Minimal VectorRecord-shaped object."""

    def __init__(self, tenant, idx, vector, text="chunk text", acl=None, fallback=False):
        self.vector_id = f"{tenant}_c{idx}"
        self.doc_id = f"{tenant}:upload:doc1"
        self.doc_ref_id = "doc1"
        self.tenant_id = tenant
        self.user_id = "u1"
        self.source = "upload"
        self.external_id = "doc1"
        self.text = text
        self.vector = vector
        self.acl = acl if acl is not None else [f"tenant:{tenant}"]
        self.chunk_index = idx
        self.total_chunks = 3
        self.prev_chunk_id = None
        self.next_chunk_id = None
        self.metadata = {"embedding_fallback": True} if fallback else {"category": "PRICING"}


def _unit(dim, lead):
    """A normalized-ish vector whose first component dominates."""
    vec = [0.0] * dim
    vec[0] = lead
    vec[1] = 1.0 - lead
    return vec


def test_schema_has_hnsw_index(index):
    from sqlalchemy import text as sql

    from rag.database import session_scope

    with session_scope() as s:
        defs = [r[0] for r in s.execute(sql(
            "SELECT indexdef FROM pg_indexes WHERE schemaname='rag' AND tablename='vector_chunks'"
        )).all()]
    assert any("hnsw" in d.lower() for d in defs), "HNSW index missing"


def test_upsert_and_similarity_ordering(index, tenant):
    dim = int(os.environ.get("EMBEDDING_DIMENSIONS", "1536"))
    assert index.upsert([
        _Rec(tenant, 0, _unit(dim, 1.0), text="closest"),
        _Rec(tenant, 1, _unit(dim, 0.2), text="furthest"),
    ]) == 2
    assert index.count(tenant) == 2

    hits = index.search(_unit(dim, 1.0), tenant, [f"tenant:{tenant}"], limit=5)
    assert hits and hits[0]["text"] == "closest", "nearest neighbour ordering is wrong"
    assert hits[0]["score"] >= hits[-1]["score"]


def test_tenant_isolation_is_enforced_in_sql(index, tenant):
    dim = int(os.environ.get("EMBEDDING_DIMENSIONS", "1536"))
    index.upsert([_Rec(tenant, 0, _unit(dim, 1.0))])
    assert index.search(_unit(dim, 1.0), "some_other_tenant", [f"tenant:{tenant}"], limit=5) == []


def test_acl_isolation_is_enforced_in_sql(index, tenant):
    dim = int(os.environ.get("EMBEDDING_DIMENSIONS", "1536"))
    index.upsert([_Rec(tenant, 0, _unit(dim, 1.0))])
    assert index.search(_unit(dim, 1.0), tenant, ["tenant:someone_else"], limit=5) == []


def test_empty_acl_returns_nothing_rather_than_erroring(index, tenant):
    dim = int(os.environ.get("EMBEDDING_DIMENSIONS", "1536"))
    index.upsert([_Rec(tenant, 0, _unit(dim, 1.0))])
    assert index.search(_unit(dim, 1.0), tenant, [], limit=5) == []


def test_fallback_embeddings_are_excluded_from_search(index, tenant):
    dim = int(os.environ.get("EMBEDDING_DIMENSIONS", "1536"))
    index.upsert([_Rec(tenant, 0, _unit(dim, 1.0), text="pseudo", fallback=True)])
    assert index.count(tenant) == 1, "row should exist"
    assert index.search(_unit(dim, 1.0), tenant, [f"tenant:{tenant}"], limit=5) == [], \
        "pseudo-embeddings must never be returned as search results"


def test_list_chunks_is_ordered_and_reports_dimension(index, tenant):
    dim = int(os.environ.get("EMBEDDING_DIMENSIONS", "1536"))
    index.upsert([
        _Rec(tenant, 1, _unit(dim, 0.5), text="second"),
        _Rec(tenant, 0, _unit(dim, 0.6), text="first"),
    ])
    rows = index.list_chunks(f"{tenant}:upload:doc1")
    assert [r["text"] for r in rows] == ["first", "second"]
    assert rows[0]["dimension"] == dim


def test_delete_by_doc_id_removes_rows(index, tenant):
    dim = int(os.environ.get("EMBEDDING_DIMENSIONS", "1536"))
    index.upsert([_Rec(tenant, 0, _unit(dim, 1.0))])
    assert index.delete_by_doc_id(f"{tenant}:upload:doc1") >= 1
    assert index.count(tenant) == 0


def test_acl_update_is_applied(index, tenant):
    dim = int(os.environ.get("EMBEDDING_DIMENSIONS", "1536"))
    index.upsert([_Rec(tenant, 0, _unit(dim, 1.0))])
    assert index.update_acl_for_doc_id(f"{tenant}:upload:doc1", ["tenant:moved"]) == 1
    assert index.search(_unit(dim, 1.0), tenant, [f"tenant:{tenant}"], limit=5) == []
    assert index.search(_unit(dim, 1.0), tenant, ["tenant:moved"], limit=5) != []
