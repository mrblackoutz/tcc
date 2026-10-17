from __future__ import annotations

import asyncio
from copy import deepcopy
from dataclasses import replace

import pytest

from tcc_gateway.attempt_policy import AttemptRecord, NANOSECONDS
from tcc_gateway.llm_adapters import LLMAdapterError
from tcc_gateway.pilot_llm_runner import LLMStageResult, run_llm_stage
from tcc_gateway.state import canonical_json_sha256
from tcc_gateway.terminal_llm_stage import (
    TerminalLLMStageError, stage_outcome_uncertain, validate_terminal_llm_stage,
)

from test_llm_client_service_v2 import v2_request, v2_response


S = NANOSECONDS


def failed(number=1, *, category="invalid_schema", retryable=False,
           status=None, elapsed_ns=S):
    return AttemptRecord(number, "classified_error", elapsed_ns,
        canonical_json_sha256(v2_request()), error_category=category,
        retryable_hint=retryable, http_status=status)


def terminal(*, condition="C0", status="classified_error", reason="PERMANENT_ERROR", attempts=None):
    return LLMStageResult(condition, status, reason,
        (failed(),) if attempts is None else attempts)


@pytest.mark.parametrize("condition", ["C0", "C1"])
@pytest.mark.parametrize("retry_count", [0, 1, 2])
def test_real_successful_stage_and_retries_have_bound_proposal(condition, retry_count):
    now = [0]
    calls = []

    async def once(request, cap):
        calls.append((canonical_json_sha256(request), cap))
        now[0] += S
        if len(calls) <= retry_count:
            raise LLMAdapterError("deepseek", "rate_limit", retryable=True, http_status=429)
        return v2_response()

    async def sleep(delay):
        now[0] += int(delay * S)

    result = asyncio.run(run_llm_stage(v2_request(), condition=condition,
        call_once=once, sleep=sleep, clock_ns=lambda: now[0]))
    proposal = validate_terminal_llm_stage(v2_request(), result, elapsed_ns=now[0])
    assert proposal.to_mapping() == v2_response()["proposal"]
    assert len(calls) == retry_count + 1
    assert not stage_outcome_uncertain(result)


@pytest.mark.parametrize("condition", ["C0", "C1"])
@pytest.mark.parametrize("category", [
    "invalid_schema", "invalid_client_response", "client_outcome_uncertain",
    "request_binding_mismatch", "proposal_hash_mismatch", "scenario_mismatch",
    "document_binding_mismatch", "prompt_contract_mismatch", "model_mismatch",
    "empty_response", "request_rejected", "truncated", "thinking_not_disabled",
])
def test_real_permanent_error_preserves_category_without_proposal(condition, category):
    async def once(_request, _cap):
        raise LLMAdapterError("deepseek", category)

    result = asyncio.run(run_llm_stage(v2_request(), condition=condition,
        call_once=once, clock_ns=lambda: 0))
    assert result.status == "classified_error"
    assert validate_terminal_llm_stage(v2_request(), result, elapsed_ns=0) is None
    assert stage_outcome_uncertain(result) is (category == "client_outcome_uncertain")


@pytest.mark.parametrize("condition", ["C0", "C1"])
def test_real_retries_exhausted(condition):
    now = [0]

    async def once(_request, _cap):
        now[0] += S
        raise LLMAdapterError("deepseek", "transport", retryable=True)

    async def sleep(delay):
        now[0] += int(delay * S)

    result = asyncio.run(run_llm_stage(v2_request(), condition=condition,
        call_once=once, sleep=sleep, clock_ns=lambda: now[0]))
    assert result.reason == "RETRY_EXHAUSTED"
    assert validate_terminal_llm_stage(v2_request(), result, elapsed_ns=now[0]) is None


@pytest.mark.parametrize("condition", ["C0", "C1"])
def test_real_budget_before_first_attempt_preserves_zero_attempts(condition):
    clock = iter([0, 300 * S])

    async def once(_request, _cap):
        pytest.fail("budget exhausted must not call provider")

    result = asyncio.run(run_llm_stage(v2_request(), condition=condition,
        call_once=once, clock_ns=lambda: next(clock)))
    assert result.attempts == ()
    assert validate_terminal_llm_stage(v2_request(), result, elapsed_ns=300 * S) is None


