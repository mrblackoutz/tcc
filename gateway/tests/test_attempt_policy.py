from __future__ import annotations

from dataclasses import replace

import pytest

from tcc_gateway.attempt_policy import (
    NANOSECONDS,
    AttemptContractError,
    AttemptRecord,
    PilotAttemptPolicy,
    decide_next_attempt,
)
from tcc_gateway.llm_adapters import LLMAdapterError
from tcc_gateway.state import canonical_json_bytes


REQUEST_HASH = "a" * 64
RESPONSE_HASH = "b" * 64


def failed(
    category: str = "timeout", *, status: int | None = None,
    number: int = 1, retryable: bool = True, side_effect_started: bool = False,
) -> AttemptRecord:
    error = LLMAdapterError("deepseek", category, retryable=retryable, http_status=status)
    return AttemptRecord.from_adapter_error(
        number=number, elapsed_ns=3 * NANOSECONDS,
        request_sha256=REQUEST_HASH, error=error,
        side_effect_started=side_effect_started,
    )


def test_approved_policy_is_exact_and_immutable() -> None:
    policy = PilotAttemptPolicy()
    assert policy.connect_timeout_ns == 10 * NANOSECONDS
    assert policy.read_inactivity_timeout_ns == 120 * NANOSECONDS
    assert policy.wall_deadline_ns == 180 * NANOSECONDS
    assert policy.logical_budget_ns == 300 * NANOSECONDS
    assert policy.retry_delays_ns == (2 * NANOSECONDS, 4 * NANOSECONDS)
    assert policy.max_attempts == 3
    with pytest.raises(AttemptContractError, match="DEC-029"):
        replace(policy, connect_timeout_ns=5 * NANOSECONDS)
    with pytest.raises(AttemptContractError, match="DEC-029"):
        replace(policy, retry_delays_ns=(1 * NANOSECONDS, 4 * NANOSECONDS))


@pytest.mark.parametrize(
    ("category", "status"),
    [
        ("timeout", None), ("transport", None),
        ("provider_unavailable", 408), ("rate_limit", 429),
        ("provider_unavailable", 500), ("provider_unavailable", 503),
    ],
)
def test_only_approved_transient_errors_schedule_retry(category: str, status: int | None) -> None:
    decision = decide_next_attempt(failed(category, status=status), logical_elapsed_ns=3 * NANOSECONDS)
    assert decision.should_retry is True
    assert decision.reason == "RETRY_SCHEDULED"
    assert decision.delay_ns == 2 * NANOSECONDS
    assert decision.next_wall_cap_ns == 180 * NANOSECONDS


@pytest.mark.parametrize(
    ("category", "status"),
    [
        ("request_rejected", 409), ("provider_unavailable", 409),
        ("request_rejected", 400), ("rate_limit", 400),
        ("model_mismatch", None), ("invalid_schema", None),
        ("truncated", None), ("provider_unavailable", None),
        ("transport", 503),
    ],
)
def test_permanent_or_incoherent_errors_do_not_retry(category: str, status: int | None) -> None:
    decision = decide_next_attempt(failed(category, status=status), logical_elapsed_ns=3 * NANOSECONDS)
    assert decision.reason == "PERMANENT_ERROR"
    assert not decision.should_retry


def test_adapter_hint_is_necessary_but_not_sufficient() -> None:
    assert decide_next_attempt(
        failed("timeout", retryable=False), logical_elapsed_ns=3 * NANOSECONDS,
    ).reason == "PERMANENT_ERROR"
    assert decide_next_attempt(
        failed("model_mismatch", retryable=True), logical_elapsed_ns=3 * NANOSECONDS,
    ).reason == "PERMANENT_ERROR"


def test_second_delay_third_attempt_limit_and_total_budget() -> None:
    second = decide_next_attempt(failed(number=2), logical_elapsed_ns=5 * NANOSECONDS)
    assert second.delay_ns == 4 * NANOSECONDS
    assert second.next_wall_cap_ns == 180 * NANOSECONDS
    assert decide_next_attempt(
        failed(number=3), logical_elapsed_ns=20 * NANOSECONDS,
    ).reason == "RETRY_EXHAUSTED"
    shortened = decide_next_attempt(
        failed(number=2), logical_elapsed_ns=280 * NANOSECONDS,
    )
    assert shortened.should_retry
    assert shortened.next_wall_cap_ns == 16 * NANOSECONDS
    assert decide_next_attempt(
        failed(number=2), logical_elapsed_ns=296 * NANOSECONDS,
    ).reason == "BUDGET_EXHAUSTED"


def test_success_uncertain_deadline_and_side_effect_stop() -> None:
    success = AttemptRecord(1, "success", NANOSECONDS, REQUEST_HASH, RESPONSE_HASH)
    assert decide_next_attempt(success, logical_elapsed_ns=NANOSECONDS).reason == "SUCCESS"
    for outcome in ("uncertain", "deadline_exceeded"):
        record = AttemptRecord(1, outcome, NANOSECONDS, REQUEST_HASH)
        assert decide_next_attempt(record, logical_elapsed_ns=NANOSECONDS).reason == "UNCONFIRMED_WALL_OUTCOME"
    assert decide_next_attempt(
        failed(side_effect_started=True), logical_elapsed_ns=3 * NANOSECONDS,
    ).reason == "SIDE_EFFECT_STARTED"


def test_attempt_record_is_sanitised_and_canonicalisable() -> None:
    record = failed("rate_limit", status=429)
    encoded = canonical_json_bytes(record.to_mapping())
    assert b"rate_limit" in encoded
    assert b"Authorization" not in encoded
    assert b"Bearer" not in encoded
    assert b"prompt" not in encoded


def test_malformed_attempts_fail_contract_without_missing_classification() -> None:
    with pytest.raises(AttemptContractError, match="request hash"):
        replace(failed(), request_sha256="not-a-hash")
    with pytest.raises(AttemptContractError, match="category"):
        replace(failed(), error_category="Bearer sensitive-value")
    with pytest.raises(AttemptContractError, match="boolean"):
        replace(failed(), retryable_hint="true")
    with pytest.raises(AttemptContractError, match="response hash"):
        AttemptRecord(1, "success", NANOSECONDS, REQUEST_HASH)
    with pytest.raises(AttemptContractError, match="logical elapsed"):
        decide_next_attempt(failed(), logical_elapsed_ns=1)
