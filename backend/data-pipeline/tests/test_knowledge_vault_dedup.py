import unittest

from module_1_document_processing.knowledge_vault_routes import (
    plan_deduplication,
    _is_healthy_doc,
    _dedup_group_key,
)


def _doc(doc_id, *, name="RoleSync Business Plan.pdf", size=2_000_000, dtype="PDF",
         chunks=17, status="Indexed", content_hash=None, created_at="2026-09-12T10:00:00+00:00"):
    return {
        "doc_id": doc_id,
        "name": name,
        "size_bytes": size,
        "type": dtype,
        "chunks": chunks,
        "status": status,
        "content_hash": content_hash,
        "created_at": created_at,
    }


class TestDeduplicationPlan(unittest.TestCase):
    def test_no_duplicates_returns_empty_plan(self):
        docs = [
            _doc("doc_a", content_hash="hash_a"),
            _doc("doc_b", name="Other.pdf", content_hash="hash_b"),
        ]
        self.assertEqual(plan_deduplication(docs), [])

    def test_identical_content_hash_is_grouped(self):
        docs = [
            _doc("doc_1", chunks=17, content_hash="same", created_at="2026-09-12T02:14:00+00:00"),
            _doc("doc_2", chunks=0, status="Indexed", content_hash="same", created_at="2026-09-12T03:32:00+00:00"),
            _doc("doc_3", chunks=17, content_hash="same", created_at="2026-09-12T04:07:00+00:00"),
        ]
        plan = plan_deduplication(docs)
        self.assertEqual(len(plan), 1)
        group = plan[0]
        # Keeper: indexed + most chunks + newest of the 17-chunk copies -> doc_3
        self.assertEqual(group["kept_doc_id"], "doc_3")
        removed_ids = {r["doc_id"] for r in group["removed"]}
        self.assertEqual(removed_ids, {"doc_1", "doc_2"})

    def test_legacy_rows_without_hash_group_by_name_size_type(self):
        # Pre-hash rows: same name + size + type must still be recognised as duplicates.
        docs = [
            _doc("doc_1", content_hash=None, chunks=17),
            _doc("doc_2", content_hash=None, chunks=17),
            _doc("doc_3", content_hash=None, chunks=17),
        ]
        plan = plan_deduplication(docs)
        self.assertEqual(len(plan), 1)
        self.assertEqual(len(plan[0]["removed"]), 2)

    def test_different_size_is_not_a_duplicate(self):
        docs = [
            _doc("doc_1", content_hash=None, size=2_000_000),
            _doc("doc_2", content_hash=None, size=2_000_001),
        ]
        self.assertEqual(plan_deduplication(docs), [])

    def test_keeper_prefers_indexed_over_errored_empty_copy(self):
        docs = [
            _doc("doc_err", chunks=0, status="Error", content_hash="same"),
            _doc("doc_ok", chunks=9, status="Indexed", content_hash="same"),
        ]
        plan = plan_deduplication(docs)
        self.assertEqual(plan[0]["kept_doc_id"], "doc_ok")
        self.assertEqual(plan[0]["removed"][0]["doc_id"], "doc_err")

    def test_hash_and_legacy_keys_do_not_collide(self):
        key_hash = _dedup_group_key(_doc("d1", content_hash="abc"))
        key_legacy = _dedup_group_key(_doc("d2", content_hash=None))
        self.assertTrue(key_hash.startswith("hash::"))
        self.assertTrue(key_legacy.startswith("legacy::"))
        self.assertNotEqual(key_hash, key_legacy)

    def test_is_healthy_doc(self):
        self.assertTrue(_is_healthy_doc({"status": "Indexed", "chunks": 5}))
        self.assertFalse(_is_healthy_doc({"status": "Indexed", "chunks": 0}))
        self.assertFalse(_is_healthy_doc({"status": "Error", "chunks": 5}))
        self.assertFalse(_is_healthy_doc({"status": "Parsing", "chunks": 0}))


if __name__ == "__main__":
    unittest.main()
