"""Domain exceptions.

Raised by the application layer, mapped to HTTP responses by the inbound adapter.
No framework imports allowed here.
"""


class WebhookError(Exception):
    """Base exception for all webhook errors."""


class AdmissionValidationError(WebhookError):
    """Raised when the inbound AdmissionReview payload is malformed."""

    def __init__(self, detail: str) -> None:
        super().__init__(detail)
        self.detail = detail


class MutationError(WebhookError):
    """Raised when a mutator fails to produce a valid patch."""

    def __init__(self, mutator_name: str, detail: str) -> None:
        super().__init__(f"Mutator '{mutator_name}' failed: {detail}")
        self.mutator_name = mutator_name
        self.detail = detail
