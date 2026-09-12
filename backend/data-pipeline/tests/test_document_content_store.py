"""Normalized text storage, and the JSONB payload guard on lineage writes.

Includes a regression test for a bug found in live testing: connector event
metadata carries raw bytes, which are not JSON-serializable, so writing them
into the lineage payload failed the insert and silently dropped the document
to the in-memory store.
"""
from module_1_document_processing.document_content_store import DocumentContentStore
from module_1_document_processing.pipeline.canonical_store import CanonicalStore


# ---- lineage payload sanitising -----------------------------------------
def test_json_safe_replaces_bytes_with_a_descriptor():
    out = CanonicalStore._json_safe({"raw_bytes": b"abcd", "name": "file.pdf"})
    assert out["name"] == "file.pdf"
    assert out["raw_bytes"] == "<bytes len=4>"


def test_json_safe_handles_nested_and_mixed_types():
    payload = {
        "attachments": [{"blob": b"xy", "size": 2}],
        "flag": True,
        "ratio": 1.5,
        "missing": None,
        "tags": ("a", "b"),
    }
    out = CanonicalStore._json_safe(payload)
    assert out["attachments"][0]["blob"] == "<bytes len=2>"
    assert out["attachments"][0]["size"] == 2
    assert out["flag"] is True and out["ratio"] == 1.5 and out["missing"] is None
    assert out["tags"] == ["a", "b"]


def test_json_safe_output_is_actually_serialisable():
    import json

    json.dumps(CanonicalStore._json_safe({"b": b"\x00\x01", "nested": {"c": bytearray(b"zz")}}))


def test_json_safe_stops_at_depth_limit():
    deep = current = {}
    for _ in range(12):
        current["next"] = {}
        current = current["next"]
    import json

    json.dumps(CanonicalStore._json_safe(deep))


# ---- content store ------------------------------------------------------
def test_content_store_unavailable_without_persistence():
    # tests/conftest.py pins RAG_PERSISTENCE=off.
    assert DocumentContentStore().available() is False


def test_content_store_operations_degrade_quietly():
    store = DocumentContentStore()
    assert store.save("doc1", "some text", tenant_id="t1") is False
    assert store.get("doc1") is None
    assert store.delete("doc1") is False


def test_content_store_rejects_empty_text():
    assert DocumentContentStore().save("doc1", "") is False
