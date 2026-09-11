"""Phase 3 write tools against doubles of Composio and data-pipeline: the provider arguments each
tool sends, what it reports, and that its undo reverses exactly what it did."""

from __future__ import annotations

import io
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

import pytest

from app.core.clock import utcnow
from app.core.context import AgentContext, RunMode
from app.platform.composio_client import ConnectorError, ConnectorOutcomeUnknown
from app.tools.adapters.catalog_writes import catalog_write_tools
from app.tools.adapters.documents import document_tools
from app.tools.adapters.google_calendar import calendar_tools
from app.tools.adapters.notion import notion_tools
from app.tools.adapters.quotes import CreateQuoteArgs, QuoteLineArgs, price_lines, quote_document, quote_tools
from app.tools.adapters.slack import slack_tools
from app.tools.documents.storage import DocumentStore
from app.tools.registry import ToolDefinition
from app.tools.types import (
    ToolAccessDenied,
    ToolFailed,
    ToolInputError,
    ToolInvocation,
    ToolOutcomeUnknown,
    UndoInvocation,
)
from tests.fake_data_pipeline import MAIN_WAREHOUSE, STORE, FakeDataPipeline, price_of, stock_of
from tests.support import FakeConnector

CTX = AgentContext(tenant_id=uuid4(), user_id=uuid4(), session_id=uuid4(), mode=RunMode.INTERACTIVE, turn=1)


class Directory:
    def __init__(self, role: str | None = "MEMBER") -> None:
        self.role = role

    async def role_in(self, user_id: UUID, tenant_id: UUID) -> str | None:
        return self.role


def _tool(tools: list[ToolDefinition], name: str) -> ToolDefinition:
    return next(tool for tool in tools if tool.name == name)


async def _run(definition: ToolDefinition, arguments: dict[str, Any], *, call_id: str = "c1"):
    args = definition.input_model.model_validate(arguments)
    if definition.acl is not None:
        await definition.acl(CTX, args)
    preview = await definition.build_preview(CTX, args)
    output = await definition.handler(ToolInvocation(CTX, "orchestrator", call_id, args))
    return preview, output


async def _undo(definition: ToolDefinition, output) -> str:
    assert output.undo is not None and definition.undo_handler is not None
    return await definition.undo_handler(UndoInvocation(CTX, output.undo.args))


# --------------------------------------------------------------------------- calendar


async def test_calendar_event_is_created_in_the_given_time_zone_and_undo_cancels_it():
    connector = FakeConnector(responses={"GOOGLECALENDAR_CREATE_EVENT": {"response_data": {"id": "evt-1", "htmlLink": "https://calendar.google.com/e/1"}}})
    create = _tool(calendar_tools(connector), "create_calendar_event")
    start = (utcnow() + timedelta(days=2)).replace(hour=15, minute=0, second=0, microsecond=0, tzinfo=None)

    preview, output = await _run(
        create,
        {"title": "Acme demo", "start": start.isoformat(), "time_zone": "Asia/Kolkata", "duration_minutes": 45,
         "attendees": ["jane@acme.test"], "add_video_link": True},
    )

    assert preview["kind"] == "calendar_event" and preview["time_zone"] == "Asia/Kolkata"
    [call] = connector.executions
    assert call["slug"] == "GOOGLECALENDAR_CREATE_EVENT"
    assert call["arguments"] == {
        "calendar_id": "primary",
        "summary": "Acme demo",
        "start_datetime": start.isoformat(timespec="seconds"),
        "end_datetime": (start + timedelta(minutes=45)).isoformat(timespec="seconds"),
        "timezone": "Asia/Kolkata",
        "attendees": ["jane@acme.test"],
        "create_meeting_room": True,
        "send_updates": "all",
    }
    assert output.ref_id == "evt-1" and output.sources[0].url == "https://calendar.google.com/e/1"
    assert "cancellation" in output.undo.label

    assert await _undo(create, output) == "calendar event evt-1 deleted"
    assert connector.executions[-1] == {
        "user_id": CTX.user_id,
        "slug": "GOOGLECALENDAR_DELETE_EVENT",
        "arguments": {"calendar_id": "primary", "event_id": "evt-1", "send_updates": "all"},
    }


