"""API interna tipada do llm-client para os gates G3b e G3c."""

from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Mapping
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib.resources import files
from typing import Any

import httpx
from jsonschema import Draft202012Validator, FormatChecker

from .action_proposal_v2 import ActionProposalSchemaError, ActionProposalV2

from .llm_adapters import (
    DeepSeekProposalAdapter,
    LLMAdapterError,
    LLMCallMetadata,
    LLMMessage,
    LLMProposalRequest,
    LLMProposalResult,
    OllamaProposalAdapter,
    DEEPSEEK_ADAPTER_ID,
    OLLAMA_ADAPTER_ID,
    OutputContract,
    expected_proposal_request_hashes,
)
from .llm_config import (
    DEEPSEEK_ALLOWED_RETURNED_MODELS,
    DEEPSEEK_BASE_URL,
    DEEPSEEK_MODEL,
    OLLAMA_ALLOWED_BASE_URLS,
    OLLAMA_MODEL,
    DeepSeekConfig,
    OllamaConfig,
)
from .pdf_ingestion import ExtractedPdf
from .state import canonical_json_bytes, canonical_json_sha256


REQUEST_SCHEMA_VERSION = "llm-client-request/v1"
RESPONSE_SCHEMA_VERSION = "llm-client-response/v1"
REQUEST_SCHEMA_VERSION_V2 = "llm-client-request/v2"
RESPONSE_SCHEMA_VERSION_V2 = "llm-client-response/v2"
MAXIMUM_BODY_BYTES = 131_072
_MOCK_KEY = "synthetic-g3b-placeholder"
_FORBIDDEN_ENV_PREFIXES = ("ODOO_", "POSTGRES_")
_DEEPSEEK_SMOKE_MODE = "deepseek-smoke"
_REQUIRED_PROXY_URL = "http://egress-proxy:8888"


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


def _v2_validator(name: str) -> Draft202012Validator:
    schema = json.loads(files("tcc_gateway.schemas").joinpath(name).read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema, format_checker=FormatChecker())


_REQUEST_VALIDATOR_V2 = _v2_validator("llm_client_request_v2.schema.json")
_RESPONSE_VALIDATOR_V2 = _v2_validator("llm_client_response_v2.schema.json")


@dataclass(frozen=True, slots=True)
class LLMClientServiceConfig:
    bind_host: str = "0.0.0.0"
    port: int = 8080
    mode: str = "mock"
    deepseek_config: DeepSeekConfig | None = field(default=None, repr=False)

    def __post_init__(self) -> None:
        if self.bind_host not in {"0.0.0.0", "127.0.0.1"}:
            raise LLMClientServiceError("invalid_bind_host")
        if not 1 <= self.port <= 65_535:
            raise LLMClientServiceError("invalid_port")
        if self.mode not in {"mock", _DEEPSEEK_SMOKE_MODE}:
            raise LLMClientServiceError("invalid_mode")
        if self.mode == "mock" and self.deepseek_config is not None:
            raise LLMClientServiceError("mock_mode_received_provider_config")
        if self.mode == _DEEPSEEK_SMOKE_MODE and self.deepseek_config is None:
            raise LLMClientServiceError("deepseek_config_required")

    @classmethod
    def from_env(
        cls, environ: Mapping[str, str] | None = None
    ) -> LLMClientServiceConfig:
        source = os.environ if environ is None else environ
        forbidden = [
            name
            for name in source
            if name == "DEEPSEEK_API_KEY"
            or name.startswith(_FORBIDDEN_ENV_PREFIXES)
        ]
        if forbidden:
            raise LLMClientServiceError("forbidden_credential_environment")
        try:
            port = int(source.get("TCC_LLM_CLIENT_PORT", "8080"))
        except ValueError:
            raise LLMClientServiceError("invalid_port") from None
        mode = source.get("TCC_LLM_CLIENT_MODE", "mock")
        deepseek_config: DeepSeekConfig | None = None
        if mode == "mock":
            if source.get("DEEPSEEK_API_KEY_FILE", "").strip():
                raise LLMClientServiceError("forbidden_credential_environment")
        elif mode == _DEEPSEEK_SMOKE_MODE:
            if source.get("HTTPS_PROXY", "").strip() != _REQUIRED_PROXY_URL:
                raise LLMClientServiceError("invalid_proxy_configuration")
            if source.get("HTTP_PROXY", "").strip() != _REQUIRED_PROXY_URL:
                raise LLMClientServiceError("invalid_proxy_configuration")
            try:
                deepseek_config = DeepSeekConfig.from_env(source)
            except ValueError:
                raise LLMClientServiceError("invalid_deepseek_configuration") from None
        else:
            raise LLMClientServiceError("invalid_mode")
        return cls(
            bind_host=source.get("TCC_LLM_CLIENT_BIND_HOST", "0.0.0.0"),
            port=port,
            mode=mode,
            deepseek_config=deepseek_config,
        )


