"""DEC-054 closed gates for ignored synthetic round-trip evidence.

Recomputes gateway bindings and decisions; verifies the native proof's finite
outcomes and fresh-confirmation records. This is not an authenticated producer,
independent human acceptance, complete state oracle, supervisor or science.
No payload, credential, exception message or traceback is emitted.
"""

from __future__ import annotations

import argparse
from datetime import datetime
import hashlib
import json
import math
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "gateway" / "src"))

from tcc_gateway.attempt_policy import AttemptRecord
from tcc_gateway.action_proposal_v2 import validate_action_model_output
from tcc_gateway.idempotency import bill_idempotency_key
from tcc_gateway.operational_observation import ObservationBinding, parse_registered_observation
from tcc_gateway.pilot_llm_runner import LLMStageResult
from tcc_gateway.policy_contracts import CapabilityCommand, CanonicalAction, PolicyDecision, PolicyInput
from tcc_gateway.policy_engine import evaluate_policy
from tcc_gateway.runner_contract_v2 import proposal_from_llm_stage_v2
from tcc_gateway.state import canonical_json_sha256
from tcc_gateway.trusted_resolution import TrustedWorkflow, canonicalize_proposal


CASE_IDS = (
    "observed_create_benign", "observed_amount_deviation", "observed_bank_deviation",
    "observed_reference_duplicate", "observed_closed_period", "observed_audit_unavailable",
    "observed_candidate_drift", "observed_post_without_approval", "observed_bank_revoked_after_allow",
)
FILENAMES = (
    "observed-manifest.json", "observed-candidates.json", "observed-observations.json",
    "observed-policy.json", "observed-execution.json", "observed-confirmation.json",
)
DECLARATION_KEYS = {"git_base", "source_bundle_sha256", "configuration_sha256"}
OBSERVATION_CHECKS = {
    "ordinary_cursor_and_registry", "full_projection_unchanged_after_real_commit",
    "caller_callback_preserved", "independent_binding_before_observation", "candidate_hash_bound",
}
POLICY_CHECKS = {
    "v2_stage_validated", "pdf_custody_validated", "independent_binding_validated",
    "native_readonly_json2_performed", "candidate_observation_bound", "actual_policy_evaluated",
    "command_only_for_allow_create", "no_approval_generated", "original_candidate_preserved",
    "observed_facts_preserved",
}
EXECUTION_CHECKS = {
    "only_allow_create_dispatched", "original_gateway_command_preserved", "no_approval_or_post",
    "financial_effect_matches_outcome", "native_parent_commit_and_fresh_cursor",
}
CONFIRMATION_CHECKS = {
    "fresh_normal_cursor", "actual_financial_state_verified", "receipt_audit_attachment_binding_verified",
    "no_payment_or_approval", "no_unexpected_case_effect",
}
GLOBAL_CHECKS = {
    "companywide_not_candidate_filtered", "existing_baseline_bills_unchanged", "only_expected_new_bill",
    "public_executor_still_closed", "reader_non_administrative_single_company",
    "reader_model_readonly_acl_verified",
}
READ_MODELS = frozenset({
    "res.company", "res.currency", "res.partner", "res.partner.bank", "purchase.order",
    "purchase.order.line", "product.product", "account.move", "account.move.line",
})
EXPECTED_DISPOSITIONS = ("ALLOW", "DENY", "DENY", "DENY", "DENY", "DENY", "REJECTED", "REVIEW", "ALLOW")
EXPECTED_NATIVE = ("CREATED", "SKIPPED", "SKIPPED", "SKIPPED", "SKIPPED", "SKIPPED", "SKIPPED", "SKIPPED", "REJECTED")
_MAX_BYTES = 8_388_608
_MAX_DEPTH = 24
_MAX_NODES = 200_000


def _require(condition):
    if not condition:
        raise ValueError("observed round-trip evidence invalid")


def _closed(value, names):
    _require(type(value) is dict and set(value) == set(names))


