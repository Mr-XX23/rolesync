"""Composition root: builds every long-lived service once per process."""

from __future__ import annotations

import logging
from collections.abc import Callable, Mapping
from contextlib import AsyncExitStack
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any

import httpx
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncEngine

from app.autonomy.policy import AutonomyPolicy, EscalateAllPolicy
from app.config import CHECKPOINT_SCHEMA, Settings
from app.db.repositories import LedgerRepository, PendingActionRepository, SessionRepository
from app.db.repositories.outbox import OutboxRepository
from app.db.session import create_engine, create_sessionmaker
from app.engine.events import RedisEventChannel
from app.engine.leases import RunLeases
from app.engine.orchestrator import Orchestrator
from app.engine.runner import SessionRunner
from app.engine.workspace_record import WorkspaceRecorder, WorkspaceSyncWorker
from app.models.providers.base import LLMProvider
from app.models.providers.gemini_provider import GeminiProvider
from app.models.providers.openrouter_provider import OpenRouterProvider
from app.models.router import ModelRouter, Route, RoutingRules
from app.observability.tracing import LangSmithTracingClient, NoopTracingClient, TracingClient
from app.platform.composio_client import ConnectorClient
from app.platform.jwt_verifier import AccessTokenVerifier, SigningKeys
from app.platform.langgraph_runtime import GraphApprovalPort, GraphRuntime, GraphSpec, open_checkpointer
from app.platform.redis import create_redis
from app.platform.workspace_client import WorkspaceDirectory, WorkspaceRecordsClient
from app.tools.adapters.gmail import gmail_tools
from app.tools.executor import ToolExecutor
from app.tools.gate import ToolGate
from app.tools.registry import AgentScopes, ToolRegistry

logger = logging.getLogger(__name__)


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
    outbox: OutboxRepository
    events: RedisEventChannel
    registry: ToolRegistry
    scopes: AgentScopes
    gate: ToolGate
    router: ModelRouter
    recorder: WorkspaceRecorder
    sync_worker: WorkspaceSyncWorker
    leases: RunLeases
    tracer: TracingClient
    runner: Any = None  # SessionRunner; tests may substitute a double
    _exit_stack: AsyncExitStack = field(default_factory=AsyncExitStack, repr=False)

    async def aclose(self) -> None:
        if self.runner is not None:
            await self.runner.aclose()
        await self._exit_stack.aclose()
        if isinstance(self.tracer, LangSmithTracingClient):
            self.tracer.flush()


GraphFactory = Callable[[Container], GraphSpec]


def build_providers(settings: Settings, http: httpx.AsyncClient) -> dict[str, LLMProvider]:
    providers: dict[str, LLMProvider] = {}
    if settings.gemini_api_key and settings.gemini_api_key.get_secret_value():
        providers["gemini"] = GeminiProvider(
            api_key=settings.gemini_api_key.get_secret_value(), timeout_seconds=settings.llm_timeout_seconds
        )
    if settings.openrouter_api_key and settings.openrouter_api_key.get_secret_value():
        providers["openrouter"] = OpenRouterProvider(
            api_key=settings.openrouter_api_key.get_secret_value(),
            http=http,
            base_url=settings.openrouter_base_url,
            timeout_seconds=settings.llm_timeout_seconds,
        )
    if not providers:
        logger.warning("no model provider configured (GEMINI_API_KEY / OPEN_ROUTER_API); chat will fail")
    return providers


def routing_rules(settings: Settings) -> RoutingRules:
    return RoutingRules(
        complex=Route("gemini", (settings.model_complex,)),
        simple=Route("openrouter", settings.split_list(settings.models_simple)),
        failover=Route("openrouter", settings.split_list(settings.models_failover)),
    )


def build_tracer(settings: Settings) -> TracingClient:
    if settings.langsmith_tracing and settings.langsmith_api_key and settings.langsmith_api_key.get_secret_value():
        return LangSmithTracingClient(
            api_key=settings.langsmith_api_key.get_secret_value(),
            project=settings.langsmith_project,
            endpoint=settings.langsmith_endpoint,
        )
    return NoopTracingClient()


def default_registry(connector: ConnectorClient | None) -> ToolRegistry:
    registry = ToolRegistry()
    if connector is None:
        logger.warning("COMPOSIO_API_KEY not set; Gmail tools are unavailable")
        return registry
    for definition in gmail_tools(connector):
        registry.register(definition)
    return registry


async def build_container(
    settings: Settings,
    *,
    registry: ToolRegistry | None = None,
    graph_factory: GraphFactory | None = None,
    http_client: httpx.AsyncClient | None = None,
    providers: Mapping[str, LLMProvider] | None = None,
    connector: ConnectorClient | None = None,
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

        tracer = tracer or build_tracer(settings)
        if registry is None:
            if connector is None and settings.composio_api_key and settings.composio_api_key.get_secret_value():
                connector = ConnectorClient(
                    api_key=settings.composio_api_key.get_secret_value(),
                    toolkit_versions=settings.composio_versions(),
                )
            registry = default_registry(connector)
        scopes = AgentScopes()
        sessions = SessionRepository(sessionmaker)
        pending_actions = PendingActionRepository(sessionmaker)
        ledger = LedgerRepository(sessionmaker)
        outbox = OutboxRepository(sessionmaker)
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
            tracer=tracer,
            approval_ttl=timedelta(seconds=settings.approval_ttl_seconds),
        )
        model_router = ModelRouter(
            providers if providers is not None else build_providers(settings, http_client),
            routing_rules(settings),
            tracer,
        )
        sync_worker = WorkspaceSyncWorker(
            outbox,
            WorkspaceRecordsClient(base_url=settings.workspace_service_url, http=http_client),
            interval_seconds=settings.workspace_sync_interval_seconds,
        )
        recorder = WorkspaceRecorder(outbox, enabled=settings.workspace_sync_enabled, on_enqueue=sync_worker.nudge)
        leases = RunLeases(redis, key_prefix=settings.redis_key_prefix, ttl_seconds=settings.run_lease_seconds)
        verifier = AccessTokenVerifier(
            keys=SigningKeys(jwks_url=settings.jwt_jwks_url, http=http_client, pem=settings.jwt_public_key()),
            issuer=settings.jwt_issuer,
            leeway_seconds=settings.jwt_leeway_seconds,
        )
        container = Container(
            settings=settings,
            engine=engine,
            redis=redis,
            http=http_client,
            token_verifier=verifier,
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
            outbox=outbox,
            events=events,
            registry=registry,
            scopes=scopes,
            gate=gate,
            router=model_router,
            recorder=recorder,
            sync_worker=sync_worker,
            leases=leases,
            tracer=tracer,
            _exit_stack=stack,
        )
        orchestrator = Orchestrator(
            router=model_router,
            gate=gate,
            registry=registry,
            scopes=scopes,
            events=events,
            recorder=recorder,
            max_steps=settings.max_steps_per_turn,
        )
        spec = graph_factory(container) if graph_factory is not None else orchestrator.graph_spec()
        container.runner = SessionRunner(
            runtime=GraphRuntime(spec, checkpointer),
            sessions=sessions,
            pending_actions=pending_actions,
            events=events,
            leases=leases,
            recorder=recorder,
            tracer=tracer,
        )
        return container
    except BaseException:
        await stack.aclose()
        raise
