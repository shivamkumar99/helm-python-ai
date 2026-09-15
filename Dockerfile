# helm-ai-mcp in a container.
#
# Two stages on Docker Hardened Images (Debian/glibc): the -dev variant
# assembles a venv straight from PyPI — helm-python-sdk ships prebuilt
# wheels for both amd64 and arm64, so nothing compiles here — and the
# hardened runtime variant ships it: non-root, no shell, no installers,
# minimal libraries, near-zero CVEs.
#
#   docker build -t helm-ai-mcp .
#   docker run -i --rm --init --read-only --cap-drop ALL \
#     --security-opt no-new-privileges --tmpfs /tmp --tmpfs /home/nonroot \
#     -v ~/.kube/config:/home/nonroot/.kube/config:ro helm-ai-mcp
#
# MCP servers speak stdio: clients launch the container with -i (see
# README "Docker" for the client configuration snippet). Base images are
# pinned by multi-arch manifest digest; every package version is pinned
# by pip's resolution of the == constraints below. Pulling dhi.io needs
# a (free) Docker login.

ARG HELM_PYTHON_VERSION=0.2.2

# --- Stage 1: assemble the Python environment ------------------------------
FROM dhi.io/python:3.13-dev@sha256:b4399bc6cbe56230cbccf203f0591520dd5f1629ccd90ba29bd3082e99807ea3 AS build
ARG HELM_PYTHON_VERSION
ENV PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1
# --upgrade-deps: the venv's seeded pip/setuptools carry known CVEs
# (e.g. CVE-2025-47273); start from current ones.
RUN python -m venv --upgrade-deps /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

COPY pyproject.toml README.md LICENSE NOTICE /src/helm-python-ai/
COPY src /src/helm-python-ai/src
# The msgpack floor clears GHSA-6v7p-g79w-8964 until the dependency chain
# catches up. Installers are then stripped: the runtime venv only runs
# code, and shipping pip/setuptools would just carry their CVE surface.
RUN pip install "helm-python-sdk==${HELM_PYTHON_VERSION}" \
        "/src/helm-python-ai[server]" "msgpack>=1.2.1" \
    && pip uninstall -y setuptools wheel pip

# --- Stage 2: runtime ------------------------------------------------------
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