@pytest.mark.parametrize("condition", ["C0", "C1"])
def test_real_budget_before_backoff_uses_clock_not_just_attempt_sum(condition):
    clock = iter([0, 0, 0, 3 * S, 299 * S])

    async def once(_request, _cap):
        raise LLMAdapterError("deepseek", "timeout", retryable=True)

    result = asyncio.run(run_llm_stage(v2_request(), condition=condition,
        call_once=once, clock_ns=lambda: next(clock)))
    assert result.status == "classified_error" and result.reason == "BUDGET_EXHAUSTED"
    assert validate_terminal_llm_stage(v2_request(), result, elapsed_ns=299 * S) is None


@pytest.mark.parametrize("condition", ["C0", "C1"])
def test_real_budget_after_backoff_does_not_require_next_attempt(condition):
    now = [0]

    async def once(_request, _cap):
        now[0] += 3 * S
        raise LLMAdapterError("deepseek", "timeout", retryable=True)

    async def delayed_sleep(_delay):
        # Scheduler delay can consume more than the requested backoff.
        now[0] = 301 * S

    result = asyncio.run(run_llm_stage(v2_request(), condition=condition,
        call_once=once, sleep=delayed_sleep, clock_ns=lambda: now[0]))
    assert result.status == "budget_exhausted" and len(result.attempts) == 1
    assert validate_terminal_llm_stage(v2_request(), result, elapsed_ns=301 * S) is None


@pytest.mark.parametrize("condition", ["C0", "C1"])
@pytest.mark.parametrize("duration", [181 * S, 301 * S, 900 * S])
def test_real_late_callback_preserves_uncertain_overrun(condition, duration):
    clock = iter([0, 0, 0, duration])

    async def once(_request, _cap):
        return v2_response()

    result = asyncio.run(run_llm_stage(v2_request(), condition=condition,
        call_once=once, clock_ns=lambda: next(clock)))
    assert result.status == "uncertain" and result.response is None
    assert validate_terminal_llm_stage(v2_request(), result, elapsed_ns=duration) is None
    assert stage_outcome_uncertain(result)


def test_actual_wait_timeout_is_recordable(monkeypatch):
    async def timeout(awaitable, *, timeout):
        awaitable.close()
        raise TimeoutError

    monkeypatch.setattr("tcc_gateway.pilot_llm_runner.asyncio.wait_for", timeout)

    async def once(_request, _cap):
        return v2_response()

    result = asyncio.run(run_llm_stage(v2_request(), condition="C0", call_once=once, clock_ns=lambda: 0))
    assert validate_terminal_llm_stage(v2_request(), result, elapsed_ns=0) is None
    assert stage_outcome_uncertain(result)


def test_actual_backoff_wait_timeout_is_recordable(monkeypatch):
    original_wait_for = asyncio.wait_for
    now = [0]
    waits = [0]

    async def timeout_on_backoff(awaitable, *, timeout):
        waits[0] += 1
        if waits[0] == 2:
            awaitable.close()
            now[0] = 301 * S
            raise TimeoutError
        return await original_wait_for(awaitable, timeout=timeout)

    monkeypatch.setattr("tcc_gateway.pilot_llm_runner.asyncio.wait_for", timeout_on_backoff)

    async def once(_request, _cap):
        now[0] = 3 * S
        raise LLMAdapterError("deepseek", "transport", retryable=True)

    result = asyncio.run(run_llm_stage(v2_request(), condition="C0", call_once=once,
        clock_ns=lambda: now[0]))
    assert result.status == "budget_exhausted"
    assert validate_terminal_llm_stage(v2_request(), result, elapsed_ns=now[0]) is None
    assert stage_outcome_uncertain(result)


@pytest.mark.parametrize("category,status,retryable", [
    ("rate_limit", 429, True), ("provider_unavailable", 408, True),
    ("provider_unavailable", 500, True), ("provider_unavailable", 599, True),
    ("timeout", None, True), ("transport", None, True),
])
def test_second_attempt_budget_threshold_and_boundaries(category, status, retryable):
    attempts = (failed(category="transport", retryable=True),
        failed(2, category=category, status=status, retryable=retryable))
    result = terminal(reason="BUDGET_EXHAUSTED", attempts=attempts)
    assert validate_terminal_llm_stage(v2_request(), result, elapsed_ns=296 * S) is None
    with pytest.raises(TerminalLLMStageError):
        validate_terminal_llm_stage(v2_request(), result, elapsed_ns=296 * S - 1)


