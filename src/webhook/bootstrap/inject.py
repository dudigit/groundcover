"""Dependency injection wiring.

This is the ONLY file allowed to:
- Import concrete adapter implementations.
- Instantiate application services.
- Wire everything together.

Import order matters: mutation modules must be imported before AdmissionService
is constructed so the @registry.register decorators execute and populate the registry.
"""

from webhook.adapters.metrics.recorder import MetricsRecorder
from webhook.adapters.mutations.registry_instance import registry

# Importing these modules triggers @registry.register(...) decorators
import webhook.adapters.mutations.labels.deployment_labels  # noqa: F401
import webhook.adapters.mutations.labels.service_labels  # noqa: F401

from webhook.adapters.api import health as health_router_module
from webhook.adapters.api import webhook as webhook_router_module
from webhook.application.services.admission_service import AdmissionService


def build_and_wire() -> tuple[AdmissionService, MetricsRecorder]:
    """Construct all components and wire them together. Returns (service, recorder)."""
    recorder = MetricsRecorder()
    service = AdmissionService(registry=registry)

    webhook_router_module.init_webhook_router(service=service, recorder=recorder)
    health_router_module.init_health_router(registry=registry)

    return service, recorder
