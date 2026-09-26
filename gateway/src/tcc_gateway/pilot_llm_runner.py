"""Estágio pré-freeze de proposta LLM, comum a C0/C1 e sem mutações Odoo.

Um timeout do cliente pode deixar a chamada remota em andamento; nesse caso o
resultado é incerto e não há retry. Isto não substitui o supervisor de processo,
o RunRecord completo, o oráculo nem a classificação SCI-03 de missing.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from time import monotonic_ns
from typing import Any, Literal

import httpx

from .attempt_policy import (
    DEEPSEEK_PILOT_POLICY,
    NANOSECONDS,
    AttemptContractError,
    AttemptRecord,
    PilotAttemptPolicy,
    decide_next_attempt,
)
from .llm_adapters import LLMAdapterError
from .llm_client_service import LLMClientServiceError, parse_client_request
from .llm_config import DEEPSEEK_ALLOWED_RETURNED_MODELS, DEEPSEEK_MODEL
from .proposal import ProposalValueError, VendorBillProposal
from .proposal_schema import ProposalSchemaError
from .state import canonical_json_sha256


CLIENT_URL = "http://llm-client-g3c:8080"
_CLIENT_ERROR_CATEGORIES = frozenset({
    "empty_response", "incomplete", "invalid_json", "invalid_json_object",
    "invalid_response_json", "invalid_response_shape", "invalid_schema",
    "model_mismatch", "multiple_or_missing_outputs", "provider_unavailable",
    "rate_limit", "request_not_serializable", "request_rejected",
    "thinking_not_disabled", "timeout", "transport", "truncated",
    "unexpected_tool_call",
})
StageCondition = Literal["C0", "C1"]
StageStatus = Literal["success", "classified_error", "uncertain", "budget_exhausted"]
CallOnce = Callable[[Mapping[str, Any], int], Awaitable[Mapping[str, Any]]]


@dataclass(frozen=True, slots=True)
class LLMStageResult:
    condition: StageCondition
    status: StageStatus
    reason: str
    attempts: tuple[AttemptRecord, ...]
    response: Mapping[str, Any] | None = field(default=None, repr=False)

    def to_sanitised_mapping(self) -> dict[str, object]:
        return {
            "condition": self.condition,
            "status": self.status,
            "reason": self.reason,
            "attempts": [attempt.to_mapping() for attempt in self.attempts],
            "response_sha256": (
                canonical_json_sha256(self.response) if self.response is not None else None
            ),
        }


def _validate_success(value: Mapping[str, Any], scenario_id: str) -> None:
    if not isinstance(value, Mapping):
        raise LLMAdapterError("deepseek", "invalid_client_response")
    if value.get("schema_version") != "llm-client-response/v1" or value.get("status") != "ok":
        raise LLMAdapterError("deepseek", "invalid_client_response")
    proposal_value = value.get("proposal")
    if not isinstance(proposal_value, Mapping):
        raise LLMAdapterError("deepseek", "invalid_client_response")
    try:
        proposal = VendorBillProposal.from_mapping(proposal_value)
    except (ProposalSchemaError, ProposalValueError, TypeError, ValueError):
        raise LLMAdapterError("deepseek", "invalid_client_response") from None
    if proposal.scenario_id != scenario_id:
        raise LLMAdapterError("deepseek", "scenario_mismatch")
    metadata = value.get("metadata")
    if not isinstance(metadata, Mapping):
        raise LLMAdapterError("deepseek", "invalid_client_response")
    if metadata.get("provider") != "deepseek" or metadata.get("requested_model") != DEEPSEEK_MODEL:
        raise LLMAdapterError("deepseek", "model_mismatch")
    returned_model = metadata.get("returned_model")
    if not isinstance(returned_model, str) or returned_model not in DEEPSEEK_ALLOWED_RETURNED_MODELS:
        raise LLMAdapterError("deepseek", "model_mismatch")
    if metadata.get("thinking") != "disabled" or metadata.get("temperature") != 0:
        raise LLMAdapterError("deepseek", "generation_mismatch")


async def call_llm_client_once(
    request_value: Mapping[str, Any],
    wall_cap_ns: int,
    *,
    client_url: str = CLIENT_URL,
    transport: httpx.AsyncBaseTransport | None = None,
) -> Mapping[str, Any]:
    """Uma chamada interna; não recebe a chave nem escreve request/response."""

    if client_url.rstrip("/") != CLIENT_URL:
        raise AttemptContractError("LLM client URL is outside the internal allowlist")
    if type(wall_cap_ns) is not int or wall_cap_ns <= 0:
        raise AttemptContractError("invalid attempt wall cap")
    wall_seconds = wall_cap_ns / NANOSECONDS
    timeout = httpx.Timeout(
        connect=min(10.0, wall_seconds),
        read=min(120.0, wall_seconds),
        write=wall_seconds,
        pool=wall_seconds,
    )
    try:
        async with httpx.AsyncClient(
            base_url=client_url, timeout=timeout, transport=transport, trust_env=False,
        ) as client:
            response = await client.post("/v1/proposals", json=dict(request_value))
    except (httpx.ConnectError, httpx.ConnectTimeout):
        raise LLMAdapterError("deepseek", "transport", retryable=True) from None
    except httpx.RequestError:
        raise LLMAdapterError("deepseek", "client_outcome_uncertain") from None
    try:
        value = response.json()
    except ValueError:
        raise LLMAdapterError("deepseek", "invalid_client_response") from None
    if not isinstance(value, Mapping):
        raise LLMAdapterError("deepseek", "invalid_client_response")
    if response.status_code == 200:
        return value
    error = value.get("error")
    if response.status_code == 502 and isinstance(error, Mapping):
        category = error.get("category")
        retryable = error.get("retryable")
        provider_status = error.get("http_status")
        if (
            isinstance(category, str)
            and category in _CLIENT_ERROR_CATEGORIES
            and type(retryable) is bool
            and (provider_status is None or (type(provider_status) is int and 100 <= provider_status <= 599))
        ):
            raise LLMAdapterError(
                "deepseek", category, retryable=retryable, http_status=provider_status,
            )
    raise LLMAdapterError("deepseek", "invalid_client_response")


async def run_llm_stage(
    request_value: Mapping[str, Any],
    *,
    condition: StageCondition,
    call_once: CallOnce,
    policy: PilotAttemptPolicy = DEEPSEEK_PILOT_POLICY,
    clock_ns: Callable[[], int] = monotonic_ns,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
) -> LLMStageResult:
    """Executa somente a etapa de proposta, com a mesma lógica em C0/C1.

    ``asyncio.wait_for`` limita a espera do runner, não prova o encerramento do
    serviço remoto. Por isso um prazo de parede excedido é terminal e incerto.
    """

    if condition not in {"C0", "C1"}:
        raise AttemptContractError("invalid experimental condition")
    try:
        provider, request = parse_client_request(request_value)
    except LLMClientServiceError:
        raise AttemptContractError("invalid typed LLM client request") from None
    if provider != "deepseek":
        raise AttemptContractError("pilot stage requires the DeepSeek model block")
    request_hash = canonical_json_sha256(request_value)
    started_ns = clock_ns()
    attempts: list[AttemptRecord] = []
    for number in range(1, policy.max_attempts + 1):
        elapsed_total_ns = clock_ns() - started_ns
        if elapsed_total_ns < 0:
            raise AttemptContractError("monotonic clock moved backwards")
        wall_cap_ns = min(policy.wall_deadline_ns, policy.logical_budget_ns - elapsed_total_ns)
        if wall_cap_ns <= 0:
            return LLMStageResult(condition, "budget_exhausted", "BUDGET_EXHAUSTED", tuple(attempts))
        attempt_started_ns = clock_ns()
        try:
            response = await asyncio.wait_for(
                call_once(request_value, wall_cap_ns), timeout=wall_cap_ns / NANOSECONDS,
            )
            _validate_success(response, request.scenario_id)
        except TimeoutError:
            elapsed_ns = max(0, clock_ns() - attempt_started_ns)
            attempts.append(AttemptRecord(number, "deadline_exceeded", elapsed_ns, request_hash))
            return LLMStageResult(condition, "uncertain", "UNCONFIRMED_WALL_OUTCOME", tuple(attempts))
        except LLMAdapterError as error:
            elapsed_ns = max(0, clock_ns() - attempt_started_ns)
            if elapsed_ns > wall_cap_ns:
                attempts.append(AttemptRecord(number, "deadline_exceeded", elapsed_ns, request_hash))
                return LLMStageResult(condition, "uncertain", "UNCONFIRMED_WALL_OUTCOME", tuple(attempts))
            attempt = AttemptRecord.from_adapter_error(
                number=number, elapsed_ns=elapsed_ns,
                request_sha256=request_hash, error=error,
            )
            attempts.append(attempt)
            decision = decide_next_attempt(
                attempt, logical_elapsed_ns=clock_ns() - started_ns, policy=policy,
            )
            if not decision.should_retry:
                return LLMStageResult(condition, "classified_error", decision.reason, tuple(attempts))
            try:
                await asyncio.wait_for(
                    sleep(decision.delay_ns / NANOSECONDS),
                    timeout=(policy.logical_budget_ns - (clock_ns() - started_ns)) / NANOSECONDS,
                )
            except TimeoutError:
                return LLMStageResult(condition, "budget_exhausted", "BUDGET_EXHAUSTED", tuple(attempts))
            continue
        elapsed_ns = max(0, clock_ns() - attempt_started_ns)
        if elapsed_ns > wall_cap_ns:
            attempts.append(AttemptRecord(number, "deadline_exceeded", elapsed_ns, request_hash))
            return LLMStageResult(condition, "uncertain", "UNCONFIRMED_WALL_OUTCOME", tuple(attempts))
        response_hash = canonical_json_sha256(response)
        attempts.append(AttemptRecord(number, "success", elapsed_ns, request_hash, response_hash))
        return LLMStageResult(condition, "success", "SUCCESS", tuple(attempts), response)
    raise AttemptContractError("retry loop exhausted without terminal decision")
