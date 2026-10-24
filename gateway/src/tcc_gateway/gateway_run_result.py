"""DEC-078: private CREATE handoff evidence around an unchanged RunRecord v4.

This closed envelope checks the real policy result and its complete proposed
action. It does not authenticate the administrative producer, establish a
financial effect from a return value, or make a candidate scientifically ready.
Approval commands/tokens are deliberately not part of this first vertical.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from decimal import Decimal
import json

from .company_capture import CaptureBinding, _native_rows, parse_company_capture
from .policy_contracts import PolicyDecision, PolicyInput
from .policy_engine import evaluate_policy
from .run_record import RunRecord, _closed, _json_snapshot
from .run_record_v2 import _stage
from .run_record_v4 import parse_run_record_v4
from .runner_contract_v2 import proposal_from_llm_stage_v2
from .state import canonical_json_bytes, canonical_json_sha256
from .trusted_resolution import TrustedWorkflow, canonicalize_proposal


VERSION = "gateway-run-result/v1"
_FIELDS = {"schema_version", "record", "workflow", "workflow_sha256", "policy_evidence", "record_sha256",
           "policy_input_sha256", "decision_sha256", "scientific_run", "human_review_complete"}


class GatewayRunResultError(ValueError):
    """Finite diagnostic; never expose private inputs, identities or credentials."""


def _require(value):
    if not value:
        raise GatewayRunResultError("invalid private gateway run result")


@dataclass(frozen=True, slots=True, repr=False)
class GatewayRunResult:
    _encoded: bytes = field(repr=False)

    def to_mapping(self) -> dict:
        """Detached PRIVATE evidence, not a sanitised or publishable export."""
        return json.loads(self._encoded)

    @property
    def record(self) -> RunRecord:
        return parse_run_record_v4(self.to_mapping()["record"])

    def __repr__(self) -> str:
        return "GatewayRunResult(private_candidate=True)"


def _bind_purchase_order(policy_input, record):
    """Check financial references against the company-bound before capture.

    ``company_ref`` is a workflow label, not the physical company name. Its
    configuration remains a trusted-producer premise; never equate the two.
    Operational health, date windows and the allowlist likewise are not inferred
    from an expected output or rewritten from a candidate.
    """
    value = record["evidence"]["captures"]["before"]
    capture = parse_company_capture(value, CaptureBinding.from_mapping(value["binding"]))
    state, expected = policy_input.trusted_state, policy_input.trusted_state.purchase_order
    orders = _native_rows(capture, "purchase.order")
    selected = [(key, row) for key, row in orders.items() if row["name"] == expected.purchase_order_ref]
    _require(len(selected) == 1)
    order_id, order = selected[0]
    partners = _native_rows(capture, "res.partner")
    currencies = _native_rows(capture, "res.currency")
    products = _native_rows(capture, "product.product")
    _require(order["company_id"] == capture.binding.company_id
        and partners[order["partner_id"]]["ref"] == expected.vendor_ref
        and currencies[order["currency_id"]]["name"] == expected.currency
        and (order["state"] in {"purchase", "done"}) is expected.confirmed
        and Decimal(order["amount_total"]) == Decimal(expected.amount))
    observed = sorted((products[line["product_id"]]["default_code"], Decimal(line["product_qty"]),
                       Decimal(line["price_unit"]), Decimal(line["qty_to_invoice"]))
                      for line in _native_rows(capture, "purchase.order.line").values()
                      if line["order_id"] == order_id)
    trusted = [(line.item_code, Decimal(line.quantity), Decimal(line.unit_price),
                Decimal(line.quantity_to_invoice)) for line in expected.lines]
    _require(observed == trusted and state.target_bill is None and state.phase == "DRAFT_INTAKE")


def _validate(value):
    _closed(value, _FIELDS)
    _require(value["schema_version"] == VERSION
        and value["scientific_run"] is False and value["human_review_complete"] is False)
    parsed_record = parse_run_record_v4(value["record"])
    record = parsed_record.to_mapping()
    _require(value["record_sha256"] == canonical_json_sha256(record))
    evidence, identity = record["evidence"], record["identity"]
    _closed(value["workflow"], TrustedWorkflow.__dataclass_fields__)
    workflow_fields = dict(value["workflow"])
    _require(type(workflow_fields["allowed_bank_refs"]) is list)
    workflow_fields["allowed_bank_refs"] = tuple(workflow_fields["allowed_bank_refs"])
    workflow = TrustedWorkflow(**workflow_fields)
    _require(value["workflow_sha256"] == canonical_json_sha256(value["workflow"])
        and workflow.company_name == evidence["captures"]["before"]["binding"]["company_name"]
        and workflow.company_name == evidence["case"]["company_name"]
        and workflow.purchase_order_ref == evidence["case"]["expected_bill"]["purchase_order_ref"]
        and workflow.scenario_id == identity["scenario_id"]
        and workflow.document_sha256 == evidence["request"]["document"]["document_sha256"]
        and workflow.phase == "DRAFT_INTAKE" and workflow.target_document_ref is None)
    stage = _stage(evidence["stage"])
    proposal = proposal_from_llm_stage_v2(evidence["request"], stage)
    _require(proposal.action == "CREATE_DRAFT_BILL"
        and evidence["case"]["expected_action"] == "CREATE_DRAFT_BILL"
        and evidence["case"]["attack_family"] != "A3a"
        and evidence["case"]["target_move_id"] is None)
    trace = evidence["trace"]
    _require(all(method == "account.move.create" for method in trace["executed_methods"]))
    policy = value["policy_evidence"]
    if identity["condition"] == "C0":
        _require(policy is None and value["policy_input_sha256"] is None
            and value["decision_sha256"] is None and trace["disposition"] == "ALLOW_EFFECTIVE"
            and trace["deny_class"] is None and trace["executed_methods"] == ["account.move.create"]
            and trace["effect_move_id"] is not None)
        return
    _closed(policy, {"policy_input", "decision"})
    policy_input = PolicyInput.from_mapping(policy["policy_input"])
    decision = PolicyDecision.from_mapping(policy["decision"])
    _require(value["policy_input_sha256"] == canonical_json_sha256(policy_input.to_mapping())
        and value["decision_sha256"] == canonical_json_sha256(decision.to_mapping()))
    action = canonicalize_proposal(proposal, policy_version=policy_input.action.policy_version,
        quantity_scale=policy_input.trusted_state.quantity_scale, target_move_id=None)
    _require(action == policy_input.action
        and (policy_input.trusted_state.scenario_id, policy_input.trusted_state.document_sha256)
        == (identity["scenario_id"], evidence["request"]["document"]["document_sha256"]))
    state = policy_input.trusted_state
    _require(state.company_ref == workflow.company_ref
        and state.phase == workflow.phase
        and state.purchase_order.purchase_order_ref == workflow.purchase_order_ref
        and tuple(sorted(state.allowed_bank_refs)) == tuple(sorted(workflow.allowed_bank_refs))
        and state.invoice_date_min == workflow.invoice_date_min
        and state.invoice_date_max == workflow.invoice_date_max
        and state.monetary_tolerance == workflow.monetary_tolerance
        and state.quantity_scale == workflow.quantity_scale)
    _bind_purchase_order(policy_input, record)
    decision.validate_binding(policy_input)
    _require(canonical_json_bytes(decision.to_mapping())
             == canonical_json_bytes(evaluate_policy(policy_input).to_mapping()))
    if decision.decision == "DENY":
        _require(trace["disposition"] == "DENY" and trace["deny_class"] == decision.deny_class
            and trace["effect_move_id"] is None and trace["executed_methods"] == [])
    else:
        _require(decision.decision == "ALLOW" and trace["disposition"] == "ALLOW")
        # A later confirmed executor refusal may carry a class even though the
        # real policy allowed CREATE. v4 checks its own observation/quiescence
        # constraints; do not replace that runtime fact with the policy class.
        if trace["effect_move_id"] is not None:
            _require(trace["deny_class"] is None and trace["executed_methods"] == ["account.move.create"])


def parse_gateway_run_result(value: dict) -> GatewayRunResult:
    """Reparse the unchanged v4, bindings, full decision and every digest."""
    try:
        value = _json_snapshot(value)
        _validate(value)
        return GatewayRunResult(canonical_json_bytes(value))
    except (ValueError, TypeError, AttributeError, KeyError, OverflowError, RecursionError):
        raise GatewayRunResultError("invalid private gateway run result") from None


def build_gateway_run_result(record: RunRecord, *, workflow: TrustedWorkflow,
                             policy_input: PolicyInput | None = None,
                             policy_decision: PolicyDecision | None = None) -> GatewayRunResult:
    """Bind an existing immutable candidate to the actual CREATE handoff.

    ``policy_sha256`` keeps its original policy-artifact meaning in the v4.
    Input/decision digests here are separate, per-run consistency bindings.
    """
    try:
        _require(type(record) is RunRecord and type(workflow) is TrustedWorkflow
            and (policy_input is None or type(policy_input) is PolicyInput)
            and (policy_decision is None or type(policy_decision) is PolicyDecision)
            and (policy_input is None) == (policy_decision is None))
        record_value = parse_run_record_v4(record.to_mapping()).to_mapping()
        policy = None if policy_input is None else {
            "policy_input": policy_input.to_mapping(), "decision": policy_decision.to_mapping()}
        workflow_value = asdict(workflow)
        workflow_value["allowed_bank_refs"] = list(workflow.allowed_bank_refs)
        return parse_gateway_run_result({"schema_version": VERSION, "record": record_value,
            "workflow": workflow_value, "workflow_sha256": canonical_json_sha256(workflow_value),
            "policy_evidence": policy, "record_sha256": canonical_json_sha256(record_value),
            "policy_input_sha256": None if policy is None else canonical_json_sha256(policy["policy_input"]),
            "decision_sha256": None if policy is None else canonical_json_sha256(policy["decision"]),
            "scientific_run": False, "human_review_complete": False})
    except (ValueError, TypeError, AttributeError, KeyError, OverflowError, RecursionError):
        raise GatewayRunResultError("invalid private gateway run result") from None
