from module_1_document_processing.composio_connector.events.canonical_event import CanonicalEvent
from module_1_document_processing.parsing.mime_router import MIMERouter, ParserCategory
from module_1_document_processing.parsing.parsed_document import ParsedDocument
from module_1_document_processing.parsing.direct_text_parser import DirectTextParser
from module_1_document_processing.parsing.llama_parser import LlamaParserService
from module_1_document_processing.parsing.parse_failure_store import ParseFailureStore

class ParserService:
    """Facade orchestrating MIME routing, document parsing, and failure recording."""

    def __init__(self) -> None:
        self.router = MIMERouter()
        self.direct_parser = DirectTextParser()
        self.llama_parser = LlamaParserService()
        self.failure_store = ParseFailureStore()

    def parse_event(self, event: CanonicalEvent, raw_bytes: bytes | None = None) -> ParsedDocument:
        mime_type = event.metadata.get("mime_type") or event.metadata.get("mime")
        filename = event.metadata.get("name") or event.metadata.get("title") or ""
        doc_id = f"{event.tenant_id}:{event.source}:{event.external_id}"

        # 1. MIME Category Routing
        category = self.router.route(mime_type=mime_type, file_path=filename)
        print(f"[ParserService] Routing doc_id={doc_id} with mime='{mime_type}', filename='{filename}' -> Category: {category.value}")

        if category == ParserCategory.UNSUPPORTED:
            reason = f"Unsupported file type/MIME '{mime_type}' for filename '{filename}'"
            self.failure_store.record_failure(
                doc_id=doc_id,
                tenant_id=event.tenant_id,
                user_id=event.user_id,
                source=event.source,
                external_id=event.external_id,
                reason=reason,
                mime_type=mime_type,
            )
            return ParsedDocument(
                doc_id=doc_id,
                tenant_id=event.tenant_id,
                user_id=event.user_id,
                source=event.source,
                external_id=event.external_id,
                acl=list(event.acl),
                mime_type=mime_type,
                parse_status="FAILED",
                parser_used="unsupported",
                metadata={"error": reason},
            )

        if category == ParserCategory.LOCAL_TEXT:
            parsed = self.direct_parser.parse(event, raw_bytes=raw_bytes)
            return parsed

        if category in (ParserCategory.LLAMA_DOCUMENT, ParserCategory.LLAMA_IMAGE):
            parsed = self.llama_parser.parse(event, raw_bytes=raw_bytes)
            if parsed.parse_status == "FAILED":
                self.failure_store.record_failure(
                    doc_id=doc_id,
                    tenant_id=event.tenant_id,
                    user_id=event.user_id,
                    source=event.source,
                    external_id=event.external_id,
                    reason=parsed.metadata.get("error", "LlamaParse failure"),
                    mime_type=mime_type,
                )
            return parsed

        # Default fallback
        parsed = self.direct_parser.parse(event, raw_bytes=raw_bytes)
        return parsed
