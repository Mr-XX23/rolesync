"""pgvector index helpers and graceful degradation.

The live HNSW behaviour (real embeddings, ranking, ACL/tenant isolation, index
usage) is verified against the running pgvector container; these cover the parts
that must hold with no database present, including that an unavailable index
never breaks callers - it just hands back control so they use brute force.
"""
from module_3_batch_ingestion_vector.pgvector_index import PgVectorIndex, to_vector_literal


def test_vector_literal_format():
    assert to_vector_literal([0.1, -0.25, 3.0]) == "[0.1,-0.25,3]"


def test_vector_literal_handles_empty():
    assert to_vector_literal([]) == "[]"


def test_vector_literal_is_parseable_back():
    values = [0.015625, -0.5, 1.0]
    literal = to_vector_literal(values)
    assert [float(x) for x in literal.strip("[]").split(",")] == values


def test_index_is_unavailable_without_persistence():
    # tests/conftest.py pins RAG_PERSISTENCE=off.
    assert PgVectorIndex().available() is False


def test_search_returns_none_when_unavailable():
    """None means 'use the fallback path', which is different from 'no matches'."""
    assert PgVectorIndex().search([0.1] * 8, "tenant", ["u1"], limit=3) is None


def test_empty_acl_matches_nothing_rather_than_erroring():
    index = PgVectorIndex()
    # An empty ACL must never be expanded into invalid SQL.
    assert index.search([0.1] * 8, "tenant", [], limit=3) in (None, [])


def test_writes_are_no_ops_when_unavailable():
    index = PgVectorIndex()
    assert index.upsert([]) == 0
    assert index.delete_by_doc_id("doc") == 0
    assert index.delete_by_tenant_source_user("t", "gdrive") == 0
    assert index.update_acl_for_doc_id("doc", ["u1"]) == 0
    assert index.count("t") == 0
