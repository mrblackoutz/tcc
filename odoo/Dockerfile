# syntax=docker/dockerfile:1.7

ARG PYTHON_BASE_IMAGE=python:3.12-slim-bookworm@sha256:4427763a1ba36f5aa8f656a03e5d00f3b8d61f5dd950c73df6c14f8c7640f8ab

FROM ${PYTHON_BASE_IMAGE} AS builder

ARG ODOO_REPOSITORY=https://github.com/odoo/odoo.git
ARG ODOO_COMMIT=a4b877245c9cb5e3d7152d1593a518170f115ca1

RUN apt-get update \
    && DEBIAN_FRONTEND=noninteractive apt-get install --yes --no-install-recommends \
        build-essential \
        ca-certificates \
        git \
        libffi-dev \
        libjpeg62-turbo-dev \
        libldap2-dev \
        libpq-dev \
        libsasl2-dev \
        libssl-dev \
        libxml2-dev \
        libxslt1-dev \
        zlib1g-dev \
    && rm -rf /var/lib/apt/lists/*

# O build nunca usa o snapshot local. O checkout é obtido da origem oficial e
# falha se o objeto retornado não corresponder exatamente ao commit aprovado.
RUN git init /src/odoo \
    && git -C /src/odoo remote add origin "${ODOO_REPOSITORY}" \
    && git -C /src/odoo fetch --depth=1 origin "${ODOO_COMMIT}" \
    && git -C /src/odoo checkout --detach FETCH_HEAD \
    && test "$(git -C /src/odoo rev-parse HEAD)" = "${ODOO_COMMIT}" \
    && git -C /src/odoo rev-parse HEAD > /src/odoo/.tcc-source-commit \
    && test "$(cat /src/odoo/.tcc-source-commit)" = "${ODOO_COMMIT}" \
    && rm -rf /src/odoo/.git

RUN python -m venv /opt/venv \
    && /opt/venv/bin/pip install \
        --disable-pip-version-check \
        --no-cache-dir \
        --requirement /src/odoo/requirements.txt

FROM ${PYTHON_BASE_IMAGE} AS runtime

ARG PYTHON_BASE_IMAGE
ARG ODOO_REPOSITORY=https://github.com/odoo/odoo.git
ARG ODOO_COMMIT=a4b877245c9cb5e3d7152d1593a518170f115ca1

LABEL org.opencontainers.image.title="TCC Odoo 19.0 Community laboratory" \
      org.opencontainers.image.description="Odoo Community built from the source revision fixed by the TCC protocol" \
      org.opencontainers.image.source="${ODOO_REPOSITORY}" \
      org.opencontainers.image.revision="${ODOO_COMMIT}" \
      org.opencontainers.image.version="19.0" \
      org.opencontainers.image.licenses="LGPL-3.0-only" \
      org.opencontainers.image.base.name="${PYTHON_BASE_IMAGE}" \
      br.edu.fci.tcc.platform="linux/amd64"

RUN apt-get update \
    && DEBIAN_FRONTEND=noninteractive apt-get install --yes --no-install-recommends \
        ca-certificates \
        fonts-dejavu-core \
        libffi8 \
        libjpeg62-turbo \
        libldap-2.5-0 \
        libmagic1 \
        libpq5 \
        libsasl2-2 \
        libssl3 \
        libxml2 \
        libxslt1.1 \
        zlib1g \
    && rm -rf /var/lib/apt/lists/* \
    && addgroup --system --gid 10001 odoo \
    && adduser --system --uid 10001 --ingroup odoo --home /var/lib/odoo --shell /usr/sbin/nologin odoo \
    && install --directory --owner=odoo --group=odoo --mode=0750 \
        /etc/odoo \
        /mnt/extra-addons \
        /opt/tcc/fixtures \
        /run/tcc-secrets \
        /var/lib/odoo

COPY --from=builder /opt/venv /opt/venv
COPY --from=builder /src/odoo /opt/odoo

ENV HOME=/var/lib/odoo \
    PATH=/opt/venv/bin:${PATH} \
    PYTHONPATH=/opt/odoo \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

USER 10001:10001
WORKDIR /var/lib/odoo

EXPOSE 8069

CMD ["/opt/odoo/odoo-bin", "-c", "/etc/odoo/odoo.conf"]
