from __future__ import annotations

import json
import threading
from copy import deepcopy
from http.server import ThreadingHTTPServer
from importlib.resources import files

import httpx
import pytest
from jsonschema import Draft202012Validator, FormatChecker

from tcc_gateway.action_proposal_v2 import ActionProposalV2
from tcc_gateway.g3c_smoke_runner import build_synthetic_request
from tcc_gateway.llm_adapters import expected_proposal_request_hashes
from tcc_gateway.llm_client_service import (
    LLMClientServiceConfig,
    LLMClientServiceError,
    build_handler,
    parse_client_request,
    parse_client_request_v2,
    process_client_request,
    validate_v2_client_response,
)
from tcc_gateway.llm_config import DEEPSEEK_MODEL, DeepSeekConfig, GenerationSettings
from tcc_gateway.state import canonical_json_sha256


MARKER = "SENSITIVE-V2-TRANSPORT-MARKER"


def v2_request(provider: str = "deepseek") -> dict:
    value = build_synthetic_request()
    value.update(schema_version="llm-client-request/v2", output_contract="v2", provider=provider)
    return value


def v2_response(provider: str = "deepseek") -> dict:
    status, value = process_client_request(v2_request(provider))
    assert status == 200
    return value


def _response_validator() -> Draft202012Validator:
    schema = json.loads(files("tcc_gateway.schemas").joinpath("llm_client_response_v2.schema.json").read_text(encoding="utf-8"))
    return Draft202012Validator(schema, format_checker=FormatChecker())


@pytest.mark.parametrize("provider", ["deepseek", "ollama"])
def test_explicit_v2_mock_is_bound_to_schema_prompt_document_and_proposal(provider: str) -> None:
    request = v2_request(provider)
    response = v2_response(provider)
    proposal = validate_v2_client_response(request, response)
    assert isinstance(proposal, ActionProposalV2)
    assert proposal.action == "CREATE_DRAFT_BILL"
    assert response["schema_version"] == "llm-client-response/v2"
    assert response["output_contract"] == "v2"
    assert response["client_request_sha256"] == canonical_json_sha256(request)
    assert response["proposal_sha256"] == canonical_json_sha256(proposal.to_mapping())
    _response_validator().validate(response)
    _, parsed = parse_client_request_v2(request)
    for name, sha256 in expected_proposal_request_hashes(parsed).items():
        assert response["metadata"][name] == sha256


def test_v1_parser_does_not_accept_v2_and_v2_does_not_promote_v1() -> None:
    with pytest.raises(LLMClientServiceError, match="invalid_request"):
        parse_client_request(v2_request())
    with pytest.raises(LLMClientServiceError, match="invalid_request"):
        parse_client_request_v2(build_synthetic_request())
    status, historical = process_client_request(build_synthetic_request())
    assert status == 200
    assert historical["schema_version"] == "llm-client-response/v1"
    assert historical["proposal"]["schema_version"] == "vendor-bill-proposal/v1"
    assert "output_contract" not in historical


@pytest.mark.parametrize("field", ["condition", "label", "approval", "workflow", "target_move_id"])
def test_request_has_no_experimental_label_or_financial_authority(field: str) -> None:
    request = v2_request()
    request[field] = MARKER
    status, response = process_client_request(request)
    assert status == 400
    assert response["error"]["category"] == "invalid_request"
    assert MARKER not in json.dumps(response)
    _response_validator().validate(response)


