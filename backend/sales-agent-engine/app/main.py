from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api import approvals, chat, health, sessions, stream
from app.api.errors import install_error_handlers
from app.config import API_PREFIX, Settings, get_settings
from app.container import Container, build_container
from app.core.logging import configure_logging
from app.platform import eureka

logger = logging.getLogger(__name__)

ContainerFactory = Callable[[Settings], Awaitable[Container]]


def create_app(settings: Settings | None = None, *, container_factory: ContainerFactory | None = None) -> FastAPI:
    settings = settings or get_settings()
    factory = container_factory or build_container

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        configure_logging(settings.log_level)
        container = await factory(settings)
        app.state.container = container
        background: list[asyncio.Task] = []
        if settings.workspace_sync_enabled:
            background.append(asyncio.create_task(container.sync_worker.run_forever(), name="workspace-sync"))
        recovered = await container.runner.recover_orphans(idle_seconds=2 * settings.run_lease_seconds)
        if recovered:
            logger.info("resumed %d interrupted session(s)", len(recovered))
        registered = settings.eureka_enabled and await eureka.register(settings)
        try:
            yield
        finally:
            if registered:
                await eureka.deregister()
            for task in background:
                task.cancel()
            for task in background:
                with contextlib.suppress(asyncio.CancelledError):
                    await task
            await container.aclose()

    app = FastAPI(
        title="RoleSync Sales Agent Engine",
        version="0.2.0",
        lifespan=lifespan,
        docs_url=f"{API_PREFIX}/docs",
        redoc_url=None,
        openapi_url=f"{API_PREFIX}/openapi.json",
    )
    install_error_handlers(app)
    for module in (health, chat, sessions, stream, approvals):
        app.include_router(module.router, prefix=API_PREFIX)
    return app


app = create_app()
