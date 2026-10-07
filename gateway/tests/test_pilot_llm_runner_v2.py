from __future__ import annotations

import asyncio
import json
from copy import deepcopy

import httpx
import pytest

from tcc_gateway.attempt_policy import NANOSECONDS, AttemptContractError
from tcc_gateway.llm_adapters import LLMAdapterError
from tcc_gateway.llm_client_service import validate_v2_client_response
from tcc_gateway.pilot_llm_runner import CLIENT_URL, call_llm_client_once, run_llm_stage
from tcc_gateway.state import canonical_json_sha256

from test_llm_client_service_v2 import v2_request, v2_response


@pytest.mark.parametrize("action", ["CREATE_DRAFT_BILL", "POST_VENDOR_BILL"])
def test_same_v2_stage_preserves_model_action_for_both_conditions(action: str) -> None:
    request = v2_request()
    response = v2_response()
    response["proposal"]["action"] = action
    response["proposal_sha256"] = canonical_json_sha256(response["proposal"])
    seen = []

    async def once(request_value, _wall_cap_ns):
        seen.append(canonical_json_sha256(request_value))
        return response

    results = [asyncio.run(run_llm_stage(request, condition=condition, call_once=once)) for condition in ("C0", "C1")]
    assert all(result.status == "success" for result in results)
    assert seen == [canonical_json_sha256(request)] * 2
    assert results[0].response == results[1].response
    assert [result.attempts[0].request_sha256 for result in results] == seen
    assert validate_v2_client_response(request, results[0].response).action == action
    for result in results:
        safe = json.dumps(result.to_sanitised_mapping())
        assert "vendor_ref" not in safe
        assert "DOCUMENTO SINTETICO" not in safe
        assert "proposal" not in repr(result)


def test_internal_v2_bridge_routes_only_to_v2_and_receives_no_api_key() -> None:
    request = v2_request()
    response_value = v2_response()
    calls = []

    def handler(request_value: httpx.Request) -> httpx.Response:
        calls.append(request_value.url)
        assert request_value.url == httpx.URL(f"{CLIENT_URL}/v2/proposals")
        assert "Authorization" not in request_value.headers
        assert request_value.extensions["timeout"]["connect"] == 10.0
        assert request_value.extensions["timeout"]["read"] == 120.0
        assert json.loads(request_value.content) == request
        return httpx.Response(200, json=response_value)

    async def once(value, cap):
        return await call_llm_client_once(value, cap, transport=httpx.MockTransport(handler))

    result = asyncio.run(run_llm_stage(request, condition="C1", call_once=once))
    assert result.status == "success"
    assert calls == [httpx.URL(f"{CLIENT_URL}/v2/proposals")]


@pytest.mark.parametrize("mutation", [
    lambda value: value.update(schema_version="llm-client-response/v1"),
    lambda value: value.update(output_contract="v1"),
    lambda value: value.update(client_request_sha256="0" * 64),
    lambda value: value.update(proposal_sha256="0" * 64),
    lambda value: value["proposal"].update(scenario_id="OTHER-SCENARIO"),
    lambda value: value["proposal"]["source"].update(document_sha256="0" * 64),
    lambda value: value["metadata"].update(schema_sha256="0" * 64),
    lambda value: value["metadata"].update(messages_sha256="0" * 64),
    lambda value: value["metadata"].update(returned_model="unselected-model"),
    lambda value: value["metadata"].update(temperature=True),
])
def test_v2_response_contract_failures_are_terminal_and_do_not_trigger_retry(mutation) -> None:
    response = deepcopy(v2_response())
    mutation(response)
    calls = 0

    async def once(_request, _cap):
        nonlocal calls
        calls += 1
        return response

    result = asyncio.run(run_llm_stage(v2_request(), condition="C0", call_once=once))
    assert result.status == "classified_error"
    assert result.reason == "PERMANENT_ERROR"
    assert calls == 1
    assert result.response is None


def test_v2_retry_preserves_identical_typed_request_and_approved_delay() -> None:
    response = v2_response()
    seen = []
    delays = []

    async def once(request, _cap):
        seen.append(canonical_json_sha256(request))
        if len(seen) == 1:
            raise LLMAdapterError("deepseek", "rate_limit", retryable=True, http_status=429)
        return response

    async def sleep(delay):
        delays.append(delay)

    result = asyncio.run(run_llm_stage(v2_request(), condition="C1", call_once=once, sleep=sleep))
    assert result.status == "success"
    assert seen == [canonical_json_sha256(v2_request())] * 2
    assert delays == [2.0]
    assert len(result.attempts) == 2


@pytest.mark.parametrize("bad_response", [
    {"schema_version": "llm-client-response/v1", "status": "error", "error": {"category": "rate_limit", "retryable": True, "http_status": 429}},
    {"schema_version": "llm-client-response/v2", "status": "error", "error": {"category": "rate_limit", "retryable": True, "http_status": 429}, "detail": "SENSITIVE-V2-MARKER"},
    {"schema_version": "llm-client-response/v2", "status": "error", "error": {"provider": "ollama", "category": "rate_limit", "retryable": True, "http_status": 429}},
])
def test_internal_v2_error_bridge_refuses_cross_version_unknown_fields_and_provider(bad_response) -> None:
    transport = httpx.MockTransport(lambda _: httpx.Response(502, json=bad_response))
    with pytest.raises(LLMAdapterError) as captured:
        asyncio.run(call_llm_client_once(v2_request(), 180 * NANOSECONDS, transport=transport))
    assert captured.value.category == "invalid_client_response"
    assert "SENSITIVE-V2-MARKER" not in str(captured.value)


def test_valid_v2_internal_provider_error_is_classified_without_echo() -> None:
    value = {"schema_version": "llm-client-response/v2", "status": "error", "error": {"provider": "deepseek", "category": "rate_limit", "retryable": True, "http_status": 429}}
    with pytest.raises(LLMAdapterError) as captured:
        asyncio.run(call_llm_client_once(v2_request(), 180 * NANOSECONDS, transport=httpx.MockTransport(lambda _: httpx.Response(502, json=value))))
    assert captured.value.category == "rate_limit"
    assert captured.value.retryable is True


@pytest.mark.parametrize("request_value", [
    [],
    {"schema_version": "llm-client-request/v2"},
    v2_request("ollama"),
])
def test_invalid_request_or_local_model_block_never_calls_model(request_value) -> None:
    calls = 0

    async def once(_request, _cap):
        nonlocal calls
        calls += 1
        return v2_response()

    with pytest.raises(AttemptContractError):
        asyncio.run(run_llm_stage(request_value, condition="C0", call_once=once))
    assert calls == 0
