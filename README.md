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

## Building an image ready for deploy

The Makefile supports two modes. **Local mode is the default** — no remote registry required.

### Mode 1 — Local registry (default)

A lightweight Docker registry runs on `localhost:5000`. Use this when iterating locally or when you have no remote registry.

```bash
# 1. Start the local registry (once per machine)
make registry-start

# 2. Build the image and push it to localhost:5000
make build

# 3. Extract the TLS certs that were baked into the image
make extract-tls-secrets
#    ↳ Prints the base64 values you need for values.yaml (tls.caBundle / tls.cert / tls.key)

# 4. Deploy with Helm (paste the values from step 3)
make helm-install
```

> The image tag defaults to the current git short SHA (`git rev-parse --short HEAD`).  
> Override it at any time: `make build TAG=1.2.3`

---

### Mode 2 — No registry at all (kind / minikube)

Builds the image directly into the local Docker daemon and loads it straight into a `kind` cluster.  
No registry container is needed.

```bash
# 1. Build and tag the image in the local Docker daemon
make build-local

# 2. Load the image into your kind cluster
make load-local

# 3. Deploy — extracts TLS certs from the image and installs the Helm chart in one step
make deploy-local
```

---

### Mode 3 — Remote registry

Set `USE_REMOTE=1` to target a remote registry (e.g. GHCR, ECR, GCR).

```bash
# Override the registry org once, or export it permanently
export REMOTE_REGISTRY=ghcr.io/my-org

make push USE_REMOTE=1
# equivalent shortcut:
make push
```

`make push` always forces `USE_REMOTE=1` regardless of the default.

---

## TLS certificates

TLS certs are **generated at Docker build time** inside stage 1 of the Dockerfile — no `cert-manager` or external CA is required.

After building, extract the certs and paste them into your Helm values:

```bash
make extract-tls-secrets
```

Output (example):

```yaml
tls:
  caBundle: LS0tLS1CRUdJTiBDRVJUSUZJQ0FURS0tLS0t...
  cert:     LS0tLS1CRUdJTiBDRVJUSUZJQ0FURS0tLS0t...
  key:      LS0tLS1CRUdJTiBQUklWQVRFIEtFWS0tLS0t...
```

Paste these values into `helm/webhook/values.yaml` or pass them on the command line:

```bash
make helm-install \
  TLS_CA_BUNDLE=<caBundle> \
  TLS_CERT=<cert> \
  TLS_KEY=<key>
```

---

## All available `make` targets

```
make help
```

| Target | Description |
|--------|-------------|
| `registry-start` | Start a local Docker registry on `localhost:5000` |
| `registry-stop` | Stop and remove the local registry |
| `build` | Build + push to local registry (default) |
| `build-local` | Build and load into local Docker daemon only (no registry) |
| `load-local` | Load the local daemon image into a kind cluster |
| `push` | Build + push to remote registry (`USE_REMOTE=1`) |
| `deploy-local` | Extract TLS from local image + `helm upgrade --install` in one step |
| `extract-tls-secrets` | Print base64 TLS values from the built image |
| `test` | Run all tests with coverage |
| `test-unit` | Run unit tests only |
| `test-integration` | Run integration tests only |
| `lint` | Run ruff linter + format check |
| `lint-fix` | Auto-fix ruff issues |
| `typecheck` | Run mypy strict type checking |
| `helm-lint` | Lint the Helm chart |
| `helm-template` | Dry-render Helm templates locally |
| `helm-install` | `helm upgrade --install` into current context |
| `dev` | Run the webhook process locally (needs TLS at `/tmp/certs/`) |

---

## End-to-end local walkthrough

```bash
# 1. Start a kind cluster (1 control-plane + 2 workers, named "groundcover")
kind create cluster --name groundcover --config <(printf \
  'kind: Cluster\napiVersion: kind.x-k8s.io/v1alpha4\nnodes:\n- role: control-plane\n- role: worker\n- role: worker\n')

# 2. Build and load the image (no registry needed)
make build-local
make load-local

# 3. Deploy — extracts TLS certs from the image and installs Helm in one step
make deploy-local

# 5. Verify the pods are running
kubectl -n webhook-system get pods --context kind-groundcover

# 6. Send a test Deployment — watch the labels appear
kubectl create deployment nginx --image=nginx --context kind-groundcover
kubectl get deployment nginx --context kind-groundcover -o jsonpath='{.metadata.labels}'
# Expected: {"app":"nginx","app.kubernetes.io/managed-by":"webhook","webhook.io/injected-at":"...","webhook.io/resource-kind":"Deployment"}
kubectl delete deployment nginx --context kind-groundcover

# 7. Send a test Service — watch the labels appear
kubectl create service clusterip nginx-svc --tcp=80:80 --context kind-groundcover
kubectl get service nginx-svc --context kind-groundcover -o jsonpath='{.metadata.labels}'
# Expected: {"app":"nginx-svc","app.kubernetes.io/managed-by":"webhook","webhook.io/injected-at":"...","webhook.io/resource-kind":"Service"}
kubectl delete service nginx-svc --context kind-groundcover
```

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
