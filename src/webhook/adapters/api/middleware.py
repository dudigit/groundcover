"""ASGI middleware for observability.

Responsibilities:
- Track active in-flight requests (Gauge).
- Record full request duration (Histogram).
- Detect slow requests and emit a WARNING log.
- Bind request_id and trace_id to structlog contextvars for the lifetime of the request.
- Clear contextvars after each request to prevent leaks across async tasks.

Health and metrics endpoints are excluded from duration recording to avoid noise.
"""

import time

import structlog
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from webhook.adapters.metrics.recorder import MetricsRecorder
from webhook.infrastructure.logging import bind_request_context, clear_request_context

logger = structlog.get_logger(__name__)

# Endpoints excluded from metrics + sampling (too noisy)
_EXCLUDED_PATHS: frozenset[str] = frozenset({"/healthz", "/readyz", "/metrics"})


class ObservabilityMiddleware(BaseHTTPMiddleware):
    """Tracks duration, active requests, slow requests, and log correlation."""

    def __init__(
        self,
        app: object,
        recorder: MetricsRecorder,
        slow_threshold_ms: int = 500,
    ) -> None:
        super().__init__(app)  # type: ignore[arg-type]
        self._recorder = recorder
        self._slow_threshold_ms = slow_threshold_ms

    async def dispatch(self, request: Request, call_next: object) -> Response:
        if request.url.path in _EXCLUDED_PATHS:
            return await call_next(request)  # type: ignore[misc]

        request_id = _extract_request_id(request)
        trace_id = request.headers.get("traceparent") or request.headers.get("x-b3-traceid")

        bind_request_context(request_id=request_id, trace_id=trace_id)
        self._recorder.increment_active_requests()
        start = time.perf_counter()

        try:
            response: Response = await call_next(request)  # type: ignore[misc]
            duration_seconds = time.perf_counter() - start
            duration_ms = duration_seconds * 1000

            resource_kind = _extract_resource_kind(request)
            operation = _extract_operation(request)

            self._recorder.observe_request_duration(
                operation=operation,
                resource_kind=resource_kind,
                duration_seconds=duration_seconds,
            )

            if duration_ms > self._slow_threshold_ms:
                await logger.awarning(
                    "admission.request.slow",
                    path=request.url.path,
                    method=request.method,
                    duration_ms=round(duration_ms, 2),
                    threshold_ms=self._slow_threshold_ms,
                )
                self._recorder.record_error(error_type="slow_request", resource_kind=resource_kind)

            return response
        finally:
            self._recorder.decrement_active_requests()
            clear_request_context()


def _extract_request_id(request: Request) -> str:
    """Extract AdmissionRequest uid from headers or generate a fallback."""
    return request.headers.get("x-request-id", "unknown")


def _extract_resource_kind(request: Request) -> str:
    """Best-effort resource kind from query params set by the webhook adapter."""
    return request.query_params.get("kind", "unknown")


def _extract_operation(request: Request) -> str:
    return request.query_params.get("operation", "unknown")
