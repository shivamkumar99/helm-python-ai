# helm-ai-mcp in a container.
#
# Multi-stage: the native Helm library is compiled from source for the
# image's own architecture (works on amd64 and arm64 alike), the Python
# stack is assembled into a venv, and the runtime stage is a slim,
# non-root image with no toolchains.
#
#   docker build -t helm-ai-mcp .
#   docker run -i --rm --init --read-only --cap-drop ALL \
#     --security-opt no-new-privileges --tmpfs /tmp --tmpfs /home/nonroot \
#     -v ~/.kube/config:/home/nonroot/.kube/config:ro helm-ai-mcp
#
# MCP servers speak stdio: clients launch the container with -i (see
# README "Docker" for the client configuration snippet).
#
# Dependency chain: only helm-python-sdk is pinned here (tag + commit).
# The helm-c-sdk version is NOT chosen by this file — it is read from
# helm-python-sdk's own pin (EXPECTED_HELM_C_VERSION), so the dependency
# stays owned by the package that declares it. Once helm-python-sdk
# ships a linux-arm64 wheel, this clone-and-build collapses to a plain
# `pip install helm-python-sdk==<ver>`.
#
# Supply-chain pinning: base images are pinned by multi-arch manifest
# digest, and the helm-python-sdk clone is verified against the exact
# commit its version tag pointed at when this file was written — a moved
# tag fails the build instead of silently changing the input.

ARG HELM_PYTHON_VERSION=0.2.1
ARG HELM_PYTHON_COMMIT=2e5032bc90fb764f756be0e8a5fd4dce91b56bbd

# --- Stage 1: sources + native library for this architecture --------------
FROM golang:1.26-bookworm@sha256:9fdc884aacc3bec89b20ffc69f4bb369c78210e3e4f600387b5128b12c199f81 AS native
ARG HELM_PYTHON_VERSION
ARG HELM_PYTHON_COMMIT
RUN git clone --depth 1 --branch "v${HELM_PYTHON_VERSION}" \
        https://github.com/shivamkumar99/helm-python-sdk /src/helm-python \
    && test "$(git -C /src/helm-python rev-parse HEAD)" = "${HELM_PYTHON_COMMIT}"
# helm-python-sdk names the helm-c-sdk release it binds to; build exactly
# that, for this architecture.
RUN HELM_C_VERSION="$(sed -n 's/^EXPECTED_HELM_C_VERSION: Final = "\(.*\)"$/\1/p' \
        /src/helm-python/src/helm_python/_native.py)" \
    && test -n "${HELM_C_VERSION}" \
    && git clone --depth 1 --branch "v${HELM_C_VERSION}" \
        https://github.com/shivamkumar99/helm-c-sdk /src/helm-c \
    && make -C /src/helm-c build VERSION="${HELM_C_VERSION}"

# --- Stage 2: assemble the Python environment -----------------------------
# Docker Hardened Images (Debian/glibc): the -dev variant carries shell and
# pip for building; the runtime variant below ships near-zero CVEs.
FROM dhi.io/python:3.13-dev@sha256:b4399bc6cbe56230cbccf203f0591520dd5f1629ccd90ba29bd3082e99807ea3 AS build
ENV PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1
# --upgrade-deps: the venv's seeded pip/setuptools carry known CVEs
# (e.g. CVE-2025-47273); start from current ones.
RUN python -m venv --upgrade-deps /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

COPY --from=native /src/helm-python /src/helm-python
# Pre-placing the library is the build hook's "CI wheel" path: the wheel
# ships it and no compile happens here.
COPY --from=native /src/helm-c/build/libhelm_c.so* /src/helm-python/src/helm_python/lib/
RUN pip install /src/helm-python

COPY pyproject.toml README.md LICENSE NOTICE /src/helm-python-ai/
COPY src /src/helm-python-ai/src
# The msgpack floor clears GHSA-6v7p-g79w-8964 until the dependency chain
# catches up. Installers are then stripped: the runtime venv only runs
# code, and shipping pip/setuptools would just carry their CVE surface.
RUN pip install "/src/helm-python-ai[server]" "msgpack>=1.2.1" \
    && pip uninstall -y setuptools wheel pip

# --- Stage 3: runtime ------------------------------------------------------
# The hardened runtime variant is what stage 3 previously hand-rolled:
# non-root (65532), no shell, no pip/ensurepip, minimal libraries.
FROM dhi.io/python:3.13@sha256:4e7d2414a4921335d88128c9b74c45dbd7791c4240fa2b0a5642ff86f1267cbe
LABEL org.opencontainers.image.title="helm-ai-mcp" \
      org.opencontainers.image.description="Helm v4 MCP server over helm-python-sdk (stdio)" \
      org.opencontainers.image.source="https://github.com/shivamkumar99/helm-python-ai" \
      org.opencontainers.image.licenses="Apache-2.0"
# The venv stays root-owned: the runtime user can execute but not modify it.
COPY --from=build /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH" \
    HOME=/home/nonroot \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1
WORKDIR /home/nonroot

# Safety gates default OFF; opt in explicitly at run time, e.g.
#   docker run -i --rm -e HELM_AI_ALLOW_WRITES=1 ...
ENTRYPOINT ["helm-ai-mcp"]
