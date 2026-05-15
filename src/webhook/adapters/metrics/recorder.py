"""Prometheus metrics recorder.

All metric objects are module-level singletons — prometheus-client is not
thread-safe for object creation so they must be created once at import time.

The MetricsRecorder class provides a clean injection boundary so adapters
and the application service can record metrics without importing prometheus
internals directly.

Cardinality rule: NO high-cardinality labels (no uid, no pod name, no image tag).
All label values come from bounded sets.
"""

import importlib.metadata

from prometheus_client import Counter, Gauge, Histogram

# ── Singletons (created once at import) ───────────────────────────────────────

_REQUESTS_TOTAL = Counter(
    "webhook_requests_total",
    "Total admission requests processed",
    ["operation", "resource_kind", "allowed"],
)

_REQUEST_DURATION = Histogram(
    "webhook_request_duration_seconds",
    "Full HTTP request wall time",
    ["operation", "resource_kind"],
    buckets=[0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0],
)

_PIPELINE_DURATION = Histogram(
    "webhook_mutation_pipeline_duration_seconds",
    "Time spent inside the mutation pipeline (excludes HTTP overhead)",
    ["resource_kind"],
    buckets=[0.0005, 0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25],
)

_MUTATIONS_APPLIED = Counter(
    "webhook_mutations_applied_total",
    "Total mutator invocations",
    ["mutator_name", "resource_kind", "operation"],
)

_PATCH_OPS_TOTAL = Counter(
    "webhook_patch_ops_total",
    "Total JSON patch operations emitted",
    ["resource_kind", "operation"],
)

_ERRORS_TOTAL = Counter(
    "webhook_errors_total",
    "Total errors by type",
    ["error_type", "resource_kind"],
)

_DRY_RUN_TOTAL = Counter(
    "webhook_dry_run_requests_total",
    "Total dry-run admission requests (mutations skipped)",
    ["resource_kind", "operation"],
)

_ACTIVE_REQUESTS = Gauge(
    "webhook_active_requests",
    "Currently in-flight admission requests",
)

_INFO = Gauge(
    "webhook_info",
    "Webhook version information",
    ["version", "python_version", "k8s_api_version"],
)


def _register_info_metric() -> None:
    try:
        version = importlib.metadata.version("k8s-mutating-webhook")
    except importlib.metadata.PackageNotFoundError:
        version = "dev"

    import sys

    python_version = f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
    _INFO.labels(
        version=version,
        python_version=python_version,
        k8s_api_version="admission.k8s.io/v1",
    ).set(1)


_register_info_metric()


# ── Recorder (injectable) ──────────────────────────────────────────────────────


class MetricsRecorder:
    """Thin wrapper around the singleton prometheus objects.

    Injected into AdmissionService and middleware via bootstrap/inject.py.
    """

    def record_request(
        self,
        *,
        operation: str,
        resource_kind: str,
        allowed: bool,
    ) -> None:
        _REQUESTS_TOTAL.labels(
            operation=operation,
            resource_kind=resource_kind,
            allowed=str(allowed).lower(),
        ).inc()

    def observe_request_duration(
        self,
        *,
        operation: str,
        resource_kind: str,
        duration_seconds: float,
    ) -> None:
        _REQUEST_DURATION.labels(
            operation=operation,
            resource_kind=resource_kind,
        ).observe(duration_seconds)

    def observe_pipeline_duration(
        self,
        *,
        resource_kind: str,
        duration_seconds: float,
    ) -> None:
        _PIPELINE_DURATION.labels(resource_kind=resource_kind).observe(duration_seconds)

    def record_mutation(
        self,
        *,
        mutator_name: str,
        resource_kind: str,
        operation: str,
    ) -> None:
        _MUTATIONS_APPLIED.labels(
            mutator_name=mutator_name,
            resource_kind=resource_kind,
            operation=operation,
        ).inc()

    def record_patch_ops(
        self,
        *,
        resource_kind: str,
        operation: str,
        count: int,
    ) -> None:
        if count > 0:
            _PATCH_OPS_TOTAL.labels(
                resource_kind=resource_kind,
                operation=operation,
            ).inc(count)

    def record_error(self, *, error_type: str, resource_kind: str = "unknown") -> None:
        _ERRORS_TOTAL.labels(error_type=error_type, resource_kind=resource_kind).inc()

    def record_dry_run(self, *, resource_kind: str, operation: str) -> None:
        _DRY_RUN_TOTAL.labels(resource_kind=resource_kind, operation=operation).inc()

    def increment_active_requests(self) -> None:
        _ACTIVE_REQUESTS.inc()

    def decrement_active_requests(self) -> None:
        _ACTIVE_REQUESTS.dec()