@pytest.mark.parametrize("mutation", [
    lambda value: value.pop("output_contract"),
    lambda value: value.update(output_contract="v1"),
    lambda value: value.update(schema_version="llm-client-request/v1"),
    lambda value: value["document"].update(page_count=True),
    lambda value: value["document"].update(page_count=1.0),
    lambda value: value["document"].update(byte_count=True),
    lambda value: value["document"].update(byte_count=100.0),
    lambda value: value["document"].update(document_sha256="INVALID"),
    lambda value: value["document"].update(text_sha256="0" * 64),
    lambda value: value["messages"].clear(),
    lambda value: value["messages"][0].update(content="\ud800"),
    lambda value: value["document"].update(text="\ud800"),
])
def test_explicit_v2_invalid_request_never_enters_adapter(mutation) -> None:
    request = v2_request()
    mutation(request)
    status, response = process_client_request(request)
    assert status == 400
    assert response["status"] == "error"
    assert MARKER not in json.dumps(response)


@pytest.mark.parametrize("path, replacement", [
    (("schema_version",), "llm-client-response/v1"),
    (("output_contract",), "v1"),
    (("client_request_sha256",), "0" * 64),
    (("proposal_sha256",), "0" * 64),
    (("proposal", "source", "document_sha256"), "0" * 64),
    (("proposal", "source", "text_sha256"), "0" * 64),
    (("proposal", "source", "page_count"), 2),
    (("proposal", "scenario_id"), "OTHER-SCENARIO"),
    (("proposal", "producer"), "ollama-chat/v1"),
    (("metadata", "provider"), "ollama"),
    (("metadata", "adapter_id"), "ollama-chat/v1"),
    (("metadata", "requested_model"), "unselected-model"),
    (("metadata", "returned_model"), "unselected-model"),
    (("metadata", "endpoint"), "https://unapproved.example.invalid/chat/completions"),
    (("metadata", "thinking"), "enabled"),
    (("metadata", "temperature"), False),
    (("metadata", "max_output_tokens"), True),
    (("metadata", "max_output_tokens"), 2048.0),
    (("metadata", "max_output_tokens"), 4096),
    (("metadata", "finish_reason"), "length"),
    (("metadata", "schema_sha256"), "0" * 64),
    (("metadata", "messages_sha256"), "0" * 64),
    (("metadata", "system_prompt_sha256"), "0" * 64),
    (("metadata", "response_body_sha256"), MARKER),
    (("metadata", "received_at_utc"), MARKER),
    (("metadata", "usage", "prompt_tokens"), True),
    (("metadata", "usage", "prompt_tokens"), 1.0),
    (("metadata", "usage", "unexpected"), 1),
    (("metadata", "durations_ns", "total_duration"), -1),
    (("metadata", "durations_ns", "total_duration"), 1.0),
])
def test_success_envelope_tampering_is_finite_failure_even_with_rehashed_proposal(path, replacement) -> None:
    response = deepcopy(v2_response())
    target = response
    for part in path[:-1]:
        target = target[part]
    target[path[-1]] = replacement
    if path[0] == "proposal":
        response["proposal_sha256"] = canonical_json_sha256(response["proposal"])
    with pytest.raises(LLMClientServiceError) as captured:
        validate_v2_client_response(v2_request(), response)
    assert MARKER not in str(captured.value)


@pytest.mark.parametrize("target", ["envelope", "proposal", "metadata"])
def test_success_envelope_rejects_unknown_fields(target: str) -> None:
    response = v2_response()
    selected = response if target == "envelope" else response[target]
    selected["unexpected"] = MARKER
    with pytest.raises(LLMClientServiceError) as captured:
        validate_v2_client_response(v2_request(), response)
    assert MARKER not in str(captured.value)


@pytest.mark.parametrize("raw_hash", [False, True])
@pytest.mark.parametrize("mutation", [
    lambda value: value["source"].update(page_count=1.0),
    lambda value: value.update(invoice_date="20260902"),
    lambda value: value.update(synthetic_data=1),
    lambda value: value.update(fiscal_value=0),
])
def test_response_proposal_cannot_be_repaired_by_mapping_casts_or_normalized_hash(mutation, raw_hash: bool) -> None:
    response = v2_response()
    mutation(response["proposal"])
    if raw_hash:
        response["proposal_sha256"] = canonical_json_sha256(response["proposal"])
    with pytest.raises(LLMClientServiceError, match="invalid_client_response"):
        validate_v2_client_response(v2_request(), response)


