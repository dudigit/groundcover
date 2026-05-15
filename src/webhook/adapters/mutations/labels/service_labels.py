"""Service label mutator.

Injects standard labels into Services on CREATE and UPDATE.
Self-registers with the singleton registry via the @registry.register decorator.

Labels injected:
- app.kubernetes.io/managed-by: "webhook"
- webhook.io/injected-at:       RFC 3339 UTC timestamp
- webhook.io/resource-kind:     "Service"
- Any custom labels from AppConfig.custom_labels
"""

from datetime import UTC, datetime
from typing import ClassVar

from webhook.adapters.mutations.base import LabelMutatorBase
from webhook.adapters.mutations.registry_instance import registry
from webhook.config import get_config
from webhook.domain.models.admission import AdmissionRequest
from webhook.domain.models.patch import JSONPatchOp
from webhook.domain.types import LabelMap


@registry.register("Service", ["CREATE", "UPDATE"])
class ServiceLabelMutator(LabelMutatorBase):
    """Injects standard labels into Service objects."""

    name: ClassVar[str] = "ServiceLabelMutator"

    async def mutate(self, request: AdmissionRequest) -> list[JSONPatchOp]:
        desired = self._build_desired_labels()
        return self._build_label_ops(request, desired)

    @staticmethod
    def _build_desired_labels() -> LabelMap:
        config = get_config()
        labels: dict[str, str] = {
            "app.kubernetes.io/managed-by": "webhook",
            "webhook.io/injected-at": datetime.now(UTC).strftime("%Y-%m-%dT%H-%M-%SZ"),
            "webhook.io/resource-kind": "Service",
        }
        labels.update(config.custom_labels)
        return labels
