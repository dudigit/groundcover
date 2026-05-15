"""POST /mutate — the main admission webhook endpoint.

Responsibilities:
- Parse and validate the raw JSON body as AdmissionReview.
- Bind request_id (AdmissionRequest.uid) to structlog context.
- Delegate to AdmissionService for mutation.
- Serialize the response AdmissionReview back to JSON.
- Map domain exceptions to structured error responses (never 5xx — K8s needs 200).
- Record per-request metrics.
"""

from typing import Any

import structlog
from fastapi import APIRouter, Request, Response
from pydantic import ValidationError

from webhook.adapters.metrics.recorder import MetricsRecorder
from webhook.application.services.admission_service import AdmissionService
from webhook.domain.exceptions import MutationError
from webhook.domain.models.admission import AdmissionResponse, AdmissionReview
from webhook.infrastructure.logging import bind_request_context

logger = structlog.get_logger(__name__)

router = APIRouter()

# Injected at bootstrap time
_service: AdmissionService | None = None
_recorder: MetricsRecorder | None = None


def init_webhook_router(service: AdmissionService, recorder: MetricsRecorder) -> None:
    """Wire dependencies. Called once from bootstrap/inject.py."""
    global _service, _recorder  # noqa: PLW0603
    _service = service
    _recorder = recorder


@router.post("/mutate", response_class=Response)
async def mutate(request: Request) -> Response:
    """Handle a Kubernetes MutatingAdmissionWebhook request."""
    assert _service is not None, "Webhook router not initialised"
    assert _recorder is not None, "Webhook router not initialised"

    raw_body: bytes = await request.body()

    # --- Parse ---
    review, parse_error = _parse_review(raw_body)
    if parse_error is not None:
        await logger.aerror(
            "admission.error.validation",
            error=str(parse_error),
        )
        _recorder.record_error(error_type="validation_error")
        # Return an allow response — failurePolicy controls cluster behaviour
        fallback = _fallback_allow_response(uid="unknown")
        return _json_response(fallback)

    assert review.request is not None

    request_uid = review.request.uid
    resource_kind = review.request.kind.kind
    operation = review.request.operation

    # Bind uid to all subsequent log calls within this request
    bind_request_context(request_id=request_uid)

    await logger.adebug(
        "admission.request.received",
        operation=operation,
        resource_kind=resource_kind,
        namespace=review.request.namespace,
        username=review.request.user_info.username,
        dry_run=review.request.dry_run,
    )

    # --- Mutate ---
    try:
        result_review = await _service.process(review)
    except MutationError as exc:
        await logger.aerror(
            "admission.error.mutation",
            mutator_name=exc.mutator_name,
            error=exc.detail,
            resource_kind=resource_kind,
            operation=operation,
        )
        _recorder.record_error(error_type="mutation_error", resource_kind=resource_kind)
        result_review = _allow_review_with_no_patch(review)
    except Exception as exc:  # noqa: BLE001
        await logger.acritical(
            "admission.error.unexpected",
            error=str(exc),
            resource_kind=resource_kind,
            operation=operation,
            exc_info=True,
        )
        _recorder.record_error(error_type="unexpected", resource_kind=resource_kind)
        result_review = _allow_review_with_no_patch(review)

    # --- Record metrics ---
    assert result_review.response is not None
    _recorder.record_request(
        operation=operation,
        resource_kind=resource_kind,
        allowed=result_review.response.allowed,
    )
    if result_review.response.patch is not None:
        patch_op_count = result_review.response.patch.count(b"},{") + 1
        _recorder.record_patch_ops(
            resource_kind=resource_kind,
            operation=operation,
            count=patch_op_count,
        )
    if review.request.dry_run:
        _recorder.record_dry_run(resource_kind=resource_kind, operation=operation)

    return _json_response(result_review)


def _parse_review(raw_body: bytes) -> tuple[AdmissionReview, None] | tuple[None, Exception]:
    """Parse raw JSON bytes into AdmissionReview. Returns (review, None) or (None, error)."""
    try:
        review = AdmissionReview.model_validate_json(raw_body)
        if review.request is None:
            return None, ValueError("AdmissionReview.request is null")
        return review, None
    except (ValidationError, ValueError) as exc:
        return None, exc


def _allow_review_with_no_patch(review: AdmissionReview) -> AdmissionReview:
    """Construct a pass-through allow response when mutation fails."""
    uid = review.request.uid if review.request else "unknown"
    review.response = AdmissionResponse.allow(uid=uid, patch_ops=[])
    return review


def _fallback_allow_response(uid: str) -> AdmissionReview:
    """Minimal allow review for when we cannot parse the request at all."""
    review = AdmissionReview(apiVersion="admission.k8s.io/v1", kind="AdmissionReview")
    review.response = AdmissionResponse.allow(uid=uid, patch_ops=[])
    return review


def _json_response(review: AdmissionReview) -> Response:
    return Response(
        content=review.model_dump_json(),
        media_type="application/json",
        status_code=200,
    )
