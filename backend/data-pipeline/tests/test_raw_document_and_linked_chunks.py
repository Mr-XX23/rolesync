import os
from module_1_document_processing.raw_document_store import RawDocumentStore
from module_1_document_processing.parsing.parsed_document import ParsedDocument
from module_3_batch_ingestion_vector.chunker import HierarchicalChunker, TextNode
from module_3_batch_ingestion_vector.vector_store import VectorRecord, VectorStore

def test_raw_document_store_in_memory():
    """Verifies that RawDocumentStore stores and returns full text unfragmented."""
    store = RawDocumentStore(mongo_uri="")  # Force local/in-memory mode
    
    full_text = "# Q3 Battlecard: Salesforce vs RoleSync\n\n## Pricing\nRoleSync is 40% more cost-effective.\n\n## Features\nAutonomous AI sales execution."
    raw_bytes = full_text.encode("utf-8")
    
    saved = store.save_raw_document(
        doc_ref_id="doc_test_101",
        tenant_id="tenant_alpha",
        user_id="usr_01",
        filename="salesforce_battlecard.md",
        mime_type="text/markdown",
        full_text_content=full_text,
        raw_bytes=raw_bytes,
        category="BATTLECARD",
        document_type="BATTLECARD",
        target_competitor="Salesforce",
        target_industry="SaaS",
        sales_summary="Comprehensive battlecard against Salesforce CRM.",
        sales_tags=["Salesforce", "Battlecard", "Pricing"],
    )
    
    assert saved["doc_ref_id"] == "doc_test_101"
    assert saved["category"] == "BATTLECARD"
    assert saved["target_competitor"] == "Salesforce"
    assert saved["word_count"] > 10
    
    # Retrieve
    retrieved = store.get_raw_document("doc_test_101")
    assert retrieved is not None
    assert retrieved["full_text_content"] == full_text
    
    # Check full text helper
    assert store.get_full_text("doc_test_101") == full_text
    
    # Update chunks count
    store.update_chunks("doc_test_101", total_chunks=3, chunk_ids=["c0", "c1", "c2"])
    updated = store.get_raw_document("doc_test_101")
    assert updated["total_chunks"] == 3
    assert updated["chunk_ids"] == ["c0", "c1", "c2"]

def test_bidirectional_chunk_linking():
    """Verifies that HierarchicalChunker links chunks with prev_chunk_id, next_chunk_id, and doc_ref_id."""
    chunker = HierarchicalChunker(chunk_size=50, chunk_overlap=0)
    
    doc = ParsedDocument(
        doc_id="tenant_1:USER_UPLOAD:doc_abc",
        tenant_id="tenant_1",
        user_id="usr_1",
        source="USER_UPLOAD",
        external_id="doc_abc",
        acl=["user:usr_1"],
        mime_type="text/markdown",
        text_content="Paragraph 1 with enough text to make a chunk.\n\nParagraph 2 with second chunk content.\n\nParagraph 3 with third chunk content.",
        metadata={
            "category": "PRICING",
            "document_type": "PRICING",
            "target_competitor": "CompetitorX",
        }
    )
    
    nodes = chunker.chunk_document(doc)
    assert len(nodes) >= 3
    
    # Chunk 0: first in chain
    assert nodes[0].chunk_index == 0
    assert nodes[0].prev_chunk_id is None
    assert nodes[0].next_chunk_id == nodes[1].chunk_id
    assert nodes[0].doc_ref_id == "doc_abc"
    assert nodes[0].metadata["doc_ref_id"] == "doc_abc"
    assert nodes[0].metadata["category"] == "PRICING"
    assert nodes[0].metadata["target_competitor"] == "CompetitorX"
    
    # Chunk 1: middle in chain
    assert nodes[1].chunk_index == 1
    assert nodes[1].prev_chunk_id == nodes[0].chunk_id
    assert nodes[1].next_chunk_id == nodes[2].chunk_id
    assert nodes[1].doc_ref_id == "doc_abc"
    assert nodes[1].metadata["prev_chunk_id"] == nodes[0].chunk_id
    assert nodes[1].metadata["next_chunk_id"] == nodes[2].chunk_id
    
    # Last chunk: end of chain
    last_idx = len(nodes) - 1
    assert nodes[last_idx].chunk_index == last_idx
    assert nodes[last_idx].prev_chunk_id == nodes[last_idx - 1].chunk_id
    assert nodes[last_idx].next_chunk_id is None
    assert nodes[last_idx].metadata["next_chunk_id"] is None

def test_vector_record_serialization():
    """Verifies that VectorRecord correctly handles doc_ref_id, prev_chunk_id, and next_chunk_id."""
    rec = VectorRecord(
        vector_id="c_1",
        doc_id="doc_full_99",
        doc_ref_id="doc_ref_99",
        tenant_id="tenant_1",
        user_id="usr_1",
        source="USER_UPLOAD",
        external_id="doc_ref_99",
        text="Sample text content for vector chunk",
        vector=[0.1, 0.2, 0.3],
        acl=["tenant_1"],
        chunk_index=1,
        prev_chunk_id="c_0",
        next_chunk_id="c_2",
        total_chunks=3,
        metadata={"category": "CASE_STUDY", "doc_ref_id": "doc_ref_99"},
    )
    
    d = rec.to_dict()
    assert d["doc_ref_id"] == "doc_ref_99"
    assert d["prev_chunk_id"] == "c_0"
    assert d["next_chunk_id"] == "c_2"
    assert d["total_chunks"] == 3
    assert d["metadata"]["category"] == "CASE_STUDY"
    
    # From dict deserialization
    rec2 = VectorRecord.from_dict(d)
    assert rec2.doc_ref_id == "doc_ref_99"
    assert rec2.prev_chunk_id == "c_0"
    assert rec2.next_chunk_id == "c_2"
    assert rec2.total_chunks == 3
    assert rec2.metadata["category"] == "CASE_STUDY"
