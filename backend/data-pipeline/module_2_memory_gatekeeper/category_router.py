from enum import Enum
from typing import Any
from module_1_document_processing.parsing.parsed_document import ParsedDocument

class DocumentCategory(str, Enum):
    ENGINEERING_DOC = "engineering_doc"
    MEETING_NOTES = "meeting_notes"
    CUSTOMER_EMAIL = "customer_email"
    CHAT_CONVERSATION = "chat_conversation"
    SUPPORT_TICKET = "support_ticket"
    FINANCIAL_RECORD = "financial_record"
    LEGAL_CONTRACT = "legal_contract"
    GENERAL_DOC = "general_doc"

class CategoryRouter:
    """Category Router assigning memory categories to documents based on metadata, mime_type, and text heuristics."""

    def route_document(self, document: ParsedDocument) -> DocumentCategory:
        mime = (document.mime_type or "").lower()
        source = (document.source or "").lower()
        text = (document.text_content or "").lower()

        if source == "gmail" or "email" in mime or "mail" in source:
            return DocumentCategory.CUSTOMER_EMAIL
        elif source == "slack" or "chat" in mime:
            return DocumentCategory.CHAT_CONVERSATION
        elif source in ("google_calendar", "calendar") or "meeting" in text:
            return DocumentCategory.MEETING_NOTES
        elif "ticket" in text or "support" in text:
            return DocumentCategory.SUPPORT_TICKET
        elif "code" in mime or "github" in source or "repo" in text or "architecture" in text or "api" in text:
            return DocumentCategory.ENGINEERING_DOC
        elif "contract" in text or "agreement" in text:
            return DocumentCategory.LEGAL_CONTRACT
        elif "invoice" in text or "financial" in text:
            return DocumentCategory.FINANCIAL_RECORD

        return DocumentCategory.GENERAL_DOC
