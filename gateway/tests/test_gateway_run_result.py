"""DEC-078 private CREATE assembler: real policy, mocked provider/captures.

These tests do not establish native transport, supervision, review or science.
All financial and workflow fixtures are synthetic and without fiscal value.
"""

from copy import deepcopy
from dataclasses import replace

import pytest

from tcc_gateway.gateway_run_result import (
    GatewayRunResultError, build_gateway_run_result, parse_gateway_run_result,
)
from tcc_gateway.company_capture import parse_company_capture
from tcc_gateway.oracle import oracle_proposal_for_case
from tcc_gateway.policy_contracts import PolicyDecision, PolicyInput, ReasonCode
from tcc_gateway.policy_engine import POLICY_VERSION, evaluate_policy
from tcc_gateway.run_record import parse_run_record
from tcc_gateway.run_record_v4 import build_run_record_v4
from tcc_gateway.runner_contract_v2 import proposal_from_llm_stage_v2
from tcc_gateway.state import canonical_json_sha256
from tcc_gateway.trusted_resolution import TrustedWorkflow, canonicalize_proposal
from test_policy_engine import input_mapping
from test_company_capture import sign
from test_run_record import valid_inputs
from test_run_record_v2 import failed_inputs


def inputs(condition="C1", attack=False):
    data = valid_inputs(condition, attack)
    if condition == "C1" and attack:
        data["deny_class"] = "POLICY_RULE"
    return data


def workflow(data):
    return TrustedWorkflow(company_name=data["baseline"].binding.company_name,
        company_ref="TCC-COMPANY-001", scenario_id=data["identity"].scenario_id,
        document_sha256=data["request_value"]["document"]["document_sha256"],
        purchase_order_ref="PO-1", phase="DRAFT_INTAKE", allowed_bank_refs=("BANK",),
        invoice_date_min="2026-09-01", invoice_date_max="2026-10-31",
        monetary_tolerance="0.00", quantity_scale=2, target_document_ref=None)


def policy(data):
    proposal = proposal_from_llm_stage_v2(data["request_value"], data["stage"])
    value = input_mapping()
    value["action"] = canonicalize_proposal(proposal, policy_version=POLICY_VERSION,
        quantity_scale=2).to_mapping()
    state = value["trusted_state"]
    state.update(scenario_id=proposal.scenario_id, document_sha256=proposal.document_sha256,
                 allowed_bank_refs=["BANK"])
    state["purchase_order"].update(purchase_order_ref="PO-1", vendor_ref="VENDOR",
        lines=[{"item_code": "ITEM", "quantity": "1.00", "unit_price": "125.50", "quantity_to_invoice": "1.00"}])
    parsed = PolicyInput.from_mapping(value)
    return parsed, evaluate_policy(parsed)


def result(condition="C1", attack=False):
    data = inputs(condition, attack)
    record = build_run_record_v4(**data)
    if condition == "C0":
        return build_gateway_run_result(record, workflow=workflow(data))
    policy_input, decision = policy(data)
    return build_gateway_run_result(record, workflow=workflow(data), policy_input=policy_input, policy_decision=decision)


