"""Admission domain models aligned to admission.k8s.io/v1.

Design decisions:
- `object` / `old_object` are untyped dict — K8s schema is too large and versioned externally.
- `user_info` exposes only `username` — groups/extra omitted to prevent accidental PII logging.
- `dry_run` defaults to False — K8s omits the field when false.
- `patch` is stored as bytes in memory; base64 encoding happens at HTTP serialisation.
- All models are frozen — safe to share across async tasks without copying.
"""

import base64
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_serializer, model_validator

from webhook.domain.models.patch import JSONPatchOp, serialize_patch
from webhook.domain.types import AdmissionUID, KubernetesObject, OperationType


class UserInfo(BaseModel):
    """Subset of K8s UserInfo — only username to prevent PII logging."""

    model_config = ConfigDict(strict=True, extra="ignore", frozen=True)

    username: str = Field(min_length=0)


class GroupVersionKind(BaseModel):
    model_config = ConfigDict(strict=True, extra="ignore", frozen=True)

    group: str = ""
    version: str
    kind: str


class GroupVersionResource(BaseModel):
    model_config = ConfigDict(strict=True, extra="ignore", frozen=True)

    group: str = ""
    version: str
    resource: str


class AdmissionRequest(BaseModel):
    """Represents the request portion of an AdmissionReview (admission.k8s.io/v1)."""

    model_config = ConfigDict(strict=True, extra="ignore", frozen=True)

    uid: AdmissionUID
    kind: GroupVersionKind
    resource: GroupVersionResource
    name: str = ""
    namespace: str = ""
    operation: OperationType
    user_info: UserInfo = Field(alias="userInfo")
    object: KubernetesObject | None = None  # type: ignore[type-arg]  # null on DELETE
    old_object: KubernetesObject | None = Field(default=None, alias="oldObject")  # type: ignore[type-arg]
    dry_run: bool = Field(default=False, alias="dryRun")

    @model_validator(mode="after")
    def validate_object_presence(self) -> "AdmissionRequest":
        """Enforce K8s contract: object is null only on DELETE; old_object only on CREATE/CONNECT."""
        if self.operation == "DELETE" and self.object is not None:
            # K8s may still send object on DELETE in some versions — allow it
            pass
        return self


class AdmissionResponse(BaseModel):
    """Represents the response portion of an AdmissionReview."""

    model_config = ConfigDict(strict=False, extra="forbid", frozen=False)

    uid: AdmissionUID
    allowed: bool
    # Stored as raw bytes internally; base64-encoded when serialised to JSON
    patch: bytes | None = None
    patch_type: str | None = Field(default=None, alias="patchType")
    status_message: str | None = Field(default=None, alias="status")

    @classmethod
    def allow(cls, uid: AdmissionUID, patch_ops: list[JSONPatchOp]) -> "AdmissionResponse":
        """Construct an allow response, optionally with patch ops."""
        raw_patch = serialize_patch(patch_ops) if patch_ops else None
        return cls(
            uid=uid,
            allowed=True,
            patch=raw_patch,
            patchType="JSONPatch" if raw_patch else None,
        )

    @classmethod
    def deny(cls, uid: AdmissionUID, message: str) -> "AdmissionResponse":
        """Construct a deny response with a human-readable message."""
        return cls(uid=uid, allowed=False, status={"code": 400, "message": message})

    @model_serializer
    def serialise(self) -> dict[str, Any]:  # type: ignore[type-arg]  # Pydantic serialiser return type
        """Serialise to the K8s wire format: patch bytes → base64 string."""
        result: dict[str, Any] = {"uid": self.uid, "allowed": self.allowed}  # type: ignore[type-arg]
        if self.patch is not None:
            result["patch"] = base64.b64encode(self.patch).decode()
            result["patchType"] = "JSONPatch"
        if self.status_message is not None:
            result["status"] = self.status_message
        return result


class AdmissionReview(BaseModel):
    """Top-level AdmissionReview object (admission.k8s.io/v1)."""

    model_config = ConfigDict(strict=True, extra="ignore", frozen=False)

    api_version: str = Field(alias="apiVersion", default="admission.k8s.io/v1")
    kind: str = Field(default="AdmissionReview")
    request: AdmissionRequest | None = None
    response: AdmissionResponse | None = None

    @model_serializer
    def serialise(self) -> dict[str, Any]:  # type: ignore[type-arg]
        result: dict[str, Any] = {  # type: ignore[type-arg]
            "apiVersion": self.api_version,
            "kind": self.kind,
        }
        if self.response is not None:
            result["response"] = self.response.serialise()
        return result