async def test_an_aware_start_time_is_converted_to_the_events_zone():
    connector = FakeConnector(responses={"GOOGLECALENDAR_CREATE_EVENT": {"response_data": {"id": "evt-2"}}})
    create = _tool(calendar_tools(connector), "create_calendar_event")
    start = (utcnow() + timedelta(days=3)).replace(hour=9, minute=30, second=0, microsecond=0)

    await _run(create, {"title": "Sync", "start": start.isoformat(), "time_zone": "America/New_York"})

    local = start.astimezone(__import__("zoneinfo").ZoneInfo("America/New_York")).replace(tzinfo=None)
    assert connector.executions[0]["arguments"]["start_datetime"] == local.isoformat(timespec="seconds")
    assert connector.executions[0]["arguments"]["send_updates"] == "none"  # nobody to notify


@pytest.mark.parametrize(
    ("arguments", "message"),
    [
        ({"start": "2030-01-01T10:00:00"}, "time_zone"),
        ({"start": "2030-01-01T10:00:00", "time_zone": "Mars/Olympus"}, "not a known IANA time zone"),
        ({"start": "2030-01-01T10:00:00+00:00", "end": "2030-01-01T09:00:00+00:00"}, "end after it starts"),
        ({"start": "2020-01-01T10:00:00+00:00"}, "in the past"),
    ],
)
async def test_unusable_event_times_are_refused_before_approval(arguments, message):
    create = _tool(calendar_tools(FakeConnector()), "create_calendar_event")
    args = create.input_model.model_validate({"title": "Demo", **arguments})
    with pytest.raises(ToolInputError, match=message):
        await create.build_preview(CTX, args)


async def test_deleting_an_event_that_is_already_gone_counts_as_undone():
    connector = FakeConnector(failures={"GOOGLECALENDAR_DELETE_EVENT": ConnectorError("GOOGLECALENDAR_DELETE_EVENT failed: 410 Resource has been deleted")})
    create = _tool(calendar_tools(connector), "create_calendar_event")
    result = await create.undo_handler(UndoInvocation(CTX, {"event_id": "evt-9", "notify": False}))
    assert result == "calendar event evt-9 was already deleted"


async def test_a_calendar_write_without_an_answer_is_unknown():
    connector = FakeConnector(failures={"GOOGLECALENDAR_CREATE_EVENT": ConnectorOutcomeUnknown("timed out")})
    create = _tool(calendar_tools(connector), "create_calendar_event")
    with pytest.raises(ToolOutcomeUnknown):
        await _run(create, {"title": "Demo", "start": "2030-01-01T10:00:00+00:00"})


# --------------------------------------------------------------------------- slack + notion


async def test_slack_message_is_posted_and_undo_deletes_it_by_channel_id_and_ts():
    connector = FakeConnector(responses={"SLACK_SEND_MESSAGE": {"channel": "C0123ABCD", "ts": "1757000000.000100", "message": {"text": "hi"}}})
    send = _tool(slack_tools(connector), "send_slack_message")

    preview, output = await _run(send, {"channel": "#sales", "text": "Acme signed :tada:"})

    assert preview == {"kind": "slack_message", "channel": "sales", "text": "Acme signed :tada:", "thread_ts": None}
    assert connector.executions[0]["arguments"] == {"channel": "sales", "markdown_text": "Acme signed :tada:"}
    assert output.summary == "Slack message posted to #sales"
    assert output.undo.args == {"channel": "C0123ABCD", "ts": "1757000000.000100"}

    assert await _undo(send, output) == "Slack message deleted"
    assert connector.executions[-1]["slug"] == "SLACK_DELETES_A_MESSAGE_FROM_A_CHAT"
    assert connector.executions[-1]["arguments"] == {"channel": "C0123ABCD", "ts": "1757000000.000100"}


async def test_a_slack_post_without_ids_in_the_answer_cannot_be_undone():
    connector = FakeConnector(responses={"SLACK_SEND_MESSAGE": {"ok": True}})
    _, output = await _run(_tool(slack_tools(connector), "send_slack_message"), {"channel": "sales", "text": "hi"})
    assert output.undo is None