@pytest.mark.parametrize("max_output_tokens", [4096, 2048.0])
def test_unapproved_v2_generation_is_rejected_before_provider_call(max_output_tokens) -> None:
    def handler(_request):
        pytest.fail("provider call occurred before checking generation contract")

    config = LLMClientServiceConfig(
        mode="deepseek-smoke",
        deepseek_config=DeepSeekConfig(
            api_key="synthetic-v2-placeholder",
            generation=GenerationSettings(max_output_tokens=max_output_tokens),
        ),
    )
    status, response = process_client_request(v2_request(), config, transport=httpx.MockTransport(handler))
    assert status == 400
    assert response["error"]["category"] == "generation_mismatch"


@pytest.mark.parametrize("action", ["CREATE_DRAFT_BILL", "POST_VENDOR_BILL"])
def test_service_preserves_action_emitted_by_model_and_injects_no_target(action: str) -> None:
    output = v2_response()["proposal"]
    for name in ("schema_version", "producer", "scenario_id", "synthetic_data", "fiscal_value", "source"):
        output.pop(name)
    output["action"] = action
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        calls.append(payload)
        assert payload["max_tokens"] == 2048
        assert payload["temperature"] == 0
        assert payload["thinking"] == {"type": "disabled"}
        assert '"POST_VENDOR_BILL"' in payload["messages"][0]["content"]
        return httpx.Response(200, json={
            "model": DEEPSEEK_MODEL,
            "choices": [{"message": {"content": json.dumps(output)}, "finish_reason": "stop"}],
        })

    config = LLMClientServiceConfig(mode="deepseek-smoke", deepseek_config=DeepSeekConfig(api_key="synthetic-v2-placeholder"))
    status, response = process_client_request(v2_request(), config, transport=httpx.MockTransport(handler))
    assert status == 200
    proposal = validate_v2_client_response(v2_request(), response)
    assert proposal.action == action
    assert "target_move_id" not in proposal.to_mapping()
    assert len(calls) == 1


def test_wrong_v1_output_on_v2_request_is_not_silently_upgraded() -> None:
    output = v2_response()["proposal"]
    for name in ("schema_version", "producer", "scenario_id", "synthetic_data", "fiscal_value", "source", "action"):
        output.pop(name)
    config = LLMClientServiceConfig(mode="deepseek-smoke", deepseek_config=DeepSeekConfig(api_key="synthetic-v2-placeholder"))
    transport = httpx.MockTransport(lambda _: httpx.Response(200, json={
        "model": DEEPSEEK_MODEL,
        "choices": [{"message": {"content": json.dumps(output)}, "finish_reason": "stop"}],
    }))
    status, response = process_client_request(v2_request(), config, transport=transport)
    assert status == 502
    assert response["schema_version"] == "llm-client-response/v2"
    assert response["error"]["category"] == "invalid_schema"
    _response_validator().validate(response)


def test_actual_internal_http_routes_refuse_contract_promotion_and_downgrade() -> None:
    server = ThreadingHTTPServer(("127.0.0.1", 0), build_handler())
    server.daemon_threads = True
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        with httpx.Client(base_url=f"http://127.0.0.1:{server.server_port}", timeout=2) as client:
            for path, request in (("/v1/proposals", v2_request()), ("/v2/proposals", build_synthetic_request())):
                response = client.post(path, json=request)
                assert response.status_code == 400
                assert response.json()["error"]["category"] == "route_contract_mismatch"
            response = client.post("/v2/proposals", json=v2_request())
            assert response.status_code == 200
            assert validate_v2_client_response(v2_request(), response.json()).action == "CREATE_DRAFT_BILL"
            assert client.post("/v3/proposals", json=v2_request()).status_code == 404
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
