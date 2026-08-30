from typing import Any
import json
from connectors.events.canonical_event import CanonicalEvent
from parsing.parsed_document import ParsedDocument

class DirectTextParser:
    """Fast local parser for plain text, Markdown, code, and JSON documents."""

    def parse(self, event: CanonicalEvent, raw_bytes: bytes | None = None) -> ParsedDocument:
        doc_id = f"{event.tenant_id}:{event.source}:{event.external_id}"
        
        # 1. Extract text from raw_bytes if available, otherwise from metadata
        text_content = ""
        if raw_bytes:
            try:
                text_content = raw_bytes.decode("utf-8")
            except UnicodeDecodeError:
                text_content = raw_bytes.decode("latin-1", errors="replace")
        else:
            # Extract text from metadata (subject, text, title, body)
            text_content = (
                event.metadata.get("text")
                or event.metadata.get("subject")
                or event.metadata.get("title")
                or str(event.metadata)
            )

        # 2. Format title header if present
        title = event.metadata.get("subject") or event.metadata.get("title") or event.metadata.get("name")
        if title and not text_content.startswith(f"# {title}"):
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
            metadata=event.metadata,
            page_count=1,
            parse_status="SUCCESS",
            parser_used="local_text",
        )
