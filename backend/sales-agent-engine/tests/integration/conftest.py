"""Integration fixtures: real Postgres (test database) + Redis (db 15) from the local stack."""

from __future__ import annotations

import asyncio
import socket
from collections.abc import AsyncIterator, Awaitable, Callable
from datetime import timedelta
from uuid import UUID, uuid4

import httpx
import pytest
import uvicorn
from alembic import command
from alembic.config import Config as AlembicConfig
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine
from sse_starlette.sse import AppStatus

from app.autonomy.policy import AutonomyPolicy, EscalateAllPolicy
from app.config import SERVICE_ROOT, Settings
from app.container import Container, build_container
from app.core.context import AgentContext, RunMode
from app.db.session import create_engine
from app.main import create_app
from app.observability.tracing import NoopTracingClient
from app.platform.redis import create_redis
from app.tools.executor import ToolExecutor
from app.tools.gate import ApprovalPort, ToolGate
from app.tools.registry import AgentScopes, ToolRegistry
from tests.support import FakeWorkspaceService

pytestmark = pytest.mark.integration


def _upgrade(connection) -> None:
    config = AlembicConfig(str(SERVICE_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(SERVICE_ROOT / "app" / "db" / "migrations"))
    config.attributes["connection"] = connection
    config.attributes["skip_logging_config"] = True
    command.upgrade(config, "head")


@pytest.fixture(scope="session")
async def db_engine(settings: Settings) -> AsyncIterator[AsyncEngine]:
    engine = create_engine(settings)
    try:
        async with engine.begin() as conn:
            await conn.run_sync(_upgrade)
    except OSError as exc:  # pragma: no cover - environment problem
        pytest.skip(f"Postgres not reachable for integration tests: {exc}")
    yield engine
    await engine.dispose()


@pytest.fixture(scope="session")
async def redis(settings: Settings):
    client = create_redis(settings)
    yield client
    await client.aclose()


@pytest.fixture
async def clean(db_engine: AsyncEngine, redis) -> None:
    async with db_engine.begin() as conn:
        await conn.execute(
            text(
                "TRUNCATE agent.audit, agent.saga_step, agent.pending_action, agent.workspace_outbox, "
                "agent.session CASCADE"
            )
        )
        await conn.execute(
            text(
                "DO $$ BEGIN IF to_regclass('agent_checkpoint.checkpoints') IS NOT NULL THEN "
                "TRUNCATE agent_checkpoint.checkpoints, agent_checkpoint.checkpoint_blobs, "
                "agent_checkpoint.checkpoint_writes; END IF; END $$"
            )
        )
    await redis.flushdb()


@pytest.fixture
def workspace_service() -> FakeWorkspaceService:
    return FakeWorkspaceService()


ContainerFactory = Callable[..., Awaitable[Container]]


@pytest.fixture
async def make_container(settings: Settings, clean, workspace_service) -> AsyncIterator[ContainerFactory]:
    opened: list[tuple[Container, httpx.AsyncClient]] = []

    async def factory(**kwargs) -> Container:
        http = httpx.AsyncClient(transport=workspace_service.transport())
        kwargs.setdefault("providers", {})
        kwargs.setdefault("registry", ToolRegistry())
        overrides = kwargs.pop("settings_overrides", None)
        effective = settings.model_copy(update=overrides) if overrides else settings
        container = await build_container(effective, http_client=http, **kwargs)
        opened.append((container, http))
        return container

    yield factory
    for container, http in opened:
        await container.aclose()
        await http.aclose()


@pytest.fixture
def tenant_id() -> UUID:
    return uuid4()


@pytest.fixture
def user_id(workspace_service: FakeWorkspaceService, tenant_id: UUID) -> UUID:
    user = uuid4()
    workspace_service.add(user, tenant_id)
    return user


async def open_session(
    container: Container, tenant_id: UUID, user_id: UUID, mode: RunMode = RunMode.INTERACTIVE
) -> AgentContext:
    row = await container.sessions.create(tenant_id=tenant_id, user_id=user_id, mode=mode)
    return AgentContext(tenant_id=tenant_id, user_id=user_id, session_id=row.id, mode=mode)


def make_gate(
    container: Container,
    registry: ToolRegistry,
    approvals: ApprovalPort,
    policy: AutonomyPolicy | None = None,
    timeout_seconds: float = 2.0,
) -> ToolGate:
    return ToolGate(
        registry=registry,
        scopes=AgentScopes(),
        ledger=container.ledger,
        pending_actions=container.pending_actions,
        approvals=approvals,
        policy=policy or EscalateAllPolicy(),
        executor=ToolExecutor(timeout_seconds),
        events=container.events,
        tracer=NoopTracingClient(),
        approval_ttl=timedelta(hours=1),
    )


async def all_events(container: Container, session_id: UUID) -> list[dict]:
    return [event.envelope for event in await container.events.read(session_id, after="0-0", count=1000)]


@pytest.fixture
async def serve() -> AsyncIterator[Callable[[Container], Awaitable[str]]]:
    """Runs the real ASGI app on a local port (SSE needs a real streaming server)."""
    # sse-starlette latches a process-wide "server is exiting" flag (and a poller keeps
    # re-syncing it from the last stopped uvicorn server), which would end every later
    # stream at once. Tests close their own streams, so switch that automation off.
    AppStatus.disable_automatic_graceful_drain()
    AppStatus.should_exit = False
    servers: list[tuple[uvicorn.Server, asyncio.Task]] = []

    async def start(container: Container) -> str:
        app = create_app(container.settings)
        app.state.container = container
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
        server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, lifespan="off", log_level="warning"))
        task = asyncio.create_task(server.serve())
        for _ in range(250):
            if server.started:
                break
            await asyncio.sleep(0.02)
        servers.append((server, task))
        return f"http://127.0.0.1:{port}"

    yield start
    for server, task in servers:
        server.should_exit = True
        await asyncio.wait_for(task, 15)
    AppStatus.should_exit = False
