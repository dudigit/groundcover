"""MutatorRegistry — dynamic self-registering plugin registry.

Mutators register themselves by importing a module that calls `@registry.register(...)`.
The registry is keyed by (ResourceKind, OperationType) tuples so mypy catches typos at
definition time, not at runtime.
"""

from collections import defaultdict
from typing import Callable

from webhook.domain.types import OperationType, ResourceKind
from webhook.ports.mutator import MutatorProtocol

# Registry key: (kind, operation) — both are Literals so mypy validates call sites
ResourceOperation = tuple[ResourceKind, OperationType]


class MutatorRegistry:
    """Holds the mapping from (kind, operation) → list of mutators.

    Usage::

        registry = MutatorRegistry()

        @registry.register("Deployment", ["CREATE", "UPDATE"])
        class DeploymentLabelMutator:
            name = "DeploymentLabelMutator"
            async def mutate(self, request): ...
    """

    def __init__(self) -> None:
        self._registry: dict[ResourceOperation, list[MutatorProtocol]] = defaultdict(list)

    def register(
        self,
        kind: ResourceKind,
        operations: list[OperationType],
    ) -> Callable[[type[MutatorProtocol]], type[MutatorProtocol]]:
        """Class decorator that registers the mutator for the given kind + operations."""

        def decorator(cls: type[MutatorProtocol]) -> type[MutatorProtocol]:
            instance: MutatorProtocol = cls()
            for operation in operations:
                self._registry[(kind, operation)].append(instance)
            return cls

        return decorator

    def get_mutators(self, kind: str, operation: str) -> list[MutatorProtocol]:
        """Return all mutators registered for the given kind/operation pair.

        Returns an empty list if no match — never raises.
        Accepts plain `str` so callers don't need to cast from AdmissionRequest fields.
        """
        key: ResourceOperation | None = self._make_key(kind, operation)
        if key is None:
            return []
        return list(self._registry.get(key, []))

    def registered_kinds(self) -> list[str]:
        """Return all resource kinds that have at least one mutator registered."""
        return list({kind for kind, _ in self._registry})

    def is_ready(self) -> bool:
        """Return True if at least one mutator is registered."""
        return len(self._registry) > 0

    @staticmethod
    def _make_key(kind: str, operation: str) -> ResourceOperation | None:
        """Validate and cast plain strings to Literal-typed key, or return None."""
        valid_kinds: set[str] = {"Deployment", "Service"}
        valid_ops: set[str] = {"CREATE", "UPDATE", "DELETE", "CONNECT"}
        if kind not in valid_kinds or operation not in valid_ops:
            return None
        return (kind, operation)  # type: ignore[return-value]  # validated above
