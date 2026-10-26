"""DEC-079 POST consistency with actual policy and explicit capture doubles.

No Docker, native financial effect, signature verification or external model is
performed. Linux clock values here are declared test doubles, never live proof.
"""

from copy import deepcopy
from dataclasses import replace
import hashlib

import pytest

from tcc_gateway.company_capture import parse_company_capture
from tcc_gateway.gateway_post_run_result import (
    GatewayPostRunResultError, build_gateway_post_run_result, parse_gateway_post_run_result,
)
from tcc_gateway.idempotency import bill_idempotency_key
from tcc_gateway.linux_clock_domain import _from_fingerprints, _ZERO_OFFSETS_SHA256
from tcc_gateway.linux_clock_scope import build_clock_scope
from tcc_gateway.policy_contracts import PolicyInput
from tcc_gateway.policy_engine import evaluate_policy
from tcc_gateway.run_record_v4 import build_run_record_v4
from tcc_gateway.run_supervision import StageInterval
from tcc_gateway.runner_contract_v2 import proposal_from_llm_stage_v2
from tcc_gateway.state import canonical_json_sha256
from tcc_gateway.trusted_resolution import TrustedWorkflow, canonicalize_proposal
from test_approval_attribution import approved_inputs
from test_company_capture import row, sign
from test_linux_clock_domain import domain
from test_policy_engine import input_mapping


MATRIX = (("exact", "C0"), ("exact", "C1"), ("tampered", "C0"), ("tampered", "C1"))


def runtime_binding():
    return {"schema_version": "local-linux-runtime/v1", "daemon_sha256": "1" * 64,
        "kernel_sha256": "2" * 64, "runtime": "runc", "endpoint_kind": "local-npipe",
        "os_type": "linux", "platform": "linux/amd64"}


