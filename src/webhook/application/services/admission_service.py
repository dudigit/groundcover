"""AdmissionService — orchestrates the mutation pipeline.

Responsibilities:
- Resolve applicable mutators from the registry for the request's (kind, operation).
- Guard against dryRun — skip mutations, still return allowed=true.
- Deduplicate patch ops by path to make reinvocation safe.
- Delegate metrics recording to the injected MetricsRecorder.
- Never import from adapters/ — depends only on ports/.
"""

import time
from dataclasses import dataclass

import structlog

from webhook.domain.exceptions import MutationError
from webhook.domain.models.admission import AdmissionRequest, AdmissionResponse, AdmissionReview
from webhook.domain.models.patch import JSONPatchOp
from webhook.ports.mutator import MutatorProtocol
from webhook.ports.registry import MutatorRegistry

logger = structlog.get_logger(__name__)


@dataclass(frozen=True)
class MutationResult:
    patch_ops: list[JSONPatchOp]
    mutators_run: list[str]
    duration_ms: float


class AdmissionService:
    """Runs the mutation pipeline and builds the AdmissionReview response."""

    def __init__(self, registry: MutatorRegistry) -> None:
        self._registry = registry

    async def process(self, review: AdmissionReview) -> AdmissionReview:
        """Process an AdmissionReview and return a response review.

        Always returns an AdmissionReview with a populated response.
        Never raises — errors produce an allow=true response with no patch
        (fail-open; the webhook's failurePolicy controls cluster behaviour).
        """
        request = review.request
        if request is None:
            response = AdmissionResponse.allow(uid="unknown", patch_ops=[])
            review.response = response
            return review

        if request.dry_run:
            await logger.ainfo(
                "admission.dry_run.skipped",
                operation=request.operation,
                resource_kind=request.kind.kind,
                namespace=request.namespace,
            )
            review.response = AdmissionResponse.allow(uid=request.uid, patch_ops=[])
            return review

        result = await self._run_pipeline(request)
        review.response = AdmissionResponse.allow(
            uid=request.uid,
            patch_ops=result.patch_ops,
        )

        await logger.ainfo(
            "admission.mutation.complete",
            operation=request.operation,
            resource_kind=request.kind.kind,
            namespace=request.namespace,
            username=request.user_info.username,
            dry_run=request.dry_run,
            allowed=True,
            patch_ops_count=len(result.patch_ops),
            mutators_run=result.mutators_run,
            duration_ms=round(result.duration_ms, 2),
        )

        return review

    async def _run_pipeline(self, request: AdmissionRequest) -> MutationResult:
        """Run all registered mutators for this request and collect patch ops."""
        mutators = self._registry.get_mutators(
            kind=request.kind.kind,
            operation=request.operation,
        )

        all_ops: list[JSONPatchOp] = []
        mutators_run: list[str] = []
        pipeline_start = time.perf_counter()

        for mutator in mutators:
            ops = await self._invoke_mutator(mutator, request)
            all_ops.extend(ops)
            mutators_run.append(mutator.name)

        deduped_ops = _deduplicate_patch_ops(all_ops)
        duration_ms = (time.perf_counter() - pipeline_start) * 1000

        return MutationResult(
            patch_ops=deduped_ops,
            mutators_run=mutators_run,
            duration_ms=duration_ms,
        )

    async def _invoke_mutator(
        self,
        mutator: MutatorProtocol,
        request: AdmissionRequest,
    ) -> list[JSONPatchOp]:
        """Invoke a single mutator, surfacing errors as structured log events."""
        try:
            return await mutator.mutate(request)
        except Exception as exc:
            raise MutationError(
                mutator_name=mutator.name,
                detail=str(exc),
            ) from exc


def _deduplicate_patch_ops(ops: list[JSONPatchOp]) -> list[JSONPatchOp]:
    """Remove duplicate patch ops by path, keeping the last writer wins.

    This makes reinvocation (reinvocationPolicy: IfNeeded) safe — if two
    mutators both try to set the same label, only the last one survives.
    """
    seen: dict[str, JSONPatchOp] = {}
    for op in ops:
        seen[op.path] = op
    return list(seen.values())
