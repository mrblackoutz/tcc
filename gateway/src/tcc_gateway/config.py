"""Configuracao local do cliente Odoo sem material sensivel em representacoes."""

from __future__ import annotations

import os
from math import isfinite
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit


class OdooConfigError(ValueError):
    """Indica configuracao ausente, ambigua ou invalida."""


def _required(environ: Mapping[str, str], name: str) -> str:
    value = environ.get(name, "").strip()
    if not value:
        raise OdooConfigError(f"required configuration is missing: {name}")
    return value


def _positive_float(environ: Mapping[str, str], name: str, default: float) -> float:
    raw_value = environ.get(name)
    if raw_value is None or not raw_value.strip():
        return default

    try:
        value = float(raw_value)
    except ValueError:
        raise OdooConfigError(f"configuration must be a number: {name}") from None

    if not isfinite(value) or value <= 0:
        raise OdooConfigError(f"configuration must be greater than zero: {name}")
    return value


def _normalise_base_url(raw_url: str) -> str:
    parsed = urlsplit(raw_url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise OdooConfigError("ODOO_BASE_URL must be an absolute HTTP(S) URL")
    if parsed.username is not None or parsed.password is not None:
        raise OdooConfigError("ODOO_BASE_URL must not contain credentials")
    if parsed.query or parsed.fragment:
        raise OdooConfigError("ODOO_BASE_URL must not contain a query or fragment")

    clean_path = parsed.path.rstrip("/")
    return urlunsplit((parsed.scheme, parsed.netloc, clean_path, "", ""))


def _read_api_token(environ: Mapping[str, str]) -> str:
    inline_token = environ.get("ODOO_API_TOKEN", "").strip()
    token_file = environ.get("ODOO_API_TOKEN_FILE", "").strip()

    if inline_token and token_file:
        raise OdooConfigError(
            "configure exactly one token source: ODOO_API_TOKEN or ODOO_API_TOKEN_FILE"
        )
    if inline_token:
        return inline_token
    if not token_file:
        raise OdooConfigError(
            "required configuration is missing: ODOO_API_TOKEN or ODOO_API_TOKEN_FILE"
        )

    try:
        token = Path(token_file).read_text(encoding="utf-8").strip()
    except OSError:
        raise OdooConfigError("unable to read the configured Odoo API token file") from None

    if not token:
        raise OdooConfigError("the configured Odoo API token file is empty")
    return token


@dataclass(frozen=True, slots=True)
class OdooConfig:
    """Parametros imutaveis usados pelo transporte JSON-2.

    O token fica fora de ``repr`` para impedir vazamento acidental em logs e
    mensagens de diagnostico.
    """

    base_url: str
    database: str
    api_token: str = field(repr=False)
    connect_timeout_seconds: float = 5.0
    request_timeout_seconds: float = 30.0

    def __post_init__(self) -> None:
        object.__setattr__(self, "base_url", _normalise_base_url(self.base_url))
        if not self.database.strip():
            raise OdooConfigError("database must not be empty")
        if not self.api_token.strip():
            raise OdooConfigError("API token must not be empty")
        if self.connect_timeout_seconds <= 0 or self.request_timeout_seconds <= 0:
            raise OdooConfigError("timeouts must be greater than zero")

    @classmethod
    def from_env(cls, environ: Mapping[str, str] | None = None) -> OdooConfig:
        """Carrega somente variaveis de ambiente ou um arquivo de segredo.

        Nenhum valor secreto e incluido nos erros desta operacao.
        """

        source = os.environ if environ is None else environ
        return cls(
            base_url=_required(source, "ODOO_BASE_URL"),
            database=_required(source, "ODOO_DATABASE"),
            api_token=_read_api_token(source),
            connect_timeout_seconds=_positive_float(
                source, "ODOO_CONNECT_TIMEOUT_SECONDS", 5.0
            ),
            request_timeout_seconds=_positive_float(
                source, "ODOO_REQUEST_TIMEOUT_SECONDS", 30.0
            ),
        )
