"""DEC-078 gateway assembly boundaries; no Docker, Odoo or provider network.

Policy fixtures exercise the real deterministic evaluator and contracts. The
separate disposable native proof validates accounting/reset and integration.
"""

from copy import deepcopy
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from tcc_gateway.policy_contracts import CapabilityCommand, PolicyInput
from tcc_gateway.policy_engine import evaluate_policy
from tcc_gateway.run_supervision import RunSupervision, StageInterval
from tcc_gateway.state import canonical_json_bytes, canonical_json_sha256


ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "odoo/probes/gateway_record_native.py"


def load_probe():
    spec = importlib.util.spec_from_file_location("_tcc_gateway_record_native_test", SOURCE)
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


probe = load_probe()


@pytest.fixture(autouse=True)
def probe_imports(monkeypatch):
    monkeypatch.syspath_prepend(str(ROOT / "odoo/probes"))


def options(case="benign", condition="C0", **changes):
    proof = "a" * 32
    generation = 1 + 2 * probe.MATRIX.index((case, condition))
    value = dict(proof_run_id=proof, slot_run_id=probe.slot_id(proof, case, condition), git_base="b" * 40,
        source_bundle_sha256="c" * 64, database="tcc_state_" + proof[:12] + f"_{generation:03d}",
        case=case, condition=condition, artifacts="/mnt/runner-artifacts")
    return SimpleNamespace(**dict(value, **changes))


def context(args):
    names = ("llm", "execution", "capture", "reset") if args.condition == "C0" else (
        "llm", "observation", "policy", "execution", "capture", "reset")
    supervision = RunSupervision(args.slot_run_id, args.condition, args.git_base, "d" * 64,
        "host-test", "clock-test", "OBSERVED", "CONFIRMED",
        tuple(StageInterval(name, index * 10, index * 10 + 9) for index, name in enumerate(names)))
    return {"schema_version": "gateway-record-context/v1", "proof_run_id": args.proof_run_id,
        "slot_run_id": args.slot_run_id, "database": args.database,
        "restored_database": "tcc_state_" + args.proof_run_id[:12] + f"_{2 + 2 * probe.MATRIX.index((args.case, args.condition)):03d}",
        "case": args.case, "condition": args.condition, "git_base": args.git_base,
        "source_bundle_sha256": args.source_bundle_sha256, "policy_sha256": "e" * 64,
        "supervision": supervision.to_mapping(), "scientific_run": False, "human_review_complete": False}


@pytest.mark.parametrize("case,condition", probe.MATRIX)
def test_valid_options_and_context_preserve_host_clock_and_slot(case, condition):
    args = options(case, condition)
    assert probe.validate_options(args) is None
    value = context(args)
    checked = probe.validate_context(value, args, SimpleNamespace(configuration_sha256="d" * 64))
    assert checked.to_mapping() == value["supervision"]
    assert checked.mode == "OBSERVED"