async def test_notion_page_is_created_under_its_parent_and_undo_archives_it():
    parent = "59833787-2cf9-4fdf-8782-e53db20768a5"
    connector = FakeConnector(responses={"NOTION_CREATE_NOTION_PAGE": {"response_data": {"id": "page-1", "url": "https://www.notion.so/page-1"}}})
    create = _tool(notion_tools(connector), "create_notion_page")

    _, output = await _run(create, {"parent_page_id": parent, "title": "Acme call notes", "content": "# Notes\n- budget ok"})

    assert connector.executions[0]["arguments"] == {"parent_id": parent, "title": "Acme call notes", "markdown": "# Notes\n- budget ok"}
    assert output.sources[0].url == "https://www.notion.so/page-1"
    await _undo(create, output)
    assert connector.executions[-1]["arguments"] == {"page_id": "page-1", "archive": True}


# --------------------------------------------------------------------------- documents


def _store(connector: FakeConnector | None, pipeline: FakeDataPipeline, *, max_bytes: int = 5_000_000) -> DocumentStore:
    return DocumentStore(connector=connector, data_pipeline=pipeline.client(), vault_link="/salesman/knowledge-vault", max_bytes=max_bytes)


DOCUMENT = {
    "title": "Acme proposal",
    "format": "docx",
    "sections": [
        {"heading": "Summary", "paragraphs": ["We propose **RoleSync Pro**."], "bullets": ["Fast", "Secure"]},
        {"heading": "Pricing", "table": {"columns": ["SKU", "Price"], "rows": [["PRO-1", "49.00"]]}},
    ],
}


async def test_documents_go_to_google_drive_when_it_is_connected():
    connector = FakeConnector(
        responses={
            "GOOGLEDRIVE_GET_ABOUT": {"storageQuota": {"limit": "15000000000", "usage": "1000"}},
            "GOOGLEDRIVE_UPLOAD_FILE": {"response_data": {"id": "file-1", "name": "Acme proposal.docx", "webViewLink": "https://drive.google.com/file/d/file-1/view"}},
        }
    )
    pipeline = FakeDataPipeline()
    generate = _tool(document_tools(_store(connector, pipeline)), "generate_document")

    preview, output = await _run(generate, DOCUMENT)

    assert preview["destination"] == "Google Drive" and preview["file_name"] == "Acme proposal.docx"
    [staged] = connector.staged
    assert staged["filename"] == "Acme proposal.docx" and staged["mimetype"].endswith("wordprocessingml.document")
    from docx import Document as WordDocument

    text = "\n".join(p.text for p in WordDocument(io.BytesIO(staged["content"])).paragraphs)
    assert "We propose RoleSync Pro." in text and "**" not in text
    upload = next(e for e in connector.executions if e["slug"] == "GOOGLEDRIVE_UPLOAD_FILE")
    assert upload["arguments"] == {"file_to_upload": {"name": "Acme proposal.docx", "mimetype": staged["mimetype"], "s3key": "staged/1/Acme proposal.docx"}}
    assert output.data["saved_to"] == "google_drive" and output.sources[0].url.endswith("/file-1/view")
    assert output.undo.label == "Move the document 'Acme proposal.docx' to the Google Drive trash"
    assert pipeline.documents == {}

    assert await _undo(generate, output) == "'Acme proposal.docx' moved to the Google Drive trash"
    assert connector.executions[-1]["arguments"] == {"file_id": "file-1"}


@pytest.mark.parametrize(
    "connector",
    [
        FakeConnector(connected={"gmail"}),  # Drive not connected
        FakeConnector(responses={"GOOGLEDRIVE_GET_ABOUT": {"storageQuota": {"limit": "1000", "usage": "999"}}}),  # full
        FakeConnector(failures={"GOOGLEDRIVE_UPLOAD_FILE": ConnectorError("GOOGLEDRIVE_UPLOAD_FILE failed: storageQuotaExceeded")}),
        None,  # Composio not configured
    ],
    ids=["not-connected", "quota-full", "upload-says-full", "no-composio"],
)
async def test_documents_fall_back_to_the_knowledge_base(connector):
    pipeline = FakeDataPipeline()
    generate = _tool(document_tools(_store(connector, pipeline)), "generate_document")

    _, output = await _run(generate, {**DOCUMENT, "format": "pdf"})

    [(doc_id, document)] = pipeline.documents.items()
    assert document["name"] == "Acme proposal.pdf"
    assert output.data["saved_to"] == "knowledge_base" and output.data["note"]
    assert output.sources[0].url == f"/salesman/knowledge-vault?doc={doc_id}"
    assert "knowledge base" in output.summary

    assert await _undo(generate, output) == "'Acme proposal.pdf' deleted from the knowledge base"
    assert pipeline.documents == {}
    assert await _undo(generate, output) == "'Acme proposal.pdf' was already gone from the knowledge base"