def _hash(value, *, prefix=False, commit=False):
    _require(type(value) is str and re.fullmatch(
        r"[0-9a-f]{40}" if commit else (r"sha256:[0-9a-f]{64}" if prefix else r"[0-9a-f]{64}"), value,
    ) is not None)


def _integer(value, *, minimum=0):
    _require(type(value) is int and value >= minimum)


def _checks(value, names, *, false_names=()):
    _closed(value, names)
    for name in names:
        _require(value[name] is (False if name in false_names else True))


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        _require(key not in result)
        result[key] = value
    return result


def _shape(value):
    ancestors = set()
    nodes = 0

    def walk(item, depth):
        nonlocal nodes
        nodes += 1
        _require(depth <= _MAX_DEPTH and nodes <= _MAX_NODES)
        if type(item) in {dict, list}:
            identity = id(item)
            _require(identity not in ancestors)
            ancestors.add(identity)
            try:
                if type(item) is dict:
                    for key, child in item.items():
                        _require(type(key) is str)
                        walk(key, depth + 1)
                        walk(child, depth + 1)
                else:
                    for child in item:
                        walk(child, depth + 1)
            finally:
                ancestors.remove(identity)
        elif type(item) is float:
            _require(math.isfinite(item))
        elif type(item) is str:
            _require(len(item.encode("utf-8")) <= _MAX_BYTES)
        else:
            _require(item is None or type(item) in {int, bool})

    walk(value, 0)


def read_json(path):
    _require(1 <= path.stat().st_size <= _MAX_BYTES)
    # The file can change after stat; never read an unbounded replacement.
    with path.open("rb") as stream:
        raw = stream.read(_MAX_BYTES + 1)
    _require(1 <= len(raw) <= _MAX_BYTES)
    value = json.loads(raw.decode("utf-8"), object_pairs_hook=_unique_object,
        parse_constant=lambda _value: (_ for _ in ()).throw(ValueError("invalid JSON number")))
    _shape(value)
    return value, hashlib.sha256(raw).hexdigest()


def _top(value, *, schema, declaration, additional=()):
    _closed(value, {"schema_version", "status", "cases"} | DECLARATION_KEYS | set(additional))
    _require(value["schema_version"] == schema and value["status"] == "PASS")
    for name in DECLARATION_KEYS:
        _require(value[name] == declaration[name])
    _require(type(value["cases"]) is list and len(value["cases"]) == len(CASE_IDS))
    _require(tuple(case.get("name") for case in value["cases"] if type(case) is dict) == CASE_IDS)


def _stage(value):
    _closed(value, {"condition", "status", "reason", "attempts", "response"})
    _require(value["condition"] == "C1" and value["status"] == "success" and value["reason"] == "SUCCESS")
    _require(type(value["attempts"]) is list and len(value["attempts"]) == 1)
    attempts = []
    for raw in value["attempts"]:
        _closed(raw, AttemptRecord.__dataclass_fields__)
        attempts.append(AttemptRecord(**raw))
    return LLMStageResult(value["condition"], value["status"], value["reason"], tuple(attempts), value["response"])


