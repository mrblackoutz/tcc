from __future__ import annotations

import json

import httpx
import pytest

from tcc_gateway.g3c_smoke_runner import (
    DEFAULT_CLIENT_URL,
    G3CSmokeError,
    SCENARIO_ID,
    build_sanitised_manifest,
    build_synthetic_request,
    execute_smoke,
)


SENSITIVE_MARKER = "SENSITIVE-G3C-RESPONSE-MARKER"
GIT_COMMIT = "a" * 40


def _client_response() -> dict[str, object]:
    request_value = build_synthetic_request()
    document = request_value["document"]
    return {
        "schema_version": "llm-client-response/v1",
        "status": "ok",
        "proposal": {
            "schema_version": "vendor-bill-proposal/v1",
            "action": "CREATE_DRAFT_BILL",
            "producer": "deepseek-chat-completions/v1",
            "scenario_id": SCENARIO_ID,
            "synthetic_data": True,
            "fiscal_value": False,
            "source": {
                "document_sha256": document["document_sha256"],
                "text_sha256": document["text_sha256"],
                "page_count": 1,
            },
            "vendor_ref": "TCC-VENDOR-001",
            "purchase_order_ref": "TCC-PO-001",
            "document_ref": "TCC-G3C-NF-001-SEM-VALOR-FISCAL",
            "invoice_date": "2026-09-02",
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
        },
        "metadata": {
            "provider": "deepseek",
            "adapter_id": "deepseek-chat-completions/v1",
            "endpoint": "https://api.deepseek.com/chat/completions",
            "requested_model": "deepseek-v4-flash",
            "returned_model": "deepseek-v4-flash",
            "response_id": "synthetic-g3c-response",
            "system_fingerprint": "fp_synthetic_g3c",
            "received_at_utc": "2026-09-02T12:00:00+00:00",
            "thinking": "disabled",
            "temperature": 0.0,
            "max_output_tokens": 2048,
            "finish_reason": "stop",
            "request_sha256": "1" * 64,
            "response_body_sha256": "2" * 64,
            "response_content_sha256": "3" * 64,
            "messages_sha256": "4" * 64,
            "system_prompt_sha256": "5" * 64,
            "schema_sha256": "6" * 64,
            "usage": {
                "prompt_tokens": 100,
                "completion_tokens": 50,
                "total_tokens": 150,
            },
            "durations_ns": {"total_duration": 10_000},
        },
    }


def test_manifest_contains_only_sanitised_metadata_and_hashes() -> None:
    request_value = build_synthetic_request()
    manifest = build_sanitised_manifest(
        request_value,
        _client_response(),
        wall_duration_ns=20_000,
        git_commit=GIT_COMMIT,
        executed_at_utc="2026-09-02T12:00:01+00:00",
    )

    assert manifest["status"] == "pass"
    assert manifest["real_provider_calls"] == 1
    assert manifest["scientific_run"] is False
    assert manifest["provider"]["response_id"] == "synthetic-g3c-response"
    assert manifest["latency_ns"]["adapter_total"] == 10_000
    encoded = json.dumps(manifest)
    assert "DOCUMENTO SINTETICO" not in encoded
    assert "vendor_ref" not in encoded
    assert SENSITIVE_MARKER not in encoded


def test_execute_smoke_writes_manifest_without_raw_response(tmp_path) -> None:
    response_value = _client_response()

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url == httpx.URL(f"{DEFAULT_CLIENT_URL}/v1/proposals")
        return httpx.Response(200, json=response_value)

    evidence_path = tmp_path / "g3c-deepseek-smoke.json"
    manifest = execute_smoke(
        client_url=DEFAULT_CLIENT_URL,
        evidence_path=evidence_path,
        git_commit=GIT_COMMIT,
        transport=httpx.MockTransport(handler),
    )

    assert manifest["status"] == "pass"
    evidence = evidence_path.read_text(encoding="utf-8")
    assert "DOCUMENTO SINTETICO" not in evidence
    assert "vendor_ref" not in evidence


def test_execute_smoke_classifies_http_failure_without_body_echo(tmp_path) -> None:
    transport = httpx.MockTransport(
        lambda _: httpx.Response(502, text=SENSITIVE_MARKER)
    )
    with pytest.raises(G3CSmokeError) as captured:
        execute_smoke(
            client_url=DEFAULT_CLIENT_URL,
            evidence_path=tmp_path / "unused.json",
            git_commit=GIT_COMMIT,
            transport=transport,
        )

    assert captured.value.category == "llm_client_http_502"
    assert SENSITIVE_MARKER not in str(captured.value)


def test_execute_smoke_preserves_only_sanitised_provider_failure(tmp_path) -> None:
    transport = httpx.MockTransport(
        lambda _: httpx.Response(
            502,
            json={
                "schema_version": "llm-client-response/v1",
                "status": "error",
                "error": {
                    "provider": "deepseek",
                    "category": "request_rejected",
                    "retryable": False,
                    "http_status": 400,
                    "detail": SENSITIVE_MARKER,
                },
            },
        )
    )
    with pytest.raises(G3CSmokeError) as captured:
        execute_smoke(
            client_url=DEFAULT_CLIENT_URL,
            evidence_path=tmp_path / "unused.json",
            git_commit=GIT_COMMIT,
            transport=transport,
        )

    assert (
        captured.value.category
        == "llm_client_request_rejected_provider_http_400"
    )
    assert SENSITIVE_MARKER not in str(captured.value)