async def test_a_viewer_cannot_fall_back_to_the_knowledge_base():
    pipeline = FakeDataPipeline(forbid_writes=True)
    generate = _tool(document_tools(_store(FakeConnector(connected=False), pipeline)), "generate_document")
    with pytest.raises(ToolFailed, match="can't add documents"):
        await _run(generate, DOCUMENT)


async def test_oversized_documents_are_refused():
    generate = _tool(document_tools(_store(None, FakeDataPipeline(), max_bytes=100)), "generate_document")
    with pytest.raises(ToolInputError, match="limit"):
        await _run(generate, DOCUMENT)


def test_table_rows_cannot_have_more_cells_than_columns():
    generate = _tool(document_tools(_store(None, FakeDataPipeline())), "generate_document")
    bad = {**DOCUMENT, "sections": [{"table": {"columns": ["A"], "rows": [["1", "2"]]}}]}
    with pytest.raises(ValueError, match="row 1 has 2 cells"):
        generate.input_model.model_validate(bad)


# --------------------------------------------------------------------------- catalog writes


def _catalog(pipeline: FakeDataPipeline, role: str | None = "MEMBER") -> list[ToolDefinition]:
    return catalog_write_tools(pipeline.client(), Directory(role))


async def test_price_and_detail_changes_record_what_they_replaced_and_undo_restores_it():
    pipeline = FakeDataPipeline()
    product = pipeline.add_product(name="RoleSync Pro", sku="PRO-1", price="49.00", max_discount_pct="10.00")
    update = _tool(_catalog(pipeline), "update_catalog_item")

    preview, output = await _run(
        update,
        {"product_id": product["id"], "max_discount_pct": 15, "description": "Now with AI", "prices": [{"sku": "PRO-1", "price": 59}]},
    )

    assert preview["changes"] == [
        {"field": "description", "before": "RoleSync Pro description", "after": "Now with AI"},
        {"field": "max_discount_pct", "before": "10.00", "after": "15.00"},
    ]
    assert preview["price_changes"] == [{"sku": "PRO-1", "before": "49.00", "after": "59.00", "currency": "USD"}]
    put = next(body for method, path, body in pipeline.requests if method == "PUT")
    assert put == {"description": "Now with AI", "max_discount_pct": "15.00"}  # only what changed
    # The variant upsert overwrites every field, so the full current state is sent.
    [upsert] = [body for method, path, body in pipeline.requests if path.endswith("/variants")]
    variant = product["variants"][0]
    assert upsert["variants"][0]["barcode"] == "BAR-PRO-1" and upsert["variants"][0]["weight"] == "1.50"
    assert upsert["variants"][0]["option_value_ids"] == [variant["option_values"][0]["id"]]
    assert price_of(pipeline, "PRO-1") == Decimal("59.00") and product["max_discount_pct"] == "15.00"

    await _undo(update, output)
    assert price_of(pipeline, "PRO-1") == Decimal("49.00")
    assert product["max_discount_pct"] == "10.00" and product["description"] == "RoleSync Pro description"
    assert [v["id"] for v in product["variants"][0]["option_values"]] == [variant["option_values"][0]["id"]]


async def test_an_update_that_changes_nothing_is_refused():
    pipeline = FakeDataPipeline()
    product = pipeline.add_product(name="RoleSync Pro", sku="PRO-1", price="49.00")
    update = _tool(_catalog(pipeline), "update_catalog_item")
    with pytest.raises(ToolInputError, match="nothing to change"):
        await _run(update, {"product_id": product["id"], "prices": [{"sku": "PRO-1", "price": 49}]})


