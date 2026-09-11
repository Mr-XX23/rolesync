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
from app.models.types import TaskSpec
from app.observability.tracing import LangSmithTracingClient, NoopTracingClient, TracingClient
from app.platform.composio_client import ConnectorClient
from app.platform.data_pipeline import DataPipelineClient
from app.platform.jwt_verifier import AccessTokenVerifier, SigningKeys
from app.platform.langgraph_runtime import GraphApprovalPort, GraphRuntime, GraphSpec, open_checkpointer
from app.platform.redis import create_redis
from app.platform.web_search import TavilySearch
from app.platform.workspace_client import WorkspaceDirectory, WorkspaceRecordsClient
from app.tools.adapters.catalog import catalog_tools
from app.tools.adapters.gmail import gmail_tools
from app.tools.adapters.google_calendar import calendar_tools
from app.tools.adapters.knowledge import knowledge_tools
from app.tools.adapters.notion import notion_tools
from app.tools.adapters.slack import slack_tools
from app.tools.adapters.web import WebResearch, web_tools
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
        web_grounded=Route("gemini", (settings.model_web_grounding,)),
    )


def build_tracer(settings: Settings) -> TracingClient:
    if settings.langsmith_tracing and settings.langsmith_api_key and settings.langsmith_api_key.get_secret_value():
        return LangSmithTracingClient(
            api_key=settings.langsmith_api_key.get_secret_value(),
            project=settings.langsmith_project,
            endpoint=settings.langsmith_endpoint,
        )
    return NoopTracingClient()


def default_registry(
    settings: Settings, *, connector: ConnectorClient | None, router: ModelRouter, http: httpx.AsyncClient
) -> ToolRegistry:
    definitions = []
    if connector is None:
        logger.warning("COMPOSIO_API_KEY not set; Gmail, Calendar, Slack and Notion tools are unavailable")
    else:
        definitions += [*gmail_tools(connector), *calendar_tools(connector), *slack_tools(connector), *notion_tools(connector)]

    data_pipeline = DataPipelineClient(base_url=settings.data_pipeline_url, http=http)
    definitions += [*knowledge_tools(data_pipeline), *catalog_tools(data_pipeline)]

    tavily = None
    if settings.tavily_api_key and settings.tavily_api_key.get_secret_value():
        tavily = TavilySearch(api_key=settings.tavily_api_key.get_secret_value(), http=http, base_url=settings.tavily_base_url)
    grounding = router.can_serve(TaskSpec(purpose="web_search", messages=(), web_grounded=True))
    if tavily is None and not grounding:
        logger.warning("no web search backend (TAVILY_API_KEY or GEMINI_API_KEY); web tools are unavailable")
    else:
        if tavily is None:
            logger.warning("TAVILY_API_KEY not set; web search uses Google Search grounding only")
        definitions += web_tools(WebResearch(router=router, tavily=tavily, grounding=grounding), router)
    return ToolRegistry(definitions)


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
        model_router = ModelRouter(
            providers if providers is not None else build_providers(settings, http_client),
            routing_rules(settings),
            tracer,
        )
        if registry is None:
            if connector is None and settings.composio_api_key and settings.composio_api_key.get_secret_value():
                connector = ConnectorClient(
                    api_key=settings.composio_api_key.get_secret_value(),
                    toolkit_versions=settings.composio_versions(),
                )
            registry = default_registry(settings, connector=connector, router=model_router, http=http_client)
        scopes = AgentScopes()
        sessions = SessionRepository(sessionmaker)
        pending_actions = PendingActionRepository(sessionmaker)
        ledger = LedgerRepository(sessionmaker)
        outbox = OutboxRepository(sessionmaker, engine)
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
            sweep_interval_seconds=max(5.0, settings.run_lease_seconds / 2),
        )
        return container
    except BaseException:
        await stack.aclose()
        raise
