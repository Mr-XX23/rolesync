from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

@dataclass
class ParsedDocument:
    doc_id: str
    tenant_id: str
    user_id: str
    source: str
    external_id: str
    acl: list[str]
    mime_type: str
    text_content: str
    tables: list[dict[str, Any]] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    page_count: int = 1
    parse_status: str = "SUCCESS"  # SUCCESS, PARTIAL, FAILED
    parser_used: str = "local_text"  # local_text, llama_parse, audio, fallback
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
