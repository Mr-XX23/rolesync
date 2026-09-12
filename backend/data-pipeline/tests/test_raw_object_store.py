"""Raw object store: local backend round trips, key safety and graceful failure.

These run against the local backend so they need no MinIO/S3 service. The S3
path is covered by the live container check.
"""
from module_1_document_processing.raw_object_store import RawObjectStore


def _store(tmp_path):
    return RawObjectStore(backend="local", storage_dir=str(tmp_path))


def test_put_and_get_round_trip(tmp_path):
    store = _store(tmp_path)
    ref = store.put("tenant_a/doc_1_report.pdf", b"hello world", "application/pdf")
    assert ref
    assert store.get(ref) == b"hello world"


def test_put_creates_nested_tenant_path(tmp_path):
    store = _store(tmp_path)
    ref = store.put("tenant_b/nested/doc_2.txt", b"data")
    assert ref and "tenant_b" in ref
    assert store.get(ref) == b"data"


def test_put_rejects_empty_payload(tmp_path):
    assert _store(tmp_path).put("tenant_a/empty.txt", b"") is None


def test_delete_removes_object(tmp_path):
    store = _store(tmp_path)
    ref = store.put("tenant_a/gone.txt", b"bye")
    assert store.delete(ref) is True
    assert store.get(ref) is None


def test_get_missing_reference_returns_none(tmp_path):
    store = _store(tmp_path)
    assert store.get("") is None
    assert store.get(str(tmp_path / "nope.bin")) is None


def test_key_traversal_is_neutralised(tmp_path):
    store = _store(tmp_path)
    ref = store.put("../../etc/passwd", b"nope")
    assert ref is not None
    # The written file must stay inside the configured storage directory.
    assert str(tmp_path) in ref
    assert "etc/passwd" in ref.replace("\\", "/")


def test_s3_reference_without_client_fails_soft(tmp_path):
    """A stale s3:// ref on a local-backend store must not raise."""
    store = _store(tmp_path)
    assert store.get("s3://some-bucket/some/key") is None
    assert store.delete("s3://some-bucket/some/key") is False


def test_local_backend_is_always_available(tmp_path):
    assert _store(tmp_path).available() is True
