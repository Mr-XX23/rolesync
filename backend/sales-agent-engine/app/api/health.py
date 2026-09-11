from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from sqlalchemy import text

from app.api.deps import ContainerDep

router = APIRouter(tags=["health"])


@router.get("/health")
async def health() -> dict[str, str]:
    return {"status": "UP"}


@router.get("/health/ready")
async def ready(container: ContainerDep) -> JSONResponse:
    checks: dict[str, str] = {}
    try:
        async with container.engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        checks["database"] = "UP"
    except Exception:
        checks["database"] = "DOWN"
    try:
        await container.redis.ping()
        checks["redis"] = "UP"
    except Exception:
        checks["redis"] = "DOWN"
    up = all(value == "UP" for value in checks.values())
    return JSONResponse(status_code=200 if up else 503, content={"status": "UP" if up else "DOWN", "checks": checks})
