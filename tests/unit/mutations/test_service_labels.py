"""Unit tests for ServiceLabelMutator."""

import pytest

from webhook.adapters.mutations.labels.service_labels import ServiceLabelMutator
from webhook.domain.models.admission import AdmissionReview
from tests.conftest import build_service_review


@pytest.fixture
def mutator() -> ServiceLabelMutator:
    return ServiceLabelMutator()


class TestServiceLabelMutator:
    def test_name_is_class_variable(self) -> None:
        assert ServiceLabelMutator.name == "ServiceLabelMutator"

    async def test_injects_managed_by_label_on_create(self, mutator: ServiceLabelMutator) -> None:
        review = AdmissionReview.model_validate(build_service_review("CREATE"))
        assert review.request is not None

        ops = await mutator.mutate(review.request)

        assert any("managed-by" in op.path for op in ops)

    async def test_injects_resource_kind_label_as_service(
        self, mutator: ServiceLabelMutator
    ) -> None:
        review = AdmissionReview.model_validate(build_service_review("CREATE"))
        assert review.request is not None

        ops = await mutator.mutate(review.request)

        kind_op = next((op for op in ops if "resource-kind" in op.path), None)
        assert kind_op is not None
        assert kind_op.value == "Service"

    async def test_idempotent_when_labels_already_present(
        self, mutator: ServiceLabelMutator
    ) -> None:
        existing = {"app.kubernetes.io/managed-by": "webhook"}
        review = AdmissionReview.model_validate(build_service_review("UPDATE", labels=existing))
        assert review.request is not None

        ops = await mutator.mutate(review.request)

        managed_by_ops = [op for op in ops if "managed-by" in op.path]
        assert len(managed_by_ops) == 0

    async def test_returns_list_of_json_patch_ops(self, mutator: ServiceLabelMutator) -> None:
        from webhook.domain.models.patch import JSONPatchOp

        review = AdmissionReview.model_validate(build_service_review("CREATE"))
        assert review.request is not None

        ops = await mutator.mutate(review.request)

        assert all(isinstance(op, JSONPatchOp) for op in ops)

    async def test_update_operation_also_injects(self, mutator: ServiceLabelMutator) -> None:
        review = AdmissionReview.model_validate(build_service_review("UPDATE"))
        assert review.request is not None

        ops = await mutator.mutate(review.request)

        assert len(ops) > 0

    async def test_no_labels_object_adds_ensure_op_first(
        self, mutator: ServiceLabelMutator
    ) -> None:
        """When metadata.labels is absent, first op should create the labels object."""
        review_data = build_service_review("CREATE")
        # Remove labels key entirely
        review_data["request"]["object"]["metadata"].pop("labels", None)
        review = AdmissionReview.model_validate(review_data)
        assert review.request is not None

        ops = await mutator.mutate(review.request)

        labels_init_op = next(
            (op for op in ops if op.path == "/metadata/labels"), None
        )
        assert labels_init_op is not None
        assert labels_init_op.op == "add"
        assert labels_init_op.value == {}