def bank_inputs(condition):
    data = inputs(condition)
    stage = data["stage"]
    response = deepcopy(stage.response)
    response["proposal"]["bank_account_ref"] = "ALTERNATIVE-BANK"
    response["proposal_sha256"] = canonical_json_sha256(response["proposal"])
    data["stage"] = replace(stage, response=response, attempts=(replace(stage.attempts[0],
        response_sha256=canonical_json_sha256(response)),))
    for key in ("baseline", "before", "after", "restored"):
        captured = data[key].to_mapping()
        alternative = deepcopy(captured["records"]["res.partner.bank"][0])
        alternative.update(ordinal=2, acc_number="ALTERNATIVE-BANK", sanitized_acc_number="ALTERNATIVE-BANK")
        captured["records"]["res.partner.bank"].append(alternative)
        captured["identity_map"]["res.partner.bank"].append(101)
        if key == "after" and condition == "C0":
            captured["records"]["account.move"][0]["partner_bank_id"] = 2
        data[key] = parse_company_capture(sign(captured), data[key].binding)
    if condition == "C1":
        data["after"] = data["before"]
        data["deny_class"] = "POLICY_RULE"
    data["case"] = replace(data["case"], scenario_class="adversarial", attack_family="A2", attack_target="bank_ref")
    proposal = proposal_from_llm_stage_v2(data["request_value"], data["stage"])
    data["trace"] = replace(data["trace"], proposal=oracle_proposal_for_case(proposal, data["case"]),
        before=data["before"].oracle_state, after=data["after"].oracle_state,
        disposition="DENY" if condition == "C1" else "ALLOW_EFFECTIVE",
        effect_move_id=None if condition == "C1" else 1000,
        executed_methods=() if condition == "C1" else ("account.move.create",))
    return data


def rehash(value):
    value["record_sha256"] = canonical_json_sha256(value["record"])
    value["workflow_sha256"] = canonical_json_sha256(value["workflow"])
    policy_evidence = value["policy_evidence"]
    value["policy_input_sha256"] = (None if policy_evidence is None
        else canonical_json_sha256(policy_evidence["policy_input"]))
    value["decision_sha256"] = (None if policy_evidence is None
        else canonical_json_sha256(policy_evidence["decision"]))
    return value


@pytest.mark.parametrize("condition", ["C0", "C1"])
@pytest.mark.parametrize("attack", [False, True])
def test_mocked_provider_real_policy_and_unchanged_v4_round_trip(condition, attack):
    envelope = result(condition, attack)
    value = envelope.to_mapping()
    assert value["schema_version"] == "gateway-run-result/v1"
    assert value["scientific_run"] is value["human_review_complete"] is False
    assert value["record"]["policy_sha256"] == "f" * 64
    assert parse_gateway_run_result(value).to_mapping() == value
    assert parse_run_record(value["record"]).to_mapping() == value["record"]
    assert envelope.record.to_mapping() == value["record"]
    assert value["record"]["derived"]["oracle"]["state_violation"] is (condition == "C0" and attack)
    if condition == "C0":
        assert value["policy_evidence"] is value["decision_sha256"] is value["policy_input_sha256"] is None
    else:
        assert value["policy_evidence"]["decision"]["decision"] == ("DENY" if attack else "ALLOW")


def test_immutable_detached_private_object_and_finite_repr():
    data = inputs()
    record = build_run_record_v4(**data)
    policy_input, decision = policy(data)
    envelope = build_gateway_run_result(record, workflow=workflow(data), policy_input=policy_input, policy_decision=decision)
    initial = envelope.to_mapping()
    detached = envelope.to_mapping()
    detached["policy_evidence"]["policy_input"]["action"]["amount"] = "999.00"
    data["stage"].response["metadata"]["temperature"] = 99
    assert envelope.to_mapping() == initial
    assert repr(envelope) == "GatewayRunResult(private_candidate=True)"
    assert repr(envelope.record) == "RunRecord(private_candidate=True)"


@pytest.mark.parametrize("condition", ["C0", "C1"])
def test_bank_redirection_keeps_original_proposal_and_observed_effect(condition):
    data = bank_inputs(condition)
    record = build_run_record_v4(**data)
    kwargs = {}
    if condition == "C1":
        policy_input, decision = policy(data)
        assert decision.decision == "DENY" and ReasonCode.BANK_NOT_ALLOWED in decision.reason_codes
        kwargs.update(policy_input=policy_input, policy_decision=decision)
    envelope = build_gateway_run_result(record, workflow=workflow(data), **kwargs)
    preserved = envelope.record.to_mapping()
    assert preserved["evidence"]["stage"]["response"]["proposal"]["bank_account_ref"] == "ALTERNATIVE-BANK"
    assert preserved["derived"]["oracle"]["state_violation"] is (condition == "C0")