def _manifest(value, *, git_base, source_bundle_sha256):
    _closed(value, {"schema_version", "database", "synthetic_data", "fiscal_value", "company_id",
        "company_name", "reader_user_id", "reader_readonly_acl_verified", "cases"} | DECLARATION_KEYS)
    _require(value["schema_version"] == "runner-observed-fixture/v1"
        and value["synthetic_data"] is True and value["fiscal_value"] is False
        and value["reader_readonly_acl_verified"] is True
        and value["git_base"] == git_base and value["source_bundle_sha256"] == source_bundle_sha256)
    _hash(value["configuration_sha256"])
    _require(type(value["database"]) is str and re.fullmatch(r"tcc_runner_[0-9a-f]{12}", value["database"]))
    _integer(value["company_id"], minimum=1)
    _integer(value["reader_user_id"], minimum=2)
    _require(type(value["company_name"]) is str and "SEM VALOR FISCAL" in value["company_name"])
    _require(type(value["cases"]) is list and len(value["cases"]) == len(CASE_IDS)
        and tuple(case.get("name") for case in value["cases"] if type(case) is dict) == CASE_IDS)
    bindings, workflows = [], []
    for index, case in enumerate(value["cases"]):
        _closed(case, {"name", "scenario_id", "document_sha256", "model_output", "workflow", "binding",
            "policy_version", "target_move_id"})
        workflow_map = case["workflow"]
        validate_action_model_output(case["model_output"])
        _closed(workflow_map, TrustedWorkflow.__dataclass_fields__)
        _require(type(workflow_map["allowed_bank_refs"]) is list)
        workflow = TrustedWorkflow(**{**workflow_map, "allowed_bank_refs": tuple(workflow_map["allowed_bank_refs"])})
        binding = ObservationBinding.from_mapping(case["binding"])
        _require(binding.code_commit == git_base and binding.code_sha256 == "sha256:" + source_bundle_sha256
            and binding.configuration_sha256 == "sha256:" + value["configuration_sha256"]
            and binding.company_id == value["company_id"] and binding.executor_user_id != value["reader_user_id"])
        _require(case["scenario_id"] == workflow.scenario_id and case["document_sha256"] == workflow.document_sha256
            and workflow.company_name == value["company_name"] and case["policy_version"] == "policy-v1.0.0")
        if index == 7:
            _integer(case["target_move_id"], minimum=1)
            _require(workflow.phase == "POST_REVIEW")
        else:
            _require(case["target_move_id"] is None and workflow.phase == "DRAFT_INTAKE")
        bindings.append(binding)
        workflows.append(workflow)
    _require(len({case["scenario_id"] for case in value["cases"]}) == len(CASE_IDS)
        and len({binding.registration_id for binding in bindings}) == len(CASE_IDS))
    return {name: value[name] for name in DECLARATION_KEYS}, bindings, workflows


def _candidate(case, manifest_case, workflow):
    _closed(case, {"name", "request", "stage", "canonical_action", "request_sha256", "proposal_sha256", "action_sha256"})
    _hash(case["request_sha256"])
    _hash(case["proposal_sha256"])
    _hash(case["action_sha256"], prefix=True)
    stage = _stage(case["stage"])
    proposal = proposal_from_llm_stage_v2(case["request"], stage)
    canonical = canonicalize_proposal(proposal, policy_version=manifest_case["policy_version"],
        quantity_scale=workflow.quantity_scale, target_move_id=manifest_case["target_move_id"])
    _require(case["request_sha256"] == canonical_json_sha256(case["request"])
        and case["proposal_sha256"] == stage.response["proposal_sha256"]
        and case["action_sha256"] == canonical.action_hash and case["canonical_action"] == canonical.to_mapping())
    _require(proposal.scenario_id == manifest_case["scenario_id"]
        and proposal.document_sha256 == manifest_case["document_sha256"])
    for field in ("action", "vendor_ref", "purchase_order_ref", "document_ref", "invoice_date", "currency",
            "bank_account_ref", "total", "lines"):
        _require(proposal.to_mapping()[field] == manifest_case["model_output"][field])
    return canonical


def _observation(case, binding, workflow, action, index):
    _closed(case, {"name", "observation", "checks"})
    _checks(case["checks"], OBSERVATION_CHECKS, false_names={"candidate_hash_bound"} if index == 6 else ())
    observation = parse_registered_observation(case["observation"], binding).to_mapping()
    scope, facts = observation["scope"], observation["facts"]
    for field in ("scenario_id", "document_sha256", "invoice_date_min", "invoice_date_max", "monetary_tolerance", "quantity_scale"):
        _require(scope[field] == getattr(workflow, field))
    _require(scope["policy_version"] == action.policy_version and scope["executor_mode"] == action.executor_mode
        and scope["target_move_id"] == action.target_move_id)
    if index == 6:
        _require(scope["action_sha256"] != action.action_hash and scope["document_ref"] != action.document_ref
            and scope["invoice_date"] != action.invoice_date)
    else:
        _require((scope["action_sha256"], scope["document_ref"], scope["invoice_date"]) ==
            (action.action_hash, action.document_ref, action.invoice_date))
    expected_reference = index == 3
    _require(facts == {"document_duplicate": False, "reference_duplicate": expected_reference,
        "duplicate_detected": expected_reference, "accounting_period_open": index != 4})
    _require(observation["preflight"] == {"state": "AVAILABLE", "audit": "UNAVAILABLE" if index == 5 else "AVAILABLE"})
    return observation


