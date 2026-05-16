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
| `dev` | Run the webhook **locally without a container** (auto-generates TLS certs, enables `--reload`) |
| `dev-debug` | Run the webhook under `debugpy` and wait for VS Code to attach on port `5678` |

---

## Local debugging with `make dev`

Use `make dev` when you want to debug the webhook handler locally with `curl`, without rebuilding the image or redeploying to kind.

### 1. Start the local dev server

```bash
make dev
```

This will:
- generate self-signed TLS certs in `.dev-certs/` on first run
- start the webhook on `https://localhost:8443`
- enable auto-reload when you edit Python files

### 2. Send a complete AdmissionReview to `/mutate`

Open a second terminal and run:

```bash
curl -sk -X POST https://localhost:8443/mutate \
    -H "Content-Type: application/json" \
    -d '{
        "apiVersion": "admission.k8s.io/v1",
        "kind": "AdmissionReview",
        "request": {
            "uid": "service-debug-001",
            "kind": {
                "group": "",
                "version": "v1",
                "kind": "Service"
            },
            "resource": {
                "group": "",
                "version": "v1",
                "resource": "services"
            },
            "requestKind": {
                "group": "",
                "version": "v1",
                "kind": "Service"
            },
            "requestResource": {
                "group": "",
                "version": "v1",
                "resource": "services"
            },
            "name": "demo-service",
            "namespace": "default",
            "operation": "CREATE",
            "userInfo": {
                "username": "debugger"
            },
            "object": {
                "apiVersion": "v1",
                "kind": "Service",
                "metadata": {
                    "name": "demo-service",
                    "namespace": "default",
                    "labels": {
                        "app": "demo-service"
                    }
                },
                "spec": {
                    "selector": {
                        "app": "demo-service"
                    },
                    "ports": [
                        {
                            "port": 80,
                            "targetPort": 8080
                        }
                    ]
                }
            },
            "oldObject": null,
            "dryRun": false
        }
    }'
```

### 3. Expected result

You should get an `AdmissionReview` response with:
- `response.allowed: true`
- `response.patchType: JSONPatch`
- `response.patch`: a base64-encoded JSON patch

The response body will look like this:

```json
{
    "apiVersion": "admission.k8s.io/v1",
    "kind": "AdmissionReview",
    "response": {
        "uid": "service-debug-001",
        "allowed": true,
        "patchType": "JSONPatch",
        "patch": "W3sib3AiOiJhZGQiLCJwYXRoIjoiL21ldGFkYXRhL2xhYmVscy8uLi4ifV0="
    }
}
```

### 4. Decode the patch so it is easy to inspect

```bash
curl -sk -X POST https://localhost:8443/mutate \
    -H "Content-Type: application/json" \
    -d '{
        "apiVersion": "admission.k8s.io/v1",
        "kind": "AdmissionReview",
        "request": {
            "uid": "service-debug-001",
            "kind": {"group": "", "version": "v1", "kind": "Service"},
            "resource": {"group": "", "version": "v1", "resource": "services"},
            "requestKind": {"group": "", "version": "v1", "kind": "Service"},
            "requestResource": {"group": "", "version": "v1", "resource": "services"},
            "name": "demo-service",
            "namespace": "default",
            "operation": "CREATE",
            "userInfo": {"username": "debugger"},
            "object": {
                "apiVersion": "v1",
                "kind": "Service",
                "metadata": {
                    "name": "demo-service",
                    "namespace": "default",
                    "labels": {"app": "demo-service"}
                },
                "spec": {
                    "selector": {"app": "demo-service"},
                    "ports": [{"port": 80, "targetPort": 8080}]
                }
            },
            "oldObject": null,
            "dryRun": false
        }
    }' | jq -r '.response.patch' | base64 --decode
```

Expected decoded patch shape:

```json
[
    {
        "op": "add",
        "path": "/metadata/labels/app.kubernetes.io~1managed-by",
        "value": "webhook"
    },
    {
        "op": "add",
        "path": "/metadata/labels/webhook.io~1injected-at",
        "value": "2026-05-16T..."
    },
    {
        "op": "add",
        "path": "/metadata/labels/webhook.io~1resource-kind",
        "value": "Service"
    }
]
```

### 5. What this is good for

This local flow is useful when you want to:
- debug the admission handler without kind or Helm in the loop
- set breakpoints in the Python code and replay the same request quickly
- modify the request body to test edge cases like `UPDATE`, unsupported resource kinds, or malformed payloads

### Important: `make dev` vs `make dev-debug`

- Use `make dev` when you only want fast local requests plus auto-reload.
- Use `make dev-debug` when you want **real breakpoints in VS Code**.

`make dev` runs Gunicorn, which starts worker processes. That is good for local manual testing, but awkward for attaching a debugger. `make dev-debug` runs the app under `debugpy` with a single process and waits for VS Code to attach before serving requests.

---

## Breakpoint debugging in VS Code

This is the full breakpoint workflow.

### 1. Prerequisites

The repository already includes:
- the `dev-debug` Make target
- `debugpy` as a dev dependency
- a VS Code attach configuration in [.vscode/launch.json](.vscode/launch.json)

That launch configuration is named:

```text
Python: Attach to webhook (debugpy)
```

### 2. Set your breakpoints first

Before starting the server, open these files in VS Code and click in the gutter to add breakpoints.

Best places to pause for a `Service CREATE` request:

