"""Base class for label mutators.

Provides shared idempotency check logic so subclasses do not repeat it.
Idempotency is required because K8s may reinvoke the webhook (reinvocationPolicy: IfNeeded).
"""

from webhook.domain.models.admission import AdmissionRequest
from webhook.domain.models.patch import JSONPatchOp, make_add_label_op, make_ensure_labels_object_op
from webhook.domain.types import LabelMap


class LabelMutatorBase:
    """Shared label injection logic for all resource kinds.

    Subclasses define `desired_labels(request)` to return the target label map.
    This base class handles idempotency: it only emits patch ops for labels
    that are absent or have a different value.
    """

    def _build_label_ops(
        self,
        request: AdmissionRequest,
        desired: LabelMap,
    ) -> list[JSONPatchOp]:
        """Return patch ops needed to bring the object's labels to the desired state.

        Only emits ops for labels that differ — safe for reinvocation.
        """
        existing_labels: dict[str, str] = self._get_existing_labels(request)
        ops: list[JSONPatchOp] = []

        # Ensure /metadata/labels exists before adding to it
        if not existing_labels:
            ops.append(make_ensure_labels_object_op())

        for key, value in desired.items():
            if existing_labels.get(key) != value:
                ops.append(make_add_label_op(key, value))

        return ops

    @staticmethod
    def _get_existing_labels(request: AdmissionRequest) -> dict[str, str]:
        """Safely extract metadata.labels from the K8s object body."""
        if request.object is None:
            return {}
        metadata: object = request.object.get("metadata", {})
        if not isinstance(metadata, dict):
            return {}
        labels: object = metadata.get("labels", {})
        if not isinstance(labels, dict):
            return {}
        return {str(k): str(v) for k, v in labels.items()}
