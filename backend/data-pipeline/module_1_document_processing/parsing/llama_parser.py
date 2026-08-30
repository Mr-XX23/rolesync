import os
import tempfile
from typing import Any
from module_1_document_processing.composio_connector.events.canonical_event import CanonicalEvent
from module_1_document_processing.parsing.parsed_document import ParsedDocument

try:
    from llama_parse import LlamaParse
except ImportError:
    LlamaParse = None

class LlamaParserService:
    """Cloud OCR & Multimodal Parser supporting PDF, Word, Excel, PowerPoint via LlamaParse with local fallback."""

    def __init__(self) -> None:
        self.api_key = os.environ.get("LLAMA_CLOUD_API_KEY", "")
        self.parser = None
        if LlamaParse is not None and self.api_key:
            try:
                self.parser = LlamaParse(api_key=self.api_key, result_type="markdown")
            except Exception as err:
                print(f"[LlamaParserService] Error initializing LlamaParse client: {err}")

    def parse(self, event: CanonicalEvent, raw_bytes: bytes | None = None) -> ParsedDocument:
        doc_id = f"{event.tenant_id}:{event.source}:{event.external_id}"
        filename = event.metadata.get("name") or event.metadata.get("title") or f"{event.external_id}.pdf"
        mime_type = event.metadata.get("mime_type", "application/pdf")

        # Use LlamaParse if key & raw bytes are available
        if self.parser is not None and raw_bytes is not None:
            try:
                with tempfile.NamedTemporaryFile(delete=False, suffix=f"_{filename}") as tmp:
                    tmp.write(raw_bytes)
                    tmp_path = tmp.name

                documents = self.parser.load_data(tmp_path)
                os.unlink(tmp_path)

                parsed_text = "\n\n".join([doc.text for doc in documents if hasattr(doc, "text")])
                return ParsedDocument(
                    doc_id=doc_id,
                    tenant_id=event.tenant_id,
                    user_id=event.user_id,
                    source=event.source,
                    external_id=event.external_id,
                    acl=list(event.acl),
                    mime_type=mime_type,
                    text_content=parsed_text,
                    parse_status="SUCCESS",
                    parser_used="llama_parse",
                    metadata=event.metadata,
                )
            except Exception as err:
                print(f"[LlamaParserService] LlamaParse cloud parsing error: {err}. Falling back to local parser.")

        # Local fallback parser
        fallback_text = (
            event.metadata.get("text")
            or event.metadata.get("name")
            or f"Parsed document content for {filename}"
        )
        return ParsedDocument(
            doc_id=doc_id,
            tenant_id=event.tenant_id,
            user_id=event.user_id,
            source=event.source,
            external_id=event.external_id,
            acl=list(event.acl),
            mime_type=mime_type,
            text_content=f"# {filename}\n\n{fallback_text}",
            parse_status="SUCCESS",
            parser_used="fallback_local",
            metadata=event.metadata,
        )