async def test_stock_is_set_at_a_named_location_and_undo_puts_the_old_count_back():
    pipeline = FakeDataPipeline()
    pipeline.locations.append({"id": STORE, "name": "Downtown store", "sellable": True, "priority": 2})
    pipeline.add_product(name="Tee", sku="TEE-M", price="20.00", on_hand=30, location=STORE)
    set_stock = _tool(_catalog(pipeline), "set_stock")

    preview, output = await _run(set_stock, {"sku": "TEE-M", "quantity": 45, "location": "downtown store", "reason": "RESTOCK"})

    assert (preview["before"], preview["after"], preview["location"]) == (30, 45, "Downtown store")
    assert stock_of(pipeline, "TEE-M", STORE)["on_hand"] == 45
    await _undo(set_stock, output)
    assert stock_of(pipeline, "TEE-M", STORE)["on_hand"] == 30


async def test_stock_changes_need_a_location_when_there_are_several_and_cannot_go_below_reservations():
    pipeline = FakeDataPipeline()
    pipeline.locations.append({"id": STORE, "name": "Downtown store", "sellable": True, "priority": 2})
    pipeline.add_product(name="Tee", sku="TEE-M", price="20.00", on_hand=30)
    tools = _catalog(pipeline)
    with pytest.raises(ToolInputError, match="say which stock location"):
        await _run(_tool(tools, "set_stock"), {"sku": "TEE-M", "quantity": 10})
    await _run(_tool(tools, "reserve_stock"), {"sku": "TEE-M", "quantity": 20})
    with pytest.raises(ToolInputError, match="reserved"):
        await _run(_tool(tools, "set_stock"), {"sku": "TEE-M", "quantity": 10, "location": "Main warehouse"})


async def test_a_reservation_is_undone_by_releasing_it_once():
    pipeline = FakeDataPipeline()
    pipeline.add_product(name="Tee", sku="TEE-M", price="20.00", on_hand=10)
    reserve = _tool(_catalog(pipeline), "reserve_stock")

    preview, output = await _run(reserve, {"sku": "TEE-M", "quantity": 4})

    assert preview["available"] == 10 and stock_of(pipeline, "TEE-M")["reserved"] == 4
    assert output.undo.label == "Release the reservation of 4 × TEE-M"
    await _undo(reserve, output)
    assert stock_of(pipeline, "TEE-M")["reserved"] == 0
    assert "already released" in await _undo(reserve, output)  # safe to repeat


async def test_reserving_more_than_is_available_is_refused_before_approval():
    pipeline = FakeDataPipeline()
    pipeline.add_product(name="Tee", sku="TEE-M", price="20.00", on_hand=3)
    reserve = _tool(_catalog(pipeline), "reserve_stock")
    with pytest.raises(ToolInputError, match="only 3"):
        await reserve.build_preview(CTX, reserve.input_model.model_validate({"sku": "TEE-M", "quantity": 5}))


async def test_retiring_an_item_can_be_undone_with_its_skus():
    pipeline = FakeDataPipeline()
    product = pipeline.add_product(name="Legacy plan", sku="OLD-1", price="10.00")
    retire = _tool(_catalog(pipeline), "retire_catalog_item")

    _, output = await _run(retire, {"product_id": product["id"]})

    assert product["status"] == "RETIRED" and product["variants"][0]["status"] == "RETIRED"
    assert not any(method == "DELETE" and "permanent" in path for method, path, _ in pipeline.requests)
    await _undo(retire, output)
    assert product["status"] == "ACTIVE" and product["variants"][0]["status"] == "ACTIVE"


