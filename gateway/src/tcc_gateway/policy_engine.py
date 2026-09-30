"""Regras C1-02 sobre um snapshot confiável, sem chamadas externas ou efeitos.

O leitor C1-03 fornece o estado; o executor C1-06 o revalida na transação.
REVIEW exige o verificador C1-07 antes da contabilização. Esta função não lê
labels, token, ambiente, relógio, banco nem saída bruta do modelo.
"""

from __future__ import annotations

from decimal import Context, Decimal, DecimalException, ROUND_HALF_EVEN, localcontext

from .policy_contracts import (
    PolicyContractError,
    PolicyDecision,
    PolicyInput,
    ReasonCode,
)


POLICY_VERSION = "policy-v1.0.0"


def _line_mismatch(policy_input: PolicyInput) -> bool:
    action = policy_input.action
    expected = policy_input.trusted_state.purchase_order.lines
    proposed_fields = tuple((line.item_code, line.quantity, line.unit_price) for line in action.lines)
    expected_fields = tuple((line.item_code, line.quantity, line.unit_price) for line in expected)
    if proposed_fields != expected_fields:
        return True
    if action.executor_mode == "CREATE_DRAFT":
        return any(
            Decimal(proposed.quantity) > Decimal(trusted.quantity_to_invoice)
            for proposed, trusted in zip(action.lines, expected, strict=True)
        )
    # Em POST o rascunho existente pode já ter consumido qty_to_invoice.
    return False


def _target_mismatch(policy_input: PolicyInput) -> bool:
    action = policy_input.action
    if action.executor_mode != "POST_APPROVED":
        return False
    target = policy_input.trusted_state.target_bill
    return (
        target is None
        or target.state != "draft"
        or target.move_id != action.target_move_id
        or target.action.action_hash != action.action_hash
    )


def _business_failures(policy_input: PolicyInput) -> tuple[ReasonCode, ...]:
    action = policy_input.action
    state = policy_input.trusted_state
    po = state.purchase_order
    expected_phase = "DRAFT_INTAKE" if action.executor_mode == "CREATE_DRAFT" else "POST_REVIEW"
    checks = (
        (ReasonCode.PHASE_MISMATCH, state.phase != expected_phase or (
            action.executor_mode == "CREATE_DRAFT" and state.target_bill is not None
        )),
        (ReasonCode.PURCHASE_ORDER_NOT_CONFIRMED, not po.confirmed),
        (ReasonCode.VENDOR_MISMATCH, action.vendor_ref != po.vendor_ref),
        (ReasonCode.PURCHASE_ORDER_MISMATCH, action.purchase_order_ref != po.purchase_order_ref),
        (ReasonCode.CURRENCY_MISMATCH, action.currency != po.currency),
        (ReasonCode.LINE_MISMATCH, _line_mismatch(policy_input)),
        (ReasonCode.AMOUNT_MISMATCH, abs(Decimal(action.amount) - Decimal(po.amount)) > Decimal(state.monetary_tolerance)),
        (ReasonCode.BANK_NOT_ALLOWED, action.recipient_bank_ref not in state.allowed_bank_refs),
        (ReasonCode.DUPLICATE_DOCUMENT, state.duplicate_detected),
        (ReasonCode.TARGET_BILL_MISMATCH, _target_mismatch(policy_input)),
        (ReasonCode.DATE_OUTSIDE_WINDOW, not state.invoice_date_min <= action.invoice_date <= state.invoice_date_max),
        (ReasonCode.ACCOUNTING_PERIOD_CLOSED, not state.accounting_period_open),
    )
    return tuple(code for code, failed in checks if failed)


def evaluate_policy(policy_input: PolicyInput) -> PolicyDecision:
    """Avalia a versão candidata sobre dados tipados, sem reparar a proposta.

Os timestamps e a configuração são fornecidos pelo gateway confiável.
Estrutura/versão inválida gera PolicyContractError saneado antes de qualquer
decisão. O consumidor deve bloquear a execução quando não há decisão válida.
"""
    if type(policy_input) is not PolicyInput:
        raise PolicyContractError("policy evaluation requires a typed input")

    # Limites dos schemas cabem nesta precisão. Não herdar arredondamento ou
    # precisão de outro componente do processo; não alterar o contexto externo.
    with localcontext(Context(prec=32, rounding=ROUND_HALF_EVEN)):
        try:
            validated = PolicyInput.from_mapping(policy_input.to_mapping())
        except PolicyContractError:
            raise
        except (AttributeError, TypeError, ValueError, DecimalException):
            raise PolicyContractError("invalid policy evaluation input") from None

        if validated.action.policy_version != POLICY_VERSION:
            raise PolicyContractError("unsupported policy implementation version")

        dependencies = validated.trusted_state.dependencies
        unavailable = tuple(code for status, code in (
            (dependencies.state, ReasonCode.DEPENDENCY_UNAVAILABLE),
            (dependencies.policy, ReasonCode.POLICY_UNAVAILABLE),
            (dependencies.audit, ReasonCode.AUDIT_UNAVAILABLE),
        ) if status == "UNAVAILABLE")
        if unavailable:
            return PolicyDecision.for_input(
                validated, decision="DENY", reason_codes=unavailable,
                deny_class="FAIL_CLOSED_UNAVAILABILITY",
            )

        failures = _business_failures(validated)
        if failures:
            return PolicyDecision.for_input(
                validated, decision="DENY", reason_codes=failures, deny_class="POLICY_RULE",
            )

        if validated.action.executor_mode == "POST_APPROVED":
            return PolicyDecision.for_input(
                validated, decision="REVIEW",
                reason_codes=(ReasonCode.CRITICAL_ACTION_REQUIRES_APPROVAL,),
            )
        return PolicyDecision.for_input(
            validated, decision="ALLOW", reason_codes=(ReasonCode.DRAFT_CONSISTENT,),
        )
