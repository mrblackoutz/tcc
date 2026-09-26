from __future__ import annotations

import asyncio
import json
from copy import deepcopy

import httpx
import pytest

from tcc_gateway.attempt_policy import NANOSECONDS, AttemptContractError
from tcc_gateway.g3c_smoke_runner import build_synthetic_request
from tcc_gateway.llm_adapters import LLMAdapterError
from tcc_gateway.llm_client_service import LLMClientServiceConfig, process_client_request
from tcc_gateway.pilot_llm_runner import (
    CLIENT_URL,
    call_llm_client_once,
    run_llm_stage,
)


def valid_response() -> dict[str, object]:
    status, response = process_client_request(
        build_synthetic_request(), LLMClientServiceConfig(),
    )
    assert status == 200
    return response


def test_internal_client_call_accepts_only_allowlisted_url_and_valid_response() -> None:
    response_value = valid_response()

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url == httpx.URL(f"{CLIENT_URL}/v1/proposals")
        assert "Authorization" not in request.headers
        assert request.extensions["timeout"]["connect"] == 10.0
        assert request.extensions["timeout"]["read"] == 120.0
        return httpx.Response(200, json=response_value)

    transport = httpx.MockTransport(handler)
    result = asyncio.run(call_llm_client_once(
        build_synthetic_request(), 180 * NANOSECONDS, transport=transport,
    ))
    assert result["status"] == "ok"
    with pytest.raises(AttemptContractError, match="allowlist"):
        asyncio.run(call_llm_client_once(
            build_synthetic_request(), 180 * NANOSECONDS,
            client_url="https://api.deepseek.com", transport=transport,
        ))


def test_internal_provider_error_is_classified_without_body_echo() -> None:
    sensitive = "SENSITIVE-RESPONSE-BODY-MARKER"
    transport = httpx.MockTransport(lambda _: httpx.Response(
        502,
        json={"error": {"category": "rate_limit", "retryable": True, "http_status": 429},
              "detail": sensitive},
    ))
    with pytest.raises(LLMAdapterError) as captured:
        asyncio.run(call_llm_client_once(
            build_synthetic_request(), 180 * NANOSECONDS, transport=transport,
        ))
    assert captured.value.category == "rate_limit"
    assert captured.value.http_status == 429
    assert sensitive not in str(captured.value)


def test_internal_provider_error_rejects_untrusted_category() -> None:
    sensitive = "SENSITIVE-ERROR-CATEGORY-MARKER"
    transport = httpx.MockTransport(lambda _: httpx.Response(
        502,
        json={"error": {"category": sensitive, "retryable": True, "http_status": 429}},
    ))
    with pytest.raises(LLMAdapterError) as captured:
        asyncio.run(call_llm_client_once(
            build_synthetic_request(), 180 * NANOSECONDS, transport=transport,
        ))
    assert captured.value.category == "invalid_client_response"
    assert sensitive not in str(captured.value)


def test_internal_read_timeout_is_uncertain_not_retryable() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("SENSITIVE-TIMEOUT", request=request)

    with pytest.raises(LLMAdapterError) as captured:
        asyncio.run(call_llm_client_once(
            build_synthetic_request(), 180 * NANOSECONDS,
            transport=httpx.MockTransport(handler),
        ))
    assert captured.value.category == "client_outcome_uncertain"
    assert captured.value.retryable is False
    assert "SENSITIVE-TIMEOUT" not in str(captured.value)


def test_same_stage_succeeds_in_c0_and_c1_without_defense_logic() -> None:
    response = valid_response()

    async def once(_request, _wall_cap_ns):
        return response

    for condition in ("C0", "C1"):
        result = asyncio.run(run_llm_stage(
            build_synthetic_request(), condition=condition, call_once=once,
        ))
        assert result.status == "success"
        assert result.reason == "SUCCESS"
        assert len(result.attempts) == 1
        assert result.attempts[0].outcome == "success"
        safe = json.dumps(result.to_sanitised_mapping())
        assert "vendor_ref" not in safe
        assert "DOCUMENTO SINTETICO" not in safe
        assert "proposal" not in repr(result)


def test_transient_provider_error_retries_once_with_same_request() -> None:
    response = valid_response()
    request_hashes = []
    wall_caps = []
    sleeps = []

    async def once(request, wall_cap_ns):
        request_hashes.append(json.dumps(request, sort_keys=True))
        wall_caps.append(wall_cap_ns)
        if len(request_hashes) == 1:
            raise LLMAdapterError("deepseek", "rate_limit", retryable=True, http_status=429)
        return response

    async def fake_sleep(seconds):
        sleeps.append(seconds)

    result = asyncio.run(run_llm_stage(
        build_synthetic_request(), condition="C0", call_once=once, sleep=fake_sleep,
    ))
    assert result.status == "success"
    assert [attempt.outcome for attempt in result.attempts] == ["classified_error", "success"]
    assert request_hashes[0] == request_hashes[1]
    assert wall_caps[0] <= 180 * NANOSECONDS
    assert wall_caps[1] <= 180 * NANOSECONDS
    assert sleeps == [2.0]


