"""Shared ingestion policy applied to EVERY path into the knowledge base.

Connector events (QueueWorker) and manual uploads / URL ingests
(knowledge_vault_routes) both run these guards, so a file cannot reach the
vector store without passing the same size, type, malware and quality checks.

All messages here are safe to show an end user: they describe what to do next
and never leak internal exception text, paths or provider details.
"""
from __future__ import annotations

import os

from module_1_document_processing.parsing.parsed_document import ParsedDocument
from module_1_document_processing.security.security_scanner import SecurityScanner
from module_2_memory_gatekeeper.gatekeeper_engine import GatekeeperDecision, GatekeeperEngine


def _int_env(name: str, default: int) -> int:
    try:
        value = int(os.environ.get(name, "") or default)
        return value if value > 0 else default
    except (TypeError, ValueError):
        return default


MAX_UPLOAD_BYTES = _int_env("MAX_UPLOAD_BYTES", 25 * 1024 * 1024)
MAX_URL_FETCH_BYTES = _int_env("MAX_URL_FETCH_BYTES", 5 * 1024 * 1024)

ALLOWED_UPLOAD_EXTS = {"PDF", "CSV", "TXT", "DOCX", "PPTX", "XLSX", "MD", "JSON", "TSV", "YAML", "YML"}

# Shared singletons so every path uses the same configured policy.
security_scanner = SecurityScanner()
gatekeeper_engine = GatekeeperEngine()


class IngestionRejected(Exception):
    """Content must not enter the pipeline. `message` is safe to show a user."""

    def __init__(self, code: str, message: str, status_code: int = 400) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code


def _format_mb(num_bytes: int) -> str:
    return f"{num_bytes / (1024 * 1024):.0f} MB"


def validate_upload(filename: str, size_bytes: int) -> str:
    """Check extension and size before anything is read into the pipeline.

    Returns the normalised uppercase extension.
    """
    name = filename or "uploaded_file"
    ext = name.rsplit(".", 1)[-1].upper() if "." in name else "FILE"

    if ext not in ALLOWED_UPLOAD_EXTS:
        raise IngestionRejected(
            "UNSUPPORTED_TYPE",
            "That file type is not supported. Please upload a PDF, Word, Excel, "
            "PowerPoint, CSV, text, Markdown or JSON file.",
        )

    if size_bytes <= 0:
        raise IngestionRejected(
            "EMPTY_FILE",
            "That file appears to be empty. Please check the file and try again.",
        )

    if size_bytes > MAX_UPLOAD_BYTES:
        raise IngestionRejected(
            "FILE_TOO_LARGE",
            f"That file is too large. The maximum size is {_format_mb(MAX_UPLOAD_BYTES)}.",
            status_code=413,
        )

    return ext


def scan_content(content: bytes, filename: str = "") -> None:
    """Malware / size / DLP scan. Raises IngestionRejected when unsafe."""
    if not content:
        raise IngestionRejected(
            "EMPTY_FILE",
            "That file appears to be empty. Please check the file and try again.",
        )

    result = security_scanner.scan_raw_bytes(content)
    if not result.is_safe:
        # The real reason (virus signature, size) is logged, never shown to the user.
        print(f"[IngestionGuards] Rejected '{filename}' by security scan: {result.reason}")
        raise IngestionRejected(
            "UNSAFE_CONTENT",
            "That file did not pass our security scan and was not uploaded.",
        )


def evaluate_gatekeeper(parsed_doc: ParsedDocument) -> GatekeeperDecision:
    """Quality/relevance gate. Callers decide how to surface a rejection."""
    return gatekeeper_engine.evaluate_document(parsed_doc)


def gatekeeper_message(decision: GatekeeperDecision) -> str:
    """Generic, user-facing explanation for a gatekeeper rejection."""
    if decision.decision == "QUARANTINED":
        return (
            "This document was held for review because its content could not be "
            "verified. It was not added to your Knowledge Vault."
        )
    return (
        "We could not extract enough usable text from this document, so it was not "
        "added to your Knowledge Vault. Try uploading a text-based version of the file."
    )


# Generic messages for failures that are not policy rejections.
PARSE_FAILED_MESSAGE = (
    "We could not read this document. It may be corrupted, password-protected, or "
    "an image-only file. Try re-saving it and uploading again."
)
NO_CONTENT_MESSAGE = (
    "No indexable text could be extracted from this document. It may be an image-only "
    "or empty file - re-upload or re-index to retry."
)
PROCESSING_FAILED_MESSAGE = (
    "Something went wrong while processing this document. Please try re-indexing it, "
    "or upload the file again."
)
URL_FETCH_FAILED_MESSAGE = (
    "We could not fetch that URL. Check that the link is public and reachable, then try again."
)
MEDIA_PENDING_MESSAGE = (
    "Audio and video files are stored but cannot be searched yet - transcription "
    "is not available. This file was not added to your Knowledge Vault."
)
