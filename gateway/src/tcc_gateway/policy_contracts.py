"""Contratos C1-01, sem I/O, execução, resolução Odoo ou verificação de assinatura.

Somente o coletor confiável pode fornecer TrustedPolicyState. Estes tipos
verificam estrutura e vínculos; hashes não comprovam a origem do snapshot.
"""

from __future__ import annotations

import json
import unicodedata
from collections.abc import Mapping
from copy import deepcopy
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP
from enum import Enum
from functools import lru_cache
from importlib.resources import files
from types import MappingProxyType
from typing import Any, Literal

from jsonschema import Draft202012Validator, FormatChecker

from .action_proposal_v2 import ACTION_PROPOSAL_SCHEMA_VERSION
from .state import canonical_json_bytes, canonical_json_sha256


POLICY_INPUT_VERSION = "policy-input/v1"
POLICY_DECISION_VERSION = "policy-decision/v1"
CAPABILITY_COMMAND_VERSION = "capability-command/v1"
Decision = Literal["ALLOW", "REVIEW", "DENY"]
DenyClass = Literal["POLICY_RULE", "FAIL_CLOSED_UNAVAILABILITY"]
_CONTRACT_DEFS = {
    POLICY_INPUT_VERSION: "policyInput",
    POLICY_DECISION_VERSION: "policyDecision",
    CAPABILITY_COMMAND_VERSION: "capabilityCommand",
}


class PolicyContractError(ValueError):
    """Erro classificado sem ecoar campo ou valor externo, inclusive assinatura."""


class ReasonCode(str, Enum):
    SCHEMA_INVALID = "SCHEMA_INVALID"
    ACTION_NOT_ALLOWED = "ACTION_NOT_ALLOWED"
    PHASE_MISMATCH = "PHASE_MISMATCH"
    VENDOR_MISMATCH = "VENDOR_MISMATCH"
    PURCHASE_ORDER_MISMATCH = "PURCHASE_ORDER_MISMATCH"
    PURCHASE_ORDER_NOT_CONFIRMED = "PURCHASE_ORDER_NOT_CONFIRMED"
    CURRENCY_MISMATCH = "CURRENCY_MISMATCH"
    AMOUNT_MISMATCH = "AMOUNT_MISMATCH"
    LINE_MISMATCH = "LINE_MISMATCH"
    TARGET_BILL_MISMATCH = "TARGET_BILL_MISMATCH"
    BANK_NOT_ALLOWED = "BANK_NOT_ALLOWED"
    FORBIDDEN_MUTATION = "FORBIDDEN_MUTATION"
    DUPLICATE_DOCUMENT = "DUPLICATE_DOCUMENT"
    IDEMPOTENCY_CONFLICT = "IDEMPOTENCY_CONFLICT"
    DRAFT_CONSISTENT = "DRAFT_CONSISTENT"
    CRITICAL_ACTION_REQUIRES_APPROVAL = "CRITICAL_ACTION_REQUIRES_APPROVAL"
    APPROVAL_INVALID = "APPROVAL_INVALID"
    APPROVAL_EXPIRED = "APPROVAL_EXPIRED"
    APPROVAL_REPLAY = "APPROVAL_REPLAY"
    APPROVAL_HASH_MISMATCH = "APPROVAL_HASH_MISMATCH"
    APPROVAL_SCENARIO_MISMATCH = "APPROVAL_SCENARIO_MISMATCH"
    DEPENDENCY_UNAVAILABLE = "DEPENDENCY_UNAVAILABLE"
    POLICY_UNAVAILABLE = "POLICY_UNAVAILABLE"
    AUDIT_UNAVAILABLE = "AUDIT_UNAVAILABLE"
    DATE_OUTSIDE_WINDOW = "DATE_OUTSIDE_WINDOW"
    ACCOUNTING_PERIOD_CLOSED = "ACCOUNTING_PERIOD_CLOSED"


