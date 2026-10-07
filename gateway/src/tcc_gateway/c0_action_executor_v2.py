"""C0 v2: dispatch closed actions without importing C1 business controls.

The trusted binding selects only the synthetic company and existing POST
target. Scenario/document equality belongs to the common input envelope.
Neither the binding nor a successful native return authorizes a financial
operation or proves its committed effect. Independent observation is required.
The historical M2/G3 v1 executor remains unchanged (DEC-050).
"""

from __future__ import annotations

from dataclasses import dataclass
import re
import unicodedata
from typing import Any

from .action_proposal_v2 import (
    ActionProposalV2, POST_VENDOR_BILL, revalidate_action_proposal_v2,
)
from .c0_executor import (
    C0ExecutionError,
    OdooCaller,
    create_c0_draft_bill,
    resolve_c0_references,
)
from .proposal import CREATE_DRAFT_BILL, SCHEMA_VERSION, VendorBillProposal


_SCENARIO = re.compile(r"[A-Z0-9][A-Z0-9._-]{0,63}\Z")
_DIGEST = re.compile(r"[0-9a-f]{64}\Z")
_REFERENCE = re.compile(r"[A-Z0-9][A-Z0-9._ /-]{0,95}\Z")
_ERROR_CATEGORIES = frozenset({
    "INVALID_BINDING", "INVALID_PROPOSAL", "INPUT_BINDING_MISMATCH",
    "TARGET_NOT_CONFIGURED", "TARGET_NOT_FOUND", "TARGET_AMBIGUOUS",
    "ODOO_RESPONSE_INVALID", "ODOO_OPERATION_FAILED",
})


class C0ActionExecutionError(C0ExecutionError):
    """Finite operational category; never an authorization DENY or raw error."""

    def __init__(self, category: str) -> None:
        if category not in _ERROR_CATEGORIES:
            raise ValueError("unsupported C0 action error category")
        self.category = category
        super().__init__("C0 action dispatch failed: " + category)


def _trusted_text(value: Any, *, maximum: int) -> bool:
    return (
        type(value) is str and 1 <= len(value) <= maximum
        and value.strip() == value and unicodedata.normalize("NFC", value) == value
        and not any(unicodedata.category(char) in {"Cc", "Cf", "Cs"} for char in value)
    )


@dataclass(frozen=True, slots=True)
class TrustedC0ActionBinding:
    """Supplied by trusted fixture code, never by document/model fields.

    It contains no expected action, phase, bank allowlist, business values,
    approval or adversarial label. Typing does not attest its origin.
    """

    company_name: str
    scenario_id: str
    document_sha256: str
    target_document_ref: str | None = None

    def __post_init__(self) -> None:
        if not _trusted_text(self.company_name, maximum=160) or (
            type(self.scenario_id) is not str or _SCENARIO.fullmatch(self.scenario_id) is None
        ) or (
            type(self.document_sha256) is not str or _DIGEST.fullmatch(self.document_sha256) is None
        ) or (
            self.target_document_ref is not None and (
                not _trusted_text(self.target_document_ref, maximum=96)
                or _REFERENCE.fullmatch(self.target_document_ref) is None
            )
        ):
            raise ValueError("invalid trusted C0 action binding")


@dataclass(frozen=True, slots=True)
class C0ActionDispatch:
    """Native call completed, not proof that the move is draft/posted.

    Odoo ``action_post`` may return False or a wizard dictionary after a real
    effect. Neither is followed as a new capability or used as state evidence.
    """

    action: str
    move_id: int

    def __post_init__(self) -> None:
        if type(self.action) is not str or self.action not in {
            CREATE_DRAFT_BILL, POST_VENDOR_BILL,
        } or type(self.move_id) is not int or self.move_id <= 0:
            raise ValueError("invalid C0 action dispatch result")


def _binding(binding: TrustedC0ActionBinding) -> TrustedC0ActionBinding:
    try:
        if type(binding) is not TrustedC0ActionBinding:
            raise ValueError("typed trusted binding required")
        return TrustedC0ActionBinding(
            binding.company_name, binding.scenario_id, binding.document_sha256,
            binding.target_document_ref,
        )
    except (AttributeError, TypeError, ValueError):
        raise C0ActionExecutionError("INVALID_BINDING") from None


def _proposal(proposal: ActionProposalV2) -> ActionProposalV2:
    try:
        return revalidate_action_proposal_v2(proposal)
    except (AttributeError, TypeError, ValueError):
        raise C0ActionExecutionError("INVALID_PROPOSAL") from None


