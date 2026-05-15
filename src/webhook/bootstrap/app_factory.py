"""FastAPI application factory with lifespan management.

Lifespan responsibilities:
- Configure structured logging.
- Wire all dependencies.
- Signal readiness (set shutting_down=False).
- On shutdown: set shutting_down=True → /readyz returns 503 → K8s drains traffic.
"""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from webhook.adapters.api import health as health_router_module
from webhook.adapters.api.health import router as health_router
from webhook.adapters.api.metrics import router as metrics_router
from webhook.adapters.api.middleware import ObservabilityMiddleware
from webhook.adapters.api.webhook import router as webhook_router
from webhook.bootstrap.inject import build_and_wire
from webhook.config import get_config
from webhook.infrastructure.logging import configure_logging

logger = structlog.get_logger(__name__)


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncGenerator[None, None]:
    """Application lifespan: startup → yield → shutdown."""
    config = get_config()

    # Configure logging first so all subsequent startup logs are structured
    configure_logging(log_level=config.log_level, sample_rate=config.log_sample_rate)

    await logger.ainfo(
        "server.startup",
        port=config.port,
        log_level=config.log_level,
        workers=config.workers,
    )

    yield  # ← application is serving requests here

    # Signal readiness probe to return 503 — K8s stops routing new traffic
    health_router_module.set_shutting_down()

    await logger.ainfo("server.shutdown")


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""
    config = get_config()

    # Wire all dependencies (imports mutation modules, triggers self-registration)
    _service, recorder = build_and_wire()

    app = FastAPI(
        title="K8s Mutating Webhook",
        version="1.0.0",
        # Disable default exception handlers — we handle everything in the webhook route
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
        lifespan=lifespan,
    )

    # Observability middleware (must be added before other middleware)
    app.add_middleware(
        ObservabilityMiddleware,  # type: ignore[arg-type]
        recorder=recorder,
        slow_threshold_ms=config.slow_request_threshold_ms,
    )

    # Routers
    app.include_router(webhook_router)
    app.include_router(health_router)
    app.include_router(metrics_router)

    return app


# Module-level app instance — used by gunicorn/uvicorn entrypoint
app = create_app()
