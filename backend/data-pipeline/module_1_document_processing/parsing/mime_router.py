from enum import Enum

class ParserCategory(str, Enum):
    LOCAL_TEXT = "local_text"          # Plain text, Markdown, Code, JSON
    LLAMA_DOCUMENT = "llama_document"  # PDF, Office Docs (docx, xlsx, pptx)
    LLAMA_IMAGE = "llama_image"        # PNG, JPEG, TIFF
    AUDIO = "audio"                    # Audio transcripts
    UNSUPPORTED = "unsupported"

class MIMERouter:
    """MIME Router categorizing incoming documents for optimal parsing paths."""

    def route(self, mime_type: str | None = None, file_path: str | None = None) -> ParserCategory:
        mime = (mime_type or "").lower().strip()
        if mime in ("none", "null", "") and not file_path:
            return ParserCategory.LOCAL_TEXT

        ext = (file_path or "").split(".")[-1].lower() if file_path and "." in file_path else ""

        if mime in ("text/plain", "text/markdown", "text/csv", "application/json", "text/html") or ext in ("txt", "md", "csv", "json", "py", "js", "html", "ts"):
            return ParserCategory.LOCAL_TEXT

        if (
            mime in (
                "application/pdf",
                "application/msword",
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                "application/vnd.ms-excel",
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                "application/vnd.ms-powerpoint",
                "application/vnd.openxmlformats-officedocument.presentationml.presentation",
            )
            or ext in ("pdf", "doc", "docx", "xls", "xlsx", "ppt", "pptx")
        ):
            return ParserCategory.LLAMA_DOCUMENT

        if mime.startswith("image/") or ext in ("png", "jpg", "jpeg", "tiff", "bmp"):
            return ParserCategory.LLAMA_IMAGE

        if mime.startswith("audio/") or ext in ("mp3", "wav", "m4a", "ogg"):
            return ParserCategory.AUDIO

        return ParserCategory.UNSUPPORTED
