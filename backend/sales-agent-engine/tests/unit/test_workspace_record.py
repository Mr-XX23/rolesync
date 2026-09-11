from __future__ import annotations

from uuid import uuid4

from app.engine.orchestrator import _clean_schema
from app.engine.workspace_record import (
    _sort_order,
    context_id_for,
    describe_action,
    note_id_for,
    task_id_for,
)


def test_record_ids_are_deterministic_so_redelivery_hits_the_same_row():
    session = uuid4()
    assert context_id_for(session) == context_id_for(session) != context_id_for(uuid4())
    assert task_id_for(f"{session}:3-0-c1") == task_id_for(f"{session}:3-0-c1") != task_id_for(f"{session}:3-1-c2")
    assert note_id_for(session, "answer:1") != note_id_for(session, "answer:2")


def test_timeline_order_comes_from_the_orchestrator_call_id():
    session = uuid4()
    assert _sort_order(f"{session}:4-1-call_abc") == 41
    assert _sort_order(f"{session}:12-0-x") == 120
    assert _sort_order(f"{session}:call-1") == 0  # not an orchestrator id (e.g. a test graph)


def test_actions_get_readable_timeline_names():
    name, output = describe_action("send_email", {"to": ["a@x.test", "b@x.test"], "subject": "Thanks"})
    assert (name, output) == ("Email to a@x.test, b@x.test: Thanks", "EMAIL")
    assert describe_action("create_calendar_event", {}) == ("Create calendar event", "CREATE_CALENDAR_EVENT")
    long_name, _ = describe_action("send_email", {"to": ["x@y.z"], "subject": "s" * 400})
    assert len(long_name) == 150


def test_tool_schemas_drop_cosmetic_titles_but_keep_a_title_field():
    schema = {
        "title": "Args",
        "type": "object",
        "properties": {"title": {"title": "Title", "type": "string"}, "body": {"title": "Body", "type": "string"}},
    }
    assert _clean_schema(schema) == {
        "type": "object",
        "properties": {"title": {"type": "string"}, "body": {"type": "string"}},
    }
