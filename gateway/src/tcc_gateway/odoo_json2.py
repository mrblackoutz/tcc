"""Transporte minimo e saneado para a API JSON-2 do Odoo 19."""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any
from urllib.parse import quote

import httpx

from .config import OdooConfig


_MODEL_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_.]*$")
_METHOD_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


class OdooJson2Error(RuntimeError):
    """Falha de transporte ou protocolo sem resposta, request ou credencial."""


class OdooJson2Client:
    """Cliente sincrono para metodos confiaveis selecionados pelo chamador.

    O cliente nao decide quais modelos ou metodos sao autorizados. Essa
    allowlist pertence a camadas superiores e, em C1, ao executor tipado.
    """

    def __init__(
        self,
        config: OdooConfig,
        *,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self._config = config
        timeout = httpx.Timeout(
            config.request_timeout_seconds,
            connect=config.connect_timeout_seconds,
        )
        self._client = httpx.Client(
            timeout=timeout,
            transport=transport,
            headers={
                "Accept": "application/json",
                "Content-Type": "application/json",
                "Authorization": f"Bearer {config.api_token}",
                "X-Odoo-Database": config.database,
            },
        )

    def __repr__(self) -> str:
        return (
            f"{type(self).__name__}(base_url={self._config.base_url!r}, "
            f"database={self._config.database!r})"
        )

    def __enter__(self) -> OdooJson2Client:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def close(self) -> None:
        self._client.close()

    def call(
        self,
        model: str,
        method: str,
        *,
        arguments: Mapping[str, Any] | None = None,
    ) -> Any:
        """Invoca um metodo JSON-2 e retorna o JSON decodificado.

        ``model`` e ``method`` devem vir de codigo confiavel, nao de documentos
        ou da saida do LLM. O ``context`` externo e rejeitado conforme DEC-013.
        """

        if not _MODEL_PATTERN.fullmatch(model):
            raise ValueError("model must be a trusted Odoo model identifier")
        if not _METHOD_PATTERN.fullmatch(method):
            raise ValueError("method must be a trusted Odoo method identifier")

        payload = dict(arguments or {})
        if "context" in payload:
            raise ValueError("external context is not accepted by the gateway")

        endpoint = (
            f"{self._config.base_url}/json/2/"
            f"{quote(model, safe='')}/{quote(method, safe='')}"
        )

        try:
            response = self._client.post(endpoint, json=payload)
        except httpx.RequestError:
            raise OdooJson2Error("Odoo JSON-2 request failed before a response") from None
        except (TypeError, ValueError):
            raise OdooJson2Error("Odoo JSON-2 arguments are not JSON serializable") from None

        if not response.is_success:
            raise OdooJson2Error(
                f"Odoo JSON-2 request failed with HTTP status {response.status_code}"
            )

        try:
            return response.json()
        except ValueError:
            raise OdooJson2Error("Odoo JSON-2 returned an invalid JSON response") from None

