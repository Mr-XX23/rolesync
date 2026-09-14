"""Knowledge-base tools against a data-pipeline double: listing every document, adding web pages, correcting
and redoing classifications, re-indexing, and deleting only what the rep may, each undone where it can be."""

from __future__ import annotations

from typing import Any
from uuid import UUID, uuid4

import pytest

from app.core.context import AgentContext, RunMode
from app.tools.adapters.knowledge import knowledge_tools
from app.tools.adapters.knowledge_writes import knowledge_write_tools
from app.tools.registry import ToolDefinition
from app.tools.types import ToolAccessDenied, ToolFailed, ToolInputError, ToolInvocation, UndoInvocation
from tests.fake_data_pipeline import FakeDataPipeline

REP, COLLEAGUE = uuid4(), uuid4()
CTX = AgentContext(tenant_id=uuid4(), user_id=REP, session_id=uuid4(), mode=RunMode.INTERACTIVE, turn=1)


class Directory:
    def __init__(self, role: str | None = "MEMBER") -> None:
        self.role = role

    async def role_in(self, user_id: UUID, tenant_id: UUID) -> str | None:
        return self.role


def _tools(pipeline: FakeDataPipeline, role: str | None = "MEMBER", *, settle_seconds: float = 40.0) -> dict[str, ToolDefinition]:
    async def processing_finishes(seconds: float) -> None:
        """While the tool waits, data-pipeline finishes processing whatever it was working on."""
        pipeline.requests.append(("SLEEP", str(seconds), None))
        for doc in pipeline.documents.values():
            if doc["status"] == "Parsing":
                doc.update(status="Indexed", chunks=3)

    client = pipeline.client()
    writes = knowledge_write_tools(
        client, Directory(role), vault_link="/salesman/knowledge-vault", settle_seconds=settle_seconds, sleep=processing_finishes
    )
    return {definition.name: definition for definition in [*knowledge_tools(client), *writes]}


async def _run(tool: ToolDefinition, arguments: dict[str, Any]):
    """ACL, then the approval preview, then the handler: the order the gate runs a write in."""
    args = tool.input_model.model_validate(arguments)
    if tool.acl is not None:
        await tool.acl(CTX, args)
    preview = await tool.build_preview(CTX, args)
    return preview, await tool.handler(ToolInvocation(CTX, "orchestrator", "c1", args))


async def _undo(tool: ToolDefinition, output) -> str:
    assert output.undo is not None and tool.undo_handler is not None
    return await tool.undo_handler(UndoInvocation(CTX, output.undo.args))


def _sent(pipeline: FakeDataPipeline, method: str, suffix: str) -> list[Any]:
    return [body for verb, path, body in pipeline.requests if verb == method and path.endswith(suffix)]


# --------------------------------------------------------------------------- listing


async def test_listing_shows_every_state_why_a_document_is_not_searchable_and_who_added_it():
    pipeline = FakeDataPipeline()
    pipeline.add_document(name="Globex battlecard", user_id=REP, category="BATTLECARD", target_competitor="Globex")
    pipeline.add_document(name="Scanned contract.pdf", user_id=COLLEAGUE, status="Error", chunks=0, error_message="No text could be read")
    pipeline.add_document(
        name="Globex pricing page", user_id=REP, status="Parsing", type="URL", source="URL_INGEST",
        metadata={"target_url": "https://globex.test/pricing"},
    )
    listing = _tools(pipeline)["list_knowledge_documents"]

    output = await listing.handler(ToolInvocation(CTX, "orchestrator", "c1", listing.input_model.model_validate({})))

    assert output.data["total"] == 3 and output.data["by_status"] == {"Indexed": 1, "Error": 1, "Parsing": 1}
    page, scanned, battlecard = output.data["documents"]  # newest first
    assert (page["source"], page["url"], page["added_by_me"]) == ("web page", "https://globex.test/pricing", True)
    assert scanned["problem"] == "No text could be read" and scanned["added_by_me"] is False
    assert battlecard["competitor"] == "Globex" and "problem" not in battlecard
    assert not any("user_id" in doc for doc in output.data["documents"])  # colleagues are never named by id
    assert "(1 not searchable)" in output.summary

    async def names(**filters: Any) -> list[str]:
        found = await listing.handler(ToolInvocation(CTX, "orchestrator", "c2", listing.input_model.model_validate(filters)))
        return [doc["name"] for doc in found.data["documents"]]

    assert await names(status="Error") == ["Scanned contract.pdf"]
    assert await names(status="Error", added_by_me=True) == []  # the rep's own failed documents: none
    assert await names(category="BATTLECARD") == ["Globex battlecard"]


