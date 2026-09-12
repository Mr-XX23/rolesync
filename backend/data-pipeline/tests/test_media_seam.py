"""Audio/video are parked, not garbage-parsed.

Media used to fall through to the plain-text parser, which UTF-8 decoded raw
bytes into noise and indexed it. These pin the MEDIA_PENDING seam instead.
"""
from datetime import datetime, timezone

import pytest

from module_1_document_processing.composio_connector.events.canonical_event import CanonicalEvent, EventType
from module_1_document_processing.parsing.media_queue import (
    MEDIA_PENDING,
    MediaJob,
    MediaJobQueue,
    TranscriptionWorker,
    media_job_queue,
)
from module_1_document_processing.parsing.mime_router import MIMERouter, ParserCategory
from module_1_document_processing.parsing.parser_service import ParserService


def _event(external_id: str, name: str, mime: str) -> CanonicalEvent:
    return CanonicalEvent(
        event_id=f"evt_{external_id}", event_type=EventType.CREATE, source="gdrive",
        tenant_id="tenant_media", user_id="u1", external_id=external_id, raw_ref={},
        acl=["u1"], timestamp=datetime.now(timezone.utc),
        metadata={"name": name, "mime_type": mime, "title": name},
    )


@pytest.mark.parametrize(
    "mime,filename,expected",
    [
        ("audio/mpeg", "call.mp3", ParserCategory.AUDIO),
        ("", "recording.wav", ParserCategory.AUDIO),
        ("video/mp4", "demo.mp4", ParserCategory.VIDEO),
        ("", "standup.mov", ParserCategory.VIDEO),
    ],
)
def test_router_classifies_media(mime, filename, expected):
    assert MIMERouter().route(mime_type=mime, file_path=filename) == expected


def test_audio_is_parked_not_parsed_into_garbage():
    parsed = ParserService().parse_event(_event("aud_1", "call.mp3", "audio/mpeg"), raw_bytes=b"\x00\x01\xff\xfe")
    assert parsed.parse_status == MEDIA_PENDING
    assert parsed.parser_used == "media_pending"
    # Crucially: no decoded binary noise gets handed to the chunker.
    assert parsed.text_content == ""
    assert parsed.metadata.get("media_pending") is True


def test_video_is_parked():
    parsed = ParserService().parse_event(_event("vid_1", "demo.mp4", "video/mp4"), raw_bytes=b"\x00\x01")
    assert parsed.parse_status == MEDIA_PENDING


def test_parked_media_lands_on_the_queue():
    ParserService().parse_event(_event("aud_2", "notes.m4a", "audio/mp4"), raw_bytes=b"\x00")
    job = media_job_queue.get("tenant_media:gdrive:aud_2")
    assert job is not None
    assert job.status == "PENDING"
    assert job.mime_type == "audio/mp4"


def test_queue_lists_and_counts_pending():
    queue = MediaJobQueue()
    queue.enqueue(MediaJob(doc_id="d1", tenant_id="t1", user_id="u", source="gdrive",
                           external_id="e1", mime_type="audio/mpeg"))
    assert queue.pending_count("t1") == 1
    assert queue.pending_count("other") == 0


def test_transcription_is_explicitly_unavailable():
    worker = TranscriptionWorker()
    assert worker.available() is False
    with pytest.raises(NotImplementedError):
        worker.transcribe(MediaJob(doc_id="d", tenant_id="t", user_id="u", source="s",
                                   external_id="e", mime_type="audio/mpeg"))