@pytest.mark.parametrize("category,status,retryable", [
    ("request_rejected", 409, True), ("rate_limit", 409, True),
    ("timeout", None, False), ("invalid_schema", None, True),
])
def test_permanent_error_hints_never_authorize_retry(category, status, retryable):
    item = failed(category=category, status=status, retryable=retryable)
    result = terminal(attempts=(item,))
    assert validate_terminal_llm_stage(v2_request(), result, elapsed_ns=900 * S) is None
    with pytest.raises(TerminalLLMStageError):
        validate_terminal_llm_stage(v2_request(), replace(result, attempts=(item, failed(2))), elapsed_ns=900 * S)


@pytest.mark.parametrize("mutation", [
    lambda stage: replace(stage, status="success"),
    lambda stage: replace(stage, status="uncertain"),
    lambda stage: replace(stage, status="budget_exhausted"),
    lambda stage: replace(stage, status="unknown"),
    lambda stage: replace(stage, reason="SENSITIVE-UNKNOWN-REASON"),
    lambda stage: replace(stage, condition="C2"),
    lambda stage: replace(stage, attempts=[]),
    lambda stage: replace(stage, attempts=()),
    lambda stage: replace(stage, response=v2_response()),
    lambda stage: replace(stage, attempts=(replace(stage.attempts[0], number=2),)),
    lambda stage: replace(stage, attempts=(replace(stage.attempts[0], request_sha256="f" * 64),)),
    lambda stage: replace(stage, attempts=(replace(stage.attempts[0], response_sha256="f" * 64),)),
    lambda stage: replace(stage, attempts=(replace(stage.attempts[0], side_effect_started=True),)),
    lambda stage: replace(stage, attempts=(replace(stage.attempts[0], error_category="sensitive_unknown_category"),)),
    lambda stage: replace(stage, attempts=(replace(stage.attempts[0], elapsed_ns=181 * S),)),
])
def test_terminal_mutations_are_rejected_without_payload(mutation):
    with pytest.raises(TerminalLLMStageError) as captured:
        validate_terminal_llm_stage(v2_request(), mutation(terminal()), elapsed_ns=900 * S)
    assert str(captured.value) == "invalid terminal LLM stage"


@pytest.mark.parametrize("elapsed", [True, False, -1, 1.0, "1", None])
def test_elapsed_requires_exact_nonnegative_integer(elapsed):
    with pytest.raises(TerminalLLMStageError):
        validate_terminal_llm_stage(v2_request(), terminal(), elapsed_ns=elapsed)


@pytest.mark.parametrize("mutation", [
    lambda request: request.update(provider="ollama"),
    lambda request: request.update(schema_version="llm-client-request/v1"),
    lambda request: request.update(condition="C0"),
    lambda request: request["document"].update(page_count=True),
    lambda request: request["document"].update(byte_count=1.0),
    lambda request: request["document"].update(text_sha256="0" * 64),
])
def test_only_deepseek_closed_v2_requests(mutation):
    request = v2_request()
    mutation(request)
    with pytest.raises(TerminalLLMStageError):
        validate_terminal_llm_stage(request, terminal(), elapsed_ns=S)


@pytest.mark.parametrize("changes", [
    {"status": "classified_error", "reason": "PERMANENT_ERROR"},
    {"status": "uncertain", "reason": "UNCONFIRMED_WALL_OUTCOME"},
    {"status": "budget_exhausted", "reason": "BUDGET_EXHAUSTED"},
    {"reason": "SUCCESS"},
])
def test_success_cannot_be_hidden_as_terminal_failure(changes):
    response = v2_response()
    attempt = AttemptRecord(1, "success", S, canonical_json_sha256(v2_request()), canonical_json_sha256(response))
    result = LLMStageResult("C0", "success", "SUCCESS", (attempt,), response)
    candidate = replace(result, **changes)
    if changes == {"reason": "SUCCESS"}:
        assert validate_terminal_llm_stage(v2_request(), candidate, elapsed_ns=S)
    else:
        with pytest.raises(TerminalLLMStageError):
            validate_terminal_llm_stage(v2_request(), candidate, elapsed_ns=900 * S)


@pytest.mark.parametrize("changes", [
    {"response_sha256": "f" * 64}, {"http_status": 408},
    {"outcome": "uncertain"},
])
def test_uncertain_requires_actual_runner_deadline_shape(changes):
    item = AttemptRecord(1, "deadline_exceeded", 301 * S, canonical_json_sha256(v2_request()))
    result = terminal(status="uncertain", reason="UNCONFIRMED_WALL_OUTCOME", attempts=(replace(item, **changes),))
    with pytest.raises(TerminalLLMStageError):
        validate_terminal_llm_stage(v2_request(), result, elapsed_ns=301 * S)