def _native_call(client: OdooCaller, model: str, method: str, *, arguments: dict) -> Any:
    try:
        return client.call(model, method, arguments=arguments)
    except Exception:
        # Native refusal/transport failure is operational. The outer runner must
        # observe the actual state rather than fabricate DENY, success or missing.
        raise C0ActionExecutionError("ODOO_OPERATION_FAILED") from None


def _one(value: Any, *, target: bool) -> dict[str, Any]:
    if type(value) is not list or len(value) > 2 or any(type(row) is not dict for row in value):
        raise C0ActionExecutionError("ODOO_RESPONSE_INVALID")
    if not value:
        raise C0ActionExecutionError("TARGET_NOT_FOUND" if target else "ODOO_RESPONSE_INVALID")
    if len(value) != 1:
        raise C0ActionExecutionError("TARGET_AMBIGUOUS" if target else "ODOO_RESPONSE_INVALID")
    row = value[0]
    if type(row.get("id")) is not int or row["id"] <= 0:
        raise C0ActionExecutionError("ODOO_RESPONSE_INVALID")
    return row


def resolve_c0_post_target(client: OdooCaller, binding: TrustedC0ActionBinding) -> int:
    """Resolve only a trusted company/type/reference; never proposed fields.

    This checks laboratory target identity, not phase, financial arguments,
    bank ownership, approval or C1 policy. Native Odoo handles its own state
    preconditions. Separate JSON-2 calls do not promise transactional atomicity.
    """

    trusted = _binding(binding)
    if trusted.target_document_ref is None:
        raise C0ActionExecutionError("TARGET_NOT_CONFIGURED")
    company = _one(_native_call(client, "res.company", "search_read", arguments={
        "domain": [["name", "=", trusted.company_name]], "fields": ["name"], "limit": 2,
    }), target=False)
    if company.get("name") != trusted.company_name:
        raise C0ActionExecutionError("ODOO_RESPONSE_INVALID")
    row = _one(_native_call(client, "account.move", "search_read", arguments={
        "domain": [
            ["company_id", "=", company["id"]], ["move_type", "=", "in_invoice"],
            ["ref", "=", trusted.target_document_ref],
        ],
        "fields": ["company_id", "move_type", "ref"], "limit": 2,
    }), target=True)
    relation = row.get("company_id")
    if type(relation) is not list or len(relation) != 2 or (
        type(relation[0]) is not int or relation[0] != company["id"]
    ) or type(relation[1]) is not str or row.get("move_type") != "in_invoice" or (
        row.get("ref") != trusted.target_document_ref
    ):
        raise C0ActionExecutionError("ODOO_RESPONSE_INVALID")
    return row["id"]


def _create_fields(proposal: ActionProposalV2) -> VendorBillProposal:
    # Explicit internal financial projection, used only AFTER CREATE dispatch
    # selection. It never upgrades historical v1 or turns POST into CREATE.
    if proposal.action != CREATE_DRAFT_BILL:
        raise C0ActionExecutionError("INVALID_PROPOSAL")
    value = proposal.to_mapping()
    value.pop("evidence")
    value["schema_version"] = SCHEMA_VERSION
    return VendorBillProposal.from_mapping(value)


def execute_c0_action_v2(
    client: OdooCaller, proposal: ActionProposalV2, *, binding: TrustedC0ActionBinding,
) -> C0ActionDispatch:
    """Dispatch the model's exact action within the trusted synthetic binding.

    CREATE retains proposed business arguments, including deviations from the
    PO and beneficiary allowlist. POST neither checks approval nor writes the
    descriptive proposed fields before calling the trusted native target.
    Independent state observation and reset remain separate responsibilities.
    """

    trusted, action_proposal = _binding(binding), _proposal(proposal)
    if (action_proposal.scenario_id, action_proposal.document_sha256) != (
        trusted.scenario_id, trusted.document_sha256,
    ):
        raise C0ActionExecutionError("INPUT_BINDING_MISMATCH")
    if action_proposal.action == POST_VENDOR_BILL:
        move_id = resolve_c0_post_target(client, trusted)
        _native_call(client, "account.move", "action_post", arguments={"ids": [move_id]})
        return C0ActionDispatch(action_proposal.action, move_id)
    try:
        financial_fields = _create_fields(action_proposal)
        references = resolve_c0_references(client, financial_fields, company_name=trusted.company_name)
        move_id = create_c0_draft_bill(client, financial_fields, references)
    except Exception:
        raise C0ActionExecutionError("ODOO_OPERATION_FAILED") from None
    if type(move_id) is not int or move_id <= 0:
        raise C0ActionExecutionError("ODOO_RESPONSE_INVALID")
    return C0ActionDispatch(action_proposal.action, move_id)
