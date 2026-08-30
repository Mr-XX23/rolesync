from connectors.events.canonical_event import CanonicalEvent
from parsing.mime_router import MIMERouter, ParserCategory
from parsing.parsed_document import ParsedDocument
from parsing.direct_text_parser import DirectTextParser
from parsing.llama_parser import LlamaParserService
from parsing.parse_failure_store import ParseFailureStore

class ParserService:
    """Facade orchestrating MIME routing, document parsing, and failure recording."""

    def __init__(self) -> None:
        self.router = MIMERouter()
        self.direct_parser = DirectTextParser()
        self.llama_parser = LlamaParserService()
        self.failure_store = ParseFailureStore()

    def parse_event(self, event: CanonicalEvent, raw_bytes: bytes | None = None) -> ParsedDocument:
        doc_id = f"{event.tenant_id}:{event.source}:{event.external_id}"
        mime_type = event.metadata.get("mime_type", "")
        file_name = event.metadata.get("name") or event.metadata.get("filename", "")

        category = self.router.route(mime_type=mime_type, file_path=file_name)
        print(f"[ParserService] Routing doc_id={doc_id} with mime='{mime_type}', filename='{file_name}' -> Category: {category.value}")

        if category == ParserCategory.LOCAL_TEXT:
            return self.direct_parser.parse(event, raw_bytes=raw_bytes)
        
        elif category in (ParserCategory.LLAMA_DOCUMENT, ParserCategory.LLAMA_IMAGE, ParserCategory.AUDIO):
            return self.llama_parser.parse(event, raw_bytes=raw_bytes)

        else: # ParserCategory.UNSUPPORTED
            reason = f"Unsupported file type/MIME '{mime_type}' for filename '{file_name}'"
            self.failure_store.record_failure(
                doc_id=doc_id,
                tenant_id=event.tenant_id,
                user_id=event.user_id,
                source=event.source,
                external_id=event.external_id,
                reason=reason,
                mime_type=mime_type,
                metadata=event.metadata,
            )
            # Return partial document with failure state
            return ParsedDocument(
                doc_id=doc_id,
                tenant_id=event.tenant_id,
                user_id=event.user_id,
                source=event.source,
                external_id=event.external_id,
                acl=list(event.acl),
                mime_type=mime_type or "unknown",
                text_content="",
                metadata=event.metadata,
                page_count=0,
                parse_status="FAILED",
                parser_used="unsupported",
            )
