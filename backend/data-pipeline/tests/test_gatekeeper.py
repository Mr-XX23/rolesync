from datetime import datetime, timezone
from parsing.parsed_document import ParsedDocument
from gatekeeper.category_router import CategoryRouter, DocumentCategory
from gatekeeper.lexical_checker import LexicalChecker
from gatekeeper.audit_logger import GatekeeperAuditLogger
from gatekeeper.rejected_store import RejectedStore
from gatekeeper.quarantine_queue import QuarantineQueue
from gatekeeper.gatekeeper_engine import GatekeeperEngine

def test_category_router():
    router = CategoryRouter()
    
    doc_email = ParsedDocument(
        doc_id="tenant_a:gmail:1", tenant_id="tenant_a", user_id="u1", source="gmail",
        external_id="1", acl=["u1"], mime_type="text/plain", text_content="Email text",
    )
    assert router.route_document(doc_email) == DocumentCategory.CUSTOMER_EMAIL

    doc_eng = ParsedDocument(
        doc_id="tenant_a:gdrive:2", tenant_id="tenant_a", user_id="u1", source="gdrive",
        external_id="2", acl=["u1"], mime_type="text/plain", text_content="# API Architecture\nclass Service:\n  def run(): pass",
    )
    assert router.route_document(doc_eng) == DocumentCategory.ENGINEERING_DOC

def test_lexical_checker_clean():
    checker = LexicalChecker()
    doc = ParsedDocument(
        doc_id="tenant_a:gdrive:clean", tenant_id="tenant_a", user_id="u1", source="gdrive",
        external_id="clean", acl=["u1"], mime_type="text/plain",
        text_content="This is a clean engineering document with multiple distinct sentences and rich technical vocabulary.",
    )
    res = checker.check(doc)
    assert res.is_valid is True
    assert res.entropy > 0.0

def test_lexical_checker_gibberish():
    checker = LexicalChecker()
    doc_short = ParsedDocument(
        doc_id="tenant_a:gdrive:short", tenant_id="tenant_a", user_id="u1", source="gdrive",
        external_id="short", acl=["u1"], mime_type="text/plain", text_content="short",
    )
    res = checker.check(doc_short)
    assert res.is_valid is False
    assert "below minimum threshold" in res.reason

    doc_repetitive = ParsedDocument(
        doc_id="tenant_a:gdrive:rep", tenant_id="tenant_a", user_id="u1", source="gdrive",
        external_id="rep", acl=["u1"], mime_type="text/plain",
        text_content="aaaaa aaaaa aaaaa aaaaa aaaaa aaaaa aaaaa aaaaa aaaaa aaaaa aaaaa aaaaa aaaaa aaaaa aaaaa aaaaa",
    )
    res_rep = checker.check(doc_repetitive)
    assert res_rep.is_valid is False
    assert "repetitive noise" in res_rep.reason

def test_gatekeeper_engine():
    engine = GatekeeperEngine()
    doc_clean = ParsedDocument(
        doc_id="tenant_a:gdrive:clean_doc", tenant_id="tenant_a", user_id="u1", source="gdrive",
        external_id="clean_doc", acl=["u1"], mime_type="text/plain",
        text_content="# Meeting Notes\nDiscussion about the Q4 product roadmap and API integration timeline.",
    )
    decision = engine.evaluate_document(doc_clean)
    assert decision.decision == "ACCEPTED"
    assert decision.category == DocumentCategory.MEETING_NOTES
    logs = engine.audit_logger.get_logs_for_doc("tenant_a:gdrive:clean_doc")
    assert len(logs) == 1
    assert logs[0].decision == "ACCEPTED"