# --------------------------------------------------------------------------- web pages


async def test_a_web_page_is_added_after_approval_and_undo_deletes_it():
    pipeline = FakeDataPipeline()
    add = _tools(pipeline)["add_web_page_to_knowledge_base"]

    preview, output = await _run(
        add, {"url": " https://globex.test/pricing ", "title": "Globex pricing", "category": "PRICING_PACKAGING", "competitor": "Globex"}
    )

    assert preview == {
        "kind": "knowledge_add_url", "url": "https://globex.test/pricing", "site": "globex.test", "title": "Globex pricing",
        "category": "PRICING_PACKAGING", "competitor": "Globex", "existing": None,
    }
    [sent] = _sent(pipeline, "POST", "/ingest-url")
    assert sent == {"url": "https://globex.test/pricing", "title": "Globex pricing", "category": "PRICING_PACKAGING", "target_competitor": "Globex"}
    [(doc_id, document)] = pipeline.documents.items()
    assert document["user_id"] == str(REP) and output.data["refreshed"] is False
    assert output.sources[0].url == f"/salesman/knowledge-vault?doc={doc_id}"
    assert output.undo.label == "Delete 'Globex pricing' from the knowledge base"

    del pipeline.requests[:]
    assert await _undo(add, output) == "'Globex pricing' deleted from the knowledge base"
    # Undoing straight away waits for processing to finish, so no half-written index is left behind.
    assert [verb for verb, _, _ in pipeline.requests] == ["GET", "SLEEP", "GET", "DELETE"]
    assert pipeline.documents == {}
    assert await _undo(add, output) == "'Globex pricing' was already gone from the knowledge base"


async def test_undoing_a_new_page_deletes_it_even_if_processing_takes_too_long():
    pipeline = FakeDataPipeline()
    add = _tools(pipeline, settle_seconds=0)["add_web_page_to_knowledge_base"]
    _, output = await _run(add, {"url": "https://globex.test/pricing"})

    assert await _undo(add, output) == "'https://globex.test/pricing' deleted from the knowledge base"
    assert pipeline.documents == {} and "SLEEP" not in [verb for verb, _, _ in pipeline.requests]


async def test_an_address_already_in_the_knowledge_base_is_refreshed_keeping_its_name_and_classification():
    pipeline = FakeDataPipeline()
    existing = pipeline.add_document(
        name="Globex pricing", user_id=COLLEAGUE, type="URL", source="URL_INGEST", category="PRICING_PACKAGING",
        target_competitor="Globex", metadata={"target_url": "https://globex.test/pricing"},
    )
    add = _tools(pipeline)["add_web_page_to_knowledge_base"]

    preview, output = await _run(add, {"url": "https://globex.test/pricing"})

    assert preview["existing"]["doc_id"] == existing["doc_id"] and preview["existing"]["added_by_me"] is False
    assert (preview["title"], preview["category"], preview["competitor"]) == ("Globex pricing", "PRICING_PACKAGING", "Globex")
    # Without a title data-pipeline would rename the page to its address and classify it from scratch.
    [sent] = _sent(pipeline, "POST", "/ingest-url")
    assert sent == {"url": "https://globex.test/pricing", "title": "Globex pricing", "category": "PRICING_PACKAGING", "target_competitor": "Globex"}
    assert (existing["name"], existing["category"], existing["target_competitor"]) == ("Globex pricing", "PRICING_PACKAGING", "Globex")
    assert output.data["refreshed"] is True and output.data["doc_id"] == existing["doc_id"]
    assert "refreshed" in output.summary and output.undo is None  # the earlier text can't be put back
    assert len(pipeline.documents) == 1

    _, retitled = await _run(add, {"url": "https://globex.test/pricing", "title": "Globex price list", "category": "BATTLECARD"})
    assert (existing["name"], existing["category"], existing["target_competitor"]) == ("Globex price list", "BATTLECARD", "Globex")
    assert retitled.data["name"] == "Globex price list"


