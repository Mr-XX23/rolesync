import os
import base64
from typing import Any
from module_1_document_processing.composio_connector.events.canonical_event import CanonicalEvent
from module_1_document_processing.parsing.mime_router import MIMERouter, ParserCategory
from module_1_document_processing.parsing.parsed_document import ParsedDocument
from module_1_document_processing.parsing.direct_text_parser import DirectTextParser
from module_1_document_processing.parsing.llama_parser import LlamaParserService
from module_1_document_processing.parsing.parse_failure_store import ParseFailureStore

class ParserService:
    """Facade orchestrating MIME routing, document parsing, Gmail combined attachment processing, and failure recording."""

    def __init__(self) -> None:
        self.router = MIMERouter()
        self.direct_parser = DirectTextParser()
        self.llama_parser = LlamaParserService()
        self.failure_store = ParseFailureStore()
        self.max_doc_size_mb = int(os.environ.get("MAX_DOC_ATTACHMENT_SIZE_MB", "20"))
        self.max_image_size_mb = int(os.environ.get("MAX_IMAGE_ATTACHMENT_SIZE_MB", "4"))
        self.max_attachment_size_mb = int(os.environ.get("MAX_EMAIL_ATTACHMENT_SIZE_MB", "25"))

    def parse_event(self, event: CanonicalEvent, raw_bytes: bytes | None = None) -> ParsedDocument:
        doc_id = f"{event.tenant_id}:{event.source}:{event.external_id}"

        # Special Universal Handling for Gmail: Combine Email Body + Attachments (<25MB)
        if event.source.lower() == "gmail":
            return self._parse_gmail_event(event, raw_bytes)

        if raw_bytes is None and "raw_bytes" in event.metadata and event.metadata["raw_bytes"]:
            raw_bytes = event.metadata["raw_bytes"]

        mime_type = event.metadata.get("mime_type") or event.metadata.get("mime")
        filename = event.metadata.get("name") or event.metadata.get("title") or ""


        # 1. MIME Category Routing for other data sources
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
            return self.direct_parser.parse(event, raw_bytes=raw_bytes)

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
        return self.direct_parser.parse(event, raw_bytes=raw_bytes)

    def _parse_gmail_event(self, event: CanonicalEvent, raw_bytes: bytes | None = None) -> ParsedDocument:
        """
        Parses a Gmail CanonicalEvent by combining email headers, body text, and valid attachments (<=25MB).
        Attachments >25MB or unsupported are selectively skipped without failing the parent email.
        """
        doc_id = f"{event.tenant_id}:{event.source}:{event.external_id}"
        meta = event.metadata or {}

        subject = meta.get("subject") or "No Subject"
        sender = meta.get("sender") or "unknown@sender.com"
        to_addr = meta.get("to") or event.user_id
        received_at = meta.get("received_at") or event.timestamp.isoformat()
        labels = meta.get("label_ids") or []
        body_text = meta.get("body") or meta.get("snippet") or ""

        sections: list[str] = [
            f"# Email: {subject}",
            f"**From:** {sender}  \n**To:** {to_addr}  \n**Date:** {received_at}  \n**Labels:** {', '.join(labels)}",
            "## Message Body",
            body_text if body_text.strip() else "*(No body content)*"
        ]

        attachments = meta.get("attachments", [])
        attachment_audits: list[dict[str, Any]] = []
        has_skipped_attachment = False

        for att in attachments:
            fname = att.get("filename", "attachment.bin")
            mime = att.get("mime_type", "application/octet-stream")
            size_bytes = int(att.get("size_bytes", 0))
            att_raw = att.get("raw_bytes")

            # Convert base64 string to bytes if needed
            if isinstance(att_raw, str):
                try:
                    att_raw = base64.b64decode(att_raw)
                except Exception:
                    att_raw = att_raw.encode("utf-8")

            # Determine size limit based on file type: Images <= 4MB, Documents <= 20MB
            is_image = (
                mime.startswith("image/")
                or fname.lower().endswith((".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp", ".svg", ".tiff"))
            )
            type_limit_mb = self.max_image_size_mb if is_image else self.max_doc_size_mb
            max_bytes = type_limit_mb * 1024 * 1024

            # Rule 1: Size Check (4MB for images, 20MB for documents)
            if size_bytes > max_bytes:
                has_skipped_attachment = True
                type_label = "image" if is_image else "document"
                skip_reason = f"{type_label.upper()}_SIZE_EXCEEDED ({size_bytes / (1024*1024):.1f}MB > {type_limit_mb}MB {type_label} limit)"
                attachment_audits.append({
                    "filename": fname,
                    "mime_type": mime,
                    "size_bytes": size_bytes,
                    "parse_status": "SKIPPED",
                    "parser": None,
                    "skip_reason": skip_reason,
                })
                sections.append(f"---\n## Skipped Attachment: {fname}\n*Reason: Attachment exceeded {type_limit_mb}MB {type_label} limit ({size_bytes / (1024*1024):.1f}MB). The parent email content was safely indexed.*")
                print(f"[ParserService] Skipped attachment '{fname}' for doc_id={doc_id}: {skip_reason}")
                continue

            # Rule 2: MIME & Format Support Check
            category = self.router.route(mime_type=mime, file_path=fname)
            if category == ParserCategory.UNSUPPORTED:
                has_skipped_attachment = True
                skip_reason = f"UNSUPPORTED_FORMAT ({mime})"
                attachment_audits.append({
                    "filename": fname,
                    "mime_type": mime,
                    "size_bytes": size_bytes,
                    "parse_status": "SKIPPED",
                    "parser": None,
                    "skip_reason": skip_reason,
                })
                sections.append(f"---\n## Skipped Attachment: {fname}\n*Reason: Unsupported file format ({mime}). The parent email content was safely indexed.*")
                print(f"[ParserService] Skipped attachment '{fname}' for doc_id={doc_id}: {skip_reason}")
                continue

            # Rule 3: Process Supported Attachment (<=25MB)
            parsed_text, parser_used, status = self.llama_parser.parse_attachment_bytes(fname, mime, att_raw)
            attachment_audits.append({
                "filename": fname,
                "mime_type": mime,
                "size_bytes": size_bytes,
                "parse_status": status,
                "parser": parser_used,
                "skip_reason": None,
            })
            sections.append(f"---\n## Attachment: {fname} (Parsed via {parser_used})\n{parsed_text}")
            print(f"[ParserService] Successfully parsed attachment '{fname}' ({size_bytes} bytes) for doc_id={doc_id} using {parser_used}")

        combined_text = "\n\n".join(sections)
        overall_status = "PARTIAL_SUCCESS" if has_skipped_attachment else "SUCCESS"

        updated_metadata = dict(meta)
        updated_metadata["attachment_audits"] = attachment_audits

        return ParsedDocument(
            doc_id=doc_id,
            tenant_id=event.tenant_id,
            user_id=event.user_id,
            source=event.source,
            external_id=event.external_id,
            acl=list(event.acl),
            mime_type="message/rfc822",
            text_content=combined_text,
            parse_status=overall_status,
            parser_used="gmail_combined_llamaparse",
            metadata=updated_metadata,
        )