def _parse_request(
    value: Any, validator: Draft202012Validator,
) -> tuple[str, LLMProposalRequest]:
    if not isinstance(value, Mapping) or not validator.is_valid(value):
        raise LLMClientServiceError("invalid_request")

    document_value = value["document"]
    text = str(document_value["text"])
    try:
        text_sha256 = hashlib.sha256(text.encode("utf-8")).hexdigest()
    except UnicodeError:
        raise LLMClientServiceError("invalid_request") from None
    if text_sha256 != document_value["text_sha256"]:
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


def parse_client_request(value: Any) -> tuple[str, LLMProposalRequest]:
    """Contrato histórico v1; nunca promove a ação para POST."""

    return _parse_request(value, _REQUEST_VALIDATOR)


def parse_client_request_v2(value: Any) -> tuple[str, LLMProposalRequest]:
    """Entrada v2 explícita, sem condição, label ou autoridade financeira."""

    provider, request = _parse_request(value, _REQUEST_VALIDATOR_V2)
    if any(type(value["document"][name]) is not int for name in ("page_count", "byte_count")):
        raise LLMClientServiceError("invalid_request")
    try:
        canonical_json_bytes(value)
    except (TypeError, ValueError, UnicodeError):
        raise LLMClientServiceError("invalid_request") from None
    return provider, request


def validate_v2_client_response(
    request_value: Mapping[str, Any], response_value: Mapping[str, Any],
) -> ActionProposalV2:
    """Verifica contrato e proveniência; não avalia nem autoriza a ação."""

    provider, request = parse_client_request_v2(request_value)
    if (
        not isinstance(response_value, Mapping)
        or not _RESPONSE_VALIDATOR_V2.is_valid(response_value)
        or response_value.get("status") != "ok"
    ):
        raise LLMClientServiceError("invalid_client_response")
    try:
        proposal = ActionProposalV2.from_mapping(response_value["proposal"])
        request_hash = canonical_json_sha256(request_value)
        proposal_hash = canonical_json_sha256(response_value["proposal"])
        if canonical_json_bytes(response_value["proposal"]) != canonical_json_bytes(proposal.to_mapping()):
            raise LLMClientServiceError("invalid_client_response")
    except (ActionProposalSchemaError, TypeError, ValueError):
        raise LLMClientServiceError("invalid_client_response") from None
    if response_value["client_request_sha256"] != request_hash:
        raise LLMClientServiceError("request_binding_mismatch")
    if response_value["proposal_sha256"] != proposal_hash:
        raise LLMClientServiceError("proposal_hash_mismatch")
    if proposal.scenario_id != request.scenario_id:
        raise LLMClientServiceError("scenario_mismatch")
    proposal_mapping = proposal.to_mapping()
    if proposal_mapping["source"] != {
        "document_sha256": request.document.document_sha256,
        "text_sha256": request.document.text_sha256,
        "page_count": request.document.page_count,
    }:
        raise LLMClientServiceError("document_binding_mismatch")
    metadata = response_value["metadata"]
    if (
        type(metadata["max_output_tokens"]) is not int
        or type(proposal_mapping["source"]["page_count"]) is not int
        or any(type(counter) is not int for counter in metadata["usage"].values())
        or any(type(duration) is not int for duration in metadata["durations_ns"].values())
    ):
        raise LLMClientServiceError("invalid_client_response")
    adapter_id = DEEPSEEK_ADAPTER_ID if provider == "deepseek" else OLLAMA_ADAPTER_ID
    expected_model = DEEPSEEK_MODEL if provider == "deepseek" else OLLAMA_MODEL
    allowed_returned = DEEPSEEK_ALLOWED_RETURNED_MODELS if provider == "deepseek" else {OLLAMA_MODEL}
    allowed_endpoints = (
        {f"{DEEPSEEK_BASE_URL}/chat/completions"} if provider == "deepseek"
        else {f"{base_url}/api/chat" for base_url in OLLAMA_ALLOWED_BASE_URLS}
    )
    if (
        metadata["provider"] != provider
        or metadata["adapter_id"] != adapter_id
        or proposal_mapping["producer"] != adapter_id
        or metadata["requested_model"] != expected_model
        or metadata["returned_model"] not in allowed_returned
        or metadata["endpoint"] not in allowed_endpoints
    ):
        raise LLMClientServiceError("model_mismatch")
    for name, expected_hash in expected_proposal_request_hashes(request).items():
        if metadata[name] != expected_hash:
            raise LLMClientServiceError("prompt_contract_mismatch")
    # These counters are transport diagnostics, not proof of provider truth.
    usage_names = (
        {"prompt_tokens", "completion_tokens", "total_tokens"} if provider == "deepseek"
        else {"prompt_eval_count", "eval_count"}
    )
    if set(metadata["usage"]) - usage_names:
        raise LLMClientServiceError("invalid_client_response")
    return proposal


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