REASON_RULES: Mapping[ReasonCode, str] = MappingProxyType({
    code: rule for rule, codes in {
        "C04": (ReasonCode.SCHEMA_INVALID,),
        "R-POL-01": (ReasonCode.ACTION_NOT_ALLOWED, ReasonCode.PHASE_MISMATCH),
        "R-POL-02": (
            ReasonCode.VENDOR_MISMATCH, ReasonCode.PURCHASE_ORDER_MISMATCH,
            ReasonCode.PURCHASE_ORDER_NOT_CONFIRMED, ReasonCode.CURRENCY_MISMATCH,
            ReasonCode.AMOUNT_MISMATCH, ReasonCode.LINE_MISMATCH,
            ReasonCode.TARGET_BILL_MISMATCH,
        ),
        "R-POL-03": (ReasonCode.BANK_NOT_ALLOWED,),
        "R-POL-04": (ReasonCode.FORBIDDEN_MUTATION,),
        "R-POL-05": (ReasonCode.DUPLICATE_DOCUMENT, ReasonCode.IDEMPOTENCY_CONFLICT),
        "R-POL-06": (ReasonCode.DRAFT_CONSISTENT,),
        "R-POL-07": (ReasonCode.CRITICAL_ACTION_REQUIRES_APPROVAL,),
        "R-POL-09": (
            ReasonCode.APPROVAL_INVALID, ReasonCode.APPROVAL_EXPIRED,
            ReasonCode.APPROVAL_REPLAY, ReasonCode.APPROVAL_HASH_MISMATCH,
            ReasonCode.APPROVAL_SCENARIO_MISMATCH,
        ),
        "R-POL-10": (
            ReasonCode.DEPENDENCY_UNAVAILABLE, ReasonCode.POLICY_UNAVAILABLE,
            ReasonCode.AUDIT_UNAVAILABLE,
        ),
        "R-POL-11": (ReasonCode.DATE_OUTSIDE_WINDOW, ReasonCode.ACCOUNTING_PERIOD_CLOSED),
    }.items() for code in codes
})
_UNAVAILABLE = frozenset(code for code, rule in REASON_RULES.items() if rule == "R-POL-10")
_SUCCESS = frozenset({ReasonCode.DRAFT_CONSISTENT, ReasonCode.CRITICAL_ACTION_REQUIRES_APPROVAL})


@lru_cache(maxsize=1)
def _definitions() -> dict[str, Any]:
    resource = files("tcc_gateway.schemas").joinpath("policy_contracts_v1.schema.json")
    return json.loads(resource.read_text(encoding="utf-8"))["$defs"]


def contract_schema(version: str) -> dict[str, Any]:
    """Schema autossuficiente, sem resolução de referências pela rede."""
    if version not in _CONTRACT_DEFS:
        raise PolicyContractError("unsupported policy contract version")
    return deepcopy(_schema(_CONTRACT_DEFS[version]))


def _schema(definition: str) -> dict[str, Any]:
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$ref": f"#/$defs/{definition}", "$defs": _definitions(),
    }


@lru_cache(maxsize=16)
def _validator(definition: str) -> Draft202012Validator:
    schema = _schema(definition)
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema, format_checker=FormatChecker())


def _validate_text(value: Any) -> None:
    if isinstance(value, str):
        if value.strip() != value or unicodedata.normalize("NFC", value) != value:
            raise PolicyContractError("noncanonical contract text")
        if any(unicodedata.category(char) in {"Cc", "Cf", "Cs"} for char in value):
            raise PolicyContractError("forbidden contract text formatting")
    elif isinstance(value, Mapping):
        for item in value.values():
            _validate_text(item)
    elif isinstance(value, (list, tuple)):
        for item in value:
            _validate_text(item)


def _validate(definition: str, value: Mapping[str, Any]) -> None:
    if not isinstance(value, Mapping):
        raise PolicyContractError("policy contract must be an object")
    if next(_validator(definition).iter_errors(value), None) is not None:
        raise PolicyContractError("policy contract schema invalid")
    _validate_text(value)


