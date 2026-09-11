"""LangGraph adapter: the only module that imports ``langgraph``.

Engine code describes a graph as a ``GraphSpec`` (plain async node functions over a
TypedDict state) and runs it through ``GraphRuntime``. Durable pause/resume is the
Postgres checkpointer; a human-approval pause is a LangGraph ``interrupt``.

Resume semantics the rest of the engine relies on: when a paused node resumes it runs
again from its first line, and each ``interrupt()`` call returns the recorded resume
value in call order. Nodes therefore keep work before an approval idempotent, and the
orchestrator executes one tool call per super-step.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Awaitable, Callable, Mapping, Sequence
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from enum import StrEnum
from typing import TYPE_CHECKING, Any

from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from langgraph.errors import GraphBubbleUp
from langgraph.graph import END as _END
from langgraph.graph import START, StateGraph
from langgraph.runtime import get_runtime
from langgraph.types import Command, interrupt
from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool

from app.core.context import AgentContext

if TYPE_CHECKING:
    from app.tools.gate import ApprovalRequest

END = "__end__"

NodeFn = Callable[[dict[str, Any]], Awaitable[dict[str, Any]]]
RouterFn = Callable[[dict[str, Any]], str]


@dataclass(frozen=True)
class GraphSpec:
    state_schema: type
    nodes: Mapping[str, NodeFn]
    entry: str
    edges: Sequence[tuple[str, str]] = ()
    routers: Sequence[tuple[str, RouterFn, Mapping[str, str]]] = field(default_factory=tuple)


class RunStatus(StrEnum):
    COMPLETED = "COMPLETED"
    INTERRUPTED = "INTERRUPTED"


@dataclass(frozen=True)
class RunOutcome:
    status: RunStatus
    interrupts: list[Any]
    checkpoint_id: str | None
    values: dict[str, Any]


class GraphRuntime:
    def __init__(self, spec: GraphSpec, checkpointer: AsyncPostgresSaver, *, recursion_limit: int = 200) -> None:
        builder = StateGraph(spec.state_schema, context_schema=AgentContext)
        for name, fn in spec.nodes.items():
            builder.add_node(name, fn)
        builder.add_edge(START, spec.entry)
        for source, target in spec.edges:
            builder.add_edge(source, _END if target == END else target)
        for source, router, mapping in spec.routers:
            builder.add_conditional_edges(
                source, router, {key: (_END if node == END else node) for key, node in mapping.items()}
            )
        self._graph = builder.compile(checkpointer=checkpointer)
        self._recursion_limit = recursion_limit

    def _config(self, ctx: AgentContext) -> dict[str, Any]:
        return {"configurable": {"thread_id": str(ctx.session_id)}, "recursion_limit": self._recursion_limit}

    async def run(self, ctx: AgentContext, *, graph_input: dict[str, Any] | None = None, resume: Any = None) -> RunOutcome:
        """Start (``graph_input``) or resume (``resume``) the session's thread until it
        finishes or pauses. ``ctx`` is runtime context: supplied on every call, never
        persisted in the checkpoint."""
        payload: Any = Command(resume=resume) if resume is not None else graph_input
        # durability="sync": the checkpoint is written before the next step starts, so a
        # crash never loses a completed step (and never replays its side effects).
        await self._graph.ainvoke(payload, self._config(ctx), context=ctx, durability="sync")
        return await self.inspect(ctx)

    async def inspect(self, ctx: AgentContext, *, checkpoint_id: str | None = None) -> RunOutcome:
        """The thread's latest state, or its state at ``checkpoint_id``."""
        config = self._config(ctx)
        if checkpoint_id:
            config["configurable"]["checkpoint_id"] = checkpoint_id
        snapshot = await self._graph.aget_state(config)
        interrupts = [item.value for item in snapshot.interrupts]
        return RunOutcome(
            status=RunStatus.INTERRUPTED if interrupts else RunStatus.COMPLETED,
            interrupts=interrupts,
            checkpoint_id=(snapshot.config or {}).get("configurable", {}).get("checkpoint_id"),
            values=dict(snapshot.values or {}),
        )


def current_context() -> AgentContext:
    """The ``AgentContext`` of the run executing this node."""
    return get_runtime(AgentContext).context


def is_control_flow_signal(exc: BaseException) -> bool:
    """True for LangGraph's internal pause/redirect exceptions, which must propagate."""
    return isinstance(exc, GraphBubbleUp)


def wait_for_human(payload: dict[str, Any]) -> Any:
    """Pause the run until it is resumed; returns the resume value."""
    return interrupt(payload)


class GraphApprovalPort:
    """The gate's ``ApprovalPort`` inside a graph node: a durable interrupt. The interrupt
    payload carries the pending action id so the runner can find the decision."""

    async def wait_for_decision(self, request: ApprovalRequest) -> None:
        wait_for_human(
            {
                "type": "approval",
                "pending_action_id": str(request.pending_action_id),
                "tool": request.tool,
                "call_id": request.call_id,
            }
        )


@asynccontextmanager
async def open_checkpointer(conninfo: str, *, schema: str, max_size: int = 10) -> AsyncIterator[AsyncPostgresSaver]:
    """Postgres checkpointer on its own schema (tables are LangGraph-managed, not Alembic)."""
    pool = AsyncConnectionPool(
        conninfo,
        min_size=1,
        max_size=max_size,
        open=False,
        kwargs={
            "autocommit": True,
            "prepare_threshold": 0,
            "row_factory": dict_row,
            "options": f"-c search_path={schema}",
        },
    )
    await pool.open()
    try:
        async with pool.connection() as conn:
            await conn.execute(f'CREATE SCHEMA IF NOT EXISTS "{schema}"')
        saver = AsyncPostgresSaver(pool)
        await saver.setup()
        yield saver
    finally:
        await pool.close()