1. Request body enters the HTTP handler at [src/webhook/adapters/api/webhook.py](src/webhook/adapters/api/webhook.py#L44)
2. AdmissionReview parsing happens at [src/webhook/adapters/api/webhook.py](src/webhook/adapters/api/webhook.py#L47)
3. Control enters the service layer at [src/webhook/adapters/api/webhook.py](src/webhook/adapters/api/webhook.py#L79)
4. Dry-run is checked at [src/webhook/application/services/admission_service.py](src/webhook/application/services/admission_service.py#L51)
5. The mutation pipeline starts at [src/webhook/application/services/admission_service.py](src/webhook/application/services/admission_service.py#L61)
6. Matching mutators are resolved at [src/webhook/application/services/admission_service.py](src/webhook/application/services/admission_service.py#L84)
7. The selected mutator is invoked at [src/webhook/application/services/admission_service.py](src/webhook/application/services/admission_service.py#L94)
8. Desired Service labels are built at [src/webhook/adapters/mutations/labels/service_labels.py](src/webhook/adapters/mutations/labels/service_labels.py#L31)
9. Existing labels are read at [src/webhook/adapters/mutations/base.py](src/webhook/adapters/mutations/base.py#L29)
10. Individual JSON patch ops are appended at [src/webhook/adapters/mutations/base.py](src/webhook/adapters/mutations/base.py#L38)

If you only want one breakpoint, start with [src/webhook/adapters/api/webhook.py](src/webhook/adapters/api/webhook.py#L79). That is the clean handoff from the HTTP layer into the mutation service.

### 3. Start the webhook in debug mode

In a terminal, run:

```bash
make dev-debug
```

What happens here:
- local TLS certs are generated in `.dev-certs/` if they do not already exist
- `debugpy` starts and listens on port `5678`
- the process waits for VS Code to attach
- once attached, the HTTPS server starts on `https://localhost:8443`

### 4. Attach VS Code to the running process

In VS Code:

1. Open the Run and Debug view
2. Choose `Python: Attach to webhook (debugpy)`
3. Click Start Debugging

Once attached, `make dev-debug` will continue booting and the webhook will start serving requests.

### 5. Trigger the webhook with a full request

Use a second terminal and send this request:

```bash
curl -sk -X POST https://localhost:8443/mutate \
    -H "Content-Type: application/json" \
    -d '{
        "apiVersion": "admission.k8s.io/v1",
        "kind": "AdmissionReview",
        "request": {
            "uid": "service-breakpoint-001",
            "kind": {"group": "", "version": "v1", "kind": "Service"},
            "resource": {"group": "", "version": "v1", "resource": "services"},
            "requestKind": {"group": "", "version": "v1", "kind": "Service"},
            "requestResource": {"group": "", "version": "v1", "resource": "services"},
            "name": "debug-service",
            "namespace": "default",
            "operation": "CREATE",
            "userInfo": {"username": "debugger"},
            "object": {
                "apiVersion": "v1",
                "kind": "Service",
                "metadata": {
                    "name": "debug-service",
                    "namespace": "default",
                    "labels": {"app": "debug-service"}
                },
                "spec": {
                    "selector": {"app": "debug-service"},
                    "ports": [{"port": 80, "targetPort": 8080}]
                }
            },
            "oldObject": null,
            "dryRun": false
        }
    }'
```

At this point VS Code should stop on your first breakpoint.

### 6. What to inspect at each breakpoint

- In [src/webhook/adapters/api/webhook.py](src/webhook/adapters/api/webhook.py#L44): inspect `raw_body` to confirm the exact JSON that reached the server.
- In [src/webhook/adapters/api/webhook.py](src/webhook/adapters/api/webhook.py#L47): step over and inspect `review` and `parse_error`.
- In [src/webhook/application/services/admission_service.py](src/webhook/application/services/admission_service.py#L84): inspect the mutators returned for `Service` + `CREATE`.
- In [src/webhook/adapters/mutations/labels/service_labels.py](src/webhook/adapters/mutations/labels/service_labels.py#L31): inspect `desired` and confirm the injected labels are present.
- In [src/webhook/adapters/mutations/base.py](src/webhook/adapters/mutations/base.py#L29): inspect `existing_labels` to see what the incoming object already had.
- In [src/webhook/adapters/mutations/base.py](src/webhook/adapters/mutations/base.py#L38): inspect `key`, `value`, and the growing `ops` list.

### 7. Expected result after continuing execution

Once execution continues past the breakpoints, the response should contain:

- `response.allowed: true`
- `response.patchType: JSONPatch`
- `response.patch`: a base64-encoded patch

If you decode the patch, it should contain `add` operations for labels like:

- `app.kubernetes.io/managed-by=webhook`
- `webhook.io/injected-at=<timestamp>`
- `webhook.io/resource-kind=Service`

### 8. Useful variants while debugging

- Change `"dryRun": false` to `"dryRun": true` and keep a breakpoint at [src/webhook/application/services/admission_service.py](src/webhook/application/services/admission_service.py#L51) to verify the dry-run short-circuit.
- Change `"operation": "CREATE"` to `"UPDATE"` to verify the same mutator path for updates.
- Remove `metadata.labels` from the request body to see the code add `/metadata/labels` before appending label entries.
- Change `kind` from `Service` to an unsupported resource to inspect the no-mutator path.

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