@pytest.mark.parametrize("name,replacement", [
    ("proof_run_id", "a" * 31), ("slot_run_id", "0" * 32), ("git_base", "b" * 39),
    ("source_bundle_sha256", "sha256:" + "c" * 64), ("database", "tcc_state_" + "a" * 12 + "_003"),
    ("database", "../tcc_state_" + "a" * 12 + "_001"), ("case", "post"), ("condition", "C2"),
    ("artifacts", "/mnt/runner-artifacts/../secret"), ("slot_run_id", True),
])
def test_invalid_options_fail_before_artifacts_or_dynamic_dependencies(name, replacement, monkeypatch):
    import builtins
    original = builtins.__import__

    def guarded(module, *args, **kwargs):
        if module.startswith(("tcc_gateway", "state_oracle_gateway", "runner_observed_gateway", "odoo")):
            pytest.fail("invalid options reached dynamic dependencies")
        return original(module, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", guarded)
    args = options()
    setattr(args, name, replacement)
    with pytest.raises(ValueError, match="^GATEWAY_RECORD_ASSEMBLY_INVALID$"):
        probe.assemble(args)


@pytest.mark.parametrize("name,replacement", [
    ("schema_version", "gateway-record-context/v2"), ("proof_run_id", "f" * 32),
    ("slot_run_id", "f" * 32), ("database", "FOREIGN"), ("restored_database", "FOREIGN"),
    ("case", "bank"), ("condition", "C1"), ("git_base", "f" * 40),
    ("source_bundle_sha256", "f" * 64), ("policy_sha256", "sha256:" + "e" * 64),
    ("policy_sha256", True), ("scientific_run", True), ("human_review_complete", True),
    ("unapproved_extra", "ignored"),
])
def test_context_cannot_be_relabelled_or_promoted(name, replacement):
    args = options()
    value = context(args)
    value[name] = replacement
    with pytest.raises(ValueError):
        probe.validate_context(value, args, SimpleNamespace(configuration_sha256="d" * 64))


@pytest.mark.parametrize("field,replacement", [
    ("run_id", "f" * 32), ("condition", "C1"), ("code_commit", "f" * 40),
    ("configuration_sha256", "f" * 64), ("mode", "MOCKED"), ("effect_quiescence", "UNKNOWN"),
])
def test_context_requires_observed_same_bound_supervision(field, replacement):
    args = options()
    value = context(args)
    value["supervision"][field] = replacement
    with pytest.raises(ValueError):
        probe.validate_context(value, args, SimpleNamespace(configuration_sha256="d" * 64))


def test_context_cannot_hide_policy_interval_or_move_it_into_llm():
    args = options(condition="C1")
    value = context(args)
    value["supervision"]["intervals"].pop(2)
    with pytest.raises(ValueError):
        probe.validate_context(value, args, SimpleNamespace(configuration_sha256="d" * 64))


def policy_inputs(deny=False):
    from runner_observed_gateway import POLICY_CHECKS
    vector = json.loads((ROOT / "gateway/tests/fixtures/canonical_action_v1.vector.json").read_text(encoding="utf-8"))
    action = vector["action"]
    trusted_lines = deepcopy(action["lines"])
    if deny:
        action["recipient_bank_ref"] = "TCC-BANK-UNAPPROVED"
    value = {"schema_version": "policy-input/v1", "action": action,
        "evaluated_at": "2026-09-30T12:00:00Z", "expires_at": "2026-09-30T12:10:00Z",
        "trusted_state": {"company_ref": "TCC-COMPANY-001", "scenario_id": action["scenario_id"],
            "document_sha256": action["document_sha256"], "phase": "DRAFT_INTAKE",
            "purchase_order": {"purchase_order_ref": action["purchase_order_ref"], "vendor_ref": action["vendor_ref"],
                "currency": "BRL", "confirmed": True, "amount": "125.50",
                "lines": [{**line, "quantity_to_invoice": "1.00"} for line in trusted_lines]},
            "allowed_bank_refs": ["TCC-BANK-001"], "duplicate_detected": False,
            "invoice_date_min": "2026-09-01", "invoice_date_max": "2026-10-31",
            "accounting_period_open": True, "monetary_tolerance": "0.00", "quantity_scale": 2,
            "dependencies": {"state": "AVAILABLE", "policy": "AVAILABLE", "audit": "AVAILABLE"}, "target_bill": None}}
    typed = PolicyInput.from_mapping(value)
    decision = evaluate_policy(typed)
    command = None if deny else CapabilityCommand(typed.action, decision, "sha256:" + "f" * 64).to_mapping()
    saved = {"request_sha256": "a" * 64, "proposal_sha256": "b" * 64,
        "action_sha256": typed.action.action_hash, "canonical_action": action}
    effect = {"disposition": decision.decision, "methods": [] if deny else ["account.move.create"],
        "move_id": None if deny else 123, "receipt_id": None if deny else 456}
    policy = {"name": "bank" if deny else "benign", "status": decision.decision, "category": "POLICY_EVALUATED",
        **{name: saved[name] for name in ("request_sha256", "proposal_sha256", "action_sha256")},
        "observation_sha256": "c" * 64, "policy_input": typed.to_mapping(), "policy_input_sha256": typed.input_hash,
        "decision": decision.to_mapping(), "command": command,
        "command_sha256": canonical_json_sha256(command) if command else None,
        "native_json2_request_count": 1, "readonly_call_trace": [["res.company", "search_read"]],
        "checks": {name: True for name in POLICY_CHECKS}}
    return saved, effect, policy, {"name": policy["name"]}


@pytest.mark.parametrize("deny", [False, True])
def test_actual_policy_input_and_command_are_bound_without_changing_candidate(deny):
    inputs = policy_inputs(deny)
    original = deepcopy(inputs)
    typed, decision = probe.policy_evidence(*inputs)
    assert decision == evaluate_policy(typed)
    assert decision.decision == ("DENY" if deny else "ALLOW")
    assert inputs == original


@pytest.mark.parametrize("location,key,value", [
    ("policy", "status", "DENY"), ("policy", "request_sha256", "d" * 64),
    ("policy", "proposal_sha256", "d" * 64), ("policy", "action_sha256", "sha256:" + "d" * 64),
    ("policy", "policy_input_sha256", "sha256:" + "d" * 64), ("policy", "command_sha256", "d" * 64),
    ("policy", "native_json2_request_count", True), ("policy", "native_json2_request_count", 0),
    ("policy", "readonly_call_trace", [["account.move", "create"]]), ("policy", "checks", {}),
    ("effect", "disposition", "DENY"), ("effect", "methods", ["account.move.action_post"]),
    ("effect", "move_id", True), ("effect", "receipt_id", None),
    ("policy", "extra", "SHOULD_NOT_PERSIST"),
])
def test_policy_or_effect_tampering_fails_before_record(location, key, value):
    saved, effect, policy, case = policy_inputs()
    {"policy": policy, "effect": effect}[location][key] = value
    with pytest.raises(ValueError):
        probe.policy_evidence(saved, effect, policy, case)


def test_policy_binding_alone_cannot_replace_deterministic_reevaluation():
    saved, effect, policy, case = policy_inputs(deny=True)
    # A manually bound ALLOW is structurally valid but disagrees with the rules.
    from tcc_gateway.policy_contracts import PolicyDecision, ReasonCode
    typed = PolicyInput.from_mapping(policy["policy_input"])
    forged = PolicyDecision.for_input(typed, decision="ALLOW", reason_codes=(ReasonCode.DRAFT_CONSISTENT,))
    policy.update(decision=forged.to_mapping(), status="ALLOW")
    effect["disposition"] = "ALLOW"
    with pytest.raises(ValueError):
        probe.policy_evidence(saved, effect, policy, case)


def test_exclusive_output_is_canonical_and_cannot_overwrite(tmp_path):
    path = tmp_path / "gateway-run.json"
    value = {"private": True, "body": ["synthetic"]}
    probe.write_exclusive(path, value)
    assert path.read_bytes() == canonical_json_bytes(value)
    with pytest.raises(FileExistsError):
        probe.write_exclusive(path, {"replaced": True})
    assert path.read_bytes() == canonical_json_bytes(value)


def test_cli_failure_never_prints_received_exception_text(monkeypatch, capsys):
    def failed(_args):
        raise ValueError("PRIVATE-SYNTHETIC-MARKER")

    monkeypatch.setattr(probe, "assemble", failed)
    args = options()
    argv = [value for name in ("database", "git_base", "source_bundle_sha256", "proof_run_id", "slot_run_id", "case", "condition")
            for value in ("--" + name.replace("_", "-"), getattr(args, name))]
    assert probe.main(argv) == 1
    assert capsys.readouterr().out == "GATEWAY_RECORD_ASSEMBLY_FAILED\n"


def test_full_c0_assembly_preserves_real_mocked_stage_and_roundtrips_private_wrapper(tmp_path, monkeypatch):
    """Offline captures are explicit doubles; no native effect is claimed here."""
    import hashlib
    from tempfile import TemporaryDirectory
    monkeypatch.syspath_prepend(str(ROOT / "gateway/tests"))
    import test_run_record
    from test_run_record import valid_inputs
    from runner_observed_gateway import stage_to_mapping
    import runner_observed_gateway
    import state_oracle_gateway
    from tcc_gateway import policy_engine
    from tcc_gateway.gateway_run_result import parse_gateway_run_result
    from tcc_gateway.runner_contract_v2 import proposal_from_llm_stage_v2
    from tcc_gateway.trusted_resolution import canonicalize_proposal

    monkeypatch.setattr(test_run_record, "TemporaryDirectory", lambda: TemporaryDirectory(dir=tmp_path))
    inputs = valid_inputs("C0")
    binding = inputs["before"].binding
    args = options(git_base=binding.code_commit, source_bundle_sha256=binding.code_sha256)
    ctx = context(args)
    ctx["supervision"]["configuration_sha256"] = binding.configuration_sha256
    ctx["policy_sha256"] = hashlib.sha256(Path(policy_engine.__file__).read_bytes()).hexdigest()
    proposal = proposal_from_llm_stage_v2(inputs["request_value"], inputs["stage"])
    action = canonicalize_proposal(proposal, policy_version="policy-v1.0.0", quantity_scale=2)
    workflow = {"company_name": binding.company_name, "company_ref": "TCC-COMPANY-001",
        "scenario_id": proposal.scenario_id, "document_sha256": proposal.document_sha256,
        "purchase_order_ref": action.purchase_order_ref, "phase": "DRAFT_INTAKE",
        "allowed_bank_refs": [action.recipient_bank_ref], "invoice_date_min": "2026-09-01",
        "invoice_date_max": "2026-10-31", "monetary_tolerance": "0.00", "quantity_scale": 2,
        "target_document_ref": None}
    row = {"name": "benign", "scenario_id": proposal.scenario_id, "workflow": workflow,
        "policy_version": "policy-v1.0.0"}
    manifest = {"native_cases": [{"name": "benign", "command": {"action": action.to_mapping()}}],
        "expected_effects": {"create": {"invoice_date": inputs["expected_effect"].invoice_date,
            "lines": [{name: getattr(line, name) for name in line.__dataclass_fields__}
                      for line in inputs["expected_effect"].lines]}}}
    stem = tmp_path / (args.database + "-benign-C0")
    saved = {"name": "benign", "request": inputs["request_value"], "stage": stage_to_mapping(inputs["stage"]),
        "canonical_action": action.to_mapping(), "request_sha256": canonical_json_sha256(inputs["request_value"]),
        "proposal_sha256": canonical_json_sha256(proposal.to_mapping()), "action_sha256": action.action_hash}
    effect = {"move_id": inputs["trace"].effect_move_id, "methods": list(inputs["trace"].executed_methods),
        "disposition": "ALLOW_EFFECTIVE", "receipt_id": None, "provider_mocked": True,
        "committed_effect_confirmed": True}
    artifacts = {stem.with_suffix(".record-context.json"): ctx, stem.with_suffix(".candidate.json"): saved,
        stem.with_suffix(".effect.json"): effect,
        stem.with_suffix(".dispatch.json"): {key: value for key, value in effect.items() if key != "committed_effect_confirmed"},
        tmp_path / (args.database + "-after.capture.json"): inputs["after"].to_mapping(),
        tmp_path / (ctx["restored_database"] + "-restored.capture.json"): inputs["restored"].to_mapping()}
    monkeypatch.setattr(runner_observed_gateway, "read_artifact", lambda path: deepcopy(artifacts[path]))
    monkeypatch.setattr(state_oracle_gateway, "inputs", lambda _: (tmp_path, stem, manifest, binding.to_mapping(), row))
    monkeypatch.setattr(state_oracle_gateway, "captures", lambda *_: (inputs["baseline"], inputs["before"]))
    (tmp_path / "benign.pdf").write_bytes(inputs["document_bytes"])
    receipt = probe.assemble(args)
    value = json.loads(stem.with_suffix(".gateway-run.json").read_bytes())
    checked = parse_gateway_run_result(value)
    assert receipt["wrapper_sha256"] == canonical_json_sha256(checked.to_mapping())
    assert checked.record.to_mapping()["evidence"]["stage"] == saved["stage"]
    assert checked.record.to_mapping()["derived"]["oracle"]["benign_task_success"] is True
    assert receipt["policy_applicable"] is False
    assert receipt["scientific_run"] is False
