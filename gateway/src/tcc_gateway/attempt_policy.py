"""Nucleo pre-freeze de tentativas do estágio LLM, sem I/O nem retries automáticos.

O futuro runner mede tempos monotônicos, impõe prazos por processo e chama
``decide_next_attempt``. Este módulo não impõe deadline de parede: não deve ser
usado isoladamente para declarar RUN-02/RUN-06 concluídos.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

from .llm_adapters import LLMAdapterError


class AttemptContractError(ValueError):
    """Metadados de tentativa incoerentes; não transformar em missing."""


NANOSECONDS = 1_000_000_000
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_CATEGORY = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
AttemptOutcome = Literal["success", "classified_error", "deadline_exceeded", "uncertain"]
RetryReason = Literal[
    "SUCCESS", "PERMANENT_ERROR", "RETRY_EXHAUSTED", "BUDGET_EXHAUSTED",
    "RETRY_SCHEDULED", "UNCONFIRMED_WALL_OUTCOME", "SIDE_EFFECT_STARTED",
]


@dataclass(frozen=True, slots=True)
class PilotAttemptPolicy:
    """Parâmetros aprovados em DEC-029; inteiros evitam drift por arredondamento."""

    connect_timeout_ns: int = 10 * NANOSECONDS
    read_inactivity_timeout_ns: int = 120 * NANOSECONDS
    wall_deadline_ns: int = 180 * NANOSECONDS
    logical_budget_ns: int = 300 * NANOSECONDS
    retry_delays_ns: tuple[int, int] = (2 * NANOSECONDS, 4 * NANOSECONDS)

    def __post_init__(self) -> None:
        expected = (10, 120, 180, 300)
        observed = (
            self.connect_timeout_ns, self.read_inactivity_timeout_ns,
            self.wall_deadline_ns, self.logical_budget_ns,
        )
        if any(type(value) is not int or value <= 0 for value in observed):
            raise AttemptContractError("timeouts and budget must be positive integer nanoseconds")
        if observed != tuple(seconds * NANOSECONDS for seconds in expected):
            raise AttemptContractError("pilot timeouts differ from DEC-029")
        if self.retry_delays_ns != (2 * NANOSECONDS, 4 * NANOSECONDS):
            raise AttemptContractError("pilot retry delays differ from DEC-029")

    @property
    def max_attempts(self) -> int:
        return len(self.retry_delays_ns) + 1


DEEPSEEK_PILOT_POLICY = PilotAttemptPolicy()


@dataclass(frozen=True, slots=True)
class AttemptRecord:
    """Resumo sem payload de uma tentativa; não é o RunRecord científico final."""

    number: int
    outcome: AttemptOutcome
    elapsed_ns: int
    request_sha256: str
    response_sha256: str | None = None
    error_category: str | None = None
    http_status: int | None = None
    retryable_hint: bool = False
    side_effect_started: bool = False

    def __post_init__(self) -> None:
        if type(self.number) is not int or not 1 <= self.number <= 3:
            raise AttemptContractError("attempt number must be 1, 2 or 3")
        if self.outcome not in {"success", "classified_error", "deadline_exceeded", "uncertain"}:
            raise AttemptContractError("invalid attempt outcome")
        if type(self.elapsed_ns) is not int or self.elapsed_ns < 0:
            raise AttemptContractError("elapsed time must be nonnegative integer nanoseconds")
        if not isinstance(self.request_sha256, str) or not _SHA256.fullmatch(self.request_sha256):
            raise AttemptContractError("invalid request hash")
        if self.response_sha256 is not None and (
            not isinstance(self.response_sha256, str)
            or not _SHA256.fullmatch(self.response_sha256)
        ):
            raise AttemptContractError("invalid response hash")
        if self.error_category is not None and (
            not isinstance(self.error_category, str)
            or not _CATEGORY.fullmatch(self.error_category)
        ):
            raise AttemptContractError("invalid error category")
        if self.http_status is not None and (
            type(self.http_status) is not int or not 100 <= self.http_status <= 599
        ):
            raise AttemptContractError("invalid HTTP status")
        if type(self.retryable_hint) is not bool or type(self.side_effect_started) is not bool:
            raise AttemptContractError("attempt flags must be boolean")
        if self.outcome == "success":
            if self.response_sha256 is None or self.error_category is not None or self.http_status is not None:
                raise AttemptContractError("successful attempt requires response hash and no error")
        elif self.outcome == "classified_error":
            if self.error_category is None:
                raise AttemptContractError("classified error requires a category")
        elif self.error_category is not None or self.retryable_hint:
            raise AttemptContractError("uncertain/deadline outcome cannot claim a classified retryable error")

    def to_mapping(self) -> dict[str, object]:
        return {
            "number": self.number,
            "outcome": self.outcome,
            "elapsed_ns": self.elapsed_ns,
            "request_sha256": self.request_sha256,
            "response_sha256": self.response_sha256,
            "error_category": self.error_category,
            "http_status": self.http_status,
            "retryable_hint": self.retryable_hint,
            "side_effect_started": self.side_effect_started,
        }

    @classmethod
    def from_adapter_error(
        cls, *, number: int, elapsed_ns: int, request_sha256: str,
        error: LLMAdapterError, side_effect_started: bool = False,
    ) -> AttemptRecord:
        return cls(
            number=number,
            outcome="classified_error",
            elapsed_ns=elapsed_ns,
            request_sha256=request_sha256,
            error_category=error.category,
            http_status=error.http_status,
            retryable_hint=error.retryable,
            side_effect_started=side_effect_started,
        )


@dataclass(frozen=True, slots=True)
class RetryDecision:
    reason: RetryReason
    delay_ns: int = 0
    next_wall_cap_ns: int = 0

    @property
    def should_retry(self) -> bool:
        return self.reason == "RETRY_SCHEDULED"


def _eligible_transport_failure(attempt: AttemptRecord) -> bool:
    if attempt.outcome != "classified_error" or not attempt.retryable_hint:
        return False
    if attempt.error_category in {"timeout", "transport"}:
        return attempt.http_status is None
    if attempt.error_category == "rate_limit":
        return attempt.http_status == 429
    if attempt.error_category == "provider_unavailable":
        status = attempt.http_status
        return status == 408 or (status is not None and 500 <= status <= 599)
    return False


def decide_next_attempt(
    attempt: AttemptRecord,
    *,
    logical_elapsed_ns: int,
    policy: PilotAttemptPolicy = DEEPSEEK_PILOT_POLICY,
) -> RetryDecision:
    """Decide sem executar. O próximo processo deve impor ``next_wall_cap_ns``."""

    if type(logical_elapsed_ns) is not int or logical_elapsed_ns < attempt.elapsed_ns:
        raise AttemptContractError("logical elapsed time is inconsistent with attempt")
    if attempt.number > policy.max_attempts:
        raise AttemptContractError("attempt number exceeds policy")
    if attempt.outcome == "success":
        return RetryDecision("SUCCESS")
    if attempt.side_effect_started:
        return RetryDecision("SIDE_EFFECT_STARTED")
    if attempt.outcome in {"deadline_exceeded", "uncertain"}:
        return RetryDecision("UNCONFIRMED_WALL_OUTCOME")
    if not _eligible_transport_failure(attempt):
        return RetryDecision("PERMANENT_ERROR")
    if attempt.number == policy.max_attempts:
        return RetryDecision("RETRY_EXHAUSTED")
    delay_ns = policy.retry_delays_ns[attempt.number - 1]
    remaining_ns = policy.logical_budget_ns - logical_elapsed_ns - delay_ns
    if remaining_ns <= 0:
        return RetryDecision("BUDGET_EXHAUSTED")
    return RetryDecision(
        "RETRY_SCHEDULED",
        delay_ns=delay_ns,
        next_wall_cap_ns=min(policy.wall_deadline_ns, remaining_ns),
    )
