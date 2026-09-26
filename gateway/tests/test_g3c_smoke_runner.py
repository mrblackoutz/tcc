from __future__ import annotations

import json

import httpx
import pytest

from tcc_gateway.g3c_smoke_runner import (
    DEFAULT_CLIENT_URL,
    G3CSmokeError,
    PILOT_SCHEMA_VERSION,
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


@pytest.mark.parametrize("returned_model", ["deepseek-flash", "DeepSeek-V4.1-Flash"])
def test_manifest_preserves_documented_v41_model(returned_model: str) -> None:
    response_value = _client_response()
    response_value["metadata"]["returned_model"] = returned_model
    manifest = build_sanitised_manifest(
        build_synthetic_request(),
        response_value,
        wall_duration_ns=20_000,
        git_commit=GIT_COMMIT,
        executed_at_utc="2026-09-24T12:00:01+00:00",
    )

    assert manifest["provider"]["requested_model"] == "deepseek-v4-flash"
    assert manifest["provider"]["returned_model"] == returned_model


@pytest.mark.parametrize("returned_model", ["deepseek-flash", "DeepSeek-V4.1-Flash"])
def test_canonical_pilot_manifest_is_separate_and_sanitised(returned_model: str) -> None:
    response_value = _client_response()
    response_value["metadata"]["requested_model"] = "deepseek-flash"
    response_value["metadata"]["returned_model"] = returned_model
    manifest = build_sanitised_manifest(
        build_synthetic_request(), response_value,
        wall_duration_ns=20_000, git_commit=GIT_COMMIT,
        executed_at_utc="2026-09-26T12:00:01+00:00", canonical_pilot=True,
    )
    assert manifest["schema_version"] == PILOT_SCHEMA_VERSION
    assert manifest["task_id"] == "G3-06"
    assert manifest["provider"]["requested_model"] == "deepseek-flash"
    assert manifest["provider"]["returned_model"] == returned_model
    assert "DOCUMENTO SINTETICO" not in json.dumps(manifest)


def test_canonical_pilot_rejects_legacy_request_or_backend() -> None:
    response_value = _client_response()
    with pytest.raises(G3CSmokeError, match="requested_model_mismatch"):
        build_sanitised_manifest(
            build_synthetic_request(), response_value,
            wall_duration_ns=20_000, git_commit=GIT_COMMIT,
            executed_at_utc="2026-09-26T12:00:01+00:00", canonical_pilot=True,
        )
    response_value["metadata"]["requested_model"] = "deepseek-flash"
    response_value["metadata"]["returned_model"] = "DeepSeek-V4-Flash-0731"
    with pytest.raises(G3CSmokeError, match="returned_model_mismatch"):
        build_sanitised_manifest(
            build_synthetic_request(), response_value,
            wall_duration_ns=20_000, git_commit=GIT_COMMIT,
            executed_at_utc="2026-09-26T12:00:01+00:00", canonical_pilot=True,
        )


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


def test_execute_canonical_pilot_uses_separate_manifest(tmp_path) -> None:
    response_value = _client_response()
    response_value["metadata"]["requested_model"] = "deepseek-flash"
    response_value["metadata"]["returned_model"] = "deepseek-flash"
    evidence_path = tmp_path / "g306-deepseek-smoke.json"
    transport = httpx.MockTransport(lambda _: httpx.Response(200, json=response_value))
    manifest = execute_smoke(
        client_url=DEFAULT_CLIENT_URL, evidence_path=evidence_path,
        git_commit=GIT_COMMIT, transport=transport, canonical_pilot=True,
    )
    assert manifest["schema_version"] == PILOT_SCHEMA_VERSION
    assert manifest["task_id"] == "G3-06"
    assert evidence_path.is_file()
    assert not (tmp_path / "g3c-deepseek-smoke.json").exists()


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


def test_execute_smoke_preserves_safe_category_without_provider_http_status(tmp_path) -> None:
    transport = httpx.MockTransport(
        lambda _: httpx.Response(
            502,
            json={
                "schema_version": "llm-client-response/v1",
                "status": "error",
                "error": {
                    "provider": "deepseek",
                    "category": "model_mismatch",
                    "retryable": False,
                    "http_status": None,
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

    assert captured.value.category == "llm_client_model_mismatch"
    assert SENSITIVE_MARKER not in str(captured.value)
