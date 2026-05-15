"""Singleton MutatorRegistry instance.

Defined here (not in ports/) to break circular imports:
  registry_instance → ports/registry (pure)
  mutation modules  → registry_instance + ports/mutator
  bootstrap/inject  → mutation modules (triggers @register decorators)
"""

from webhook.ports.registry import MutatorRegistry

registry = MutatorRegistry()
