from dataclasses import dataclass
from typing import Any
import re
try:
    import clamd
except ImportError:
    clamd = None
from module_1_document_processing.composio_connector.events.canonical_event import CanonicalEvent

MAX_PAYLOAD_SIZE_BYTES = 25 * 1024 * 1024  # 25MB

@dataclass
class ScanResult:
    is_safe: bool
    reason: str
    event: CanonicalEvent | None = None

class SecurityScanner:
    """Security Scanner for Malware & DLP check on untrusted incoming payloads."""

    def __init__(self, clamav_host: str = "localhost", clamav_port: int = 3310) -> None:
        self._clamav_host = clamav_host
        self._clamav_port = clamav_port
        self._cd = None

    def scan_raw_bytes(self, data: bytes) -> ScanResult:
        if len(data) > MAX_PAYLOAD_SIZE_BYTES:
            return ScanResult(is_safe=False, reason=f"Payload size ({len(data)} bytes) exceeds limit of 25MB")
        
        # Try ClamAV if available
        if self._cd is not None:
            try:
                scan_res = self._cd.scan_stream(data)
                if scan_res and scan_res.get("stream", (None, None))[0] == "FOUND":
                    virus_name = scan_res["stream"][1]
                    return ScanResult(is_safe=False, reason=f"Malware detected: {virus_name}")
            except Exception as e:
                print(f"[SecurityScanner] ClamAV stream scan error: {e}")

        return ScanResult(is_safe=True, reason="Clean")

    def scan_and_sanitize_event(self, event: CanonicalEvent) -> ScanResult:
        if not event.event_id or not event.tenant_id:
            return ScanResult(is_safe=False, reason="Invalid event: missing event_id or tenant_id")

        # Sanitize metadata text
        sanitized_metadata = self._sanitize_dict(event.metadata)
        event.metadata = sanitized_metadata

        # Simple DLP / script injection check
        raw_text = str(event.metadata.get("text") or event.metadata.get("subject") or event.metadata.get("title") or "")
        if self._contains_suspicious_script(raw_text):
            return ScanResult(is_safe=False, reason="Potential XSS / script injection detected in payload text")

        return ScanResult(is_safe=True, reason="Passed security check", event=event)

    def _sanitize_dict(self, data: dict[str, Any]) -> dict[str, Any]:
        cleaned = {}
        for key, val in data.items():
            if isinstance(val, str):
                cleaned[key] = self._sanitize_string(val)
            elif isinstance(val, dict):
                cleaned[key] = self._sanitize_dict(val)
            elif isinstance(val, list):
                cleaned[key] = [self._sanitize_string(v) if isinstance(v, str) else v for v in val]
            else:
                cleaned[key] = val
        return cleaned

    def _sanitize_string(self, text: str) -> str:
        # Strip null bytes and control characters
        return text.replace("\x00", "").strip()

    def _contains_suspicious_script(self, text: str) -> bool:
        script_pattern = re.compile(r"<\s*script[^>]*>.*?</\s*script\s*>", re.IGNORECASE | re.DOTALL)
        return bool(script_pattern.search(text))
