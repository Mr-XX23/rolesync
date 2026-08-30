from enum import Enum
import os

class ParserCategory(str, Enum):
    LOCAL_TEXT = "local_text"
    LLAMA_DOCUMENT = "llama_document"
    LLAMA_IMAGE = "llama_image"
    AUDIO = "audio"
    UNSUPPORTED = "unsupported"

class MIMERouter:
    """MIME Router determining parser selection based on MIME type or extension."""

    TEXT_EXTENSIONS = {".txt", ".md", ".json", ".csv", ".tsv", ".py", ".java", ".js", ".ts", ".html", ".xml", ".yaml", ".yml", ".ini"}
    DOC_EXTENSIONS = {".pdf", ".docx", ".doc", ".pptx", ".ppt", ".xlsx", ".xls", ".epub", ".rtf"}
    IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".tiff", ".bmp", ".gif"}
    AUDIO_EXTENSIONS = {".mp3", ".wav", ".m4a", ".webm", ".mpeg", ".mpga"}

    TEXT_MIMES = {
        "text/plain", "text/markdown", "application/json", "text/csv",
        "text/html", "text/xml", "application/xml", "text/x-python", "text/javascript"
    }
    DOC_MIMES = {
        "application/pdf",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "application/msword",
        "application/vnd.openxmlformats-officedocument.presentationml.presentation",
        "application/vnd.ms-powerpoint",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "application/vnd.ms-excel",
        "application/epub+zip",
    }
    IMAGE_MIMES = {"image/png", "image/jpeg", "image/webp", "image/tiff", "image/bmp"}
    AUDIO_MIMES = {"audio/mpeg", "audio/wav", "audio/mp4", "audio/x-m4a", "audio/webm"}

    def route(self, mime_type: str | None = None, file_path: str | None = None) -> ParserCategory:
        clean_mime = (mime_type or "").lower().split(";")[0].strip()
        
        if clean_mime in self.TEXT_MIMES:
            return ParserCategory.LOCAL_TEXT
        elif clean_mime in self.DOC_MIMES:
            return ParserCategory.LLAMA_DOCUMENT
        elif clean_mime in self.IMAGE_MIMES:
            return ParserCategory.LLAMA_IMAGE
        elif clean_mime in self.AUDIO_MIMES:
            return ParserCategory.AUDIO

        # Fallback to file extension
        if file_path:
            _, ext = os.path.splitext(file_path.lower())
            if ext in self.TEXT_EXTENSIONS:
                return ParserCategory.LOCAL_TEXT
            elif ext in self.DOC_EXTENSIONS:
                return ParserCategory.LLAMA_DOCUMENT
            elif ext in self.IMAGE_EXTENSIONS:
                return ParserCategory.LLAMA_IMAGE
            elif ext in self.AUDIO_EXTENSIONS:
                return ParserCategory.AUDIO

        # Default fallback for raw inline text metadata (e.g. email/slack text)
        if not clean_mime and not file_path:
            return ParserCategory.LOCAL_TEXT

        return ParserCategory.UNSUPPORTED
