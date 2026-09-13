"""Chunking has to honour the settings it is given.

`chunk_overlap` was accepted, stored and never used: chunks never overlapped, so
a sentence spanning a boundary was split and neither chunk carried the whole
thought - while the workspace's `overlap` setting looked like it did something.
A paragraph longer than `chunk_size` was also never split, which matters because
the embeddings call truncates its input, so text past that limit was stored but
never represented in any vector. And the two ingestion paths resolved settings
separately, so the same workspace chunked differently depending on how a document
arrived.
"""
import pytest

from module_1_document_processing.parsing.parsed_document import ParsedDocument
from module_3_batch_ingestion_vector import chunk_config as cc
from module_3_batch_ingestion_vector.chunk_config import ChunkConfig, resolve_chunk_config
from module_3_batch_ingestion_vector.chunker import HierarchicalChunker

TENANT = "tenant_a"


@pytest.fixture(autouse=True)
def no_registered_reader():
    """Each test starts with no workspace config reader registered."""
    cc.set_config_reader(None)
    yield
    cc.set_config_reader(None)


def doc(text: str, tenant_id: str = TENANT, user_id: str = "u1") -> ParsedDocument:
    return ParsedDocument(
        doc_id=f"{tenant_id}:USER_UPLOAD:doc_1", tenant_id=tenant_id, user_id=user_id,
        source="USER_UPLOAD", external_id="doc_1", acl=["user:u1"],
        mime_type="text/plain", text_content=text,
    )


def words(count: int, start: int = 0) -> str:
    return " ".join(f"w{i:04d}" for i in range(start, start + count))


# --- overlap actually happens --------------------------------------------
def test_consecutive_chunks_share_text():
    """The whole point: context must span a boundary."""
    paragraphs = "\n\n".join(words(12, start=i * 12) for i in range(6))
    nodes = HierarchicalChunker(chunk_size=120, chunk_overlap=30).chunk_document(doc(paragraphs))

    assert len(nodes) > 1
    for previous, following in zip(nodes, nodes[1:]):
        shared = following.text[:30].strip().split()
        assert shared, "later chunks must carry text forward"
        assert shared[0] in previous.text, f"no overlap between chunks: {following.text[:40]!r}"


def test_zero_overlap_shares_nothing():
    paragraphs = "\n\n".join(words(12, start=i * 12) for i in range(6))
    nodes = HierarchicalChunker(chunk_size=120, chunk_overlap=0).chunk_document(doc(paragraphs))

    assert len(nodes) > 1
    for previous, following in zip(nodes, nodes[1:]):
        assert not set(previous.text.split()) & set(following.text.split())


def test_overlap_starts_on_a_word_boundary():
    """Carried text must read as language, not begin mid-word."""
    paragraphs = "\n\n".join(words(12, start=i * 12) for i in range(5))
    nodes = HierarchicalChunker(chunk_size=120, chunk_overlap=25).chunk_document(doc(paragraphs))

    for node in nodes[1:]:
        first = node.text.split()[0]
        assert first.startswith("w") and len(first) == 5, f"truncated word carried over: {first!r}"


def test_the_first_chunk_carries_nothing_extra():
    paragraphs = "\n\n".join(words(12, start=i * 12) for i in range(4))
    plain = HierarchicalChunker(chunk_size=120, chunk_overlap=0).chunk_document(doc(paragraphs))
    lapped = HierarchicalChunker(chunk_size=120, chunk_overlap=30).chunk_document(doc(paragraphs))

    assert plain[0].text == lapped[0].text


def test_overlap_changes_the_hashes_so_a_reindex_re_embeds():
    paragraphs = "\n\n".join(words(12, start=i * 12) for i in range(4))
    plain = HierarchicalChunker(chunk_size=120, chunk_overlap=0).chunk_document(doc(paragraphs))
    lapped = HierarchicalChunker(chunk_size=120, chunk_overlap=30).chunk_document(doc(paragraphs))

    assert [n.chunk_hash for n in plain][1:] != [n.chunk_hash for n in lapped][1:]


# --- no chunk is silently truncated later --------------------------------
def test_an_oversized_paragraph_is_split():
    """One long paragraph used to become one oversized chunk, and the embeddings
    call truncates its input - so the tail was never represented in a vector."""
    nodes = HierarchicalChunker(chunk_size=200, chunk_overlap=0).chunk_document(doc(words(400)))

    assert len(nodes) > 1
    assert all(len(n.text) <= 200 for n in nodes), [len(n.text) for n in nodes]


def test_splitting_a_long_paragraph_keeps_every_word():
    text = words(300)
    nodes = HierarchicalChunker(chunk_size=180, chunk_overlap=0).chunk_document(doc(text))

    recovered = " ".join(n.text for n in nodes).split()
    assert recovered == text.split()


