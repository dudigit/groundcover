"""Single source of truth for all domain type aliases.

All Annotated constraints are enforced at Pydantic parse time — not scattered at call sites.
"""

from typing import Annotated, Any, Literal

from pydantic import Field

# --- Kubernetes admission types ---

AdmissionUID = Annotated[str, Field(min_length=1)]

ResourceKind = Literal["Deployment", "Service"]

OperationType = Literal["CREATE", "UPDATE", "DELETE", "CONNECT"]

# --- JSON Patch types (RFC 6902) ---

JSONPatchOperation = Literal["add", "remove", "replace", "move", "copy", "test"]

# Path must start with "/" per RFC 6902
PatchPath = Annotated[str, Field(pattern=r"^/")]

# --- Kubernetes label types ---

# Mirrors the K8s label key spec: 63-char name, optional 253-char prefix
LabelKey = Annotated[
    str,
    Field(
        min_length=1,
        max_length=316,  # 253 prefix + "/" + 63 name
        pattern=r"^([a-z0-9][a-z0-9\-.]{0,251}[a-z0-9]/)?[a-zA-Z0-9][a-zA-Z0-9\-_.]{0,61}[a-zA-Z0-9]?$",
    ),
]

LabelValue = Annotated[str, Field(max_length=63)]

LabelMap = dict[LabelKey, LabelValue]  # type: ignore[type-arg]  # K8s label key spec is complex

# Untyped K8s resource body — schema too large and versioned externally
KubernetesObject = dict[str, Any]  # type: ignore[type-arg]  # intentional; K8s schema not modelled
