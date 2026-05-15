.PHONY: help build-local load-local deploy-local local uninstall clean test lint lint-fix typecheck helm-lint

# ── Configuration ────────────────────────────────────────────────────────────
IMAGE_BASE        := k8s-mutating-webhook
TAG               ?= $(shell git rev-parse --short HEAD 2>/dev/null || echo "dev")
HELM_CHART        := helm/webhook
KIND_CLUSTER      ?= groundcover

# ── Help ──────────────────────────────────────────────────────────────────────

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | \
	  awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-20s\033[0m %s\n", $$1, $$2}'

# ── Build ────────────────────────────────────────────────────────────────────

build-local: ## Build image and load directly into local Docker daemon (no registry needed)
	docker build \
	  --build-arg BUILDKIT_INLINE_CACHE=1 \
	  --build-arg SERVICE_NAME=$(IMAGE_BASE) \
	  --build-arg SERVICE_NAMESPACE=webhook-system \
	  -t $(IMAGE_BASE):$(TAG) \
	  -t $(IMAGE_BASE):latest \
	  -t localhost/$(IMAGE_BASE):$(TAG) \
	  -t localhost/$(IMAGE_BASE):latest \
	  .
	@echo "Image loaded into local Docker daemon as $(IMAGE_BASE):$(TAG)"
	@echo "To load into kind: make load-local"

load-local: ## Load the locally-built image into a kind cluster (KIND_CLUSTER=groundcover)
	@if ! docker image inspect localhost/$(IMAGE_BASE):$(TAG) > /dev/null 2>&1; then \
	  echo "Image localhost/$(IMAGE_BASE):$(TAG) not found — run 'make build-local' first"; exit 1; \
	fi
	kind load docker-image localhost/$(IMAGE_BASE):$(TAG) --name $(KIND_CLUSTER)
	@echo "Image localhost/$(IMAGE_BASE):$(TAG) loaded into kind cluster '$(KIND_CLUSTER)'"

# ── Tests ─────────────────────────────────────────────────────────────────────

test: ## Run all tests with coverage
	@uv run python -c "import pytest_cov" 2>/dev/null || uv add --dev pytest-cov
	uv run pytest tests/ \
	  --asyncio-mode=auto \
	  --cov=src/webhook \
	  --cov-report=term-missing \
	  --cov-report=html:htmlcov \
	  -v

test-unit: ## Run only unit tests
	uv run pytest tests/unit/ --asyncio-mode=auto -v

test-integration: ## Run only integration tests
	uv run pytest tests/integration/ --asyncio-mode=auto -v

# ── Static analysis ───────────────────────────────────────────────────────────

lint: ## Run ruff linter and formatter check
	uv run ruff check src/ tests/
	uv run ruff format --check src/ tests/

lint-fix: ## Auto-fix ruff lint issues
	uv run ruff check --fix src/ tests/
	uv run ruff format src/ tests/

typecheck: ## Run mypy strict type checking
	uv run mypy src/webhook/

# ── Helm ─────────────────────────────────────────────────────────────────────

helm-lint: ## Lint the Helm chart
	helm lint $(HELM_CHART) --values $(HELM_CHART)/ci/lint-values.yaml

deploy-local: ## Extract TLS certs from the local image and install the Helm chart in one step
	@if ! docker image inspect $(IMAGE_BASE):$(TAG) > /dev/null 2>&1; then \
	  echo "Image $(IMAGE_BASE):$(TAG) not found — run 'make build-local' first"; exit 1; \
	fi
	@echo "Extracting TLS certs from $(IMAGE_BASE):$(TAG)..."
	@IS_UPGRADE=$$(helm status k8s-mutating-webhook --namespace webhook-system --kube-context kind-$(KIND_CLUSTER) > /dev/null 2>&1 && echo "1" || echo "0"); \
	 CA_BUNDLE=$$(docker run --rm --entrypoint base64 $(IMAGE_BASE):$(TAG) -w0 /app/certs/ca.crt); \
	 TLS_CERT=$$(docker run --rm --entrypoint base64 $(IMAGE_BASE):$(TAG) -w0 /app/certs/tls.crt); \
	 TLS_KEY=$$(docker run --rm --entrypoint base64 $(IMAGE_BASE):$(TAG) -w0 /app/certs/tls.key); \
	 echo "Deploying with Helm..."; \
	 helm upgrade --install k8s-mutating-webhook $(HELM_CHART) \
	   --namespace webhook-system \
	   --create-namespace \
	   --values $(HELM_CHART)/values.yaml \
	   --set image.repository=localhost/$(IMAGE_BASE) \
	   --set image.tag=$(TAG) \
	   --set resources.requests.memory=256Mi \
	   --set resources.limits.memory=384Mi \
	   --set tls.caBundle="$$CA_BUNDLE" \
	   --set tls.cert="$$TLS_CERT" \
	   --set tls.key="$$TLS_KEY" \
	   --set topologySpread.enabled=false \
	   --set replicaCount=2 \
	   --set podDisruptionBudget.minAvailable=1 \
	   --set autoscaling.enabled=false \
	   --set image.pullPolicy=Never \
	   --set webhook.failurePolicy=Ignore \
	   --kube-context kind-$(KIND_CLUSTER); \
	 if [ "$$IS_UPGRADE" = "1" ]; then \
	   echo "Restarting pods to pick up new image..."; \
	   kubectl rollout restart deployment k8s-mutating-webhook \
	     -n webhook-system --context kind-$(KIND_CLUSTER) 2>/dev/null || true; \
	 fi

uninstall: ## Remove the webhook completely (Helm release, namespace, and MutatingWebhookConfiguration)
	helm uninstall k8s-mutating-webhook --namespace webhook-system --kube-context kind-$(KIND_CLUSTER) 2>/dev/null || true
	kubectl delete namespace webhook-system --context kind-$(KIND_CLUSTER) --ignore-not-found
	kubectl delete mutatingwebhookconfiguration k8s-mutating-webhook --context kind-$(KIND_CLUSTER) --ignore-not-found
	@echo "Webhook uninstalled."

local: ## Full local setup: build image, load into kind, deploy webhook (requires an empty kind cluster named $(KIND_CLUSTER))
	$(MAKE) build-local
	$(MAKE) load-local
	$(MAKE) deploy-local

clean: ## Remove all local build artifacts (caches, coverage, venv)
	rm -rf .venv .mypy_cache .ruff_cache .pytest_cache htmlcov .coverage
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name '*.pyc' -delete
	@echo "Cleaned."

