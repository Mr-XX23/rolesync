from typing import Any
import json
from module_1_document_processing.composio_connector.events.canonical_event import CanonicalEvent
from module_1_document_processing.parsing.parsed_document import ParsedDocument

class DirectTextParser:
    """Fast local parser for plain text, Markdown, code, and JSON documents."""

    def parse(self, event: CanonicalEvent, raw_bytes: bytes | None = None) -> ParsedDocument:
        doc_id = f"{event.tenant_id}:{event.source}:{event.external_id}"
        text_content = ""

        if raw_bytes is not None:
            try:
                text_content = raw_bytes.decode("utf-8", errors="replace")
            except Exception as err:
                print(f"[DirectTextParser] Error decoding raw bytes for doc_id={doc_id}: {err}")

        if not text_content:
            meta = event.metadata or {}
            # Extract content from common metadata payload fields
            text_content = (
                meta.get("text")
                or meta.get("body")
                or meta.get("snippet")
                or meta.get("description")
                or meta.get("summary")
                or meta.get("subject")
                or meta.get("title")
                or ""
            )
            # Format subject/title header if available
            title = meta.get("subject") or meta.get("title") or meta.get("name")
            if title and title not in text_content:
                text_content = f"# {title}\n\n{text_content}"

        return ParsedDocument(
            doc_id=doc_id,
            tenant_id=event.tenant_id,
            user_id=event.user_id,
            source=event.source,
            external_id=event.external_id,
            acl=list(event.acl),
            mime_type=event.metadata.get("mime_type", "text/plain"),
            text_content=text_content,
            parse_status="SUCCESS",
            parser_used="local_text",
            metadata=event.metadata,
        )