def post_inputs(variant="exact", condition="C0"):
    """No signature or real clock claim; supports host/probe boundary tests."""
    effect = condition == "C0" or variant == "exact"
    data = approved_inputs(condition, "amount" if variant == "tampered" else None,
        effect=effect, benign=variant == "exact")
    proof = "a" * 32
    slot = hashlib.sha256((proof + ":" + variant + ":" + condition).encode("ascii")).hexdigest()[:32]
    data["identity"] = replace(data["identity"], run_id=slot)
    clock = domain()
    scope = build_clock_scope(clock, runtime_binding())
    producers = {"sampler": clock, **{name: _from_fingerprints(clock["boot_sha256"], digit * 64, _ZERO_OFFSETS_SHA256)
        for name, digit in (("native", "c"), ("candidate", "d"), ("policy", "e"), ("assembly", "f"))}}
    if condition == "C0":
        producers["policy"] = None
    names = ("llm", "observation", "execution", "capture", "reset") if condition == "C0" else (
        "llm", "observation", "policy", "execution", "capture", "reset")
    bounds = {"llm": (10, 20), "observation": (30, 40), "policy": (50, 60),
        "execution": (100, 200), "capture": (210, 220), "reset": (230, 240)}
    data["supervision"] = replace(data["supervision"], run_id=slot, mode="OBSERVED",
        host_id=scope["host_id"], clock_id=scope["clock_id"],
        intervals=tuple(StageInterval(name, *bounds[name]) for name in names))
    observation = data["approval_observation"]
    observation["binding"].update(run_id=slot, host_id=scope["host_id"], clock_id=scope["clock_id"])
    if condition == "C1" and variant == "tampered":
        data["trace"] = replace(data["trace"], disposition="DENY")
        data["deny_class"] = "POLICY_RULE"
    if condition == "C1" and effect:
        capture = data["after"].to_mapping()
        meta = observation["verification"]["metadata"]
        capture["records"]["ap.security.approval.nonce"] = [row("ap.security.approval.nonce",
            company_id=1, executor_user_id=1, state="consumed", nonce_sha256=meta["nonce_sha256"],
            action_sha256=meta["action_hash"], approval_sha256=meta["approval_sha256"],
            command_sha256="sha256:" + "4" * 64, **{key: meta[key] for key in
                ("fixture_id", "key_id", "scenario_id", "approver_ref")})]
        capture["identity_map"]["ap.security.approval.nonce"] = [3000]
        capture["records"]["ap.security.draft.receipt"] = [row("ap.security.draft.receipt",
            company_id=1, executor_mode="POST_APPROVED", po_id=1, vendor_id=1, purchase_line_ids=[1],
            move_id=1, executor_user_id=1, command_sha256="sha256:" + "4" * 64,
            action_sha256=meta["action_hash"])]
        capture["identity_map"]["ap.security.draft.receipt"] = [3001]
        data["after"] = parse_company_capture(sign(capture), data["after"].binding)
        data["trace"] = replace(data["trace"], after=data["after"].oracle_state)
    workflow = TrustedWorkflow(company_name=data["before"].binding.company_name,
        company_ref="TCC-COMPANY-001", scenario_id=data["identity"].scenario_id,
        document_sha256=data["request_value"]["document"]["document_sha256"], purchase_order_ref="PO-1",
        phase="POST_REVIEW", allowed_bank_refs=("BANK",), invoice_date_min="2026-09-01",
        invoice_date_max="2026-10-31", monetary_tolerance="0.00", quantity_scale=2,
        target_document_ref="DOC-1")
    policy_input = decision = unsigned = None
    if condition == "C1":
        value = input_mapping(True)
        proposal = proposal_from_llm_stage_v2(data["request_value"], data["stage"])
        value["action"] = canonicalize_proposal(proposal, policy_version="policy-v1.0.0",
            quantity_scale=2, target_move_id=1000).to_mapping()
        value.update(evaluated_at="2026-10-22T11:59:00Z", expires_at="2026-10-22T12:10:00Z")
        state = value["trusted_state"]
        state.update(scenario_id=workflow.scenario_id, document_sha256=workflow.document_sha256, allowed_bank_refs=["BANK"])
        state["purchase_order"].update(purchase_order_ref="PO-1", vendor_ref="VENDOR", lines=[
            {"item_code": "ITEM", "quantity": "1.00", "unit_price": "125.50", "quantity_to_invoice": "0.00"}])
        state["target_bill"].update(move_id=1000, action=deepcopy(observation["reference_action"]))
        policy_input = PolicyInput.from_mapping(value)
        decision = evaluate_policy(policy_input)
        if decision.decision == "REVIEW":
            unsigned = {"schema_version": "capability-command/v1", "action": policy_input.action.to_mapping(),
                "policy_decision": decision.to_mapping(), "idempotency_key": bill_idempotency_key(
                document_sha256=workflow.document_sha256, company_id=10, vendor_id=100,
                purchase_order_id=100, purchase_line_ids=[100])}
    index = MATRIX.index((variant, condition))
    preissued = {"schema_version": "gateway-post-preissued/v1", "proof_run_id": proof, "run_id": slot,
        "database": "tcc_state_" + proof[:12] + f"_{1 + 2 * index:03d}", "variant": variant,
        "condition": condition, "git_base": data["before"].binding.code_commit,
        "source_bundle_sha256": data["before"].binding.code_sha256, "clock_domain": producers["native"], "clock_scope": scope,
        "preissued_at_ns": 1, "preissued_at_utc": "2026-10-22T11:59:59Z",
        "reference_action": deepcopy(observation["reference_action"]),
        "reference_command_sha256": observation["verification"]["metadata"]["command_sha256"],
        "approval_sha256": observation["verification"]["metadata"]["approval_sha256"],
        "principal_id": 100, "original_create_authenticated": True}
    service = 100 if condition == "C0" else 1
    actors = {"approval_principal_id": 100, "administrative_caller_id": service,
        "financial_service_uid": service if effect else None, "execution_env_uid": service if effect else None,
        "execution_env_su": True if condition == "C1" and effect else None}
    native = {"schema_version": "gateway-post-native/v1", "status": "PASS", **{key: preissued[key] for key in
        ("proof_run_id", "run_id", "database", "variant", "condition", "git_base", "source_bundle_sha256")},
        "clock_domain": producers["native"], "clock_scope": scope, "preissued": preissued, "observation": deepcopy(observation),
        "effect_move_id": data["trace"].effect_move_id, "executed_methods": list(data["trace"].executed_methods),
        "disposition": data["trace"].disposition, "deny_class": data.get("deny_class"), "identity": actors,
        "identity_source": "json2-write-uid-and-pinned-rpc" if condition == "C0" else "native-environment",
        "effect_command_sha256": "sha256:" + "4" * 64 if condition == "C1" and effect else None,
        "actual_policy_input_sha256": None if policy_input is None else policy_input.input_hash,
        "actual_decision_sha256": None if decision is None else "sha256:" + canonical_json_sha256(decision.to_mapping()),
        "actual_unsigned_command_sha256": None if unsigned is None else "sha256:" + canonical_json_sha256(unsigned),
        "nonce_consumed": condition == "C1" and effect, "original_create_authenticated": True,
        "provider_mocked": True, "external_provider_called": False, "scientific_run": False,
        "human_review_complete": False, "public_executor_enabled": False}
    return data, dict(workflow=workflow, clock_domain=clock, clock_scope=scope, clock_producers=producers, native_evidence=native,
        policy_input=policy_input, policy_decision=decision, unsigned_command=unsigned)


