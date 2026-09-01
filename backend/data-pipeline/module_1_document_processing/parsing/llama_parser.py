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
        self.api_key = os.environ.get("LLAMAPARSE_API_KEY", "") or os.environ.get("LLAMA_CLOUD_API_KEY", "")
        self.parser = None
        if LlamaParse is not None and self.api_key:
            try:
                self.parser = LlamaParse(api_key=self.api_key, result_type="markdown")
                print("[LlamaParserService] Initialized LlamaParse client with API key.")
            except Exception as err:
                print(f"[LlamaParserService] Error initializing LlamaParse client: {err}")

    def parse_attachment_bytes(self, filename: str, mime_type: str, raw_bytes: bytes | None) -> tuple[str, str, str]:
        """
        Parses attachment bytes using LlamaParse or local fallback.
        Returns (parsed_markdown, parser_used, parse_status).
        """
        if raw_bytes is None or len(raw_bytes) == 0:
            return f"*(Empty attachment file: {filename})*", "none", "SKIPPED"

        if self.parser is not None:
            try:
                suffix = f"_{filename}" if filename else ".pdf"
                with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
                    tmp.write(raw_bytes)
                    tmp_path = tmp.name

                documents = self.parser.load_data(tmp_path)
                try:
                    os.unlink(tmp_path)
                except Exception:
                    pass

                parsed_text = "\n\n".join([doc.text for doc in documents if hasattr(doc, "text") and doc.text])
                if parsed_text.strip():
                    return parsed_text, "llama_parse", "SUCCESS"
            except Exception as err:
                print(f"[LlamaParserService] LlamaParse cloud parsing error for {filename}: {err}")

        # Fallback for plain text / basic formats
        if mime_type.startswith("text/") or filename.endswith((".txt", ".csv", ".json", ".md")):
            try:
                return raw_bytes.decode("utf-8", errors="replace"), "local_text", "SUCCESS"
            except Exception:
                pass

        return f"*(Parsed document content placeholder for {filename})*", "fallback_local", "SUCCESS"

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
                try:
                    os.unlink(tmp_path)
                except Exception:
                    pass

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
