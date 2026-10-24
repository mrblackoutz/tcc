# SPDX-License-Identifier: LGPL-3.0-or-later
"""DEC-078 gateway-only assembly after a disposable CREATE and verified reset.

Despite the historical probe naming, this process runs in the gateway image,
never imports Odoo, performs no financial call and loads no credential. It
preserves the actual mocked-provider stage, policy, captures and host timing.
Raw output is private evidence, not a publication or scientific run.
"""

import argparse
import hashlib
import json
import logging
from pathlib import Path
import re


MATRIX = tuple((case, condition) for case in ("benign", "amount", "bank") for condition in ("C0", "C1"))
CONTEXT_FIELDS = frozenset({"schema_version", "proof_run_id", "slot_run_id", "database", "restored_database",
    "case", "condition", "git_base", "source_bundle_sha256", "policy_sha256", "supervision",
    "scientific_run", "human_review_complete"})
VERSION = "gateway-record-native/v1"
MAX_OUTPUT_BYTES = 128 * 1024 * 1024


def require(value):
    if not value:
        raise ValueError("GATEWAY_RECORD_ASSEMBLY_INVALID")


def schedule_sha256():
    return hashlib.sha256(json.dumps(MATRIX, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")).hexdigest()


def slot_id(proof_run_id, case, condition):
    require(type(proof_run_id) is str and re.fullmatch(r"[0-9a-f]{32}", proof_run_id)
            and (case, condition) in MATRIX)
    return hashlib.sha256((proof_run_id + ":" + case + ":" + condition).encode("ascii")).hexdigest()[:32]


def validate_options(args):
    for name, pattern in (("proof_run_id", r"[0-9a-f]{32}"), ("slot_run_id", r"[0-9a-f]{32}"),
                          ("git_base", r"[0-9a-f]{40}"), ("source_bundle_sha256", r"[0-9a-f]{64}")):
        value = getattr(args, name, None)
        require(type(value) is str and re.fullmatch(pattern, value))
    require(type(args.case) is str and type(args.condition) is str and (args.case, args.condition) in MATRIX
            and args.artifacts == "/mnt/runner-artifacts"
            and args.slot_run_id == slot_id(args.proof_run_id, args.case, args.condition))
    generation = 1 + 2 * MATRIX.index((args.case, args.condition))
    require(args.database == "tcc_state_" + args.proof_run_id[:12] + f"_{generation:03d}")


def validate_context(value, args, binding):
    from tcc_gateway.run_supervision import RunSupervision
    require(type(value) is dict and set(value) == CONTEXT_FIELDS
            and value["schema_version"] == "gateway-record-context/v1"
            and value["scientific_run"] is False and value["human_review_complete"] is False)
    for name in ("proof_run_id", "slot_run_id", "database", "case", "condition", "git_base", "source_bundle_sha256"):
        require(value[name] == getattr(args, name))
    generation = 2 + 2 * MATRIX.index((args.case, args.condition))
    require(value["restored_database"] == "tcc_state_" + args.proof_run_id[:12] + f"_{generation:03d}"
            and type(value["policy_sha256"]) is str and re.fullmatch(r"[0-9a-f]{64}", value["policy_sha256"]))
    supervision = RunSupervision.from_mapping(value["supervision"])
    supervision.validate_binding(run_id=args.slot_run_id, condition=args.condition,
        code_commit=args.git_base, configuration_sha256=binding.configuration_sha256)
    stages = ("llm", "execution", "capture", "reset") if args.condition == "C0" else (
        "llm", "observation", "policy", "execution", "capture", "reset")
    require(supervision.mode == "OBSERVED" and supervision.effect_quiescence == "CONFIRMED"
            and tuple(interval.name for interval in supervision.intervals) == stages)
    return supervision


def write_exclusive(path, value):
    """Write once inside the fixed private artifact mount, without following links."""
    from tcc_gateway import run_record_store as fs
    from tcc_gateway.state import canonical_json_bytes
    raw = canonical_json_bytes(value)
    require(len(raw) <= MAX_OUTPUT_BYTES)
    directory = path.parent
    identity = fs._identity(fs._directory_chain(directory))
    fs._write_exclusive(path, raw)
    fs._verify_directory(directory, identity)
    require(fs._read_bounded(path, MAX_OUTPUT_BYTES) == raw)
    fs._verify_directory(directory, identity)


def policy_evidence(saved, effect, policy, case):
    """Bind a preserved C1 command to the actual input/decision, not its label."""
    from tcc_gateway.policy_contracts import CapabilityCommand, PolicyDecision, PolicyInput
    from tcc_gateway.policy_engine import evaluate_policy
    from tcc_gateway.state import canonical_json_sha256
    from runner_observed_gateway import POLICY_CHECKS, READ_MODELS
    require(type(policy) is dict and set(policy) == {"name", "status", "category", "request_sha256",
        "proposal_sha256", "action_sha256", "observation_sha256", "policy_input", "policy_input_sha256",
        "decision", "command", "command_sha256", "native_json2_request_count", "readonly_call_trace", "checks"}
        and policy["name"] == case["name"] and policy["category"] == "POLICY_EVALUATED"
        and all(policy[name] == saved[name] for name in ("request_sha256", "proposal_sha256", "action_sha256"))
        and type(policy["native_json2_request_count"]) is int and policy["native_json2_request_count"] > 0)
    require(type(policy["checks"]) is dict and set(policy["checks"]) == POLICY_CHECKS
            and all(value is True for value in policy["checks"].values())
            and type(policy["readonly_call_trace"]) is list
            and len(policy["readonly_call_trace"]) == policy["native_json2_request_count"]
            and all(type(row) is list and len(row) == 2 and row[0] in READ_MODELS and row[1] == "search_read"
                    for row in policy["readonly_call_trace"]))
    policy_input = PolicyInput.from_mapping(policy["policy_input"])
    decision = PolicyDecision.from_mapping(policy["decision"])
    decision.validate_binding(policy_input)
    require(evaluate_policy(policy_input) == decision
            and policy_input.input_hash == policy["policy_input_sha256"]
            and policy_input.action.to_mapping() == saved["canonical_action"]
            and decision.decision == policy["status"] == effect["disposition"])
    if decision.decision == "ALLOW":
        command = CapabilityCommand.from_mapping(policy["command"])
        command.validate_binding(policy_input)
        require(command.policy_decision == decision and command.approval is None
                and command.action.action == "CREATE_DRAFT_BILL" and command.action.executor_mode == "CREATE_DRAFT"
                and canonical_json_sha256(command.to_mapping()) == policy["command_sha256"]
                and effect["methods"] == ["account.move.create"]
                and type(effect["move_id"]) is int and effect["move_id"] > 0
                and type(effect["receipt_id"]) is int and effect["receipt_id"] > 0)
    else:
        require(decision.decision == "DENY" and policy["command"] is None and policy["command_sha256"] is None
                and effect["methods"] == [] and effect["move_id"] is None and effect["receipt_id"] is None)
    return policy_input, decision


def assemble(args):
    validate_options(args)
    from state_oracle_gateway import captures, inputs, saved_stage
    from runner_observed_gateway import parse_workflow, read_artifact
    from tcc_gateway.company_capture import CaptureBinding, ExpectedEffect, ExpectedInvoiceLine, assert_restored, parse_company_capture
    from tcc_gateway.gateway_run_result import build_gateway_run_result, parse_gateway_run_result
    from tcc_gateway.oracle import BillFacts, OracleCase, OracleProposal, OracleTrace
    from tcc_gateway.run_record import RunIdentity
    from tcc_gateway.run_record_v4 import build_run_record_v4
    from tcc_gateway.runner_contract_v2 import proposal_from_llm_stage_v2
    from tcc_gateway.state import canonical_json_sha256
    from tcc_gateway.trusted_resolution import canonicalize_proposal

    root, stem, manifest, binding_value, case_row = inputs(args)
    binding = CaptureBinding.from_mapping(binding_value)
    context = read_artifact(stem.with_suffix(".record-context.json"))
    supervision = validate_context(context, args, binding)
    from tcc_gateway import policy_engine
    require(hashlib.sha256(Path(policy_engine.__file__).read_bytes()).hexdigest() == context["policy_sha256"])
    baseline, before = captures(args, "before")
    assert_restored(baseline, before)
    after = parse_company_capture(read_artifact(root / (args.database + "-after.capture.json")), binding)
    restored = parse_company_capture(read_artifact(root / (context["restored_database"] + "-restored.capture.json")), binding)
    assert_restored(baseline, restored)
    saved = read_artifact(stem.with_suffix(".candidate.json"))
    require(set(saved) == {"name", "request", "stage", "canonical_action", "request_sha256", "proposal_sha256", "action_sha256"}
            and saved["name"] == args.case)
    stage = saved_stage(saved, args.condition)
    require(stage.condition == args.condition)
    proposal = proposal_from_llm_stage_v2(saved["request"], stage)
    workflow = parse_workflow(case_row["workflow"])
    canonical = canonicalize_proposal(proposal, policy_version=case_row["policy_version"], quantity_scale=workflow.quantity_scale,
                                      target_move_id=None)
    require(canonical.action == "CREATE_DRAFT_BILL" and canonical.executor_mode == "CREATE_DRAFT"
            and canonical.to_mapping() == saved["canonical_action"] and canonical.action_hash == saved["action_sha256"]
            and canonical_json_sha256(saved["request"]) == saved["request_sha256"]
            and canonical_json_sha256(proposal.to_mapping()) == saved["proposal_sha256"])
    effect = read_artifact(stem.with_suffix(".effect.json"))
    require(set(effect) == {"move_id", "methods", "disposition", "receipt_id", "provider_mocked", "committed_effect_confirmed"}
            and effect["provider_mocked"] is True and effect["committed_effect_confirmed"] is True)
    policy_input = decision = None
    deny_class = None
    if args.condition == "C1":
        from tcc_gateway.operational_observation import ObservationBinding, parse_registered_observation
        policy = read_artifact(stem.with_suffix(".policy.json"))
        policy_input, decision = policy_evidence(saved, effect, policy, case_row)
        observation = parse_registered_observation(read_artifact(stem.with_suffix(".observation.json")),
                                                   ObservationBinding.from_mapping(case_row["binding"])).to_mapping()
        require(policy["observation_sha256"] == observation["observation_sha256"]
                and observation["scope"]["action_sha256"] == canonical.action_hash
                and policy_input.trusted_state.duplicate_detected == observation["facts"]["duplicate_detected"]
                and policy_input.trusted_state.accounting_period_open == observation["facts"]["accounting_period_open"])
        deny_class = decision.deny_class
    else:
        dispatch = read_artifact(stem.with_suffix(".dispatch.json"))
        require(set(dispatch) == set(effect) - {"committed_effect_confirmed"}
                and all(effect[name] == value for name, value in dispatch.items())
                and effect["disposition"] == "ALLOW_EFFECTIVE" and effect["methods"] == ["account.move.create"]
                and type(effect["move_id"]) is int and effect["move_id"] > 0 and effect["receipt_id"] is None)
    original = next(row for row in manifest["native_cases"] if row["name"] == args.case)["command"]["action"]
    expected = BillFacts(original["vendor_ref"], original["purchase_order_ref"], original["document_ref"],
        original["amount"], original["currency"], original["recipient_bank_ref"], "draft")
    family, field = {"benign": (None, None), "amount": ("A1", "amount"), "bank": ("A2", "bank_ref")}[args.case]
    case = OracleCase(case_row["scenario_id"], binding.company_name, "benign" if args.case == "benign" else "adversarial",
        "CREATE_DRAFT_BILL", expected, family, field)
    trace = OracleTrace(args.condition, True, True, True, True, OracleProposal.from_action_proposal_v2(proposal),
        effect["disposition"], False, tuple(effect["methods"]), before.oracle_state, after.oracle_state,
        effect_move_id=effect["move_id"])
    expected_rows = manifest["expected_effects"]["create"]
    expected_effect = ExpectedEffect(expected_rows["invoice_date"], tuple(ExpectedInvoiceLine(**row) for row in expected_rows["lines"]))
    identity = RunIdentity(args.slot_run_id, case.scenario_id, "TCC-GATEWAY-RECORD-" + args.case.upper(), args.condition,
        1, MATRIX.index((args.case, args.condition)) + 1, schedule_sha256(), "MOCKED")
    document_path = root / (args.case + ".pdf")
    require(0 < document_path.stat().st_size <= 1_048_576)
    with document_path.open("rb") as stream:
        document_bytes = stream.read(1_048_577)
    require(len(document_bytes) <= 1_048_576)
    record = build_run_record_v4(identity=identity, document_bytes=document_bytes, request_value=saved["request"], stage=stage,
        policy_sha256=context["policy_sha256"], supervision=supervision, case=case, trace=trace, expected_effect=expected_effect,
        baseline=baseline, before=before, after=after, restored=restored, deny_class=deny_class)
    result = build_gateway_run_result(record, workflow=workflow, policy_input=policy_input, policy_decision=decision)
    value = result.to_mapping()
    require(value["record"]["derived"]["batch_gate"] == "CONTINUE"
            and value["record"]["derived"]["assessment_status"] == "EVALUATED")
    write_exclusive(stem.with_suffix(".gateway-run.json"), value)
    # Do not accept an in-memory success when the persisted representation fails
    # its own closed parser. The exclusive file is deliberately never replaced.
    from tcc_gateway import run_record_store as fs
    persisted = fs._json(fs._read_bounded(stem.with_suffix(".gateway-run.json"), MAX_OUTPUT_BYTES))
    require(parse_gateway_run_result(persisted).to_mapping() == value)
    receipt = {"schema_version": VERSION, "status": "PASS", "proof_run_id": args.proof_run_id,
        "database": args.database, "restored_database": context["restored_database"], "case": args.case,
        "condition": args.condition, "git_base": args.git_base, "source_bundle_sha256": args.source_bundle_sha256,
        "record_sha256": canonical_json_sha256(value["record"]), "wrapper_sha256": canonical_json_sha256(value),
        "run_id": args.slot_run_id, "policy_applicable": args.condition == "C1", "record_version": "run-record/v4",
        "batch_gate": value["record"]["derived"]["batch_gate"], "scientific_run": False,
        "human_review_complete": False, "provider_mocked": True, "external_provider_called": False}
    write_exclusive(stem.with_suffix(".gateway-result.json"), receipt)
    return receipt


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("database", "git-base", "source-bundle-sha256", "proof-run-id", "slot-run-id"):
        parser.add_argument("--" + name, required=True)
    parser.add_argument("--case", choices=("benign", "amount", "bank"), required=True)
    parser.add_argument("--condition", choices=("C0", "C1"), required=True)
    parser.add_argument("--artifacts", default="/mnt/runner-artifacts")
    args = parser.parse_args(argv)
    logging.disable(logging.CRITICAL)
    try:
        assemble(args)
    except Exception:
        # No traceback, path, native body or received text escapes to stdout.
        print("GATEWAY_RECORD_ASSEMBLY_FAILED")
        return 1
    print("GATEWAY_RECORD_ASSEMBLY_PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
