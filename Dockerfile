# helm-ai-mcp in a container.
#
# Multi-stage: the native Helm library is compiled from the pinned
# helm-c-sdk tag for the image's own architecture (works on amd64 and
# arm64 alike), the Python stack is assembled into a venv, and the
# runtime stage is a slim, non-root image with no toolchains.
#
#   docker build -t helm-ai-mcp .
#   docker run -i --rm -v ~/.kube/config:/home/helm/.kube/config:ro helm-ai-mcp
#
# MCP servers speak stdio: clients launch the container with -i (see
# README "Docker" for the client configuration snippet).

ARG HELM_C_VERSION=0.2.1
ARG HELM_PYTHON_VERSION=0.2.1

# --- Stage 1: build the native library for this architecture --------------
FROM golang:1.26-bookworm AS native
ARG HELM_C_VERSION
RUN git clone --depth 1 --branch "v${HELM_C_VERSION}" \
        https://github.com/shivamkumar99/helm-c-sdk /src/helm-c
RUN make -C /src/helm-c build VERSION="${HELM_C_VERSION}"

# --- Stage 2: assemble the Python environment -----------------------------
FROM python:3.13-slim AS build
ARG HELM_PYTHON_VERSION
RUN apt-get update && apt-get install -y --no-install-recommends git \
    && rm -rf /var/lib/apt/lists/*
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

RUN git clone --depth 1 --branch "v${HELM_PYTHON_VERSION}" \
        https://github.com/shivamkumar99/helm-python-sdk /src/helm-python
# Pre-placing the library is the build hook's "CI wheel" path: the wheel
# ships it and no compile happens here.
COPY --from=native /src/helm-c/build/libhelm_c.so* /src/helm-python/src/helm_python/lib/
RUN pip install --no-cache-dir /src/helm-python

COPY pyproject.toml README.md LICENSE NOTICE /src/helm-python-ai/
COPY src /src/helm-python-ai/src
RUN pip install --no-cache-dir "/src/helm-python-ai[server]"

# --- Stage 3: runtime ------------------------------------------------------
FROM python:3.13-slim
RUN useradd --create-home --shell /usr/sbin/nologin helm
COPY --from=build /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH" \
    HOME=/home/helm
USER helm
WORKDIR /home/helm

# Safety gates default OFF; opt in explicitly at run time, e.g.
#   docker run -i --rm -e HELM_AI_ALLOW_WRITES=1 ...
ENTRYPOINT ["helm-ai-mcp"]
