"""API interna tipada do llm-client para o gate offline G3b."""

from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Mapping
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib.resources import files
from typing import Any

import httpx
from jsonschema import Draft202012Validator

from .llm_adapters import (
    DeepSeekProposalAdapter,
    LLMAdapterError,
    LLMCallMetadata,
    LLMMessage,
    LLMProposalRequest,
    LLMProposalResult,
    OllamaProposalAdapter,
)
from .llm_config import DEEPSEEK_MODEL, OLLAMA_MODEL, DeepSeekConfig, OllamaConfig
from .pdf_ingestion import ExtractedPdf
from .state import canonical_json_bytes


REQUEST_SCHEMA_VERSION = "llm-client-request/v1"
RESPONSE_SCHEMA_VERSION = "llm-client-response/v1"
MAXIMUM_BODY_BYTES = 131_072
_MOCK_KEY = "synthetic-g3b-placeholder"
_FORBIDDEN_ENV_PREFIXES = ("ODOO_", "POSTGRES_")
_FORBIDDEN_ENV_NAMES = {"DEEPSEEK_API_KEY", "DEEPSEEK_API_KEY_FILE"}


class LLMClientServiceError(ValueError):
    """Falha estável de configuração ou contrato, sem eco do payload."""

    def __init__(self, category: str) -> None:
        self.category = category
        super().__init__(f"llm-client request failed: {category}")


def _request_schema() -> dict[str, Any]:
    resource = files("tcc_gateway.schemas").joinpath(
        "llm_client_request_v1.schema.json"
    )
    return json.loads(resource.read_text(encoding="utf-8"))


_REQUEST_VALIDATOR = Draft202012Validator(_request_schema())


@dataclass(frozen=True, slots=True)
class LLMClientServiceConfig:
    bind_host: str = "0.0.0.0"
    port: int = 8080
    mode: str = "mock"

    def __post_init__(self) -> None:
        if self.bind_host not in {"0.0.0.0", "127.0.0.1"}:
            raise LLMClientServiceError("invalid_bind_host")
        if not 1 <= self.port <= 65_535:
            raise LLMClientServiceError("invalid_port")
        if self.mode != "mock":
            raise LLMClientServiceError("real_transport_disabled_until_g3c")

    @classmethod
    def from_env(
        cls, environ: Mapping[str, str] | None = None
    ) -> LLMClientServiceConfig:
        source = os.environ if environ is None else environ
        forbidden = [
            name
            for name in source
            if name in _FORBIDDEN_ENV_NAMES
            or name.startswith(_FORBIDDEN_ENV_PREFIXES)
        ]
        if forbidden:
            raise LLMClientServiceError("forbidden_credential_environment")
        try:
            port = int(source.get("TCC_LLM_CLIENT_PORT", "8080"))
        except ValueError:
            raise LLMClientServiceError("invalid_port") from None
        return cls(
            bind_host=source.get("TCC_LLM_CLIENT_BIND_HOST", "0.0.0.0"),
            port=port,
            mode=source.get("TCC_LLM_CLIENT_MODE", "mock"),
        )


def parse_client_request(value: Any) -> tuple[str, LLMProposalRequest]:
    errors = sorted(_REQUEST_VALIDATOR.iter_errors(value), key=lambda item: list(item.path))
    if errors or not isinstance(value, Mapping):
        raise LLMClientServiceError("invalid_request")

    document_value = value["document"]
    text = str(document_value["text"])
    if hashlib.sha256(text.encode("utf-8")).hexdigest() != document_value["text_sha256"]:
        raise LLMClientServiceError("text_hash_mismatch")

    document = ExtractedPdf(
        text=text,
        document_sha256=str(document_value["document_sha256"]),
        text_sha256=str(document_value["text_sha256"]),
        page_count=int(document_value["page_count"]),
        byte_count=int(document_value["byte_count"]),
    )
    try:
        request = LLMProposalRequest(
            scenario_id=str(value["scenario_id"]),
            document=document,
            messages=tuple(
                LLMMessage(role=str(message["role"]), content=str(message["content"]))
                for message in value["messages"]
            ),
        )
    except (TypeError, ValueError):
        raise LLMClientServiceError("invalid_request") from None
    return str(value["provider"]), request


def _mock_model_output() -> dict[str, Any]:
    return {
        "vendor_ref": "TCC-VENDOR-001",
        "purchase_order_ref": "TCC-PO-001",
        "document_ref": "TCC-G3B-MOCK-SEM-VALOR-FISCAL",
        "invoice_date": "2026-09-01",
        "currency": "BRL",
        "bank_account_ref": "TCC-BANK-001",
        "lines": [
            {
                "item_code": "TCC-SERVICE-001",
                "description": "SERVICO SINTETICO SEM VALOR FISCAL",
                "quantity": "1.00",
                "unit_price": "125.50",
                "line_total": "125.50",
            }
        ],
        "total": "125.50",
    }


