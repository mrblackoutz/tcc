from __future__ import annotations

import json
from copy import deepcopy
from datetime import datetime, timezone

import httpx
import pytest

from tcc_gateway.llm_adapters import (
    DEEPSEEK_ADAPTER_ID,
    OLLAMA_ADAPTER_ID,
    DeepSeekProposalAdapter,
    LLMAdapterError,
    LLMMessage,
    LLMProposalRequest,
    OllamaProposalAdapter,
)
from tcc_gateway.llm_config import (
    DEEPSEEK_CURRENT_ALIAS,
    DEEPSEEK_CURRENT_BACKEND,
    DEEPSEEK_MODEL,
    OLLAMA_MODEL,
    DeepSeekConfig,
    GenerationSettings,
    OllamaConfig,
)
from tcc_gateway.pdf_ingestion import ExtractedPdf


SYNTHETIC_KEY = "synthetic-deepseek-key-not-a-credential"
SENSITIVE_MARKER = "SENSITIVE-TRANSPORT-MARKER-DO-NOT-ECHO"
FIXED_TIME = datetime(2026, 8, 31, 18, 0, tzinfo=timezone.utc)


def _document() -> ExtractedPdf:
    return ExtractedPdf(
        text="DOCUMENTO SINTETICO - SEM VALOR FISCAL\nTOTAL: 125.50",
        document_sha256="a" * 64,
        text_sha256="b" * 64,
        page_count=1,
        byte_count=200,
    )


def _request() -> LLMProposalRequest:
    document = _document()
    return LLMProposalRequest(
        scenario_id="G3A-BENIGN-001",
        document=document,
        messages=(
            LLMMessage(
                role="system",
                content="Extraia os campos do documento sintetico para uma proposta.",
            ),
            LLMMessage(role="user", content=document.text),
        ),
    )


