"""JSON Patch (RFC 6902) domain model.

Patch operations are typed domain objects throughout the application layer.
Serialization to base64 JSON happens only at the HTTP boundary.
"""

import json
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

from webhook.domain.types import JSONPatchOperation, PatchPath


class JSONPatchOp(BaseModel):
    """A single JSON Patch operation (RFC 6902)."""

    model_config = ConfigDict(
        strict=True,
        extra="forbid",
        frozen=True,
        # Serialize `from_path` field back to JSON key "from"
        populate_by_name=True,
    )

    op: JSONPatchOperation
    path: PatchPath
    value: str | int | bool | dict[str, Any] | list[Any] | None = None  # type: ignore[type-arg]  # RFC 6902 allows any JSON value
    from_path: PatchPath | None = Field(default=None, alias="from")

    @model_validator(mode="after")
    def validate_op_fields(self) -> "JSONPatchOp":
        """Enforce RFC 6902 op-field contracts at model creation time."""
        if self.op == "remove" and self.value is not None:
            raise ValueError("'remove' op must not carry 'value'")
        if self.op in ("move", "copy") and self.from_path is None:
            raise ValueError(f"'{self.op}' op requires 'from' field")
        if self.op == "test" and self.value is None:
            raise ValueError("'test' op requires 'value'")
        return self


def serialize_patch(ops: list[JSONPatchOp]) -> bytes:
    """Serialize a list of patch ops to a JSON bytes array for the AdmissionResponse."""
    return json.dumps(
        [
            op.model_dump(by_alias=True, exclude_none=True)
            for op in ops
        ]
    ).encode()


def make_add_label_op(key: str, value: str) -> JSONPatchOp:
    """Create an 'add' patch op for a single metadata label."""
    safe_key = key.replace("/", "~1")
    return JSONPatchOp(op="add", path=f"/metadata/labels/{safe_key}", value=value)


def make_ensure_labels_object_op() -> JSONPatchOp:
    """Create an 'add' op to initialise /metadata/labels if absent."""
    return JSONPatchOp(op="add", path="/metadata/labels", value={})
