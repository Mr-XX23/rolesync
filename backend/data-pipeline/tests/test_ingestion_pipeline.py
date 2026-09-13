from datetime import datetime, timezone
from module_1_document_processing.parsing.parsed_document import ParsedDocument
from module_3_batch_ingestion_vector.chunker import HierarchicalChunker
from module_3_batch_ingestion_vector.delta_checker import DeltaChecker, VersionedHashDB
from module_3_batch_ingestion_vector.embedding_worker import EmbeddingWorker
from module_3_batch_ingestion_vector.vector_store import VectorStore
from module_3_batch_ingestion_vector.bulk_writer import BulkWriter
from module_3_batch_ingestion_vector.checkpoint_store import CheckpointStore
from module_3_batch_ingestion_vector.ingestion_pipeline import BatchIngestionPipeline

def test_hierarchical_chunker():
    chunker = HierarchicalChunker(chunk_size=100, chunk_overlap=10)
    doc = ParsedDocument(
        doc_id="tenant_x:gdrive:doc_100", tenant_id="tenant_x", user_id="u1", source="gdrive",
        external_id="doc_100", acl=["u1@example.com", "u2@example.com"], mime_type="text/plain",
        text_content="This is a test document that contains multiple sentences to be split into chunks with full metadata attached.",
    )
    nodes = chunker.chunk_document(doc)
    assert len(nodes) >= 1
    assert nodes[0].doc_id == "tenant_x:gdrive:doc_100"
    assert "u2@example.com" in nodes[0].acl

def test_delta_checker():
    hash_db = VersionedHashDB()
    delta_checker = DeltaChecker(hash_db)
    chunker = HierarchicalChunker(chunk_size=100, chunk_overlap=10)
    doc = ParsedDocument(
        doc_id="tenant_x:gdrive:doc_101", tenant_id="tenant_x", user_id="u1", source="gdrive",
        external_id="doc_101", acl=["u1"], mime_type="text/plain", text_content="Document text content for delta hashing test.",
    )
    nodes = chunker.chunk_document(doc)
    
    # 1. First run -> Chunks are new
    new_nodes, unchanged_nodes = delta_checker.filter_changed_chunks(nodes)
    assert len(new_nodes) == len(nodes)
    assert len(unchanged_nodes) == 0

    # Commit hashes
    delta_checker.commit_chunk_hashes(nodes)

    # 2. Second run with same content -> Chunks are skipped as unchanged
    new_nodes_2, unchanged_nodes_2 = delta_checker.filter_changed_chunks(nodes)
    assert len(new_nodes_2) == 0
    assert len(unchanged_nodes_2) == len(nodes)

def test_vector_store_acl_filtering():
    vstore = VectorStore()
    chunker = HierarchicalChunker(chunk_size=100)
    doc = ParsedDocument(
        doc_id="tenant_x:slack:channel_01", tenant_id="tenant_x", user_id="u1", source="slack",
        external_id="channel_01", acl=["user_authorized"], mime_type="text/plain", text_content="Restricted channel message.",
    )
    nodes = chunker.chunk_document(doc)
    embedder = EmbeddingWorker()
    embedded = embedder.generate_embeddings(nodes)
    vstore.upsert_vectors(embedded)

    # Search with authorized ACL -> Found
    results_auth = vstore.search_similarity(query_vector=[0.0]*1536, tenant_id="tenant_x", user_acl=["user_authorized"])
    assert len(results_auth) == 1

    # Search with unauthorized ACL -> Empty (Filtered out by security ACL)
    results_unauth = vstore.search_similarity(query_vector=[0.0]*1536, tenant_id="tenant_x", user_acl=["user_unauthorized"])
    assert len(results_unauth) == 0

def test_batch_ingestion_pipeline():
    pipeline = BatchIngestionPipeline()
    doc = ParsedDocument(
        doc_id="tenant_x:notion:page_55", tenant_id="tenant_x", user_id="u1", source="notion",
        external_id="page_55", acl=["u1@example.com"], mime_type="text/plain",
        text_content="# Architecture Document\nFull architectural specification for enterprise RAG ingestion pipeline.",
    )
    written_count = pipeline.process_accepted_document(doc)
    assert written_count >= 1
    
    # Check checkpoint status
    chk = pipeline.checkpoint_store.get_checkpoint("batch_tenant_x:notion:page_55")
    assert chk is not None
    assert chk.status == "DONE"
