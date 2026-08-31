# syntax=docker/dockerfile:1.7

ARG PYTHON_BASE_IMAGE=python:3.12-slim-bookworm@sha256:4427763a1ba36f5aa8f656a03e5d00f3b8d61f5dd950c73df6c14f8c7640f8ab
FROM ${PYTHON_BASE_IMAGE}

ARG PYTHON_BASE_IMAGE

LABEL org.opencontainers.image.title="TCC JSON-2 gateway laboratory" \
      org.opencontainers.image.version="0.2.0" \
      org.opencontainers.image.base.name="${PYTHON_BASE_IMAGE}" \
      br.edu.fci.tcc.platform="linux/amd64"

ENV HOME=/tmp \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /opt/tcc/gateway

COPY pyproject.toml constraints.txt ./
COPY src ./src
COPY tests ./tests

RUN python -m pip install \
        --disable-pip-version-check \
        --no-cache-dir \
        --constraint constraints.txt \
        ".[test]" \
    && useradd --create-home --uid 10002 --shell /usr/sbin/nologin gateway

USER 10002:10002

CMD ["python", "-m", "pytest", "-q"]