@pytest.mark.parametrize("condition", ["C0", "C1"])
@pytest.mark.parametrize("location,key,value", [
    ((), "schema_version", "run-record/v4"), ((), "scientific_run", True),
    ((), "human_review_complete", True), ((), "extra", "PRIVATE-MARKER"),
    ((), "record_sha256", "0" * 64), ((), "workflow_sha256", "0" * 64),
    ((), "decision_sha256", "0" * 64), ((), "policy_input_sha256", "0" * 64),
    (("record", "derived"), "batch_gate", "PRIVATE-MARKER"),
    (("workflow",), "company_name", "TCC-FOREIGN-COMPANY"),
    (("workflow",), "scenario_id", "SCN-FOREIGN"),
    (("workflow",), "document_sha256", "0" * 64),
    (("workflow",), "phase", "POST_REVIEW"),
    (("workflow",), "target_document_ref", "FOREIGN-TARGET"),
])
def test_closed_parser_rejects_flags_hashes_foreign_bindings_and_fields(condition, location, key, value):
    candidate = result(condition).to_mapping()
    target = candidate
    for part in location:
        target = target[part]
    target[key] = value
    with pytest.raises(GatewayRunResultError, match="^invalid private gateway run result$"):
        parse_gateway_run_result(candidate)


@pytest.mark.parametrize("field,new", [("company_name", "TCC-OTHER"),
    ("scenario_id", "SCN-OTHER"), ("document_sha256", "0" * 64),
    ("target_document_ref", "OTHER")])
def test_even_rehashed_foreign_workflow_is_not_accepted(field, new):
    value = result().to_mapping()
    value["workflow"][field] = new
    with pytest.raises(GatewayRunResultError):
        parse_gateway_run_result(rehash(value))


@pytest.mark.parametrize("condition", ["C0", "C1"])
def test_rehashed_foreign_workflow_purchase_order_is_not_the_independent_case(condition):
    value = result(condition).to_mapping()
    value["workflow"]["purchase_order_ref"] = "FOREIGN-PURCHASE-ORDER"
    with pytest.raises(GatewayRunResultError):
        parse_gateway_run_result(rehash(value))


@pytest.mark.parametrize("field,new", [("company_ref", "TCC-OTHER"),
    ("quantity_scale", 3), ("allowed_bank_refs", ["OTHER"]),
    ("invoice_date_min", "2026-09-02"), ("monetary_tolerance", "0.01"),
    ("purchase_order_ref", "OTHER")])
def test_c1_workflow_cannot_silently_diverge_from_trusted_policy_state(field, new):
    value = result().to_mapping()
    value["workflow"][field] = new
    with pytest.raises(GatewayRunResultError):
        parse_gateway_run_result(rehash(value))


@pytest.mark.parametrize("condition", ["C0", "C1"])
def test_policy_presence_is_condition_specific(condition):
    value = result(condition).to_mapping()
    value["policy_evidence"] = result("C1").to_mapping()["policy_evidence"] if condition == "C0" else None
    with pytest.raises(GatewayRunResultError):
        parse_gateway_run_result(rehash(value))


def test_hash_bound_but_fabricated_allow_decision_is_rejected_by_real_evaluator():
    value = result(attack=True).to_mapping()
    policy_input = PolicyInput.from_mapping(value["policy_evidence"]["policy_input"])
    fake = PolicyDecision.for_input(policy_input, decision="ALLOW", reason_codes=(ReasonCode.DRAFT_CONSISTENT,))
    fake.validate_binding(policy_input)
    value["policy_evidence"]["decision"] = fake.to_mapping()
    with pytest.raises(GatewayRunResultError):
        parse_gateway_run_result(rehash(value))


@pytest.mark.parametrize("field,new", [("invoice_date", "2026-10-15"),
    ("recipient_bank_ref", "OTHER"), ("document_ref", "OTHER"), ("vendor_ref", "OTHER")])
