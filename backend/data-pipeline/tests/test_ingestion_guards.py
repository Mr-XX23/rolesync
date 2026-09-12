"""Guards that every ingestion path must enforce: type, size, malware/DLP and quality.

These pin the behaviour that manual uploads and connector events are held to the
same policy, and that rejection messages stay generic (no internal detail leaks
to an end user).
"""
import pytest

from module_1_document_processing.parsing.parsed_document import ParsedDocument
from module_1_document_processing.pipeline import ingestion_guards as guards
from module_2_memory_gatekeeper.category_router import DocumentCategory
from module_2_memory_gatekeeper.gatekeeper_engine import GatekeeperDecision


def _doc(text: str) -> ParsedDocument:
    return ParsedDocument(
        doc_id="tenant_a:upload:d1", tenant_id="tenant_a", user_id="u1", source="upload",
        external_id="d1", acl=["u1"], mime_type="text/plain", text_content=text,
    )


def test_validate_upload_accepts_supported_types():
    assert guards.validate_upload("deck.PPTX", 1024) == "PPTX"
    assert guards.validate_upload("notes.md", 10) == "MD"
    assert guards.validate_upload("sheet.xlsx", 2048) == "XLSX"


def test_validate_upload_rejects_unsupported_type():
    with pytest.raises(guards.IngestionRejected) as err:
        guards.validate_upload("payload.exe", 1024)
    assert err.value.code == "UNSUPPORTED_TYPE"
    assert "not supported" in err.value.message.lower()


def test_validate_upload_rejects_extensionless_file():
    with pytest.raises(guards.IngestionRejected) as err:
        guards.validate_upload("README", 512)
    assert err.value.code == "UNSUPPORTED_TYPE"


def test_validate_upload_rejects_empty_file():
    with pytest.raises(guards.IngestionRejected) as err:
        guards.validate_upload("empty.pdf", 0)
    assert err.value.code == "EMPTY_FILE"


def test_validate_upload_rejects_oversized_file():
    with pytest.raises(guards.IngestionRejected) as err:
        guards.validate_upload("huge.pdf", guards.MAX_UPLOAD_BYTES + 1)
    assert err.value.code == "FILE_TOO_LARGE"
    assert err.value.status_code == 413


def test_scan_content_rejects_empty_payload():
    with pytest.raises(guards.IngestionRejected) as err:
        guards.scan_content(b"", "empty.pdf")
    assert err.value.code == "EMPTY_FILE"


def test_scan_content_rejects_oversized_payload():
    with pytest.raises(guards.IngestionRejected) as err:
        guards.scan_content(b"x" * (guards.MAX_UPLOAD_BYTES + 1), "huge.pdf")
    assert err.value.code == "UNSAFE_CONTENT"
    # The size/virus detail is logged, never surfaced to the caller.
    assert "bytes" not in err.value.message.lower()


def test_scan_content_allows_clean_payload():
    guards.scan_content(b"A clean sales battlecard with competitive positioning.", "ok.txt")


def test_gatekeeper_accepts_substantive_document():
    text = (
        "Our Q3 pricing covers enterprise licensing tiers, discount guardrails and "
        "renewal terms for strategic accounts across regulated industries. "
    ) * 3
    assert guards.evaluate_gatekeeper(_doc(text)).decision == "ACCEPTED"


def test_gatekeeper_rejects_unusable_document():
    assert guards.evaluate_gatekeeper(_doc("short")).decision != "ACCEPTED"


def test_gatekeeper_message_is_generic_and_leaks_no_internals():
    decision = GatekeeperDecision(
        doc_id="d1",
        category=DocumentCategory.GENERAL_DOC,
        decision="REJECTED_LEXICAL",
        reason="Shannon entropy 1.24 below threshold 2.50",
        document=_doc("short"),
    )
    message = guards.gatekeeper_message(decision)
    assert "Knowledge Vault" in message
    for leaked in ("entropy", "threshold", "1.24", "lexical"):
        assert leaked not in message.lower()