def test_schema_and_model_errors_never_retry() -> None:
    for category in ("model_mismatch", "invalid_schema", "truncated"):
        calls = 0

        async def once(_request, _wall_cap_ns):
            nonlocal calls
            calls += 1
            raise LLMAdapterError("deepseek", category, retryable=True)

        result = asyncio.run(run_llm_stage(
            build_synthetic_request(), condition="C1", call_once=once,
        ))
        assert result.status == "classified_error"
        assert result.reason == "PERMANENT_ERROR"
        assert calls == 1


def test_wrong_returned_model_is_classified_even_if_callback_says_success() -> None:
    response = deepcopy(valid_response())
    response["metadata"]["returned_model"] = "unselected-model"

    async def once(_request, _wall_cap_ns):
        return response

    result = asyncio.run(run_llm_stage(
        build_synthetic_request(), condition="C1", call_once=once,
    ))
    assert result.status == "classified_error"
    assert result.reason == "PERMANENT_ERROR"


def test_malformed_returned_model_is_classified_without_crashing() -> None:
    response = deepcopy(valid_response())
    response["metadata"]["returned_model"] = {"unexpected": "value"}

    async def once(_request, _wall_cap_ns):
        return response

    result = asyncio.run(run_llm_stage(
        build_synthetic_request(), condition="C0", call_once=once,
    ))
    assert result.status == "classified_error"
    assert result.attempts[0].error_category == "model_mismatch"


def test_common_stage_uses_internal_client_bridge_without_network() -> None:
    response = valid_response()
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url)
        return httpx.Response(200, json=response)

    transport = httpx.MockTransport(handler)

    async def once(request, wall_cap_ns):
        return await call_llm_client_once(request, wall_cap_ns, transport=transport)

    result = asyncio.run(run_llm_stage(
        build_synthetic_request(), condition="C1", call_once=once,
    ))
    assert result.status == "success"
    assert calls == [httpx.URL(f"{CLIENT_URL}/v1/proposals")]


def test_logical_budget_prevents_retry_before_backoff() -> None:
    readings = iter([0, 0, 0, 3 * NANOSECONDS, 299 * NANOSECONDS])

    async def once(_request, _wall_cap_ns):
        raise LLMAdapterError("deepseek", "timeout", retryable=True)

    result = asyncio.run(run_llm_stage(
        build_synthetic_request(), condition="C0", call_once=once,
        clock_ns=lambda: next(readings),
    ))
    assert result.status == "classified_error"
    assert result.reason == "BUDGET_EXHAUSTED"
    assert len(result.attempts) == 1


def test_wall_timeout_stops_without_retry(monkeypatch) -> None:
    async def fake_wait_for(awaitable, *, timeout):
        awaitable.close()
        raise TimeoutError

    monkeypatch.setattr("tcc_gateway.pilot_llm_runner.asyncio.wait_for", fake_wait_for)

    async def once(_request, _wall_cap_ns):
        return valid_response()

    result = asyncio.run(run_llm_stage(
        build_synthetic_request(), condition="C0", call_once=once,
    ))
    assert result.status == "uncertain"
    assert result.reason == "UNCONFIRMED_WALL_OUTCOME"
    assert len(result.attempts) == 1
    assert result.attempts[0].outcome == "deadline_exceeded"


def test_elapsed_wall_cap_is_checked_even_if_callback_returns_late() -> None:
    readings = iter([0, 0, 0, 181 * NANOSECONDS])

    async def once(_request, _wall_cap_ns):
        return valid_response()

    result = asyncio.run(run_llm_stage(
        build_synthetic_request(), condition="C0", call_once=once,
        clock_ns=lambda: next(readings),
    ))
    assert result.status == "uncertain"
    assert result.response is None
    assert result.attempts[0].outcome == "deadline_exceeded"


def test_malformed_callback_response_is_classified() -> None:
    async def once(_request, _wall_cap_ns):
        return ["unexpected"]

    result = asyncio.run(run_llm_stage(
        build_synthetic_request(), condition="C1", call_once=once,
    ))
    assert result.status == "classified_error"
    assert result.attempts[0].error_category == "invalid_client_response"


def test_invalid_condition_or_request_never_calls_model() -> None:
    calls = 0

    async def once(_request, _wall_cap_ns):
        nonlocal calls
        calls += 1
        return valid_response()

    with pytest.raises(AttemptContractError, match="condition"):
        asyncio.run(run_llm_stage(
            build_synthetic_request(), condition="C2", call_once=once,
        ))
    with pytest.raises(AttemptContractError, match="typed LLM client"):
        asyncio.run(run_llm_stage(
            {"schema_version": "wrong"}, condition="C0", call_once=once,
        ))
    assert calls == 0