@pytest.mark.parametrize(
    "url",
    [
        "http://localhost:8083/api/v1/workspaces",
        "http://workspace-service:8083/api/v1/workspaces",
        "http://10.0.0.5/admin",
        "http://169.254.169.254/latest/meta-data/",
        "http://[::ffff:127.0.0.1]/",
        "http://printer.local/status",
        "ftp://files.globex.test/prices.csv",
        "https://admin:secret@globex.test/",
        "https://globex.test/pricing page",
    ],
)
async def test_addresses_that_are_not_public_web_pages_are_refused_before_approval(url):
    pipeline = FakeDataPipeline()
    add = _tools(pipeline)["add_web_page_to_knowledge_base"]
    with pytest.raises(ToolInputError):
        await add.build_preview(CTX, add.input_model.model_validate({"url": url}))
    assert not _sent(pipeline, "POST", "/ingest-url")


async def test_a_page_that_cannot_be_fetched_fails_without_leaving_a_document():
    pipeline = FakeDataPipeline(unreachable_pages={"https://globex.test/gone"})
    add = _tools(pipeline)["add_web_page_to_knowledge_base"]
    with pytest.raises(ToolFailed, match="could not fetch that page"):
        await _run(add, {"url": "https://globex.test/gone"})
    assert pipeline.documents == {}


# --------------------------------------------------------------------------- classification


async def test_classification_changes_record_what_they_replaced_and_undo_restores_it():
    pipeline = FakeDataPipeline()
    doc = pipeline.add_document(
        name="Globex battlecard", user_id=COLLEAGUE, category="BATTLECARD", target_competitor="Globex",
        sales_summary="How we beat Globex", sales_tags=["pricing"],
    )
    update = _tools(pipeline)["update_knowledge_document"]

    preview, output = await _run(
        update, {"doc_id": doc["doc_id"], "category": "PRICING_PACKAGING", "competitor": "", "tags": ["pricing", "discounts", "pricing"], "summary": "How we beat Globex"}
    )

    assert preview["changes"] == [
        {"field": "category", "before": "BATTLECARD", "after": "PRICING_PACKAGING"},
        {"field": "competitor", "before": "Globex", "after": None},
        {"field": "tags", "before": ["pricing"], "after": ["pricing", "discounts"]},
    ]  # the unchanged summary isn't sent
    assert _sent(pipeline, "PATCH", "/sales-classification") == [
        {"category": "PRICING_PACKAGING", "target_competitor": "", "sales_tags": ["pricing", "discounts"]}
    ]
    assert (doc["category"], doc["target_competitor"], doc["sales_tags"]) == ("PRICING_PACKAGING", None, ["pricing", "discounts"])
    assert output.summary == "Updated 'Globex battlecard': category BATTLECARD → PRICING_PACKAGING; competitor Globex → none; tags: pricing, discounts"

    assert await _undo(update, output) == "restored the previous classification of 'Globex battlecard'"
    assert (doc["category"], doc["target_competitor"], doc["sales_tags"]) == ("BATTLECARD", "Globex", ["pricing"])


async def test_an_update_that_changes_nothing_or_names_an_unknown_document_is_refused():
    pipeline = FakeDataPipeline()
    doc = pipeline.add_document(name="SOC 2 report", user_id=REP, category="SECURITY_COMPLIANCE")
    update = _tools(pipeline)["update_knowledge_document"]
    with pytest.raises(ToolInputError, match="nothing to change"):
        await _run(update, {"doc_id": doc["doc_id"], "category": "SECURITY_COMPLIANCE"})
    with pytest.raises(ToolInputError, match="no document 'doc_elsewhere'"):
        await _run(update, {"doc_id": "doc_elsewhere", "category": "BATTLECARD"})
    assert not _sent(pipeline, "PATCH", "/sales-classification")


async def test_classifying_again_replaces_values_set_by_hand_and_undo_puts_them_back():
    pipeline = FakeDataPipeline()
    doc = pipeline.add_document(
        name="Globex notes", user_id=REP, category="BATTLECARD", target_competitor="Initech", sales_tags=["old"],
        classifier_used="manual_user_override",
    )
    reclassify = _tools(pipeline)["reclassify_knowledge_document"]

    preview, output = await _run(reclassify, {"doc_id": doc["doc_id"]})

    assert preview["kind"] == "knowledge_reclassify" and preview["set_by_hand"] is True
    assert preview["current"]["competitor"] == "Initech"
    assert doc["category"] == "PRICING_PACKAGING" and doc["target_competitor"] == "Globex"
    assert {change["field"] for change in output.data["changes"]} == {"category", "competitor", "industry", "summary", "tags"}

    await _undo(reclassify, output)
    assert (doc["category"], doc["target_competitor"], doc["target_industry"], doc["sales_tags"]) == ("BATTLECARD", "Initech", None, ["old"])


