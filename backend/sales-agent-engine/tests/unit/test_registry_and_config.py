from __future__ import annotations

import pytest
from psycopg.conninfo import conninfo_to_dict

from app.config import Settings
from app.tools.registry import AgentScopes, ToolDefinition, ToolRegistry
from app.tools.types import ToolCategory, ToolInput, ToolKind, ToolScope
from tests.support import SideEffects, stub_registry


async def _noop(invocation):  # pragma: no cover - never called
    raise AssertionError


def _definition(**overrides) -> ToolDefinition:
    params = dict(
        name="t",
        description="d",
        kind=ToolKind.WRITE,
        scope=ToolScope.COMMUNICATION,
        category=ToolCategory.ACTION,
        input_model=ToolInput,
        handler=_noop,
    )
    params.update(overrides)
    return ToolDefinition(**params)


def test_read_tools_must_have_read_scope_and_writes_must_not():
    with pytest.raises(ValueError):
        _definition(kind=ToolKind.READ, scope=ToolScope.COMMUNICATION)
    with pytest.raises(ValueError):
        _definition(kind=ToolKind.WRITE, scope=ToolScope.READ)


def test_duplicate_tool_names_are_refused():
    registry = ToolRegistry([_definition()])
    with pytest.raises(ValueError):
        registry.register(_definition())


def test_scope_map_keeps_research_read_only():
    registry = stub_registry(SideEffects())
    scopes = AgentScopes()
    assert [d.name for d in scopes.tools_for("research", registry)] == ["lookup_facts"]
    assert {d.name for d in scopes.tools_for("outreach", registry)} == {
        "lookup_facts", "send_note", "broken_send", "unconfirmed_send"
    }
    assert scopes.tools_for("unknown-agent", registry) == []


def _full_registry() -> ToolRegistry:
    """The production tool set, built over doubles (nothing is called)."""
    from unittest.mock import AsyncMock, MagicMock

    import httpx

    from app.container import default_registry
    from app.engine.guardrails.saga import Compensator
    from tests.support import FakeConnector

    router = MagicMock()
    router.can_serve.return_value = True
    settings = Settings(tavily_api_key=None, composio_api_key=None)
    registry = default_registry(
        settings, connector=FakeConnector(), router=router, http=httpx.AsyncClient(), workspaces=AsyncMock()
    )
    registry.register(Compensator(ledger=MagicMock(), registry=registry, executor=MagicMock()).tool())
    return registry


def test_every_write_tool_shows_the_reviewer_a_preview_and_says_how_to_undo_it():
    registry = _full_registry()
    writes = {d.name: d for d in registry.all() if d.kind is ToolKind.WRITE}
    assert set(writes) == {
        "send_email", "create_calendar_event", "send_slack_message", "create_notion_page", "generate_document",
        "create_quote", "create_catalog_item", "update_catalog_item", "set_stock", "reserve_stock", "release_stock",
        "retire_catalog_item", "undo_actions",
    }
    assert all(d.preview is not None for d in writes.values())
    # Only these can't be reversed: a sent email, a released reservation, and an undo itself.
    assert {name for name, d in writes.items() if d.undo_handler is None} == {"send_email", "release_stock", "undo_actions"}


def test_sub_agent_scopes_stay_narrow_over_the_full_tool_set():
    registry = _full_registry()
    scopes = AgentScopes()
    assert all(d.kind is ToolKind.READ for d in scopes.tools_for("research", registry))
    assert {d.name for d in scopes.tools_for("quote", registry) if d.kind is ToolKind.WRITE} == {
        "generate_document", "create_quote", "create_catalog_item", "update_catalog_item", "set_stock",
        "reserve_stock", "release_stock", "retire_catalog_item",
    }
    assert {d.name for d in scopes.tools_for("outreach", registry) if d.kind is ToolKind.WRITE} == {
        "send_email", "create_calendar_event", "send_slack_message", "create_notion_page",
    }
    assert "undo_actions" in {d.name for d in scopes.tools_for("orchestrator", registry)}


def test_database_urls_are_derived_safely_from_one_source():
    settings = Settings(database_url="postgresql://svc:p%40ss%3Aword@db.internal:5433/agentdb")
    assert settings.sqlalchemy_url.drivername == "postgresql+asyncpg"
    assert settings.sqlalchemy_url.password == "p@ss:word"
    parts = conninfo_to_dict(settings.psycopg_conninfo)
    assert parts == {"host": "db.internal", "port": "5433", "dbname": "agentdb", "user": "svc", "password": "p@ss:word"}