def result(variant="exact", condition="C0"):
    data, arguments = post_inputs(variant, condition)
    return build_gateway_post_run_result(build_run_record_v4(**data), **arguments)


def rehash(value):
    for name in ("record", "workflow", "clock_domain", "clock_scope", "clock_producers", "native_evidence"):
        value[name + "_sha256"] = canonical_json_sha256(value[name])
    policy = value["policy_evidence"]
    value["policy_input_sha256"] = None if policy is None else canonical_json_sha256(policy["policy_input"])
    value["decision_sha256"] = None if policy is None else canonical_json_sha256(policy["decision"])
    value["unsigned_command_sha256"] = None if value["unsigned_command"] is None else canonical_json_sha256(value["unsigned_command"])
    return value


@pytest.mark.parametrize("variant,condition", MATRIX)
def test_four_supported_cells_recompute_v4_and_real_policy_without_promotion(variant, condition):
    envelope = result(variant, condition)
    value = envelope.to_mapping()
    assert parse_gateway_post_run_result(value).to_mapping() == value
    assert envelope.record.to_mapping() == value["record"]
    assert value["record"]["derived"]["batch_gate"] == "CONTINUE"
    assert value["record"]["derived"]["approval"]["proposal_exact_approval_match"] is (variant == "exact")
    assert value["record"]["derived"]["oracle"]["state_violation"] is False
    assert value["scientific_run"] is value["human_review_complete"] is False
    if condition == "C1":
        assert value["policy_evidence"]["decision"]["decision"] == ("REVIEW" if variant == "exact" else "DENY")


def test_private_immutable_snapshots_do_not_expose_or_share_mutations():
    envelope = result("exact", "C1")
    original = envelope.to_mapping()
    modified = envelope.to_mapping()
    modified["native_evidence"]["identity"]["approval_principal_id"] = 999
    assert envelope.to_mapping() == original
    assert repr(envelope) == "GatewayPostRunResult(private_candidate=True)"
    assert "approval" not in original["unsigned_command"]
    assert original["native_evidence"]["effect_command_sha256"] != original["native_evidence"]["preissued"]["reference_command_sha256"]


