# K8s Mutating Admission Webhook

A production-grade Kubernetes Mutating Admission Webhook written in Python 3.13+.  
Injects labels into **Deployments** and **Services** on `CREATE` and `UPDATE` using a self-registering `MutatorRegistry` and a 3-stage Alpine Docker build with dynamic TLS cert generation.

---

## Prerequisites

| Tool | Minimum version | Purpose |
|------|----------------|---------|
| Docker | 24+ with BuildKit | Build the image |
| `make` | any | Task runner |
| `helm` | 3.14+ | Deploy the chart |
| `kubectl` | 1.29+ | Cluster access |
| `kind` _(optional)_ | 0.22+ | Local cluster for testing |
| `uv` _(optional)_ | 0.4+ | Run tests / lint locally |

---

## Quickstart

```bash
# 1. Start a kind cluster (1 control-plane + 2 workers, named "groundcover")
kind create cluster --name groundcover --config <(printf 'kind: Cluster\napiVersion: kind.x-k8s.io/v1alpha4\nnodes:\n- role: control-plane\n- role: worker\n- role: worker\n')

# 2. Build the image, load it into kind, and deploy the webhook
make local

# 3. Verify the pods are running
kubectl -n webhook-system get pods --context kind-groundcover
```

> The image tag defaults to the current git short SHA (`git rev-parse --short HEAD`).  
> Override it at any time: `make local TAG=1.2.3`

---

## All available `make` targets

```
make help
```

| Target | Description |
|--------|-------------|
| `local` | **Full local setup**: build image, load into kind, deploy webhook |
| `build-local` | Build and tag the image in the local Docker daemon |
| `load-local` | Load the local daemon image into the kind cluster |
| `deploy-local` | Extract TLS from local image + `helm upgrade --install` in one step |
| `uninstall` | Remove the Helm release, namespace, and MutatingWebhookConfiguration |
| `test` | Run all tests with coverage |
| `test-unit` | Run unit tests only |
| `test-integration` | Run integration tests only |
| `lint` | Run ruff linter + format check |
| `lint-fix` | Auto-fix ruff issues |
| `typecheck` | Run mypy strict type checking |
| `helm-lint` | Lint the Helm chart |
| `helm-template` | Dry-render Helm templates locally |
| `dev` | Run the webhook process locally (needs TLS at `/tmp/certs/`) |

---

## End-to-end local walkthrough

```bash
# 1. Start a kind cluster (1 control-plane + 2 workers, named "groundcover")
kind create cluster --name groundcover --config <(printf 'kind: Cluster\napiVersion: kind.x-k8s.io/v1alpha4\nnodes:\n- role: control-plane\n- role: worker\n- role: worker\n')

# 2. Build, load, and deploy in one command
make local

# 3. Verify the pods are running
kubectl -n webhook-system get pods --context kind-groundcover

# 4. Send a test Deployment — watch the labels appear
kubectl create deployment nginx --image=nginx --context kind-groundcover
kubectl get deployment nginx --context kind-groundcover -o jsonpath='{.metadata.labels}'
# Expected: {"app":"nginx","app.kubernetes.io/managed-by":"webhook","webhook.io/injected-at":"...","webhook.io/resource-kind":"Deployment"}
kubectl delete deployment nginx --context kind-groundcover

# 5. Send a test Service — watch the labels appear
kubectl create service clusterip nginx-svc --tcp=80:80 --context kind-groundcover
kubectl get service nginx-svc --context kind-groundcover -o jsonpath='{.metadata.labels}'
# Expected: {"app":"nginx-svc","app.kubernetes.io/managed-by":"webhook","webhook.io/injected-at":"...","webhook.io/resource-kind":"Service"}
kubectl delete service nginx-svc --context kind-groundcover
```

---

## Teardown

To remove the webhook entirely — as if it was never installed:

```bash
make uninstall
```

This removes:
- The Helm release and all its Kubernetes resources (Deployment, Service, Secret, etc.)
- The `webhook-system` namespace
- The `MutatingWebhookConfiguration` (so the API server stops routing admission requests to the webhook)

After this, new Deployments and Services will no longer have labels injected.

---

## Project structure

```
.
├── Dockerfile                  3-stage Alpine build (cert-gen → builder → runtime)
├── Makefile
├── pyproject.toml
├── helm/webhook/               Helm chart
│   ├── Chart.yaml
│   ├── values.yaml
│   └── templates/
│       ├── deployment.yaml
│       ├── service.yaml
│       ├── mutatingwebhookconfiguration.yaml
│       ├── secret-tls.yaml
│       ├── horizontalpodautoscaler.yaml
│       ├── poddisruptionbudget.yaml
│       ├── networkpolicy.yaml
│       ├── prometheusrule.yaml
│       └── serviceaccount.yaml
└── src/webhook/
    ├── domain/                 Pure Python — no framework imports
    ├── application/            AdmissionService (fail-open pipeline)
    ├── ports/                  MutatorProtocol + MutatorRegistry
    ├── adapters/               FastAPI routes, Prometheus metrics, label mutators
    ├── infrastructure/         structlog JSON logging
    └── bootstrap/              App factory + dependency wiring
```
