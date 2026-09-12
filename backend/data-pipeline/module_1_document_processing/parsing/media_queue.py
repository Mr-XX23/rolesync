"""Media (audio/video) ingestion seam - PLACEHOLDER, transcription NOT IMPLEMENTED.

Audio and video previously fell through to the plain-text parser, which UTF-8
decoded the raw bytes into garbage and indexed it. Until a transcription
provider is wired up, media is instead parked here with a MEDIA_PENDING status:
the original file is still stored, nothing meaningless reaches the vector store,
and the jobs can be replayed once transcription exists.

To implement later, give TranscriptionWorker a real `transcribe()` (Whisper via
Groq/Deepgram/OpenAI) and drain the queue from a background worker.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional

# Parse status used for media that is stored but not yet transcribed.
MEDIA_PENDING = "MEDIA_PENDING"


@dataclass
class MediaJob:
    doc_id: str
    tenant_id: str
    user_id: str
    source: str
    external_id: str
    mime_type: str
    storage_ref: str = ""
    status: str = "PENDING"  # PENDING | PROCESSING | DONE | FAILED
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    metadata: dict[str, Any] = field(default_factory=dict)


class MediaJobQueue:
    """In-memory parking area for media awaiting transcription.

    Deliberately simple: this is a seam, not a durable queue. When transcription
    is implemented this should move onto the same durable queue as the rest of
    the pipeline (see the remediation backlog in the conformance doc).
    """

    def __init__(self) -> None:
        self._jobs: dict[str, MediaJob] = {}

    def enqueue(self, job: MediaJob) -> MediaJob:
        self._jobs[job.doc_id] = job
        print(
            f"[MediaJobQueue] Parked media doc_id={job.doc_id} "
            f"({job.mime_type}) - transcription not implemented yet."
        )
        return job

    def get(self, doc_id: str) -> Optional[MediaJob]:
        return self._jobs.get(doc_id)

    def list_pending(self, tenant_id: str = "", limit: int = 100) -> list[MediaJob]:
        jobs = [
            job
            for job in self._jobs.values()
            if job.status == "PENDING" and (not tenant_id or job.tenant_id == tenant_id)
        ]
        return jobs[:limit]

    def pending_count(self, tenant_id: str = "") -> int:
        return len(self.list_pending(tenant_id=tenant_id, limit=10**6))


class TranscriptionWorker:
    """PLACEHOLDER transcription worker.

    `available()` returns False, so callers keep media parked rather than
    pretending an empty transcript is a successful parse.
    """

    provider = "none"

    def available(self) -> bool:
        return False

    def transcribe(self, job: MediaJob, raw_bytes: bytes | None = None) -> str:
        raise NotImplementedError(
            "Audio/video transcription is not implemented. Wire a provider "
            "(e.g. Whisper via Groq/Deepgram) into TranscriptionWorker.transcribe()."
        )


media_job_queue = MediaJobQueue()
transcription_worker = TranscriptionWorker()
