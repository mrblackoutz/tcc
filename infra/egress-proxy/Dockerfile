# syntax=docker/dockerfile:1.7

ARG PYTHON_BASE_IMAGE=python:3.12-slim-bookworm@sha256:4427763a1ba36f5aa8f656a03e5d00f3b8d61f5dd950c73df6c14f8c7640f8ab
FROM ${PYTHON_BASE_IMAGE}

ARG PYTHON_BASE_IMAGE

LABEL org.opencontainers.image.title="TCC allowlist CONNECT egress proxy" \
      org.opencontainers.image.version="0.1.0" \
      org.opencontainers.image.base.name="${PYTHON_BASE_IMAGE}" \
      br.edu.fci.tcc.platform="linux/amd64"

ENV HOME=/tmp \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /opt/tcc/egress-proxy

COPY proxy.py ./proxy.py
COPY tests ./tests

RUN useradd --create-home --uid 10003 --shell /usr/sbin/nologin tccproxy

USER 10003:10003

EXPOSE 8888

CMD ["python", "/opt/tcc/egress-proxy/proxy.py"]