async def test_new_items_need_an_existing_category_and_unused_skus_and_undo_retires_them():
    pipeline = FakeDataPipeline()
    pipeline.add_product(name="Existing", sku="TAKEN-1", price="5.00")
    create = _tool(_catalog(pipeline), "create_catalog_item")
    item = {"name": "Onboarding package", "type": "SERVICE", "category": "software", "status": "ACTIVE", "max_discount_pct": 10,
            "variants": [{"sku": "ONB-1", "price": 499}]}

    with pytest.raises(ToolInputError, match="not a catalog category"):
        await _run(create, {**item, "category": "hardware"})
    with pytest.raises(ToolInputError, match="TAKEN-1"):
        await _run(create, {**item, "variants": [{"sku": "TAKEN-1", "price": 1}]})

    _, output = await _run(create, item)
    created = pipeline.products[output.ref_id]
    assert created["status"] == "ACTIVE" and created["variants"][0]["sku"] == "ONB-1"
    assert created["max_discount_pct"] == "10.00"
    await _undo(create, output)
    assert created["status"] == "RETIRED"


async def test_viewers_cannot_change_the_catalog():
    pipeline = FakeDataPipeline()
    product = pipeline.add_product(name="RoleSync Pro", sku="PRO-1", price="49.00")
    retire = _tool(_catalog(pipeline, role="VIEWER"), "retire_catalog_item")
    with pytest.raises(ToolAccessDenied, match="viewers"):
        await _run(retire, {"product_id": product["id"]})
    assert product["status"] == "ACTIVE"


# --------------------------------------------------------------------------- quotes


def _quote_args(**overrides: Any) -> CreateQuoteArgs:
    base = {"customer_company": "Acme", "items": [{"sku": "PRO-1", "quantity": 3, "discount_pct": 10}]}
    return CreateQuoteArgs.model_validate({**base, **overrides})


def _catalog_entry(price: str, *, max_pct: str = "15.00", currency: str = "USD", status: str = "ACTIVE", type: str = "PRODUCT"):
    variant = {"sku": "X", "price": price, "currency": currency, "status": status}
    product = {"name": "RoleSync Pro", "status": status, "type": type, "max_discount_pct": max_pct}
    return variant, product


def test_quote_totals_use_catalog_prices_and_round_each_line_to_cents():
    items = [QuoteLineArgs(sku="PRO-1", quantity=3, discount_pct=12.5), QuoteLineArgs(sku="ADD-1", quantity=1)]
    catalog = {"PRO-1": _catalog_entry("33.33"), "ADD-1": _catalog_entry("10.00", type="SERVICE")}
    quote = price_lines(items, catalog, {"PRO-1": 100}, reserve_stock=False, issued=datetime(2026, 9, 12).date(), valid_days=30)

    pro, add = quote.lines
    assert (pro.subtotal, pro.discount, pro.total) == (Decimal("99.99"), Decimal("12.50"), Decimal("87.49"))
    assert add.available is None  # services have no stock
    assert (quote.subtotal, quote.discount, quote.total) == (Decimal("109.99"), Decimal("12.50"), Decimal("97.49"))
    assert quote.valid_until.isoformat() == "2026-10-12" and quote.warnings == ()


def test_quote_problems_are_all_reported_together():
    items = [
        QuoteLineArgs(sku="PRO-1", quantity=1, discount_pct=40),
        QuoteLineArgs(sku="GONE", quantity=1),
        QuoteLineArgs(sku="OLD", quantity=1),
    ]
    catalog = {"PRO-1": _catalog_entry("10.00"), "GONE": None, "OLD": _catalog_entry("5.00", status="RETIRED")}
    with pytest.raises(ToolInputError) as caught:
        price_lines(items, catalog, {}, reserve_stock=False, issued=datetime(2026, 9, 12).date(), valid_days=30)
    message = str(caught.value)
    assert "above its discount limit of 15.00%" in message and "no SKU 'GONE'" in message and "not an active" in message


def test_short_stock_is_a_warning_unless_the_quote_reserves_it():
    items = [QuoteLineArgs(sku="PRO-1", quantity=5)]
    catalog = {"PRO-1": _catalog_entry("10.00")}
    quote = price_lines(items, catalog, {"PRO-1": 2}, reserve_stock=False, issued=datetime(2026, 9, 12).date(), valid_days=7)
    assert quote.warnings == ("only 2 of 5 × 'RoleSync Pro' (PRO-1) in stock",)
    with pytest.raises(ToolInputError, match="only 2 of 5"):
        price_lines(items, catalog, {"PRO-1": 2}, reserve_stock=True, issued=datetime(2026, 9, 12).date(), valid_days=7)


