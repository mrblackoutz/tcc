"""Ponte pré-freeze do estágio LLM para C0, política C1 e proposta do oráculo.

Não é um runner experimental completo. C0 pode despachar uma operação; C1
prepara política e, quando ALLOW, comando CREATE para consumidores privados. Nenhum resultado
desta ponte comprova efeito, aprovação, reset ou captura de estado de §14.5.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Literal

from .action_proposal_v2 import ActionProposalV2, revalidate_action_proposal_v2
from .attempt_policy import DEEPSEEK_PILOT_POLICY, AttemptRecord, decide_next_attempt
from .c0_action_executor_v2 import C0ActionDispatch, TrustedC0ActionBinding, execute_c0_action_v2
from .c0_executor import OdooCaller
from .llm_adapters import LLMMessage, LLMProposalRequest
from .idempotency import idempotency_key_for_resolved
from .llm_client_service import (
    REQUEST_SCHEMA_VERSION_V2, parse_client_request_v2, validate_v2_client_response,
)
from .oracle import OracleProposal
from .pdf_ingestion import ExtractedPdf
from .pilot_llm_runner import LLMStageResult
from .policy_contracts import CapabilityCommand, PolicyDecision, PolicyInput
from .policy_engine import evaluate_policy
from .state import canonical_json_sha256
from .trusted_resolution import ResolvedTrustedState, prepare_policy_input


class RunnerContractError(ValueError):
    """Handoff inválido: não despachar nem inferir missing ou resultado financeiro."""


def build_client_request_v2(
    request: LLMProposalRequest, *, provider: Literal["deepseek", "ollama"],
) -> dict[str, Any]:
    """Serializa só a entrada comum; condição, rótulos e autorização ficam fora.

    O hash documental é metadata do extrator confiável, não uma leitura de bytes
    feita aqui. A custódia/validação do PDF continua obrigatória antes desta ponte.
    """
    try:
        if (type(request) is not LLMProposalRequest or type(request.document) is not ExtractedPdf
                or type(request.messages) is not tuple
                or any(type(message) is not LLMMessage for message in request.messages)):
            raise ValueError("typed request required")
        request.__post_init__()
        document = request.document
        value = {
            "schema_version": REQUEST_SCHEMA_VERSION_V2,
            "output_contract": "v2",
            "provider": provider,
            "scenario_id": request.scenario_id,
            "document": {
                "text": document.text,
                "document_sha256": document.document_sha256,
                "text_sha256": document.text_sha256,
                "page_count": document.page_count,
                "byte_count": document.byte_count,
            },
            "messages": [{"role": message.role, "content": message.content} for message in request.messages],
        }
        parse_client_request_v2(value)
        return value
    except (AttributeError, TypeError, ValueError):
        raise RunnerContractError("invalid common v2 client request") from None


def proposal_from_llm_stage_v2(
    request_value: Mapping[str, Any], stage: LLMStageResult,
) -> ActionProposalV2:
    """Vincula a resposta à entrada e ao resumo efetivo do estágio bem-sucedido.

    Hashes detectam mistura/mutação de registros, não autenticam o produtor.
    Recusa, timeout ou erro não são convertidos em proposta ou efeito vazio.
    """
    try:
        provider, _request = parse_client_request_v2(request_value)
        if (provider != "deepseek" or type(stage) is not LLMStageResult
                or stage.condition not in {"C0", "C1"} or stage.status != "success"
                or stage.reason != "SUCCESS" or stage.response is None
                or type(stage.attempts) is not tuple or not 1 <= len(stage.attempts) <= 3):
            raise ValueError("successful DeepSeek v2 stage required")
        request_hash = canonical_json_sha256(request_value)
        response_hash = canonical_json_sha256(stage.response)
        # Only a lower bound is reconstructible from summaries. Real monotonic
        # timing and process termination still require the future supervisor.
        elapsed_floor_ns = 0
        for number, attempt in enumerate(stage.attempts, start=1):
            if type(attempt) is not AttemptRecord:
                raise ValueError("typed attempt required")
            validated = AttemptRecord(**attempt.to_mapping())
            if (validated.number != number or validated.request_sha256 != request_hash
                    or validated.side_effect_started):
                raise ValueError("attempt binding differs")
            elapsed_floor_ns += validated.elapsed_ns
            if (validated.elapsed_ns > DEEPSEEK_PILOT_POLICY.wall_deadline_ns
                    or elapsed_floor_ns > DEEPSEEK_PILOT_POLICY.logical_budget_ns):
                raise ValueError("attempt history exceeds approved budget")
            if number == len(stage.attempts):
                if (validated.outcome != "success" or validated.response_sha256 != response_hash
                        or validated.retryable_hint):
                    raise ValueError("response differs from successful attempt")
            else:
                if validated.response_sha256 is not None:
                    raise ValueError("failed attempt cannot claim a validated response")
                retry = decide_next_attempt(validated, logical_elapsed_ns=elapsed_floor_ns)
                if not retry.should_retry:
                    raise ValueError("nonterminal attempt was not eligible for retry")
                elapsed_floor_ns += retry.delay_ns
        return revalidate_action_proposal_v2(validate_v2_client_response(request_value, stage.response))
    except (AttributeError, TypeError, ValueError):
        raise RunnerContractError("invalid v2 LLM stage handoff") from None


def dispatch_c0_llm_stage_v2(
    client: OdooCaller, request_value: Mapping[str, Any], stage: LLMStageResult,
    *, binding: TrustedC0ActionBinding,
) -> C0ActionDispatch:
    """Despacha C0; o chamador ainda deve observar o efeito independentemente."""
    proposal = proposal_from_llm_stage_v2(request_value, stage)
    if stage.condition != "C0":
        raise RunnerContractError("C0 consumer requires a C0 stage")
    return execute_c0_action_v2(client, proposal, binding=binding)


def prepare_c1_llm_stage_v2(
    request_value: Mapping[str, Any], stage: LLMStageResult,
    *, resolved: ResolvedTrustedState, policy_version: str, evaluated_at: str, expires_at: str,
) -> PolicyInput:
    """Só prepara política C1, sem defaults operacionais, aprovação ou execução."""
    proposal = proposal_from_llm_stage_v2(request_value, stage)
    if stage.condition != "C1":
        raise RunnerContractError("C1 consumer requires a C1 stage")
    return prepare_policy_input(
        proposal, resolved, policy_version=policy_version,
        evaluated_at=evaluated_at, expires_at=expires_at,
    )


def oracle_proposal_from_llm_stage_v2(
    request_value: Mapping[str, Any], stage: LLMStageResult, *, target_move_id: int | None = None,
) -> OracleProposal:
    """Converte apenas intenção validada; não cria OracleTrace/OracleState."""
    return OracleProposal.from_action_proposal_v2(
        proposal_from_llm_stage_v2(request_value, stage), target_move_id=target_move_id,
    )


@dataclass(frozen=True, slots=True)
class C1DraftPreparation:
    """Resultado transitório, não recibo de efeito nem autorização de POST."""

    policy_input: PolicyInput
    decision: PolicyDecision
    command: CapabilityCommand | None


def prepare_c1_draft_command_v2(
    request_value: Mapping[str, Any], stage: LLMStageResult,
    *, resolved: ResolvedTrustedState, policy_version: str, evaluated_at: str, expires_at: str,
) -> C1DraftPreparation:
    """Avalia regras existentes; só ALLOW de CREATE produz comando sem aprovação.

    O chamador fornece observações operacionais reais no estado resolvido. Esta
    função não as coleta, não supõe disponibilidade e não despacha efeitos.
    DENY/REVIEW mantêm intenção e motivos, sem converter POST em CREATE. O
    consumidor privado deve repetir validações sob lock e observar após commit.
    """
    policy_input = prepare_c1_llm_stage_v2(
        request_value, stage, resolved=resolved, policy_version=policy_version,
        evaluated_at=evaluated_at, expires_at=expires_at,
    )
    decision = evaluate_policy(policy_input)
    decision.validate_binding(policy_input)
    command = None
    if decision.decision == "ALLOW":
        if (policy_input.action.executor_mode != "CREATE_DRAFT"
                or policy_input.action.action != "CREATE_DRAFT_BILL"):
            raise RunnerContractError("ALLOW cannot authorize a non-CREATE draft handoff")
        command = CapabilityCommand(
            policy_input.action, decision, idempotency_key_for_resolved(resolved),
        )
        command.validate_binding(policy_input)
    return C1DraftPreparation(policy_input, decision, command)