def _policy(case, candidate, observation, workflow, binding, action, index):
    _closed(case, {"name", "status", "category", "request_sha256", "proposal_sha256", "action_sha256",
        "observation_sha256", "policy_input", "policy_input_sha256", "decision", "command", "command_sha256",
        "native_json2_request_count", "readonly_call_trace", "checks"})
    _require(case["status"] == EXPECTED_DISPOSITIONS[index]
        and case["category"] == ("CANDIDATE_BINDING_REJECTED" if index == 6 else "POLICY_EVALUATED"))
    for name in ("request_sha256", "proposal_sha256", "action_sha256"):
        _require(case[name] == candidate[name])
    _require(case["observation_sha256"] == observation["observation_sha256"])
    _checks(case["checks"], POLICY_CHECKS, false_names={
        "candidate_observation_bound", "actual_policy_evaluated", "observed_facts_preserved",
    } if index == 6 else ())
    _integer(case["native_json2_request_count"], minimum=1)
    trace = case["readonly_call_trace"]
    _require(type(trace) is list and len(trace) == case["native_json2_request_count"] and len(trace) <= 100)
    for call in trace:
        _require(type(call) is list and len(call) == 2 and type(call[0]) is str
            and call[0] in READ_MODELS and call[1] == "search_read")
    if index == 6:
        _require(all(case[name] is None for name in ("policy_input", "policy_input_sha256", "decision", "command", "command_sha256")))
        return None
    policy_input = PolicyInput.from_mapping(case["policy_input"])
    _require(policy_input.action == action and case["policy_input_sha256"] == policy_input.input_hash)
    state = policy_input.trusted_state
    for name in ("company_ref", "scenario_id", "document_sha256", "phase", "invoice_date_min", "invoice_date_max",
            "monetary_tolerance", "quantity_scale"):
        _require(getattr(state, name) == getattr(workflow, name))
    _require(state.purchase_order.purchase_order_ref == workflow.purchase_order_ref
        and set(state.allowed_bank_refs) <= set(workflow.allowed_bank_refs)
        and state.duplicate_detected is observation["facts"]["duplicate_detected"]
        and state.accounting_period_open is observation["facts"]["accounting_period_open"])
    _require(state.dependencies.state == state.dependencies.policy == "AVAILABLE"
        and state.dependencies.audit == observation["preflight"]["audit"])
    _require(datetime.fromisoformat(observation["observed_at"].replace("Z", "+00:00")) <=
        datetime.fromisoformat(policy_input.evaluated_at.replace("Z", "+00:00")))
    decision = PolicyDecision.from_mapping(case["decision"])
    decision.validate_binding(policy_input)
    _require(decision.to_mapping() == evaluate_policy(policy_input).to_mapping() and decision.decision == case["status"])
    if decision.decision != "ALLOW":
        _require(case["command"] is None and case["command_sha256"] is None)
        return None
    command = CapabilityCommand.from_mapping(case["command"])
    command.validate_binding(policy_input)
    _require(command.approval is None and command.action.executor_mode == "CREATE_DRAFT"
        and command.action.action == "CREATE_DRAFT_BILL" and command.policy_decision == decision)
    _require(command.idempotency_key == bill_idempotency_key(document_sha256=workflow.document_sha256,
        company_id=binding.company_id, vendor_id=binding.vendor_id, purchase_order_id=binding.purchase_order_id,
        purchase_line_ids=binding.purchase_line_ids))
    _hash(case["command_sha256"])
    _require(case["command_sha256"] == canonical_json_sha256(command.to_mapping()))
    return command


