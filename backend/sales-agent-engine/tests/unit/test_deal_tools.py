"""Deal tools against a workspace-service double: idempotent create, merge on concurrent edits,
undo that keeps other people's changes, and quotes linked to deals."""

from __future__ import annotations

from typing import Any
from uuid import UUID, uuid4

import httpx
import pytest

from app.core.context import AgentContext, RunMode
from app.platform.workspace_client import DealsClient
from app.tools.adapters.deals import deal_tools, link_quote, unlink_quote
from app.tools.registry import ToolDefinition
from app.tools.types import ToolAccessDenied, ToolFailed, ToolInputError, ToolInvocation, UndoInvocation
from tests.support import FakeWorkspaceService

WORKSPACE, REP = uuid4(), uuid4()
CTX = AgentContext(tenant_id=WORKSPACE, user_id=REP, session_id=uuid4(), mode=RunMode.INTERACTIVE, turn=1)


class Directory:
    def __init__(self, role: str | None = "MEMBER") -> None:
        self.role = role

    async def role_in(self, user_id: UUID, tenant_id: UUID) -> str | None:
        return self.role


def _setup(role: str = "MEMBER") -> tuple[FakeWorkspaceService, DealsClient, dict[str, ToolDefinition]]:
    service = FakeWorkspaceService()
    service.add(REP, WORKSPACE)
    service.roles[(REP, WORKSPACE)] = role
    client = DealsClient(base_url="http://workspace.test", http=httpx.AsyncClient(transport=service.transport()))
    return service, client, {tool.name: tool for tool in deal_tools(client, Directory(role))}


async def _run(tool: ToolDefinition, arguments: dict[str, Any], *, call_id: str = "3-0-c1"):
    args = tool.input_model.model_validate(arguments)
    if tool.acl is not None:
        await tool.acl(CTX, args)
    preview = await tool.build_preview(CTX, args)
    return preview, await tool.handler(ToolInvocation(CTX, "orchestrator", call_id, args))


ACME = {"title": "Acme - 50 Pro seats", "company": "Acme Corp", "stage": "QUALIFIED", "amount": 12_000,
        "next_step": "Send pricing", "contacts": [{"name": "Jane Doe", "email": "jane@acme.test", "role": "CFO"}]}


async def test_a_deal_is_created_with_an_id_that_makes_a_retry_harmless():
    service, _, tools = _setup()

    preview, output = await _run(tools["create_deal"], ACME)

    assert preview["kind"] == "deal_create" and preview["warnings"] == []
    [deal] = service.deals.values()
    assert (deal["company"], deal["stage"], deal["amount"], deal["source"]) == ("Acme Corp", "QUALIFIED", 12_000.0, "AGENT")
    assert output.ref_id == deal["deal_id"] and "USD 12,000.00" in output.summary
    assert output.sources[0].url == f"/salesman/deals?deal={deal['deal_id']}"  # the rep can open it from the transcript
    # The same call again (a replayed step) targets the same deal instead of creating another.
    await tools["create_deal"].handler(ToolInvocation(CTX, "orchestrator", "3-0-c1", tools["create_deal"].input_model.model_validate(ACME)))
    assert len(service.deals) == 1

    again, _ = await _run(tools["create_deal"], {**ACME, "title": "Acme - expansion", "company": "ACME, Inc."}, call_id="9-0-c2")
    assert again["warnings"] == ["There is already an open deal for Acme Corp: 'Acme - 50 Pro seats' (QUALIFIED)"]


async def test_an_update_changes_only_what_it_names_and_merges_with_a_concurrent_edit():
    service, _, tools = _setup()
    _, created = await _run(tools["create_deal"], ACME)
    deal_id = created.ref_id

    def teammate_edits(put_id: str, body: dict[str, Any]) -> None:
        # Between this update's read and its write, a teammate changes the next step.
        service.before_deal_put = None
        service.deals[put_id]["next_step"] = "Teammate: book a demo"
        service.deals[put_id]["version"] += 1

    service.before_deal_put = teammate_edits
    preview, output = await _run(tools["update_deal"], {"deal_id": deal_id, "stage": "PROPOSAL", "amount": 15_000})

    assert preview["changes"] == [
        {"field": "stage", "before": "QUALIFIED", "after": "PROPOSAL"},
        {"field": "amount", "before": 12_000.0, "after": 15_000.0},
    ]
    deal = service.deals[deal_id]
    assert (deal["stage"], deal["amount"]) == ("PROPOSAL", 15_000.0)
    assert deal["next_step"] == "Teammate: book a demo"  # their change survived: re-read and re-applied
    stale = [body for method, _, body in service.deal_requests if method == "PUT" and body and "expected_version" in body]
    assert len(stale) == 2  # the first write was refused (409) and retried on the new version
    assert "stage QUALIFIED → PROPOSAL" in output.summary


