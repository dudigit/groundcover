"""Integration tests for POST /mutate using AsyncClient against the real FastAPI app."""

import base64
import json
from typing import Any

import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport

from tests.conftest import build_deployment_review, build_service_review


# ── App fixture ───────────────────────────────────────────────────────────────

@pytest.fixture
def app():
    """Create the FastAPI app with test overrides applied."""
    # Config singleton already patched by autouse mock_tls_paths in conftest.py
    # Reset bootstrap state between tests
    from webhook.adapters.api.health import _shutting_down
    import webhook.adapters.api.health as health_module
    health_module._shutting_down = False

    from webhook.bootstrap.app_factory import create_app
    return create_app()


@pytest_asyncio.fixture
async def client(app) -> AsyncClient:
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as ac:
        yield ac


# ── Health endpoints ──────────────────────────────────────────────────────────

class TestHealthEndpoints:
    async def test_healthz_returns_200(self, client: AsyncClient) -> None:
        response = await client.get("/healthz")
        assert response.status_code == 200

    async def test_readyz_returns_200_when_registry_has_mutators(
        self, client: AsyncClient
    ) -> None:
        response = await client.get("/readyz")
        assert response.status_code == 200

    async def test_metrics_endpoint_is_accessible(self, client: AsyncClient) -> None:
        response = await client.get("/metrics")
        assert response.status_code == 200
        assert b"webhook_" in response.content or b"python_" in response.content


# ── Deployment mutations ──────────────────────────────────────────────────────

class TestDeploymentMutation:
    async def test_create_deployment_returns_allowed_true(
        self, client: AsyncClient
    ) -> None:
        review = build_deployment_review("CREATE")
        resp = await client.post("/mutate", json=review)
        assert resp.status_code == 200
        data = resp.json()
        assert data["response"]["allowed"] is True

    async def test_create_deployment_returns_patch(self, client: AsyncClient) -> None:
        review = build_deployment_review("CREATE")
        resp = await client.post("/mutate", json=review)
        data = resp.json()
        patch_b64 = data["response"].get("patch")
        assert patch_b64 is not None
        ops = json.loads(base64.b64decode(patch_b64))
        paths = [op["path"] for op in ops]
        assert any("managed-by" in p for p in paths)

    async def test_update_deployment_returns_patch(self, client: AsyncClient) -> None:
        review = build_deployment_review("UPDATE")
        resp = await client.post("/mutate", json=review)
        assert resp.status_code == 200
        data = resp.json()
        assert data["response"]["allowed"] is True

    async def test_dry_run_deployment_returns_allowed_no_patch(
        self, client: AsyncClient
    ) -> None:
        review = build_deployment_review("CREATE", dry_run=True)
        resp = await client.post("/mutate", json=review)
        assert resp.status_code == 200
        data = resp.json()
        assert data["response"]["allowed"] is True
        assert data["response"].get("patch") is None

    async def test_uid_echoed_in_response(self, client: AsyncClient) -> None:
        review = build_deployment_review("CREATE")
        resp = await client.post("/mutate", json=review)
        data = resp.json()
        assert data["response"]["uid"] == "test-uid-1234"

    async def test_patch_type_is_json_patch(self, client: AsyncClient) -> None:
        review = build_deployment_review("CREATE")
        resp = await client.post("/mutate", json=review)
        data = resp.json()
        if data["response"].get("patch"):
            assert data["response"]["patchType"] == "JSONPatch"


# ── Service mutations ─────────────────────────────────────────────────────────

class TestServiceMutation:
    async def test_create_service_returns_allowed_true(
        self, client: AsyncClient
    ) -> None:
        review = build_service_review("CREATE")
        resp = await client.post("/mutate", json=review)
        assert resp.status_code == 200
        assert resp.json()["response"]["allowed"] is True

    async def test_create_service_injects_resource_kind_label(
        self, client: AsyncClient
    ) -> None:
        review = build_service_review("CREATE")
        resp = await client.post("/mutate", json=review)
        patch_b64 = resp.json()["response"].get("patch")
        assert patch_b64 is not None
        ops = json.loads(base64.b64decode(patch_b64))
        kind_op = next((op for op in ops if "resource-kind" in op["path"]), None)
        assert kind_op is not None
        assert kind_op["value"] == "Service"

    async def test_update_service_returns_patch(self, client: AsyncClient) -> None:
        review = build_service_review("UPDATE")
        resp = await client.post("/mutate", json=review)
        assert resp.status_code == 200
        assert resp.json()["response"]["allowed"] is True


# ── Error handling ────────────────────────────────────────────────────────────

class TestMutateErrorHandling:
    async def test_malformed_body_returns_200_allowed(
        self, client: AsyncClient
    ) -> None:
        """Webhook must never block — invalid bodies return allowed=True."""
        resp = await client.post(
            "/mutate",
            content=b"not json",
            headers={"Content-Type": "application/json"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["response"]["allowed"] is True

    async def test_missing_request_field_returns_allowed(
        self, client: AsyncClient
    ) -> None:
        """AdmissionReview without 'request' is allowed through (fail-open)."""
        resp = await client.post(
            "/mutate",
            json={"apiVersion": "admission.k8s.io/v1", "kind": "AdmissionReview"},
        )
        assert resp.status_code == 200
        assert resp.json()["response"]["allowed"] is True

    async def test_unknown_kind_returns_allowed_no_patch(
        self, client: AsyncClient
    ) -> None:
        """Resources with no registered mutator are allowed through without patch."""
        from tests.conftest import build_admission_review
        review = build_admission_review(
            kind="ConfigMap",
            api_version_group="",
            api_version="v1",
            operation="CREATE",
            object_body={"metadata": {"name": "test", "labels": {}}},
        )
        resp = await client.post("/mutate", json=review)
        assert resp.status_code == 200
        data = resp.json()
        assert data["response"]["allowed"] is True
        assert data["response"].get("patch") is None
