.PHONY: help build build-local push load-local registry-start registry-stop test lint typecheck helm-lint extract-tls-secrets deploy-local

# ── Registry configuration ────────────────────────────────────────────────────
# By default the image is built for the local registry (localhost:5000).
# Set USE_REMOTE=1 to target a remote registry instead.
USE_REMOTE        ?= 0
LOCAL_REGISTRY    ?= localhost:5000
REMOTE_REGISTRY   ?= ghcr.io/your-org
IMAGE_BASE        := k8s-mutating-webhook
TAG               ?= $(shell git rev-parse --short HEAD 2>/dev/null || echo "dev")
HELM_CHART        := helm/webhook
KIND_CLUSTER      ?= groundcover

ifeq ($(USE_REMOTE),1)
  IMAGE_NAME := $(REMOTE_REGISTRY)/$(IMAGE_BASE)
else
  IMAGE_NAME := $(LOCAL_REGISTRY)/$(IMAGE_BASE)
endif

# ── Help ──────────────────────────────────────────────────────────────────────

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | \
	  awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-20s\033[0m %s\n", $$1, $$2}'

# ── Local registry ────────────────────────────────────────────────────────────

registry-start: ## Start a local Docker registry on localhost:5000
	@if docker ps --format '{{.Names}}' | grep -q '^local-registry$$'; then \
	  echo "Local registry already running on $(LOCAL_REGISTRY)"; \
	else \
	  docker run -d --name local-registry --restart=always -p 5000:5000 registry:2 && \
	  echo "Local registry started on $(LOCAL_REGISTRY)"; \
	fi

registry-stop: ## Stop and remove the local Docker registry
	docker rm -f local-registry || true

# ── Build ─────────────────────────────────────────────────────────────────────

build: ## Build and push image to local registry (default). Set USE_REMOTE=1 for remote.
	docker build \
	  --build-arg BUILDKIT_INLINE_CACHE=1 \
	  --build-arg SERVICE_NAME=$(IMAGE_BASE) \
	  --build-arg SERVICE_NAMESPACE=webhook-system \
	  -t $(IMAGE_NAME):$(TAG) \
	  -t $(IMAGE_NAME):latest \
	  -t $(IMAGE_BASE):$(TAG) \
	  -t $(IMAGE_BASE):latest \
	  .
	docker push $(IMAGE_NAME):$(TAG)
	docker push $(IMAGE_NAME):latest
	@echo "Image available at $(IMAGE_NAME):$(TAG)"

build-local: ## Build image and load directly into local Docker daemon (no registry needed)
	docker build \
	  --build-arg BUILDKIT_INLINE_CACHE=1 \
	  --build-arg SERVICE_NAME=$(IMAGE_BASE) \
	  --build-arg SERVICE_NAMESPACE=webhook-system \
	  -t $(IMAGE_BASE):$(TAG) \
	  -t $(IMAGE_BASE):latest \
	  .
	@echo "Image loaded into local Docker daemon as $(IMAGE_BASE):$(TAG)"
	@echo "To use with kind:  make load-local"

load-local: ## Load the locally-built image into a kind cluster (KIND_CLUSTER=groundcover)
	@if ! docker image inspect $(IMAGE_BASE):$(TAG) > /dev/null 2>&1; then \
	  echo "Image $(IMAGE_BASE):$(TAG) not found — run 'make build-local' first"; exit 1; \
	fi
	kind load docker-image $(IMAGE_BASE):$(TAG) --name $(KIND_CLUSTER)
	@echo "Image $(IMAGE_BASE):$(TAG) loaded into kind cluster '$(KIND_CLUSTER)'"

push: ## Build and push to the remote registry (USE_REMOTE is forced to 1)
	$(MAKE) build USE_REMOTE=1

# ── TLS helpers ───────────────────────────────────────────────────────────────

extract-tls-secrets: ## Extract TLS certs from the locally-built image and output Helm values
	@if ! docker image inspect $(IMAGE_BASE):$(TAG) > /dev/null 2>&1; then \
	  echo "Image $(IMAGE_BASE):$(TAG) not found — run 'make build-local' or 'make build' first"; exit 1; \
	fi
	@echo "Extracting certs from $(IMAGE_BASE):$(TAG)..."
	@CA_BUNDLE=$$(docker run --rm --entrypoint base64 $(IMAGE_BASE):$(TAG) -w0 /app/certs/ca.crt); \
	 TLS_CERT=$$(docker run --rm --entrypoint base64 $(IMAGE_BASE):$(TAG) -w0 /app/certs/tls.crt); \
	 TLS_KEY=$$(docker run --rm --entrypoint base64 $(IMAGE_BASE):$(TAG) -w0 /app/certs/tls.key); \
	 echo "tls:"; \
	 echo "  caBundle: $$CA_BUNDLE"; \
	 echo "  cert: $$TLS_CERT"; \
	 echo "  key: $$TLS_KEY"

# ── Tests ─────────────────────────────────────────────────────────────────────

test: ## Run all tests with coverage
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
	helm lint $(HELM_CHART)

helm-template: ## Render Helm templates locally (requires values override for tls)
	helm template k8s-mutating-webhook $(HELM_CHART) \
	  --set tls.caBundle=Zm9v \
	  --set tls.cert=Zm9v \
	  --set tls.key=Zm9v

deploy-local: ## Extract TLS certs from the local image and install the Helm chart in one step
	@if ! docker image inspect $(IMAGE_BASE):$(TAG) > /dev/null 2>&1; then \
	  echo "Image $(IMAGE_BASE):$(TAG) not found — run 'make build-local' first"; exit 1; \
	fi
	@echo "Extracting TLS certs from $(IMAGE_BASE):$(TAG)..."
	@CA_BUNDLE=$$(docker run --rm --entrypoint base64 $(IMAGE_BASE):$(TAG) -w0 /app/certs/ca.crt); \
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
	 echo "Restarting pods to pick up new image..."; \
	 kubectl rollout restart deployment k8s-mutating-webhook \
	   -n webhook-system --context kind-$(KIND_CLUSTER) 2>/dev/null || true

helm-install: ## Install the Helm chart into the current kubectl context (TLS values must be set in values.yaml)
	helm upgrade --install k8s-mutating-webhook $(HELM_CHART) \
	  --namespace webhook-system \
	  --create-namespace \
	  --values $(HELM_CHART)/values.yaml

# ── Dev helpers ───────────────────────────────────────────────────────────────

dev: ## Run the webhook locally (requires TLS certs at /tmp/certs/)
	WEBHOOK_TLS_CERT_PATH=/tmp/certs/tls.crt \
	WEBHOOK_TLS_KEY_PATH=/tmp/certs/tls.key \
	uv run gunicorn webhook.bootstrap.app_factory:app \
	  --worker-class uvicorn.workers.UvicornWorker \
	  --bind 0.0.0.0:8443 \
	  --workers 2 \
	  --keyfile /tmp/certs/tls.key \
	  --certfile /tmp/certs/tls.crt \
	  --log-level info
