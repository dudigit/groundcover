"""Health check endpoints.

GET /healthz — liveness probe: returns 200 if the process is alive.
GET /readyz  — readiness probe: returns 200 if ready to serve traffic, 503 if shutting down.

The shutting_down flag is set by the lifespan shutdown handler so that K8s
stops sending traffic before the process receives SIGTERM.
"""

import structlog
from fastapi import APIRouter
from fastapi.responses import JSONResponse

from webhook.ports.registry import MutatorRegistry

logger = structlog.get_logger(__name__)

router = APIRouter()

_registry: MutatorRegistry | None = None
_shutting_down: bool = False


def init_health_router(registry: MutatorRegistry) -> None:
    """Wire dependencies. Called once from bootstrap/inject.py."""
    global _registry  # noqa: PLW0603
    _registry = registry


def set_shutting_down() -> None:
    """Signal that the server is draining. /readyz will return 503."""
    global _shutting_down  # noqa: PLW0603
    _shutting_down = True


@router.get("/healthz")
async def liveness() -> JSONResponse:
    """Liveness probe — returns 200 while the process is running."""
    return JSONResponse(content={"status": "ok"})


@router.get("/readyz")
async def readiness() -> JSONResponse:
    """Readiness probe — returns 503 when shutting down or not yet ready."""
    if _shutting_down:
        await logger.awarning("server.readyz.degraded", reason="shutting_down")
        return JSONResponse(
            content={"status": "shutting_down", "reason": "SIGTERM received"},
            status_code=503,
        )

    if _registry is not None and not _registry.is_ready():
        return JSONResponse(
            content={"status": "not_ready", "reason": "no mutators registered"},
            status_code=503,
        )

    return JSONResponse(content={"status": "ready"})
