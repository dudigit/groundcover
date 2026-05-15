"""Shared test fixtures for unit and integration tests."""

import json
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

# ── TLS fixture for config validation ─────────────────────────────────────────

@pytest.fixture(autouse=True)
def mock_tls_paths(tmp_path: Path) -> None:
    """Create dummy TLS files so AppConfig passes path existence validation."""
    cert = tmp_path / "tls.crt"
    key = tmp_path / "tls.key"
    cert.write_text("CERT")
    key.write_text("KEY")
    with patch.dict(
        "os.environ",
        {
            "WEBHOOK_TLS_CERT_PATH": str(cert),
            "WEBHOOK_TLS_KEY_PATH": str(key),
        },
    ):
        # Reset singleton so each test gets a fresh config
        import webhook.config as cfg_module
        cfg_module._config = None
        yield
        cfg_module._config = None


# ── AdmissionReview fixture builders ─────────────────────────────────────────

def build_admission_review(
    kind: str,
    api_version_group: str,
    api_version: str,
    operation: str,
    object_body: dict[str, Any],
    namespace: str = "default",
    username: str = "test-user",
    dry_run: bool = False,
) -> dict[str, Any]:
    """Build a minimal AdmissionReview dict for tests."""
    return {
        "apiVersion": "admission.k8s.io/v1",
        "kind": "AdmissionReview",
        "request": {
            "uid": "test-uid-1234",
            "kind": {
                "group": api_version_group,
                "version": api_version,
                "kind": kind,
            },
            "resource": {
                "group": api_version_group,
                "version": api_version,
                "resource": kind.lower() + "s",
            },
            "name": object_body.get("metadata", {}).get("name", "test-resource"),
            "namespace": namespace,
            "operation": operation,
            "userInfo": {"username": username, "uid": "user-uid"},
            "object": object_body,
            "oldObject": None,
            "dryRun": dry_run,
        },
    }


def build_deployment_review(
    operation: str = "CREATE",
    labels: dict[str, str] | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    return build_admission_review(
        kind="Deployment",
        api_version_group="apps",
        api_version="v1",
        operation=operation,
        dry_run=dry_run,
        object_body={
            "apiVersion": "apps/v1",
            "kind": "Deployment",
            "metadata": {
                "name": "test-deployment",
                "namespace": "default",
                "labels": labels or {},
            },
            "spec": {},
        },
    )


def build_service_review(
    operation: str = "CREATE",
    labels: dict[str, str] | None = None,
) -> dict[str, Any]:
    return build_admission_review(
        kind="Service",
        api_version_group="",
        api_version="v1",
        operation=operation,
        object_body={
            "apiVersion": "v1",
            "kind": "Service",
            "metadata": {
                "name": "test-service",
                "namespace": "default",
                "labels": labels or {},
            },
            "spec": {},
        },
    )