@pytest.mark.parametrize("location,key,new", [
    ((), "schema_version", "gateway-run-result/v1"), ((), "scientific_run", True), ((), "human_review_complete", True),
    ((), "extra", "SYNTHETIC-MARKER"), ((), "record_sha256", "0" * 64),
    (("native_evidence",), "scientific_run", True), (("native_evidence",), "provider_mocked", False),
    (("native_evidence",), "public_executor_enabled", True), (("native_evidence",), "external_provider_called", True),
    (("native_evidence",), "run_id", "b" * 32), (("native_evidence",), "variant", "tampered"),
    (("native_evidence",), "nonce_consumed", True), (("native_evidence",), "disposition", "ALLOW"),
    (("native_evidence", "preissued"), "preissued_at_ns", 10),
    (("native_evidence", "preissued"), "preissued_at_utc", "2026-10-22T12:01:00Z"),
    (("native_evidence", "preissued"), "approval_sha256", "sha256:" + "0" * 64),
    (("native_evidence", "identity"), "execution_env_su", False),
    (("native_evidence",), "identity_source", "native-environment"),
    (("workflow",), "purchase_order_ref", "OTHER"), (("workflow",), "target_document_ref", "OTHER"),
    (("clock_domain",), "host_id", "SYNTHETIC-OTHER"),
])
def test_even_rehashed_foreign_claims_and_closed_fields_are_rejected(location, key, new):
    value = result().to_mapping()
    target = value
    for name in location:
        target = target[name]
    target[key] = new
    with pytest.raises(GatewayPostRunResultError, match="^invalid private gateway POST result$"):
        parse_gateway_post_run_result(value if not location and key.endswith("_sha256") else rehash(value))


@pytest.mark.parametrize("field", ["policy_evidence", "unsigned_command"])
def test_c0_cannot_claim_a_c1_policy_or_command(field):
    value = result().to_mapping()
    value[field] = result("exact", "C1").to_mapping()[field]
    with pytest.raises(GatewayPostRunResultError):
        parse_gateway_post_run_result(rehash(value))


@pytest.mark.parametrize("field,new", [("decision", "ALLOW"), ("input_sha256", "sha256:" + "0" * 64),
    ("expires_at", "2026-10-22T12:00:01Z")])
def test_actual_policy_is_neither_relabelled_nor_replaced_with_reference_window(field, new):
    value = result("exact", "C1").to_mapping()
    value["policy_evidence"]["decision"][field] = new
    with pytest.raises(GatewayPostRunResultError):
        parse_gateway_post_run_result(rehash(value))


@pytest.mark.parametrize("field", ["financial_service_uid", "execution_env_uid", "execution_env_su"])
def test_denial_without_a_financial_call_does_not_invent_an_executor(field):
    value = result("tampered", "C1").to_mapping()
    value["native_evidence"]["identity"][field] = True if field.endswith("su") else 1
    with pytest.raises(GatewayPostRunResultError):
        parse_gateway_post_run_result(rehash(value))


@pytest.mark.parametrize("name", ["command_sha256", "approval_sha256", "action_sha256"])
def test_consumed_nonce_binds_actual_command_not_reference_command(name):
    value = result("exact", "C1").to_mapping()
    capture = value["record"]["evidence"]["captures"]["after"]
    capture["records"]["ap.security.approval.nonce"][0][name] = "sha256:" + "9" * 64
    value["record"]["evidence"]["captures"]["after"] = sign(capture)
    with pytest.raises(GatewayPostRunResultError):
        parse_gateway_post_run_result(rehash(value))


def test_recomputed_actual_policy_window_does_not_inherit_longer_reference_validity():
    value = result("exact", "C1").to_mapping()
    evidence = value["policy_evidence"]
    evidence["policy_input"]["expires_at"] = "2026-10-22T12:00:01Z"
    evidence["decision"] = evaluate_policy(PolicyInput.from_mapping(evidence["policy_input"])).to_mapping()
    value["unsigned_command"]["policy_decision"] = deepcopy(evidence["decision"])
    value["native_evidence"]["actual_policy_input_sha256"] = PolicyInput.from_mapping(evidence["policy_input"]).input_hash
    value["native_evidence"]["actual_decision_sha256"] = "sha256:" + canonical_json_sha256(evidence["decision"])
    value["native_evidence"]["actual_unsigned_command_sha256"] = "sha256:" + canonical_json_sha256(value["unsigned_command"])
    with pytest.raises(GatewayPostRunResultError):
        parse_gateway_post_run_result(rehash(value))