def _model_output() -> dict[str, object]:
    return {
        "vendor_ref": "TCC-VENDOR-001",
        "purchase_order_ref": "TCC-PO-001",
        "document_ref": "TCC-NF-001-SEM-VALOR-FISCAL",
        "invoice_date": "2026-08-31",
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


def _deepseek_response(**overrides: object) -> dict[str, object]:
    value: dict[str, object] = {
        "id": "synthetic-request-001",
        "model": DEEPSEEK_MODEL,
        "system_fingerprint": "fp_synthetic_001",
        "choices": [
            {
                "index": 0,
                "message": {
                    "role": "assistant",
                    "content": json.dumps(_model_output()),
                },
                "finish_reason": "stop",
            }
        ],
        "usage": {
            "prompt_tokens": 120,
            "completion_tokens": 80,
            "total_tokens": 200,
        },
    }
    value.update(overrides)
    return value


def _ollama_response(**overrides: object) -> dict[str, object]:
    value: dict[str, object] = {
        "model": OLLAMA_MODEL,
        "created_at": "2026-08-31T18:00:00Z",
        "message": {
            "role": "assistant",
            "content": json.dumps(_model_output()),
            "thinking": "",
        },
        "done": True,
        "done_reason": "stop",
        "total_duration": 2_000_000,
        "load_duration": 500_000,
        "prompt_eval_count": 120,
        "prompt_eval_duration": 700_000,
        "eval_count": 80,
        "eval_duration": 800_000,
    }
    value.update(overrides)
    return value


def _deepseek_adapter(handler) -> DeepSeekProposalAdapter:
    return DeepSeekProposalAdapter(
        DeepSeekConfig(
            api_key=SYNTHETIC_KEY,
            generation=GenerationSettings(max_output_tokens=1024),
        ),
        transport=httpx.MockTransport(handler),
        clock=lambda: FIXED_TIME,
    )


def _ollama_adapter(handler) -> OllamaProposalAdapter:
    return OllamaProposalAdapter(
        OllamaConfig(generation=GenerationSettings(max_output_tokens=1024)),
        transport=httpx.MockTransport(handler),
        clock=lambda: FIXED_TIME,
    )


def test_deepseek_valid_json_is_normalised_with_sanitised_metadata() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "POST"
        assert request.url == httpx.URL("https://api.deepseek.com/chat/completions")
        assert request.headers["Authorization"] == f"Bearer {SYNTHETIC_KEY}"
        payload = json.loads(request.content)
        assert payload["model"] == DEEPSEEK_MODEL
        assert payload["thinking"] == {"type": "disabled"}
        assert payload["response_format"] == {"type": "json_object"}
        assert payload["temperature"] == 0.0
        assert payload["stream"] is False
        assert "JSON Schema" in payload["messages"][0]["content"]
        return httpx.Response(200, json=_deepseek_response())

    with _deepseek_adapter(handler) as adapter:
        result = adapter.propose(_request())

    assert result.proposal.producer == DEEPSEEK_ADAPTER_ID
    assert result.proposal.scenario_id == "G3A-BENIGN-001"
    assert result.proposal.source.document_sha256 == "a" * 64
    assert result.metadata.provider == "deepseek"
    assert result.metadata.returned_model == DEEPSEEK_MODEL
    assert result.metadata.system_fingerprint == "fp_synthetic_001"
    assert result.metadata.usage == (
        ("prompt_tokens", 120),
        ("completion_tokens", 80),
        ("total_tokens", 200),
    )
    assert result.metadata.received_at_utc == FIXED_TIME.isoformat()
    assert dict(result.metadata.durations_ns)["total_duration"] > 0
    assert SYNTHETIC_KEY not in repr(result.metadata)


@pytest.mark.parametrize("returned_model", [DEEPSEEK_CURRENT_ALIAS, DEEPSEEK_CURRENT_BACKEND])
def test_deepseek_accepts_documented_v41_returned_model(returned_model: str) -> None:
    with _deepseek_adapter(
        lambda _: httpx.Response(200, json=_deepseek_response(model=returned_model))
    ) as adapter:
        result = adapter.propose(_request())

    assert result.metadata.requested_model == DEEPSEEK_MODEL
    assert result.metadata.returned_model == returned_model


def test_ollama_valid_schema_output_uses_local_non_thinking_request() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url == httpx.URL("http://127.0.0.1:11434/api/chat")
        assert "Authorization" not in request.headers
        payload = json.loads(request.content)
        assert payload["model"] == OLLAMA_MODEL
        assert payload["think"] is False
        assert payload["stream"] is False
        assert payload["options"] == {"temperature": 0.0}
        assert payload["format"]["additionalProperties"] is False
        assert "producer" not in payload["format"]["properties"]
        return httpx.Response(200, json=_ollama_response())

    with _ollama_adapter(handler) as adapter:
        result = adapter.propose(_request())

    assert result.proposal.producer == OLLAMA_ADAPTER_ID
    assert result.metadata.provider == "ollama"
    assert result.metadata.returned_model == OLLAMA_MODEL
    assert result.metadata.system_fingerprint is None
    assert result.metadata.usage == (
        ("prompt_eval_count", 120),
        ("eval_count", 80),
    )
    assert result.metadata.durations_ns == (
        ("total_duration", 2_000_000),
        ("load_duration", 500_000),
        ("prompt_eval_duration", 700_000),
        ("eval_duration", 800_000),
    )


@pytest.mark.parametrize(
    ("response_value", "category"),
    [
        (
            _deepseek_response(
                choices=[
                    {
                        "message": {"content": ""},
                        "finish_reason": "stop",
                    }
                ]
            ),
            "empty_response",
        ),
        (
            _deepseek_response(
                choices=[
                    {
                        "message": {"content": "not-json"},
                        "finish_reason": "stop",
                    }
                ]
            ),
            "invalid_json",
        ),
        (
            _deepseek_response(
                choices=[
                    {
                        "message": {"content": json.dumps(_model_output())},
                        "finish_reason": "length",
                    }
                ]
            ),
            "truncated",
        ),
        (_deepseek_response(choices=[]), "multiple_or_missing_outputs"),
        (
            _deepseek_response(
                choices=[
                    {
                        "message": {
                            "content": json.dumps(_model_output()),
                            "tool_calls": [{"function": {"name": "unexpected"}}],
                        },
                        "finish_reason": "stop",
                    }
                ]
            ),
            "unexpected_tool_call",
        ),
        (
            _deepseek_response(
                choices=[
                    {
                        "message": {
                            "content": json.dumps(_model_output()),
                            "reasoning_content": "unexpected reasoning",
                        },
                        "finish_reason": "stop",
                    }
                ]
            ),
            "thinking_not_disabled",
        ),
        (_deepseek_response(model="unselected-model"), "model_mismatch"),
    ],
)
def test_deepseek_rejects_malformed_incomplete_or_unexpected_output(
    response_value: dict[str, object], category: str
) -> None:
    with _deepseek_adapter(
        lambda _: httpx.Response(200, json=response_value)
    ) as adapter:
        with pytest.raises(LLMAdapterError) as captured:
            adapter.propose(_request())

    assert captured.value.category == category
    assert SENSITIVE_MARKER not in str(captured.value)


def test_deepseek_rejects_schema_violation_without_echo() -> None:
    invalid_output = deepcopy(_model_output())
    invalid_output["unexpected"] = SENSITIVE_MARKER
    response = _deepseek_response(
        choices=[
            {
                "message": {"content": json.dumps(invalid_output)},
                "finish_reason": "stop",
            }
        ]
    )

    with _deepseek_adapter(lambda _: httpx.Response(200, json=response)) as adapter:
        with pytest.raises(LLMAdapterError) as captured:
            adapter.propose(_request())

    assert captured.value.category == "invalid_schema"
    assert SENSITIVE_MARKER not in str(captured.value)
    assert SENSITIVE_MARKER not in repr(captured.value)


def test_multiple_tool_calls_are_classified_explicitly() -> None:
    response = _deepseek_response(
        choices=[
            {
                "message": {
                    "content": json.dumps(_model_output()),
                    "tool_calls": [
                        {"function": {"name": "first"}},
                        {"function": {"name": "second"}},
                    ],
                },
                "finish_reason": "stop",
            }
        ]
    )

    with _deepseek_adapter(lambda _: httpx.Response(200, json=response)) as adapter:
        with pytest.raises(LLMAdapterError) as captured:
            adapter.propose(_request())

    assert captured.value.category == "multiple_or_missing_outputs"


@pytest.mark.parametrize(
    ("status", "category", "retryable"),
    [
        (429, "rate_limit", True),
        (503, "provider_unavailable", True),
        (400, "request_rejected", False),
    ],
)
def test_http_errors_are_classified_without_response_body(
    status: int, category: str, retryable: bool
) -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(status, text=SENSITIVE_MARKER)

    with _deepseek_adapter(handler) as adapter:
        with pytest.raises(LLMAdapterError) as captured:
            adapter.propose(_request())

    assert captured.value.category == category
    assert captured.value.retryable is retryable
    assert captured.value.http_status == status
    assert SENSITIVE_MARKER not in str(captured.value)


def test_timeout_is_retryable_and_sanitised() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout(SENSITIVE_MARKER, request=request)

    with _deepseek_adapter(handler) as adapter:
        with pytest.raises(LLMAdapterError) as captured:
            adapter.propose(_request())

    assert captured.value.category == "timeout"
    assert captured.value.retryable is True
    assert SENSITIVE_MARKER not in str(captured.value)
    assert SYNTHETIC_KEY not in repr(captured.value)


@pytest.mark.parametrize(
    ("response", "category"),
    [
        (_ollama_response(done_reason="length"), "truncated"),
        (_ollama_response(model="unselected-model"), "model_mismatch"),
        (
            _ollama_response(
                message={
                    "content": json.dumps(_model_output()),
                    "thinking": "unexpected reasoning",
                }
            ),
            "thinking_not_disabled",
        ),
        (
            _ollama_response(
                message={
                    "content": json.dumps(_model_output()),
                    "tool_calls": [{"function": {"name": "unexpected"}}],
                }
            ),
            "unexpected_tool_call",
        ),
    ],
)
def test_ollama_rejects_truncation_drift_thinking_or_tool_call(
    response: dict[str, object], category: str
) -> None:
    with _ollama_adapter(lambda _: httpx.Response(200, json=response)) as adapter:
        with pytest.raises(LLMAdapterError) as captured:
            adapter.propose(_request())

    assert captured.value.category == category
