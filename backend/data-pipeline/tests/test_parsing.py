from datetime import datetime, timezone
from module_1_document_processing.composio_connector.events.canonical_event import CanonicalEvent, EventType
from module_1_document_processing.parsing.mime_router import MIMERouter, ParserCategory
from module_1_document_processing.parsing.direct_text_parser import DirectTextParser
from module_1_document_processing.parsing.llama_parser import LlamaParserService
from module_1_document_processing.parsing.parse_failure_store import ParseFailureStore
from module_1_document_processing.parsing.parser_service import ParserService

def test_mime_router():
    router = MIMERouter()
    assert router.route("text/plain") == ParserCategory.LOCAL_TEXT
    assert router.route("application/pdf") == ParserCategory.LLAMA_DOCUMENT
    assert router.route("application/vnd.openxmlformats-officedocument.wordprocessingml.document") == ParserCategory.LLAMA_DOCUMENT
    assert router.route("image/png") == ParserCategory.LLAMA_IMAGE
    assert router.route("audio/mpeg") == ParserCategory.AUDIO
    assert router.route(file_path="report.docx") == ParserCategory.LLAMA_DOCUMENT
    assert router.route(file_path="script.py") == ParserCategory.LOCAL_TEXT
    assert router.route("application/unknown-binary") == ParserCategory.UNSUPPORTED

def test_direct_text_parser():
    parser = DirectTextParser()
    event = CanonicalEvent(
        event_id="evt_txt_01",
        event_type=EventType.CREATE,
        source="gmail",
        tenant_id="tenant_alpha",
        user_id="usr_01",
        external_id="msg_01",
        raw_ref={},
        acl=["usr_01@example.com"],
        timestamp=datetime.now(timezone.utc),
        metadata={"subject": "Project Status", "text": "All services operating normally.", "mime_type": "text/plain"},
    )
    parsed = parser.parse(event)
    assert parsed.doc_id == "tenant_alpha:gmail:msg_01"
    assert "# Project Status" in parsed.text_content
    assert "All services operating normally." in parsed.text_content
    assert parsed.parser_used == "local_text"

def test_llama_parser_fallback():
    service = LlamaParserService()
    event = CanonicalEvent(
        event_id="evt_pdf_01",
        event_type=EventType.CREATE,
        source="gdrive",
        tenant_id="tenant_alpha",
        user_id="usr_02",
        external_id="file_pdf_99",
        raw_ref={},
        acl=["usr_02@example.com"],
        timestamp=datetime.now(timezone.utc),
        metadata={"name": "Q3_Report.pdf", "mime_type": "application/pdf"},
    )
    parsed = service.parse(event)
    assert parsed.doc_id == "tenant_alpha:gdrive:file_pdf_99"
    assert parsed.parse_status == "SUCCESS"
    assert parsed.parser_used in ("llama_parse", "fallback_local")

def test_parse_failure_store():
    store = ParseFailureStore()
    record = store.record_failure(
        doc_id="tenant_alpha:gdrive:bad_01",
        tenant_id="tenant_alpha",
        user_id="usr_03",
        source="gdrive",
        external_id="bad_01",
        reason="Password-protected PDF",
        mime_type="application/pdf",
    )
    assert record.doc_id == "tenant_alpha:gdrive:bad_01"
    assert record.reason == "Password-protected PDF"
    assert store.get_failure("tenant_alpha:gdrive:bad_01") is not None

def test_parser_service_unsupported():
    service = ParserService()
    event = CanonicalEvent(
        event_id="evt_bin_01",
        event_type=EventType.CREATE,
        source="gdrive",
        tenant_id="tenant_alpha",
        user_id="usr_04",
        external_id="bin_01",
        raw_ref={},
        acl=["usr_04@example.com"],
        timestamp=datetime.now(timezone.utc),
        metadata={"name": "unknown.xyz", "mime_type": "application/unknown-binary"},
    )
    parsed = service.parse_event(event)
    assert parsed.parse_status == "FAILED"
    assert parsed.parser_used == "unsupported"
    failure = service.failure_store.get_failure("tenant_alpha:gdrive:bin_01")
    assert failure is not None
