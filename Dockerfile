# syntax=docker/dockerfile:1.9

# ─────────────────────────────────────────────────────────────────────────────
# Stage 1 — cert-gen
# Dynamically generates CA + server TLS cert on every docker build.
# Nothing from this stage enters the runtime image except /certs via COPY --from.
# ─────────────────────────────────────────────────────────────────────────────
FROM alpine:3.21 AS cert-gen

ARG SERVICE_NAME=webhook
ARG SERVICE_NAMESPACE=default

RUN apk add --no-cache openssl

WORKDIR /certs

RUN <<EOF
set -e

# CA private key
openssl genrsa -out ca.key 4096

# Self-signed CA cert (10-year, CA:TRUE)
openssl req -new -x509 -key ca.key -out ca.crt -days 3650 \
  -subj "/CN=webhook-ca/O=webhook"

# Server private key
openssl genrsa -out tls.key 4096

# openssl.cnf with SANs for the in-cluster service DNS names
cat > /certs/san.cnf <<CNFEOF
[req]
distinguished_name = req_distinguished_name
req_extensions     = v3_req
prompt             = no

[req_distinguished_name]
CN = ${SERVICE_NAME}.${SERVICE_NAMESPACE}.svc

[v3_req]
subjectAltName = @alt_names
keyUsage       = digitalSignature, keyEncipherment
extendedKeyUsage = serverAuth

[alt_names]
DNS.1 = ${SERVICE_NAME}
DNS.2 = ${SERVICE_NAME}.${SERVICE_NAMESPACE}
DNS.3 = ${SERVICE_NAME}.${SERVICE_NAMESPACE}.svc
DNS.4 = ${SERVICE_NAME}.${SERVICE_NAMESPACE}.svc.cluster.local
DNS.5 = localhost
IP.1  = 127.0.0.1
CNFEOF

# Server CSR
openssl req -new -key tls.key -out tls.csr -config /certs/san.cnf

# Sign server cert with the CA (1-year validity)
openssl x509 -req -in tls.csr -CA ca.crt -CAkey ca.key \
  -CAcreateserial -out tls.crt -days 365 \
  -extensions v3_req -extfile /certs/san.cnf

# Verify
openssl verify -CAfile ca.crt tls.crt

# Cleanup — only keep the three output files
rm -f ca.key ca.srl tls.csr san.cnf
EOF


# ─────────────────────────────────────────────────────────────────────────────
# Stage 2 — builder
# Builds the Python venv + pre-compiles bytecode.
# Uses python:3.13-alpine — SAME musl libc as runtime stage.
# C/Rust extension wheels (pydantic-core, uvloop) compiled here stay compatible.
# build-base is installed here and does NOT reach the runtime image.
# ─────────────────────────────────────────────────────────────────────────────
FROM python:3.13-alpine AS builder

SHELL ["/bin/sh", "-exc"]

# Build tools for C/Rust extension compilation — stays in this stage only
RUN apk add --no-cache build-base libffi-dev

# Copy uv from the official image — no apt/apk install needed
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

ENV UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1 \
    UV_PYTHON_DOWNLOADS=never \
    UV_PROJECT_ENVIRONMENT=/app

# Project root inside the build container.
# pyproject.toml declares packages = ["src/webhook"] (hatch convention), so uv /
# hatch expects the source tree at {project_root}/src/webhook/.
# Keeping everything under /build satisfies that layout.
WORKDIR /build

# ── Layer 1: install DEPENDENCIES only (cached until uv.lock changes) ──
RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    uv sync \
        --locked \
        --no-dev \
        --no-install-project

# ── Layer 2: install APPLICATION (cached until src/ changes) ──
# COPY src/ /build/src/ → package lives at /build/src/webhook/
# pyproject.toml bind-mounted at /build/pyproject.toml → hatch resolves
# packages = ["src/webhook"] as /build/src/webhook/ ✓
COPY src/ /build/src/
RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    uv sync \
        --locked \
        --no-dev \
        --no-editable


# ─────────────────────────────────────────────────────────────────────────────
# Stage 3 — runtime
# Minimal Alpine image — no uv, no openssl, no build tools, no source code.
# Contains only: Python runtime + compiled venv + TLS certs.
# Expected final image size: ~90–110 MB.
# ─────────────────────────────────────────────────────────────────────────────
FROM python:3.13-alpine AS runtime

SHELL ["/bin/sh", "-exc"]

# Only add what the runtime actually needs
RUN apk add --no-cache ca-certificates

# Non-root user (uid/gid 1000)
RUN addgroup -S -g 1000 app && \
    adduser  -S -u 1000 -G app -h /app -D app

# Copy the compiled venv from builder
COPY --from=builder --chown=app:app /app /app

# Copy TLS certs from cert-gen
COPY --from=cert-gen --chown=app:app /certs /app/certs

ENV PATH=/app/bin:$PATH \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONASYNCIODEBUG=0

USER app
WORKDIR /app
EXPOSE 8443

# Smoke-test: verify the app can be imported before declaring the image healthy.
# Use the venv Python explicitly — -I (isolated mode) suppresses pyvenv.cfg
# detection which breaks venv site-packages resolution.
RUN /app/bin/python -c "import webhook.bootstrap.app_factory"

ENTRYPOINT ["/app/bin/gunicorn", \
    "webhook.bootstrap.app_factory:app", \
    "--worker-class",  "uvicorn.workers.UvicornWorker", \
    "--bind",          "0.0.0.0:8443", \
    "--workers",       "4", \
    "--timeout",       "15", \
    "--graceful-timeout", "10", \
    "--max-requests",  "1000", \
    "--max-requests-jitter", "50", \
    "--worker-tmp-dir", "/tmp", \
    "--keyfile",       "/app/certs/tls.key", \
    "--certfile",      "/app/certs/tls.crt", \
    "--log-file",      "-", \
    "--access-logfile", "-" \
]
