"""Composition root: builds every long-lived service once per process."""

from __future__ import annotations

from collections.abc import Callable
from contextlib import AsyncExitStack
from dataclasses import dataclass, field
from datetime import timedelta

import httpx
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncEngine

from app.autonomy.policy import AutonomyPolicy, EscalateAllPolicy
from app.config import CHECKPOINT_SCHEMA, Settings
from app.db.repositories import LedgerRepository, PendingActionRepository, SessionRepository
from app.db.session import create_engine, create_sessionmaker
from app.engine.events import RedisEventChannel
from app.engine.runner import SessionRunner
from app.observability.tracing import NoopTracingClient, TracingClient
from app.platform.jwt_verifier import AccessTokenVerifier
from app.platform.langgraph_runtime import GraphApprovalPort, GraphRuntime, GraphSpec, open_checkpointer
from app.platform.redis import create_redis
from app.platform.workspace_client import WorkspaceDirectory
from app.tools.executor import ToolExecutor
from app.tools.gate import ToolGate
from app.tools.registry import AgentScopes, ToolRegistry


@dataclass
class Container:
    settings: Settings
    engine: AsyncEngine
    redis: Redis
    http: httpx.AsyncClient
    token_verifier: AccessTokenVerifier
    workspaces: WorkspaceDirectory
    sessions: SessionRepository
    pending_actions: PendingActionRepository
    ledger: LedgerRepository
    events: RedisEventChannel
    registry: ToolRegistry
    scopes: AgentScopes
    gate: ToolGate
    runner: SessionRunner | None = None
    _exit_stack: AsyncExitStack = field(default_factory=AsyncExitStack, repr=False)

    async def aclose(self) -> None:
        if self.runner is not None:
            await self.runner.aclose()
        await self._exit_stack.aclose()


GraphFactory = Callable[[Container], GraphSpec]


async def build_container(
    settings: Settings,
    *,
    registry: ToolRegistry | None = None,
    graph_factory: GraphFactory | None = None,
    http_client: httpx.AsyncClient | None = None,
    policy: AutonomyPolicy | None = None,
    tracer: TracingClient | None = None,
) -> Container:
    stack = AsyncExitStack()
    try:
        engine = create_engine(settings)
        stack.push_async_callback(engine.dispose)
        sessionmaker = create_sessionmaker(engine)

        redis = create_redis(settings)
        stack.push_async_callback(redis.aclose)

        if http_client is None:
            http_client = httpx.AsyncClient()
            stack.push_async_callback(http_client.aclose)

        checkpointer = await stack.enter_async_context(
            open_checkpointer(settings.psycopg_conninfo, schema=CHECKPOINT_SCHEMA)
        )

        registry = registry or ToolRegistry()
        scopes = AgentScopes()
        sessions = SessionRepository(sessionmaker)
        pending_actions = PendingActionRepository(sessionmaker)
        ledger = LedgerRepository(sessionmaker)
        events = RedisEventChannel(
            redis,
            key_prefix=settings.redis_key_prefix,
            maxlen=settings.event_stream_maxlen,
            ttl_seconds=settings.event_stream_ttl_seconds,
        )
        gate = ToolGate(
            registry=registry,
            scopes=scopes,
            ledger=ledger,
            pending_actions=pending_actions,
            approvals=GraphApprovalPort(),
            policy=policy or EscalateAllPolicy(),
            executor=ToolExecutor(settings.tool_timeout_seconds),
            events=events,
            tracer=tracer or NoopTracingClient(),
            approval_ttl=timedelta(seconds=settings.approval_ttl_seconds),
        )
        container = Container(
            settings=settings,
            engine=engine,
            redis=redis,
            http=http_client,
            token_verifier=AccessTokenVerifier(
                public_key_pem=settings.jwt_public_key(),
                issuer=settings.jwt_issuer,
                leeway_seconds=settings.jwt_leeway_seconds,
            ),
            workspaces=WorkspaceDirectory(
                base_url=settings.workspace_service_url,
                http=http_client,
                redis=redis,
                key_prefix=settings.redis_key_prefix,
                cache_seconds=settings.membership_cache_seconds,
            ),
            sessions=sessions,
            pending_actions=pending_actions,
            ledger=ledger,
            events=events,
            registry=registry,
            scopes=scopes,
            gate=gate,
            _exit_stack=stack,
        )
        if graph_factory is not None:
            container.runner = SessionRunner(
                runtime=GraphRuntime(graph_factory(container), checkpointer),
                sessions=sessions,
                pending_actions=pending_actions,
                events=events,
            )
        return container
    except BaseException:
        await stack.aclose()
        raise
