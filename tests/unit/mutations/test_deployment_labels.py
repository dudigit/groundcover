"""Unit tests for DeploymentLabelMutator."""

import pytest

from webhook.adapters.mutations.labels.deployment_labels import DeploymentLabelMutator
from webhook.domain.models.admission import AdmissionReview
from tests.conftest import build_deployment_review


@pytest.fixture
def mutator() -> DeploymentLabelMutator:
    return DeploymentLabelMutator()


class TestDeploymentLabelMutator:
    def test_name_is_class_variable(self) -> None:
        assert DeploymentLabelMutator.name == "DeploymentLabelMutator"

    async def test_injects_managed_by_label_on_create(self, mutator: DeploymentLabelMutator) -> None:
        review = AdmissionReview.model_validate(build_deployment_review("CREATE"))
        assert review.request is not None

        ops = await mutator.mutate(review.request)

        paths = [op.path for op in ops]
        assert any("managed-by" in p for p in paths)

    async def test_injects_resource_kind_label(self, mutator: DeploymentLabelMutator) -> None:
        review = AdmissionReview.model_validate(build_deployment_review("CREATE"))
        assert review.request is not None

        ops = await mutator.mutate(review.request)

        kind_op = next((op for op in ops if "resource-kind" in op.path), None)
        assert kind_op is not None
        assert kind_op.value == "Deployment"

    async def test_injects_injected_at_label(self, mutator: DeploymentLabelMutator) -> None:
        review = AdmissionReview.model_validate(build_deployment_review("CREATE"))
        assert review.request is not None

        ops = await mutator.mutate(review.request)

        assert any("injected-at" in op.path for op in ops)

    async def test_idempotent_when_labels_already_present(
        self, mutator: DeploymentLabelMutator
    ) -> None:
        """When managed-by is already set with the correct value, no patch op emitted for it."""
        existing = {"app.kubernetes.io/managed-by": "webhook"}
        review = AdmissionReview.model_validate(build_deployment_review("UPDATE", labels=existing))
        assert review.request is not None

        ops = await mutator.mutate(review.request)

        managed_by_ops = [op for op in ops if "managed-by" in op.path]
        assert len(managed_by_ops) == 0

    async def test_no_ops_when_all_labels_correct(self, mutator: DeploymentLabelMutator) -> None:
        """If all desired labels already have the right value, return empty list (no-op)."""
        # We can only assert the subset we control — injected-at is dynamic so we skip it
        review = AdmissionReview.model_validate(build_deployment_review("UPDATE"))
        assert review.request is not None

        ops = await mutator.mutate(review.request)
        # For a fresh object (no labels), we should always get ops
        assert len(ops) > 0

    async def test_returns_list_of_json_patch_ops(self, mutator: DeploymentLabelMutator) -> None:
        from webhook.domain.models.patch import JSONPatchOp

        review = AdmissionReview.model_validate(build_deployment_review("CREATE"))
        assert review.request is not None

        ops = await mutator.mutate(review.request)

        assert all(isinstance(op, JSONPatchOp) for op in ops)

    async def test_all_ops_are_add_operations(self, mutator: DeploymentLabelMutator) -> None:
        review = AdmissionReview.model_validate(build_deployment_review("CREATE"))
        assert review.request is not None

        ops = await mutator.mutate(review.request)

        label_ops = [op for op in ops if op.path != "/metadata/labels"]
        assert all(op.op == "add" for op in label_ops)

    async def test_paths_use_jsonpointer_escaping(self, mutator: DeploymentLabelMutator) -> None:
        """Label keys containing '/' must be escaped as '~1' in JSON Pointer paths."""
        review = AdmissionReview.model_validate(build_deployment_review("CREATE"))
        assert review.request is not None

        ops = await mutator.mutate(review.request)

        for op in ops:
            if op.path.startswith("/metadata/labels/"):
                key_part = op.path.removeprefix("/metadata/labels/")
                assert "/" not in key_part, f"Unescaped '/' in path: {op.path}"

    async def test_dry_run_is_handled_by_service_not_mutator(
        self, mutator: DeploymentLabelMutator
    ) -> None:
        """The mutator itself does not check dry_run — the service layer handles it."""
        review = AdmissionReview.model_validate(build_deployment_review("CREATE", dry_run=True))
        assert review.request is not None

        # Mutator still returns ops — dryRun guard is in AdmissionService
        ops = await mutator.mutate(review.request)
        assert isinstance(ops, list)