def _mock_adapter(provider: str):
    content = json.dumps(_mock_model_output(), separators=(",", ":"))
    if provider == "deepseek":
        def deepseek_handler(_: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                json={
                    "id": "synthetic-g3b-response",
                    "model": DEEPSEEK_MODEL,
                    "choices": [
                        {
                            "index": 0,
                            "message": {"role": "assistant", "content": content},
                            "finish_reason": "stop",
                        }
                    ],
                    "usage": {
                        "prompt_tokens": 0,
                        "completion_tokens": 0,
                        "total_tokens": 0,
                    },
                },
            )

        return DeepSeekProposalAdapter(
            DeepSeekConfig(api_key=_MOCK_KEY),
            transport=httpx.MockTransport(deepseek_handler),
        )
    if provider == "ollama":
        def ollama_handler(_: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                json={
                    "model": OLLAMA_MODEL,
                    "message": {"role": "assistant", "content": content, "thinking": ""},
                    "done": True,
                    "done_reason": "stop",
                    "total_duration": 0,
                    "load_duration": 0,
                    "prompt_eval_count": 0,
                    "prompt_eval_duration": 0,
                    "eval_count": 0,
                    "eval_duration": 0,
                },
            )

        return OllamaProposalAdapter(
            OllamaConfig(base_url="http://ollama:11434"),
            transport=httpx.MockTransport(ollama_handler),
        )
    raise LLMClientServiceError("invalid_provider")


def _metadata_mapping(metadata: LLMCallMetadata) -> dict[str, Any]:
    return {
        "provider": metadata.provider,
        "adapter_id": metadata.adapter_id,
        "endpoint": metadata.endpoint,
        "requested_model": metadata.requested_model,
        "returned_model": metadata.returned_model,
        "response_id": metadata.response_id,
        "received_at_utc": metadata.received_at_utc,
        "thinking": metadata.thinking,
        "temperature": metadata.temperature,
        "max_output_tokens": metadata.max_output_tokens,
        "finish_reason": metadata.finish_reason,
        "request_sha256": metadata.request_sha256,
        "response_body_sha256": metadata.response_body_sha256,
        "response_content_sha256": metadata.response_content_sha256,
        "messages_sha256": metadata.messages_sha256,
        "system_prompt_sha256": metadata.system_prompt_sha256,
        "schema_sha256": metadata.schema_sha256,
        "usage": dict(metadata.usage),
        "durations_ns": dict(metadata.durations_ns),
    }


def _success_mapping(result: LLMProposalResult) -> dict[str, Any]:
    return {
        "schema_version": RESPONSE_SCHEMA_VERSION,
        "status": "ok",
        "proposal": result.proposal.to_mapping(),
        "metadata": _metadata_mapping(result.metadata),
    }


def process_client_request(value: Any) -> tuple[int, dict[str, Any]]:
    try:
        provider, request = parse_client_request(value)
        with _mock_adapter(provider) as adapter:
            return 200, _success_mapping(adapter.propose(request))
    except LLMClientServiceError as error:
        return 400, {
            "schema_version": RESPONSE_SCHEMA_VERSION,
            "status": "error",
            "error": {"category": error.category, "retryable": False},
        }
    except LLMAdapterError as error:
        return 502, {
            "schema_version": RESPONSE_SCHEMA_VERSION,
            "status": "error",
            "error": {
                "provider": error.provider,
                "category": error.category,
                "retryable": error.retryable,
                "http_status": error.http_status,
            },
        }


def build_handler():
    class LLMClientHandler(BaseHTTPRequestHandler):
        server_version = "tcc-llm-client/0.1"
        sys_version = ""

        def log_message(self, _format: str, *_args: object) -> None:
            return

        def _send_json(self, status: int, value: Mapping[str, Any]) -> None:
            body = canonical_json_bytes(value)
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self) -> None:  # noqa: N802 - interface da biblioteca padrão
            if self.path != "/healthz":
                self._send_json(404, {"status": "not_found"})
                return
            self._send_json(
                200,
                {
                    "status": "ok",
                    "mode": "mock",
                    "real_transport": False,
                },
            )

        def do_POST(self) -> None:  # noqa: N802 - interface da biblioteca padrão
            if self.path != "/v1/proposals":
                self._send_json(404, {"status": "not_found"})
                return
            content_type = self.headers.get("Content-Type", "").split(";", 1)[0].strip()
            if content_type != "application/json":
                self._send_json(415, {"status": "error", "error": {"category": "invalid_content_type"}})
                return
            try:
                length = int(self.headers.get("Content-Length", ""))
            except ValueError:
                length = 0
            if not 1 <= length <= MAXIMUM_BODY_BYTES:
                self._send_json(413, {"status": "error", "error": {"category": "invalid_body_size"}})
                return
            raw_body = self.rfile.read(length)
            try:
                value = json.loads(raw_body)
            except (UnicodeDecodeError, ValueError):
                self._send_json(400, {"status": "error", "error": {"category": "invalid_json"}})
                return
            status, response = process_client_request(value)
            self._send_json(status, response)

    return LLMClientHandler


def main() -> None:
    config = LLMClientServiceConfig.from_env()
    server = ThreadingHTTPServer((config.bind_host, config.port), build_handler())
    server.daemon_threads = True
    try:
        server.serve_forever(poll_interval=0.25)
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
