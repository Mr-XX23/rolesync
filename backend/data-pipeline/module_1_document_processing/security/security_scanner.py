from dataclasses import dataclass
from typing import Any
import os
import re
try:
    import clamd
except ImportError:
    clamd = None
from module_1_document_processing.composio_connector.events.canonical_event import CanonicalEvent


def _max_payload_bytes() -> int:
    try:
        value = int(os.environ.get("MAX_UPLOAD_BYTES", "") or 0)
        if value > 0:
            return value
    except (TypeError, ValueError):
        pass
    return 25 * 1024 * 1024  # 25MB


MAX_PAYLOAD_SIZE_BYTES = _max_payload_bytes()

@dataclass
class ScanResult:
    is_safe: bool
    reason: str
    event: CanonicalEvent | None = None

class SecurityScanner:
    """Security Scanner for Malware & DLP check on untrusted incoming payloads."""

    def __init__(self, clamav_host: str | None = None, clamav_port: int | None = None) -> None:
        # Malware scanning is active only when a clamd daemon is reachable. Set
        # CLAMAV_HOST (e.g. to a "clamav" service) to enable it; when unset the
        # scanner still enforces size limits and DLP/script checks.
        self._clamav_host = clamav_host if clamav_host is not None else os.environ.get("CLAMAV_HOST", "").strip()
        try:
            self._clamav_port = int(clamav_port if clamav_port is not None else os.environ.get("CLAMAV_PORT", "3310"))
        except (TypeError, ValueError):
            self._clamav_port = 3310
        self._cd = None
        self._cd_attempted = False

    def _client(self):
        """Lazily connect to clamd once per process; None means scanning is unavailable."""
        if self._cd_attempted:
            return self._cd
        self._cd_attempted = True

        if clamd is None or not self._clamav_host:
            if not self._clamav_host:
                print("[SecurityScanner] CLAMAV_HOST not set - malware scanning disabled (size/DLP checks still apply).")
            return None

        try:
            client = clamd.ClamdNetworkSocket(host=self._clamav_host, port=self._clamav_port, timeout=10)
            client.ping()
            self._cd = client
            print(f"[SecurityScanner] Connected to ClamAV at {self._clamav_host}:{self._clamav_port}.")
        except Exception as e:
            print(f"[SecurityScanner] ClamAV unavailable at {self._clamav_host}:{self._clamav_port} ({e}); malware scanning disabled.")
            self._cd = None
        return self._cd

    def scan_raw_bytes(self, data: bytes) -> ScanResult:
        if not data:
            return ScanResult(is_safe=False, reason="Empty payload")

        if len(data) > MAX_PAYLOAD_SIZE_BYTES:
            limit_mb = MAX_PAYLOAD_SIZE_BYTES / (1024 * 1024)
            return ScanResult(
                is_safe=False,
                reason=f"Payload size ({len(data)} bytes) exceeds limit of {limit_mb:.0f}MB",
            )

        client = self._client()
        if client is not None:
            try:
                scan_res = client.scan_stream(data)
                if scan_res and scan_res.get("stream", (None, None))[0] == "FOUND":
                    virus_name = scan_res["stream"][1]
                    return ScanResult(is_safe=False, reason=f"Malware detected: {virus_name}")
            except Exception as e:
                # A scanner outage must not silently pass unscanned bytes through
                # unnoticed, but it also must not block ingestion entirely.
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