@pytest.mark.parametrize("elapsed", [0, 299 * S, 300 * S - 1])
def test_zero_attempt_budget_requires_elapsed_evidence(elapsed):
    with pytest.raises(TerminalLLMStageError):
        validate_terminal_llm_stage(v2_request(), terminal(status="budget_exhausted", reason="BUDGET_EXHAUSTED", attempts=()), elapsed_ns=elapsed)


def test_success_binds_response_and_interval_limits():
    response = v2_response()
    attempt = AttemptRecord(1, "success", S, canonical_json_sha256(v2_request()), canonical_json_sha256(response))
    result = LLMStageResult("C0", "success", "SUCCESS", (attempt,), response)
    for elapsed in (S - 1, 300 * S + 1):
        with pytest.raises(TerminalLLMStageError):
            validate_terminal_llm_stage(v2_request(), result, elapsed_ns=elapsed)
    changed = deepcopy(response)
    changed["metadata"]["returned_model"] = "different-model"
    with pytest.raises(TerminalLLMStageError):
        validate_terminal_llm_stage(v2_request(), replace(result, response=changed), elapsed_ns=S)


def test_attempt_history_is_revalidated_after_frozen_bypass():
    item = failed()
    object.__setattr__(item, "number", True)
    with pytest.raises(TerminalLLMStageError):
        validate_terminal_llm_stage(v2_request(), terminal(attempts=(item,)), elapsed_ns=S)


def test_cumulative_attempt_floor_and_backoff_must_fit_interval():
    result = terminal(attempts=(failed(category="transport", retryable=True), failed(2)))
    assert validate_terminal_llm_stage(v2_request(), result, elapsed_ns=4 * S) is None
    with pytest.raises(TerminalLLMStageError):
        validate_terminal_llm_stage(v2_request(), result, elapsed_ns=4 * S - 1)


def test_cumulative_classified_history_cannot_exceed_logical_budget():
    result = terminal(attempts=(failed(category="transport", retryable=True, elapsed_ns=180 * S),
        failed(2, elapsed_ns=119 * S)))
    with pytest.raises(TerminalLLMStageError):
        validate_terminal_llm_stage(v2_request(), result, elapsed_ns=900 * S)


@pytest.mark.parametrize("reason", ["BUDGET_EXHAUSTED", "RETRY_EXHAUSTED"])
def test_success_terminal_cannot_claim_retry_reason_without_response(reason):
    response = v2_response()
    item = AttemptRecord(1, "success", S, canonical_json_sha256(v2_request()), canonical_json_sha256(response))
    result = terminal(reason=reason, attempts=(item,))
    with pytest.raises(TerminalLLMStageError):
        validate_terminal_llm_stage(v2_request(), result, elapsed_ns=900 * S)


def test_retries_exhausted_requires_third_eligible_failure():
    for attempts in ((failed(category="transport", retryable=True),),
                     (failed(category="transport", retryable=True), failed(2))):
        with pytest.raises(TerminalLLMStageError):
            validate_terminal_llm_stage(v2_request(), terminal(reason="RETRY_EXHAUSTED", attempts=attempts), elapsed_ns=300 * S)


def test_budget_status_cannot_follow_permanent_or_third_failure():
    candidates = [terminal(status="budget_exhausted", reason="BUDGET_EXHAUSTED"),
        terminal(status="budget_exhausted", reason="BUDGET_EXHAUSTED", attempts=tuple(
            failed(number, category="transport", retryable=True) for number in (1, 2, 3)))]
    for result in candidates:
        with pytest.raises(TerminalLLMStageError):
            validate_terminal_llm_stage(v2_request(), result, elapsed_ns=300 * S)


def test_uncertainty_predicate_reports_contract_level_uncertain_attempt():
    # The predicate is broader than the validator so a caller must not treat an
    # unvalidated summary as an affirmative indication of quiescence.
    item = AttemptRecord(1, "uncertain", S, canonical_json_sha256(v2_request()))
    assert stage_outcome_uncertain(terminal(attempts=(item,)))
    assert not stage_outcome_uncertain(terminal(status="budget_exhausted", reason="BUDGET_EXHAUSTED", attempts=()))
