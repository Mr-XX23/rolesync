"""Eureka registration so the gateway can route ``lb://SALES-AGENT-ENGINE``."""

from __future__ import annotations

import logging

from app.config import API_PREFIX, Settings

logger = logging.getLogger(__name__)


async def register(settings: Settings) -> bool:
    from py_eureka_client import eureka_client

    base = f"http://{settings.hostname}:{settings.port}"
    try:
        await eureka_client.init_async(
            eureka_server=settings.eureka_server,
            app_name=settings.service_name,
            instance_host=settings.hostname,
            instance_port=settings.port,
            home_page_url=f"{base}{API_PREFIX}/health",
            status_page_url=f"{base}{API_PREFIX}/health",
            health_check_url=f"{base}{API_PREFIX}/health",
        )
    except Exception:
        # The service still works when called directly; only gateway routing is affected.
        logger.exception("Eureka registration failed")
        return False
    logger.info("registered with Eureka as %s", settings.service_name)
    return True


async def deregister() -> None:
    from py_eureka_client import eureka_client

    try:
        await eureka_client.stop_async()
    except Exception:
        logger.warning("Eureka deregistration failed", exc_info=True)
