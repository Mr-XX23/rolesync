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
    assert {d.name for d in scopes.tools_for("outreach", registry)} == {"lookup_facts", "send_note", "broken_send"}
    assert scopes.tools_for("unknown-agent", registry) == []


def test_database_urls_are_derived_safely_from_one_source():
    settings = Settings(database_url="postgresql://svc:p%40ss%3Aword@db.internal:5433/agentdb")
    assert settings.sqlalchemy_url.drivername == "postgresql+asyncpg"
    assert settings.sqlalchemy_url.password == "p@ss:word"
    parts = conninfo_to_dict(settings.psycopg_conninfo)
    assert parts == {"host": "db.internal", "port": "5433", "dbname": "agentdb", "user": "svc", "password": "p@ss:word"}