def _mock_adapter(provider: str, *, output_contract: OutputContract = "v1"):
    output = _mock_model_output()
    if output_contract == "v2":
        output = {"action": "CREATE_DRAFT_BILL", **output}
    content = json.dumps(output, separators=(",", ":"))
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
            output_contract=output_contract,
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
            output_contract=output_contract,
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
        "system_fingerprint": metadata.system_fingerprint,
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


def _success_mapping(
    result: LLMProposalResult,
    request_value: Mapping[str, Any],
    *, output_contract: OutputContract,
) -> dict[str, Any]:
    value = {
        "schema_version": RESPONSE_SCHEMA_VERSION,
        "status": "ok",
        "proposal": result.proposal.to_mapping(),
        "metadata": _metadata_mapping(result.metadata),
    }
    if output_contract == "v2":
        value.update({
            "schema_version": RESPONSE_SCHEMA_VERSION_V2,
            "output_contract": "v2",
            "client_request_sha256": canonical_json_sha256(request_value),
            "proposal_sha256": canonical_json_sha256(value["proposal"]),
        })
        validate_v2_client_response(request_value, value)
    return value


def _adapter_for(
    provider: str,
    config: LLMClientServiceConfig,
    *,
    output_contract: OutputContract = "v1",
    transport: httpx.BaseTransport | None = None,
):
    if config.mode == "mock":
        return _mock_adapter(provider, output_contract=output_contract)
    if config.mode == _DEEPSEEK_SMOKE_MODE:
        if provider != "deepseek" or config.deepseek_config is None:
            raise LLMClientServiceError("provider_not_allowed_in_mode")
        return DeepSeekProposalAdapter(
            config.deepseek_config, output_contract=output_contract, transport=transport,
        )
    raise LLMClientServiceError("invalid_mode")


def process_client_request(
    value: Any,
    config: LLMClientServiceConfig | None = None,
    *,
    transport: httpx.BaseTransport | None = None,
    expected_request_version: str | None = None,
) -> tuple[int, dict[str, Any]]:
    selected_config = config or LLMClientServiceConfig()
    is_v2 = isinstance(value, Mapping) and value.get("schema_version") == REQUEST_SCHEMA_VERSION_V2
    output_contract: OutputContract = "v2" if is_v2 else "v1"
    response_version = RESPONSE_SCHEMA_VERSION_V2 if is_v2 else RESPONSE_SCHEMA_VERSION
    try:
        if expected_request_version is not None and (
            not isinstance(value, Mapping) or value.get("schema_version") != expected_request_version
        ):
            raise LLMClientServiceError("route_contract_mismatch")
        parser = parse_client_request_v2 if is_v2 else parse_client_request
        provider, request = parser(value)
        if (
            is_v2 and selected_config.deepseek_config is not None
            and (
                type(selected_config.deepseek_config.generation.max_output_tokens) is not int
                or selected_config.deepseek_config.generation.max_output_tokens != 2048
            )
        ):
            raise LLMClientServiceError("generation_mismatch")
        with _adapter_for(
            provider, selected_config, output_contract=output_contract, transport=transport,
        ) as adapter:
            return 200, _success_mapping(adapter.propose(request), value, output_contract=output_contract)
    except LLMClientServiceError as error:
        return 400, {
            "schema_version": response_version,
            "status": "error",
            "error": {"category": error.category, "retryable": False},
        }
    except LLMAdapterError as error:
        return 502, {
            "schema_version": response_version,
            "status": "error",
            "error": {
                "provider": error.provider,
                "category": error.category,
                "retryable": error.retryable,
                "http_status": error.http_status,
            },
        }


def build_handler(config: LLMClientServiceConfig | None = None):
    selected_config = config or LLMClientServiceConfig()

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
                    "mode": selected_config.mode,
                    "real_transport": selected_config.mode == _DEEPSEEK_SMOKE_MODE,
                },
            )

        def do_POST(self) -> None:  # noqa: N802 - interface da biblioteca padrão
            if self.path not in {"/v1/proposals", "/v2/proposals"}:
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
            status, response = process_client_request(
                value, selected_config,
                expected_request_version=(
                    REQUEST_SCHEMA_VERSION_V2 if self.path == "/v2/proposals" else REQUEST_SCHEMA_VERSION
                ),
            )
            self._send_json(status, response)

    return LLMClientHandler


def main() -> None:
    config = LLMClientServiceConfig.from_env()
    server = ThreadingHTTPServer((config.bind_host, config.port), build_handler(config))
    server.daemon_threads = True
    try:
        server.serve_forever(poll_interval=0.25)
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