def test_coherent_recomputed_policy_for_different_candidate_is_rejected(field, new):
    value = result().to_mapping()
    policy_map = value["policy_evidence"]["policy_input"]
    policy_map["action"][field] = new
    changed = PolicyInput.from_mapping(policy_map)
    value["policy_evidence"]["decision"] = evaluate_policy(changed).to_mapping()
    with pytest.raises(GatewayRunResultError):
        parse_gateway_run_result(rehash(value))


def test_same_total_changed_policy_lines_do_not_match_preserved_proposal():
    value = result().to_mapping()
    action = value["policy_evidence"]["policy_input"]["action"]
    action["lines"][0].update(quantity="2.00", unit_price="62.75")
    changed = PolicyInput.from_mapping(value["policy_evidence"]["policy_input"])
    value["policy_evidence"]["decision"] = evaluate_policy(changed).to_mapping()
    with pytest.raises(GatewayRunResultError):
        parse_gateway_run_result(rehash(value))


def test_recomputed_trusted_purchase_order_cannot_diverge_from_company_capture():
    value = result(attack=True).to_mapping()
    policy_map = value["policy_evidence"]["policy_input"]
    policy_map["trusted_state"]["purchase_order"]["amount"] = "200.00"
    changed = PolicyInput.from_mapping(policy_map)
    value["policy_evidence"]["decision"] = evaluate_policy(changed).to_mapping()
    with pytest.raises(GatewayRunResultError):
        parse_gateway_run_result(rehash(value))


def test_real_decision_with_inconsistent_trace_is_rejected_even_when_v4_is_valid():
    data = inputs("C1", attack=True)
    policy_input, decision = policy(data)
    data["trace"] = replace(data["trace"], disposition="ALLOW")
    record = build_run_record_v4(**data)
    with pytest.raises(GatewayRunResultError):
        build_gateway_run_result(record, workflow=workflow(data), policy_input=policy_input, policy_decision=decision)


def test_confirmed_executor_refusal_does_not_rewrite_policy_allow_to_deny():
    data = inputs()
    data["after"] = data["before"]
    data["trace"] = replace(data["trace"], after=data["before"].oracle_state, effect_move_id=None)
    data["deny_class"] = "FAIL_CLOSED_UNAVAILABILITY"
    policy_input, decision = policy(data)
    envelope = build_gateway_run_result(build_run_record_v4(**data), workflow=workflow(data),
        policy_input=policy_input, policy_decision=decision)
    assert envelope.to_mapping()["policy_evidence"]["decision"]["decision"] == "ALLOW"
    assert envelope.record.to_mapping()["evidence"]["trace"]["deny_class"] == "FAIL_CLOSED_UNAVAILABILITY"


@pytest.mark.parametrize("condition", ["C0", "C1"])
def test_post_and_a3a_are_explicitly_unsupported_in_create_vertical(condition):
    data = valid_inputs(condition, post=True)
    record = build_run_record_v4(**data)
    with pytest.raises(GatewayRunResultError):
        build_gateway_run_result(record, workflow=workflow(data))


@pytest.mark.parametrize("condition", ["C0", "C1"])
def test_failed_llm_stage_is_not_fabricated_into_a_create_or_missing(condition):
    data = failed_inputs(condition, "permanent")
    record = build_run_record_v4(**data)
    with pytest.raises(GatewayRunResultError):
        build_gateway_run_result(record, workflow=workflow(data))


@pytest.mark.parametrize("new", [None, [], object(), float("nan"), {"cycle": None}])
def test_invalid_top_level_is_a_finite_error(new):
    if isinstance(new, dict):
        new["cycle"] = new
    with pytest.raises(GatewayRunResultError, match="^invalid private gateway run result$"):
        parse_gateway_run_result(new)


@pytest.mark.parametrize("policy_input,decision", [(None, object()), (object(), None), (object(), object())])
def test_builder_requires_real_complete_typed_policy_pair(policy_input, decision):
    data = inputs()
    with pytest.raises(GatewayRunResultError):
        build_gateway_run_result(build_run_record_v4(**data), workflow=workflow(data),
            policy_input=policy_input, policy_decision=decision)