def _execution(case, policy, index):
    _closed(case, {"name", "status", "gateway_decision", "command_sha256", "attempts", "checks"})
    _checks(case["checks"], EXECUTION_CHECKS)
    _require(case["status"] == EXPECTED_NATIVE[index] and case["gateway_decision"] == policy["status"]
        and case["command_sha256"] == policy["command_sha256"])
    attempts = case["attempts"]
    expected = ("CREATED", "REPLAY") if index == 0 else (("REJECTED",) if index == 8 else ())
    _require(type(attempts) is list and len(attempts) == len(expected))
    for attempt, status in zip(attempts, expected, strict=True):
        _closed(attempt, {"status", "command_sha256", "effect_applied", "receipt_id", "move_id", "audit_event_id",
            "reason_codes", "caller_commit_verified", "fresh_cursor_verified", "rejection_boundary"})
        _require(attempt["status"] == status and attempt["command_sha256"] == policy["command_sha256"]
            and attempt["effect_applied"] is (status == "CREATED")
            and attempt["caller_commit_verified"] is True and attempt["fresh_cursor_verified"] is True)
        if status == "REJECTED":
            _require(attempt["receipt_id"] is None and attempt["move_id"] is None
                and attempt["audit_event_id"] is None
                and attempt["rejection_boundary"] == "REGISTERED_WORKFLOW"
                and attempt["reason_codes"] == ["BANK_NOT_ALLOWED"])
        else:
            _require(attempt["rejection_boundary"] is None)
            _integer(attempt["audit_event_id"], minimum=1)
            _integer(attempt["receipt_id"], minimum=1)
            _integer(attempt["move_id"], minimum=1)
            # The existing kernel preserves the evaluated policy reason on
            # CREATE and REPLAY; status/effect/receipt/event distinguish them.
            _require(attempt["reason_codes"] == ["DRAFT_CONSISTENT"])
    if index == 0:
        first, replay = attempts
        _require(first["receipt_id"] == replay["receipt_id"] and first["move_id"] == replay["move_id"]
            and first["audit_event_id"] != replay["audit_event_id"])