async def test_undoing_an_update_restores_only_fields_nobody_changed_since():
    service, _, tools = _setup()
    _, created = await _run(tools["create_deal"], ACME)
    deal_id = created.ref_id
    _, updated = await _run(tools["update_deal"], {"deal_id": deal_id, "stage": "NEGOTIATION", "next_step": "Legal review",
                                                   "add_contacts": [{"name": "Bob Lee", "email": "bob@acme.test"}]}, call_id="5-0-c3")
    service.deals[deal_id]["next_step"] = "Teammate: call Bob"  # someone else edits afterwards
    service.deals[deal_id]["version"] += 1

    result = await tools["update_deal"].undo_handler(UndoInvocation(CTX, updated.undo.args))

    deal = service.deals[deal_id]
    assert deal["stage"] == "QUALIFIED" and deal["next_step"] == "Teammate: call Bob"
    assert [contact["name"] for contact in deal["contacts"]] == ["Jane Doe"]
    assert "kept later changes to next_step" in result


async def test_undoing_a_created_deal_deletes_it_unless_it_was_changed():
    service, _, tools = _setup()
    _, created = await _run(tools["create_deal"], ACME)
    assert await tools["create_deal"].undo_handler(UndoInvocation(CTX, created.undo.args)) == "deleted the deal 'Acme - 50 Pro seats'"
    assert service.deals == {}
    assert await tools["create_deal"].undo_handler(UndoInvocation(CTX, created.undo.args)) == "the deal was already deleted"

    _, created = await _run(tools["create_deal"], ACME, call_id="7-0-c9")
    service.deals[created.ref_id]["amount"] = 99_000.0
    with pytest.raises(ToolFailed, match="changed after it was created"):
        await tools["create_deal"].undo_handler(UndoInvocation(CTX, created.undo.args))
    assert created.ref_id in service.deals


async def test_updates_that_change_nothing_or_name_a_missing_deal_are_refused_before_approval():
    _, _, tools = _setup()
    _, created = await _run(tools["create_deal"], ACME)
    update = tools["update_deal"]
    with pytest.raises(ToolInputError, match="nothing to change"):
        await update.build_preview(CTX, update.input_model.model_validate({"deal_id": created.ref_id, "stage": "QUALIFIED"}))
    with pytest.raises(ToolInputError, match="no deal"):
        await update.build_preview(CTX, update.input_model.model_validate({"deal_id": str(uuid4()), "stage": "WON"}))


async def test_viewers_cannot_change_deals():
    _, _, tools = _setup(role="VIEWER")
    with pytest.raises(ToolAccessDenied, match="viewers"):
        await _run(tools["create_deal"], ACME)


async def test_search_finds_the_workspaces_deals():
    service, _, tools = _setup()
    await _run(tools["create_deal"], ACME)
    await _run(tools["create_deal"], {**ACME, "title": "Globex pilot", "company": "Globex", "stage": "PROSPECTING"}, call_id="8-0-x")
    _, found = await _run(tools["search_deals"], {"query": "acme"})
    assert [deal["title"] for deal in found.data["deals"]] == ["Acme - 50 Pro seats"]
    assert found.data["deals"][0]["contacts"] == ["Jane Doe"]


async def test_quotes_are_linked_to_deals_and_unlinked_on_undo():
    service, client, tools = _setup()
    _, created = await _run(tools["create_deal"], ACME)
    deal_id = UUID(created.ref_id)
    quote = {"number": "Q-20260912-ABC123", "total": 132.3, "currency": "USD", "link": "/salesman/knowledge-vault?doc=d1"}

    assert await link_quote(client, CTX, deal_id, quote) is None
    assert await link_quote(client, CTX, deal_id, quote) is None  # linking again doesn't duplicate it
    assert [item["number"] for item in service.deals[str(deal_id)]["quotes"]] == ["Q-20260912-ABC123"]

    await unlink_quote(client, CTX, deal_id, "Q-20260912-ABC123")
    assert service.deals[str(deal_id)]["quotes"] == []
    await unlink_quote(client, CTX, deal_id, "Q-20260912-ABC123")  # safe to repeat
    assert await link_quote(client, CTX, uuid4(), quote) == "the deal no longer exists"