def _time(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _lifetime(start: str, end: str) -> None:
    if _time(end) <= _time(start):
        raise PolicyContractError("invalid contract lifetime")


def _typed_tuple(value: Any, expected: type) -> None:
    if type(value) is not tuple or any(not isinstance(item, expected) for item in value):
        raise PolicyContractError("contract collection must be a typed tuple")


def _line_order(lines: tuple[Any, ...]) -> None:
    codes = [line.item_code for line in lines]
    if codes != sorted(codes) or len(codes) != len(set(codes)):
        raise PolicyContractError("line codes must be unique and sorted")


@dataclass(frozen=True, slots=True)
class CanonicalLine:
    item_code: str
    quantity: str
    unit_price: str

    def __post_init__(self) -> None:
        _validate("canonicalLine", self.to_mapping())
        if Decimal(self.quantity) <= 0 or Decimal(self.unit_price) <= 0:
            raise PolicyContractError("canonical line must be positive")

    def to_mapping(self) -> dict[str, str]:
        return {"item_code": self.item_code, "quantity": self.quantity, "unit_price": self.unit_price}

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> CanonicalLine:
        _validate("canonicalLine", value)
        return cls(**value)


@dataclass(frozen=True, slots=True)
class CanonicalAction:
    policy_version: str
    action: Literal["CREATE_DRAFT_BILL", "POST_VENDOR_BILL"]
    executor_mode: Literal["CREATE_DRAFT", "POST_APPROVED"]
    scenario_id: str
    document_sha256: str
    vendor_ref: str
    purchase_order_ref: str
    document_ref: str
    invoice_date: str
    currency: str
    amount: str
    recipient_bank_ref: str
    lines: tuple[CanonicalLine, ...]
    target_move_id: int | None = None
    canonicalization_version: str = "canon/v1"
    action_schema_version: str = ACTION_PROPOSAL_SCHEMA_VERSION

    def __post_init__(self) -> None:
        _typed_tuple(self.lines, CanonicalLine)
        _validate("canonicalAction", self.to_mapping())
        if self.target_move_id is not None and type(self.target_move_id) is not int:
            raise PolicyContractError("target move must be a strict integer")
        _line_order(self.lines)
        total = sum((
            (Decimal(line.quantity) * Decimal(line.unit_price)).quantize(
                Decimal("0.01"), rounding=ROUND_HALF_UP
            ) for line in self.lines
        ), Decimal("0.00"))
        if Decimal(self.amount) <= 0 or Decimal(self.amount) != total:
            raise PolicyContractError("canonical amount does not reconcile")

    def to_mapping(self) -> dict[str, Any]:
        value = {
            "canonicalization_version": self.canonicalization_version,
            "action_schema_version": self.action_schema_version,
            "policy_version": self.policy_version, "action": self.action,
            "executor_mode": self.executor_mode, "scenario_id": self.scenario_id,
            "document_sha256": self.document_sha256, "vendor_ref": self.vendor_ref,
            "purchase_order_ref": self.purchase_order_ref, "document_ref": self.document_ref,
            "invoice_date": self.invoice_date, "currency": self.currency,
            "amount": self.amount, "recipient_bank_ref": self.recipient_bank_ref,
            "lines": [line.to_mapping() for line in self.lines],
        }
        if self.target_move_id is not None:
            value["target_move_id"] = self.target_move_id
        return value

    @property
    def canonical_bytes(self) -> bytes:
        return canonical_json_bytes(self.to_mapping())

    @property
    def action_hash(self) -> str:
        return "sha256:" + canonical_json_sha256(self.to_mapping())

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> CanonicalAction:
        _validate("canonicalAction", value)
        fields = dict(value)
        fields["lines"] = tuple(CanonicalLine.from_mapping(item) for item in value["lines"])
        return cls(**fields)


@dataclass(frozen=True, slots=True)
class TrustedPurchaseLine:
    item_code: str
    quantity: str
    unit_price: str
    quantity_to_invoice: str

    def __post_init__(self) -> None:
        _validate("purchaseLine", self.to_mapping())
        CanonicalLine(self.item_code, self.quantity, self.unit_price)

    def to_mapping(self) -> dict[str, str]:
        return {
            "item_code": self.item_code, "quantity": self.quantity,
            "unit_price": self.unit_price, "quantity_to_invoice": self.quantity_to_invoice,
        }

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> TrustedPurchaseLine:
        _validate("purchaseLine", value)
        return cls(**value)


@dataclass(frozen=True, slots=True)
class TrustedPurchaseOrder:
    purchase_order_ref: str
    vendor_ref: str
    currency: str
    confirmed: bool
    amount: str
    lines: tuple[TrustedPurchaseLine, ...]

    def __post_init__(self) -> None:
        _typed_tuple(self.lines, TrustedPurchaseLine)
        _validate("purchaseOrder", self.to_mapping())
        _line_order(self.lines)
        if Decimal(self.amount) <= 0:
            raise PolicyContractError("trusted PO amount must be positive")

    def to_mapping(self) -> dict[str, Any]:
        return {
            "purchase_order_ref": self.purchase_order_ref, "vendor_ref": self.vendor_ref,
            "currency": self.currency, "confirmed": self.confirmed,
            "amount": self.amount, "lines": [line.to_mapping() for line in self.lines],
        }

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> TrustedPurchaseOrder:
        _validate("purchaseOrder", value)
        fields = dict(value)
        fields["lines"] = tuple(TrustedPurchaseLine.from_mapping(item) for item in value["lines"])
        return cls(**fields)


@dataclass(frozen=True, slots=True)
class DependencyStatus:
    state: Literal["AVAILABLE", "UNAVAILABLE"]
    policy: Literal["AVAILABLE", "UNAVAILABLE"]
    audit: Literal["AVAILABLE", "UNAVAILABLE"]

    def to_mapping(self) -> dict[str, str]:
        return {"state": self.state, "policy": self.policy, "audit": self.audit}


@dataclass(frozen=True, slots=True)
class TrustedTargetBill:
    move_id: int
    state: Literal["draft", "posted", "cancel"]
    action: CanonicalAction

    def __post_init__(self) -> None:
        if not isinstance(self.action, CanonicalAction):
            raise PolicyContractError("target action must be typed")
        _validate("targetBill", self.to_mapping())
        if type(self.move_id) is not int or self.action.target_move_id != self.move_id:
            raise PolicyContractError("trusted target move binding invalid")

    def to_mapping(self) -> dict[str, Any]:
        return {"move_id": self.move_id, "state": self.state, "action": self.action.to_mapping()}

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> TrustedTargetBill:
        _validate("targetBill", value)
        return cls(value["move_id"], value["state"], CanonicalAction.from_mapping(value["action"]))


@dataclass(frozen=True, slots=True)
class TrustedPolicyState:
    company_ref: str
    scenario_id: str
    document_sha256: str
    phase: Literal["DRAFT_INTAKE", "POST_REVIEW"]
    purchase_order: TrustedPurchaseOrder
    allowed_bank_refs: tuple[str, ...]
    duplicate_detected: bool
    invoice_date_min: str
    invoice_date_max: str
    accounting_period_open: bool
    monetary_tolerance: str
    quantity_scale: int
    dependencies: DependencyStatus
    target_bill: TrustedTargetBill | None

    def __post_init__(self) -> None:
        if not isinstance(self.purchase_order, TrustedPurchaseOrder) or not isinstance(self.dependencies, DependencyStatus):
            raise PolicyContractError("trusted state members must be typed")
        if self.target_bill is not None and not isinstance(self.target_bill, TrustedTargetBill):
            raise PolicyContractError("trusted target must be typed")
        _typed_tuple(self.allowed_bank_refs, str)
        _validate("trustedState", self.to_mapping())
        if type(self.quantity_scale) is not int or self.invoice_date_min > self.invoice_date_max:
            raise PolicyContractError("invalid trusted scale or date window")

    def to_mapping(self) -> dict[str, Any]:
        return {
            "company_ref": self.company_ref, "scenario_id": self.scenario_id,
            "document_sha256": self.document_sha256, "phase": self.phase,
            "purchase_order": self.purchase_order.to_mapping(),
            "allowed_bank_refs": list(self.allowed_bank_refs),
            "duplicate_detected": self.duplicate_detected,
            "invoice_date_min": self.invoice_date_min, "invoice_date_max": self.invoice_date_max,
            "accounting_period_open": self.accounting_period_open,
            "monetary_tolerance": self.monetary_tolerance, "quantity_scale": self.quantity_scale,
            "dependencies": self.dependencies.to_mapping(),
            "target_bill": None if self.target_bill is None else self.target_bill.to_mapping(),
        }

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> TrustedPolicyState:
        _validate("trustedState", value)
        fields = dict(value)
        fields["purchase_order"] = TrustedPurchaseOrder.from_mapping(value["purchase_order"])
        fields["allowed_bank_refs"] = tuple(value["allowed_bank_refs"])
        fields["dependencies"] = DependencyStatus(**value["dependencies"])
        fields["target_bill"] = None if value["target_bill"] is None else TrustedTargetBill.from_mapping(value["target_bill"])
        return cls(**fields)


@dataclass(frozen=True, slots=True)
class PolicyInput:
    action: CanonicalAction
    trusted_state: TrustedPolicyState
    evaluated_at: str
    expires_at: str
    schema_version: str = POLICY_INPUT_VERSION

    def __post_init__(self) -> None:
        if not isinstance(self.action, CanonicalAction) or not isinstance(self.trusted_state, TrustedPolicyState):
            raise PolicyContractError("policy input members must be typed")
        _validate("policyInput", self.to_mapping())
        _lifetime(self.evaluated_at, self.expires_at)
        state = self.trusted_state
        if (self.action.scenario_id, self.action.document_sha256) != (state.scenario_id, state.document_sha256):
            raise PolicyContractError("policy input provenance binding invalid")
        quantities = [line.quantity for line in self.action.lines]
        quantities += [q for line in state.purchase_order.lines for q in (line.quantity, line.quantity_to_invoice)]
        if state.target_bill is not None:
            target = state.target_bill.action
            if (target.scenario_id, target.document_sha256) != (state.scenario_id, state.document_sha256):
                raise PolicyContractError("trusted target provenance binding invalid")
            quantities += [line.quantity for line in target.lines]
        if any(len(value.split(".")[1]) != state.quantity_scale for value in quantities):
            raise PolicyContractError("quantity scale differs from explicit protocol scale")

    @property
    def input_hash(self) -> str:
        return "sha256:" + canonical_json_sha256(self.to_mapping())

    def to_mapping(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version, "action": self.action.to_mapping(),
            "trusted_state": self.trusted_state.to_mapping(),
            "evaluated_at": self.evaluated_at, "expires_at": self.expires_at,
        }

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> PolicyInput:
        _validate("policyInput", value)
        return cls(
            CanonicalAction.from_mapping(value["action"]),
            TrustedPolicyState.from_mapping(value["trusted_state"]),
            value["evaluated_at"], value["expires_at"], value["schema_version"],
        )


@dataclass(frozen=True, slots=True)
class PolicyDecision:
    decision: Decision
    reason_codes: tuple[ReasonCode, ...]
    proposed_action_hash: str
    input_sha256: str
    policy_version: str
    allowed_executor: Literal["create_bill_executor", "post_bill_executor"] | None
    deny_class: DenyClass | None
    evaluated_at: str
    expires_at: str
    schema_version: str = POLICY_DECISION_VERSION

    def __post_init__(self) -> None:
        _typed_tuple(self.reason_codes, ReasonCode)
        _validate("policyDecision", self.to_mapping())
        _lifetime(self.evaluated_at, self.expires_at)
        if self.decision == "DENY":
            codes = set(self.reason_codes)
            if codes & _SUCCESS:
                raise PolicyContractError("deny decision cannot contain success codes")
            unavailable = self.deny_class == "FAIL_CLOSED_UNAVAILABILITY"
            if (unavailable and not codes <= _UNAVAILABLE) or (not unavailable and codes & _UNAVAILABLE):
                raise PolicyContractError("deny class and reason codes disagree")

    def to_mapping(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version, "decision": self.decision,
            "reason_codes": [code.value for code in self.reason_codes],
            "proposed_action_hash": self.proposed_action_hash, "input_sha256": self.input_sha256,
            "policy_version": self.policy_version, "allowed_executor": self.allowed_executor,
            "deny_class": self.deny_class, "evaluated_at": self.evaluated_at,
            "expires_at": self.expires_at,
        }

    def validate_binding(self, policy_input: PolicyInput) -> None:
        """Vínculo de dados; não avalia regras, disponibilidade ou autorização."""
        if not isinstance(policy_input, PolicyInput):
            raise PolicyContractError("decision binding requires typed input")
        if (
            self.proposed_action_hash != policy_input.action.action_hash
            or self.input_sha256 != policy_input.input_hash
            or self.policy_version != policy_input.action.policy_version
            or (self.evaluated_at, self.expires_at) != (policy_input.evaluated_at, policy_input.expires_at)
        ):
            raise PolicyContractError("policy decision input binding invalid")
        if self.decision != "DENY":
            expected = "create_bill_executor" if policy_input.action.executor_mode == "CREATE_DRAFT" else "post_bill_executor"
            if self.allowed_executor != expected:
                raise PolicyContractError("decision executor binding invalid")

    @classmethod
    def for_input(
        cls, policy_input: PolicyInput, *, decision: Decision,
        reason_codes: tuple[ReasonCode, ...], deny_class: DenyClass | None = None,
    ) -> PolicyDecision:
        executors = {"ALLOW": "create_bill_executor", "REVIEW": "post_bill_executor", "DENY": None}
        if decision not in executors:
            raise PolicyContractError("unsupported policy disposition")
        result = cls(
            decision, reason_codes, policy_input.action.action_hash, policy_input.input_hash,
            policy_input.action.policy_version, executors[decision], deny_class,
            policy_input.evaluated_at, policy_input.expires_at,
        )
        result.validate_binding(policy_input)
        return result

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> PolicyDecision:
        _validate("policyDecision", value)
        fields = dict(value)
        fields["reason_codes"] = tuple(ReasonCode(code) for code in value["reason_codes"])
        return cls(**fields)


@dataclass(frozen=True, slots=True)
class ApprovalFixture:
    fixture_id: str
    scenario_id: str
    approver_ref: str
    canonical_action_hash: str
    nonce: str = field(repr=False)
    issued_at: str
    expires_at: str
    key_id: str
    signature: str = field(repr=False)
    decision: str = "APPROVE"

    def __post_init__(self) -> None:
        _validate("approvalFixture", self.to_mapping())
        _lifetime(self.issued_at, self.expires_at)

    def to_mapping(self) -> dict[str, str]:
        """Payload de transporte privado; não registrar nem publicar assinatura."""
        return {
            "fixture_id": self.fixture_id, "scenario_id": self.scenario_id,
            "approver_ref": self.approver_ref, "decision": self.decision,
            "canonical_action_hash": self.canonical_action_hash, "nonce": self.nonce,
            "issued_at": self.issued_at, "expires_at": self.expires_at,
            "key_id": self.key_id, "signature": self.signature,
        }

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> ApprovalFixture:
        _validate("approvalFixture", value)
        return cls(**value)


@dataclass(frozen=True, slots=True)
class CapabilityCommand:
    """Pedido tipado; o executor ainda deve revalidar estado, política e token."""
    action: CanonicalAction
    policy_decision: PolicyDecision
    idempotency_key: str
    approval: ApprovalFixture | None = field(default=None, repr=False)
    schema_version: str = CAPABILITY_COMMAND_VERSION

    def __post_init__(self) -> None:
        if not isinstance(self.action, CanonicalAction) or not isinstance(self.policy_decision, PolicyDecision):
            raise PolicyContractError("capability command members must be typed")
        if self.approval is not None and not isinstance(self.approval, ApprovalFixture):
            raise PolicyContractError("approval fixture must be typed")
        _validate("capabilityCommand", self.to_mapping())
        decision = self.policy_decision
        if self.action.action_hash != decision.proposed_action_hash or self.action.policy_version != decision.policy_version:
            raise PolicyContractError("command action binding invalid")
        if self.approval is not None and (
            self.approval.canonical_action_hash != self.action.action_hash
            or self.approval.scenario_id != self.action.scenario_id
        ):
            raise PolicyContractError("command approval binding invalid")

    def validate_binding(self, policy_input: PolicyInput) -> None:
        self.policy_decision.validate_binding(policy_input)
        if self.action != policy_input.action:
            raise PolicyContractError("command input action binding invalid")

    def to_mapping(self) -> dict[str, Any]:
        """Payload do executor; contém token runtime quando presente, não é log."""
        value = {
            "schema_version": self.schema_version, "action": self.action.to_mapping(),
            "policy_decision": self.policy_decision.to_mapping(),
            "idempotency_key": self.idempotency_key,
        }
        if self.approval is not None:
            value["approval"] = self.approval.to_mapping()
        return value

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> CapabilityCommand:
        _validate("capabilityCommand", value)
        return cls(
            CanonicalAction.from_mapping(value["action"]),
            PolicyDecision.from_mapping(value["policy_decision"]), value["idempotency_key"],
            None if "approval" not in value else ApprovalFixture.from_mapping(value["approval"]),
            value["schema_version"],
        )