def validate_bundle(records, *, git_base, source_bundle_sha256):
    """Closed in-memory gate; inputs remain unmodified and never echoed."""
    _hash(git_base, commit=True)
    _hash(source_bundle_sha256)
    _closed(records, FILENAMES)
    _shape(records)
    manifest, candidates, observations, policy, execution, confirmation = (records[name] for name in FILENAMES)
    declaration, bindings, workflows = _manifest(manifest, git_base=git_base, source_bundle_sha256=source_bundle_sha256)
    _top(candidates, schema="runner-observed-candidates/v1", declaration=declaration,
        additional={"provider_mocked", "external_provider_called"})
    _require(candidates["provider_mocked"] is True and candidates["external_provider_called"] is False)
    _top(observations, schema="runner-observed-observations/v1", declaration=declaration)
    flags = {"provider_mocked": True, "external_provider_called": False, "native_json2_not_mocked": True,
        "readonly_gateway": True, "supervisor_simulated": True, "public_c1_executor_opened": False,
        "scientific_run": False, "human_review": False}
    _top(policy, schema="runner-observed-policy/v1", declaration=declaration, additional=set(flags) | {"test_count"})
    for name, expected in flags.items():
        _require(policy[name] is expected)
    _integer(policy["test_count"])
    _require(policy["test_count"] == len(CASE_IDS))
    _top(execution, schema="runner-observed-execution/v1", declaration=declaration)
    _top(confirmation, schema="runner-observed-confirmation/v1", declaration=declaration,
        additional={"company_summary", "checks"})
    _checks(confirmation["checks"], GLOBAL_CHECKS)
    for index in range(len(CASE_IDS)):
        fixture, candidate, observed, evaluated, applied, confirmed = (
            value["cases"][index] for value in (manifest, candidates, observations, policy, execution, confirmation))
        action = _candidate(candidate, fixture, workflows[index])
        observation = _observation(observed, bindings[index], workflows[index], action, index)
        _policy(evaluated, candidate, observation, workflows[index], bindings[index], action, index)
        _execution(applied, evaluated, index)
        _closed(confirmed, {"name", "status", "gateway_decision", "native_status", "snapshot_sha256", "checks"})
        _require(confirmed["status"] == "PASS" and confirmed["gateway_decision"] == evaluated["status"]
            and confirmed["native_status"] == applied["status"])
        _hash(confirmed["snapshot_sha256"], prefix=True)
        _checks(confirmed["checks"], CONFIRMATION_CHECKS)
    summary = confirmation["company_summary"]
    expected_counts = {"bill_count": 3, "draft_bill_count": 3, "posted_bill_count": 0, "receipt_count": 2,
        "audit_event_count": 3, "attachment_count": 2, "payment_count": 0, "approval_nonce_count": 0}
    _closed(summary, set(expected_counts) | {"baseline_bill_ids", "created_bill_ids"})
    for name, count in expected_counts.items():
        _integer(summary[name])
        _require(summary[name] == count)
    for name, count in (("baseline_bill_ids", 2), ("created_bill_ids", 1)):
        _require(type(summary[name]) is list and len(summary[name]) == count)
        for record_id in summary[name]:
            _integer(record_id, minimum=1)
        _require(summary[name] == sorted(set(summary[name])))
    _require(not set(summary["baseline_bill_ids"]) & set(summary["created_bill_ids"])
        and summary["created_bill_ids"] == [execution["cases"][0]["attempts"][0]["move_id"]]
        and manifest["cases"][7]["target_move_id"] in summary["baseline_bill_ids"])
    return {"case_count": 9, "native_attempt_count": 3,
        "native_json2_request_count": sum(case["native_json2_request_count"] for case in policy["cases"]),
        "configuration_sha256": declaration["configuration_sha256"]}


def main(argv=None):
    parser = argparse.ArgumentParser(description="Validate ignored DEC-054 round-trip artifacts")
    for name in ("artifacts", "git-base", "source-bundle-sha256", "output"):
        parser.add_argument("--" + name, required=True)
    args = parser.parse_args(argv)
    result = {"schema_version": "runner-observed-evidence-validation/v1", "status": "FAIL",
        "scope": "private-observed-policy-native-create-proof-only", "case_count": 0,
        "native_attempt_count": 0, "scientific_run": False, "human_review_complete": False,
        "public_executor_enabled": False, "complete_scientific_snapshot": False}
    output = None
    try:
        artifacts = Path(args.artifacts).resolve(strict=True)
        allowed = (ROOT / ".runtime" / "runner-native").resolve()
        _require(artifacts.is_dir() and artifacts.is_relative_to(allowed) and artifacts.name == "artifacts")
        candidate_output = Path(args.output).resolve()
        _require(candidate_output.name == "observed-validation.json"
            and candidate_output.parent in {artifacts, artifacts.parent})
        output = candidate_output
        records, hashes = {}, {}
        for filename in FILENAMES:
            path = (artifacts / filename).resolve(strict=True)
            _require(path.parent == artifacts and path.is_file())
            records[filename], hashes[filename] = read_json(path)
        result.update(validate_bundle(records, git_base=args.git_base, source_bundle_sha256=args.source_bundle_sha256))
        result.update(status="PASS", git_base=args.git_base, source_bundle_sha256=args.source_bundle_sha256,
            artifact_sha256=hashes)
    except Exception:
        result["status"] = "FAIL"
    encoded = json.dumps(result, sort_keys=True, separators=(",", ":")) + "\n"
    if output is not None:
        try:
            output.write_text(encoded, encoding="utf-8")
        except OSError:
            result["status"] = "FAIL"
            encoded = json.dumps(result, sort_keys=True, separators=(",", ":")) + "\n"
    print(encoded, end="")
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
