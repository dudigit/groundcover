"""MutatorProtocol — the port contract every mutator must satisfy.

The application layer depends only on this Protocol, never on concrete implementations.
This keeps the domain + application layers free of adapter-level imports.
"""

from typing import ClassVar, Protocol, runtime_checkable

from webhook.domain.models.admission import AdmissionRequest
from webhook.domain.models.patch import JSONPatchOp


@runtime_checkable
class MutatorProtocol(Protocol):
    """Contract for a resource mutator.

    Implementations must:
    - Declare `name` as a class variable (used in metric labels).
    - Be idempotent — safe to call multiple times on the same object (reinvocationPolicy: IfNeeded).
    - Return an empty list when no mutation is needed (never raise for a no-op).
    - Never mutate the `request` argument.
    """

    name: ClassVar[str]

    async def mutate(self, request: AdmissionRequest) -> list[JSONPatchOp]:
        """Compute patch operations for the given admission request.

        Args:
            request: The inbound AdmissionRequest. Treat as read-only.

        Returns:
            List of JSON Patch operations to apply. Empty list means no mutation.
        """
        ...