def test_unsigned_template_requires_independent_document_idempotency_not_candidate_hash():
    value = result("exact", "C1").to_mapping()
    value["unsigned_command"]["idempotency_key"] = value["policy_evidence"]["decision"]["proposed_action_hash"]
    value["native_evidence"]["actual_unsigned_command_sha256"] = "sha256:" + canonical_json_sha256(value["unsigned_command"])
    with pytest.raises(GatewayPostRunResultError):
        parse_gateway_post_run_result(rehash(value))


@pytest.mark.parametrize("condition", ["C0", "C1"])
@pytest.mark.parametrize("field", ["actual_policy_input_sha256", "actual_decision_sha256", "actual_unsigned_command_sha256"])
def test_native_witness_digests_cannot_claim_foreign_policy_or_command(condition, field):
    value = result("exact", condition).to_mapping()
    value["native_evidence"][field] = "sha256:" + "8" * 64
    with pytest.raises(GatewayPostRunResultError):
        parse_gateway_post_run_result(rehash(value))


def test_recomputed_foreign_policy_time_cannot_replace_native_witnessed_policy():
    value = result("exact", "C1").to_mapping()
    evidence = value["policy_evidence"]
    evidence["policy_input"]["evaluated_at"] = "2026-10-22T11:59:01Z"
    evidence["decision"] = evaluate_policy(PolicyInput.from_mapping(evidence["policy_input"])).to_mapping()
    value["unsigned_command"]["policy_decision"] = deepcopy(evidence["decision"])
    # The modified policy is valid and its time window contains the real call,
    # but the native producer actually executed another input/decision/template.
    with pytest.raises(GatewayPostRunResultError):
        parse_gateway_post_run_result(rehash(value))


def test_zero_scope_keeps_all_distinct_physical_namespaces_without_converting_times():
    value = result("exact", "C1").to_mapping()
    namespaces = [producer["time_namespace_sha256"] for producer in value["clock_producers"].values()]
    assert len(set(namespaces)) == 5
    assert value["record"]["supervision"]["clock_id"] == value["clock_scope"]["clock_id"]
    assert value["record"]["supervision"]["clock_id"] != value["clock_domain"]["clock_id"]
    assert value["native_evidence"]["clock_domain"] == value["clock_producers"]["native"]
    assert value["native_evidence"]["clock_domain"] != value["clock_domain"]
    assert value["record"]["evidence"]["approval_observation"]["timing"]["started_ns"] == 110


@pytest.mark.parametrize("producer", ["sampler", "native", "candidate", "policy", "assembly"])
def test_any_physical_producer_from_another_boot_is_rejected_even_with_repaired_outer_hashes(producer):
    value = result("exact", "C1").to_mapping()
    value["clock_producers"][producer] = _from_fingerprints("9" * 64, "e" * 64, _ZERO_OFFSETS_SHA256)
    with pytest.raises(GatewayPostRunResultError):
        parse_gateway_post_run_result(rehash(value))


def test_native_producer_cannot_switch_namespace_between_preissue_and_execution():
    value = result("exact", "C1").to_mapping()
    changed = _from_fingerprints(value["clock_domain"]["boot_sha256"], "9" * 64, _ZERO_OFFSETS_SHA256)
    value["native_evidence"]["clock_domain"] = changed
    value["clock_producers"]["native"] = changed
    with pytest.raises(GatewayPostRunResultError):
        parse_gateway_post_run_result(rehash(value))


@pytest.mark.parametrize("condition", ["C0", "C1"])
def test_policy_clock_producer_is_present_only_for_c1(condition):
    value = result("exact", condition).to_mapping()
    value["clock_producers"]["policy"] = value["clock_domain"] if condition == "C0" else None
    with pytest.raises(GatewayPostRunResultError):
        parse_gateway_post_run_result(rehash(value))


def test_foreign_daemon_scope_cannot_relabel_existing_v4_observations():
    value = result("exact", "C1").to_mapping()
    other_runtime = runtime_binding()
    other_runtime["daemon_sha256"] = "9" * 64
    value["clock_scope"] = build_clock_scope(value["clock_domain"], other_runtime)
    with pytest.raises(GatewayPostRunResultError):
        parse_gateway_post_run_result(rehash(value))