async def test_a_document_still_being_processed_is_not_classified_indexed_or_deleted():
    pipeline = FakeDataPipeline()
    doc = pipeline.add_document(name="New upload.pdf", user_id=REP, status="Parsing", chunks=0)
    tools = _tools(pipeline)
    with pytest.raises(ToolInputError, match="still being processed"):
        await _run(tools["reclassify_knowledge_document"], {"doc_id": doc["doc_id"]})
    with pytest.raises(ToolInputError, match="already being processed"):
        await _run(tools["reindex_knowledge_document"], {"doc_id": doc["doc_id"]})
    with pytest.raises(ToolInputError, match="can be deleted once that finishes"):
        await _run(tools["delete_knowledge_document"], {"doc_id": doc["doc_id"]})
    assert set(pipeline.documents) == {doc["doc_id"]}


async def test_a_failed_document_is_indexed_again_from_its_stored_content():
    pipeline = FakeDataPipeline()
    doc = pipeline.add_document(name="Pricing.xlsx", user_id=COLLEAGUE, status="Error", chunks=0, error_message="Embedding failed")
    reindex = _tools(pipeline)["reindex_knowledge_document"]

    preview, output = await _run(reindex, {"doc_id": doc["doc_id"]})

    assert preview == {
        "kind": "knowledge_reindex", "doc_id": doc["doc_id"], "name": "Pricing.xlsx", "status": "Error", "chunks": 0,
        "problem": "Embedding failed", "source": "uploaded file",
    }
    assert doc["status"] == "Parsing" and output.data["previous_status"] == "Error" and output.undo is None


# --------------------------------------------------------------------------- deleting


async def test_members_delete_only_their_own_documents_and_a_deleted_file_cannot_be_restored():
    pipeline = FakeDataPipeline()
    theirs = pipeline.add_document(name="Colleague deck.pptx", user_id=COLLEAGUE)
    mine = pipeline.add_document(name="My notes.md", user_id=REP)
    delete = _tools(pipeline, role="MEMBER")["delete_knowledge_document"]

    with pytest.raises(ToolAccessDenied, match="only the person who added 'Colleague deck.pptx'"):
        await _run(delete, {"doc_id": theirs["doc_id"]})

    preview, output = await _run(delete, {"doc_id": mine["doc_id"]})
    assert preview["kind"] == "knowledge_delete" and preview["added_by_me"] is True and preview["restorable"] is False
    assert set(pipeline.documents) == {theirs["doc_id"]}
    assert output.undo is None and output.summary == "Deleted 'My notes.md' from the knowledge base; it can't be restored"


@pytest.mark.parametrize(("role", "allowed"), [("OWNER", True), ("ADMIN", True), ("VIEWER", False), (None, False)])
async def test_owners_and_admins_delete_any_document_and_viewers_none(role, allowed):
    pipeline = FakeDataPipeline()
    theirs = pipeline.add_document(name="Colleague deck.pptx", user_id=COLLEAGUE)
    delete = _tools(pipeline, role=role)["delete_knowledge_document"]
    if allowed:
        await _run(delete, {"doc_id": theirs["doc_id"]})
        assert pipeline.documents == {}
    else:
        with pytest.raises(ToolAccessDenied):
            await _run(delete, {"doc_id": theirs["doc_id"]})
        assert set(pipeline.documents) == {theirs["doc_id"]}


async def test_a_deleted_web_page_is_added_back_from_its_address_on_undo():
    pipeline = FakeDataPipeline()
    page = pipeline.add_document(
        name="Globex pricing", user_id=REP, type="URL", source="URL_INGEST", category="PRICING_PACKAGING",
        target_competitor="Globex", metadata={"target_url": "https://globex.test/pricing"},
    )
    delete = _tools(pipeline)["delete_knowledge_document"]

    preview, output = await _run(delete, {"doc_id": page["doc_id"]})

    assert preview["restorable"] is True and preview["url"] == "https://globex.test/pricing"
    assert pipeline.documents == {}
    assert output.undo.label == "Add the web page 'Globex pricing' back from https://globex.test/pricing"

    assert await _undo(delete, output) == "added the web page 'Globex pricing' back from https://globex.test/pricing (it is being indexed)"
    [restored] = pipeline.documents.values()
    assert (restored["category"], restored["target_competitor"], restored["metadata"]) == (
        "PRICING_PACKAGING", "Globex", {"target_url": "https://globex.test/pricing"}
    )
