from enum import Enum
from typing import Any
from parsing.parsed_document import ParsedDocument

class DocumentCategory(str, Enum):
    ENGINEERING_DOC = "engineering_doc"
    MEETING_NOTES = "meeting_notes"
    CUSTOMER_EMAIL = "customer_email"
    CHAT_CONVERSATION = "chat_conversation"
    SUPPORT_TICKET = "support_ticket"
    GENERAL_DOC = "general_doc"

class CategoryRouter:
    """Config-driven category router for classifying parsed documents."""

    def route_document(self, document: ParsedDocument) -> DocumentCategory:
        source = document.source.lower()
        text_lower = document.text_content.lower()
        mime = document.mime_type.lower()

        if source == "gmail" or "email" in mime:
            return DocumentCategory.CUSTOMER_EMAIL
        elif source == "slack" or "chat" in mime:
            return DocumentCategory.CHAT_CONVERSATION
        elif source == "notion" or "meeting" in text_lower or "agenda" in text_lower:
            return DocumentCategory.MEETING_NOTES
        elif any(k in text_lower for k in ["architecture", "api", "code", "def ", "class ", "git", "function"]):
            return DocumentCategory.ENGINEERING_DOC
        elif "ticket" in text_lower or "issue" in text_lower:
            return DocumentCategory.SUPPORT_TICKET
        else:
            return DocumentCategory.GENERAL_DOC