def test_a_single_enormous_token_still_splits():
    nodes = HierarchicalChunker(chunk_size=50, chunk_overlap=0).chunk_document(doc("x" * 260))

    assert len(nodes) == 6  # hard cut, since there is no word boundary to use
    assert "".join(n.text for n in nodes) == "x" * 260


def test_chunks_stay_bounded_even_with_overlap():
    nodes = HierarchicalChunker(chunk_size=150, chunk_overlap=40).chunk_document(doc(words(500)))

    # Overlap adds to a chunk by design, but never unboundedly.
    assert all(len(n.text) <= 150 + 40 + 1 for n in nodes), [len(n.text) for n in nodes]


def test_overlap_is_never_allowed_to_stall_chunking():
    """Overlap at or above the chunk size would stop the window advancing."""
    nodes = HierarchicalChunker(chunk_size=100, chunk_overlap=500).chunk_document(doc(words(200)))

    assert len(nodes) > 1
    assert all(n.text for n in nodes)


# --- resolution is shared -------------------------------------------------
def test_settings_come_from_the_workspace_config():
    cc.set_config_reader(lambda tenant, user: {"chunk_size": 300, "overlap": 10})

    config = HierarchicalChunker().config_for(doc("text"))

    assert config.chunk_size == 300
    assert config.chunk_overlap == 30


def test_both_ingestion_paths_resolve_the_same_settings():
    """An upload and a connector document must chunk identically."""
    cc.set_config_reader(lambda tenant, user: {"chunk_size": 256, "overlap": 20})
    text = "\n\n".join(words(20, start=i * 20) for i in range(8))

    upload = HierarchicalChunker().chunk_document(doc(text))
    connector = HierarchicalChunker().chunk_document(
        ParsedDocument(
            doc_id=f"{TENANT}:gdrive:file_9", tenant_id=TENANT, user_id="u1", source="gdrive",
            external_id="file_9", acl=["user:u1"], mime_type="text/plain", text_content=text,
        )
    )

    assert [n.text for n in upload] == [n.text for n in connector]


def test_explicit_settings_win_over_the_workspace_config():
    cc.set_config_reader(lambda tenant, user: {"chunk_size": 2048, "overlap": 30})

    config = HierarchicalChunker(chunk_size=150, chunk_overlap=15).config_for(doc("text"))

    assert (config.chunk_size, config.chunk_overlap) == (150, 15)


def test_a_broken_config_reader_falls_back_to_defaults():
    def explode(tenant, user):
        raise RuntimeError("mongo is down")

    cc.set_config_reader(explode)

    assert resolve_chunk_config(TENANT, "u1") == cc.default_chunk_config()


def test_stored_settings_are_clamped_to_supported_bounds():
    cc.set_config_reader(lambda tenant, user: {"chunk_size": 99999, "overlap": 90})

    config = resolve_chunk_config(TENANT, "u1")

    assert config.chunk_size == cc.MAX_CHUNK_SIZE
    assert config.chunk_overlap == cc.MAX_CHUNK_SIZE * cc.MAX_OVERLAP_PERCENT // 100


def test_defaults_come_from_the_environment(monkeypatch):
    monkeypatch.setenv("CHUNK_SIZE", "400")
    monkeypatch.setenv("CHUNK_OVERLAP_PERCENT", "25")

    assert cc.default_chunk_config() == ChunkConfig(chunk_size=400, chunk_overlap=100)


def test_stride_always_advances():
    assert ChunkConfig(chunk_size=100, chunk_overlap=100).stride == 1
    assert ChunkConfig(chunk_size=100, chunk_overlap=20).stride == 80


# --- unchanged guarantees -------------------------------------------------
def test_empty_text_produces_nothing():
    assert HierarchicalChunker(chunk_size=100, chunk_overlap=10).chunk_document(doc("   ")) == []


def test_nodes_stay_linked_and_carry_acl():
    paragraphs = "\n\n".join(words(12, start=i * 12) for i in range(4))
    nodes = HierarchicalChunker(chunk_size=120, chunk_overlap=20).chunk_document(doc(paragraphs))

    assert nodes[0].prev_chunk_id is None
    assert nodes[-1].next_chunk_id is None
    for idx, node in enumerate(nodes):
        assert node.chunk_index == idx
        assert node.total_chunks == len(nodes)
        assert node.acl == ["user:u1"]
    for previous, following in zip(nodes, nodes[1:]):
        assert previous.next_chunk_id == following.chunk_id
        assert following.prev_chunk_id == previous.chunk_id