def test_mixed_currencies_cannot_share_a_quote():
    items = [QuoteLineArgs(sku="A", quantity=1), QuoteLineArgs(sku="B", quantity=1)]
    catalog = {"A": _catalog_entry("1.00"), "B": _catalog_entry("1.00", currency="EUR")}
    with pytest.raises(ToolInputError, match="different currencies"):
        price_lines(items, catalog, {"A": 9, "B": 9}, reserve_stock=False, issued=datetime(2026, 9, 12).date(), valid_days=7)


def test_the_quote_document_lists_lines_totals_and_validity():
    catalog = {"PRO-1": _catalog_entry("49.00")}
    args = _quote_args(customer_contact="Jane", customer_email="jane@acme.test")
    quote = price_lines(args.items, catalog, {"PRO-1": 9}, reserve_stock=False, issued=datetime(2026, 9, 12).date(), valid_days=30)
    document = quote_document("Q-20260912-ABC123", quote, args)
    assert document.title == "Quote Q-20260912-ABC123" and document.subtitle == "Prepared for Acme"
    items = next(section for section in document.sections if section.heading == "Items").table
    assert items.rows == (("PRO-1", "RoleSync Pro", 3, "USD 49.00", "10%", "USD 132.30"),)
    totals = next(section for section in document.sections if section.heading == "Summary").table.rows
    assert totals[-1] == ("Total", "USD 132.30")


async def test_a_quote_is_priced_saved_and_can_hold_stock_and_undo_releases_it():
    pipeline = FakeDataPipeline()
    pipeline.add_product(name="RoleSync Pro", sku="PRO-1", price="49.00", max_discount_pct="15.00", on_hand=10)
    connector = FakeConnector(connected=False)  # saved to the knowledge base
    tools = quote_tools(pipeline.client(), _store(connector, pipeline), Directory())
    create = _tool(tools, "create_quote")

    preview, output = await _run(create, {**_quote_args().model_dump(), "reserve_stock": True, "format": "xlsx"})

    assert preview["total"] == "132.30" and preview["destination"] == "the workspace knowledge base"
    assert output.data["quote_number"].startswith("Q-") and output.data["total"] == "132.30"
    assert stock_of(pipeline, "PRO-1")["reserved"] == 3
    [document] = pipeline.documents.values()
    assert document["name"].startswith("Quote Q-") and document["name"].endswith(" - Acme.xlsx")
    assert "release the reserved stock" in output.undo.label

    # Same call → same quote number (a replay can never produce a second number).
    _, again = await _run(create, {**_quote_args().model_dump(), "format": "xlsx"})
    assert again.data["quote_number"] == output.data["quote_number"]

    result = await _undo(create, output)
    assert "released 1 reservation" in result
    assert stock_of(pipeline, "PRO-1")["reserved"] == 0
    assert output.data["file_id"] not in pipeline.documents


async def test_a_quote_that_cannot_be_saved_releases_the_stock_it_reserved():
    pipeline = FakeDataPipeline(failures={("POST", "/api/v1/knowledge-vault/upload"): 500})
    pipeline.add_product(name="RoleSync Pro", sku="PRO-1", price="49.00", on_hand=10)
    create = _tool(quote_tools(pipeline.client(), _store(None, pipeline), Directory()), "create_quote")
    with pytest.raises(ToolFailed):
        await _run(create, {**_quote_args(items=[{"sku": "PRO-1", "quantity": 2}]).model_dump(), "reserve_stock": True})
    assert stock_of(pipeline, "PRO-1")["reserved"] == 0


async def test_viewers_can_quote_but_not_reserve():
    pipeline = FakeDataPipeline()
    pipeline.add_product(name="RoleSync Pro", sku="PRO-1", price="49.00", on_hand=10)
    create = _tool(quote_tools(pipeline.client(), _store(None, pipeline), Directory("VIEWER")), "create_quote")
    with pytest.raises(ToolAccessDenied, match="reserve"):
        await create.acl(CTX, _quote_args(reserve_stock=True))
    await create.acl(CTX, _quote_args())  # no reservation: allowed


def test_warehouse_constant_is_the_default_location():
    assert FakeDataPipeline().locations[0]["id"] == MAIN_WAREHOUSE
