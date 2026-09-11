from __future__ import annotations

from uuid import uuid4

import json

from app.engine.orchestrator import _clean_schema, repair_history
from app.engine.workspace_record import (
    _clip,
    _sort_order,
    _utf16_len,
    context_id_for,
    describe_action,
    note_id_for,
    task_id_for,
)
from app.models.types import Message, Role, ToolCall


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
    assert describe_action("create_calendar_event", {"title": "Demo"}) == ("Calendar event: Demo", "CALENDAR_EVENT")
    assert describe_action("create_quote", {"customer_company": "Acme"}) == ("Quote for Acme", "QUOTE")
    assert describe_action("set_stock", {"sku": "TS-1", "quantity": 40}) == ("Set stock of TS-1 to 40", "INVENTORY_CHANGE")
    assert describe_action("undo_actions", {"action_ids": ["a", "b"]}) == ("Undo 2 completed action(s)", "UNDO")
    assert describe_action("brand_new_tool", {}) == ("Brand new tool", "BRAND_NEW_TOOL")
    long_name, _ = describe_action("send_email", {"to": ["x@y.z"], "subject": "s" * 400})
    assert len(long_name) == 150


def test_timeline_names_survive_whatever_arguments_the_model_sent():
    assert describe_action("send_email", {"to": "a@x.test", "subject": 42, "cc": [None]}) == ("Email to a@x.test:", "EMAIL")
    assert describe_action("send_email", "not an object") == ("Email to :", "EMAIL")
    assert describe_action("send_email", None) == ("Email to :", "EMAIL")


def test_clipping_counts_length_the_way_java_does():
    # workspace-service validates @Size in UTF-16 code units: an emoji is two of them.
    clipped = _clip("😀" * 100, 150)
    assert _utf16_len(clipped) <= 150 and clipped.endswith("…")
    assert _clip("😀" * 75, 150) == "😀" * 75  # exactly at the limit: untouched
    assert _clip("  plain  ", 150) == "plain"


def _call(call_id: str) -> ToolCall:
    return ToolCall(id=call_id, name="send_email", arguments={})


def test_unanswered_tool_calls_get_a_reply_before_the_history_reaches_a_model():
    history = [
        Message(role=Role.USER, content="Email Jane and Bob"),
        Message(role=Role.ASSISTANT, content="", tool_calls=(_call("c1"), _call("c2"))),
        Message(role=Role.TOOL, content='{"ok": true}', tool_call_id="c1", name="send_email"),
        # The run crashed before c2 was answered; then the rep sent another message.
        Message(role=Role.USER, content="Any update?"),
        Message(role=Role.ASSISTANT, content="", tool_calls=(_call("c3"),)),  # still pending: left open
    ]

    repaired = repair_history(history)

    assert [(m.role, m.tool_call_id) for m in repaired] == [
        (Role.USER, None),
        (Role.ASSISTANT, None),
        (Role.TOOL, "c1"),
        (Role.TOOL, "c2"),
        (Role.USER, None),
        (Role.ASSISTANT, None),
    ]
    assert json.loads(repaired[3].content)["outcome"] == "FAILED"
    assert repair_history(list(repaired)) == repaired  # a well-formed history is unchanged


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
