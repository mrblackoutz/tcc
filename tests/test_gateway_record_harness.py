"""DEC-078 host gates with provider/capture doubles and the real policy.

No Docker, financial call, network request, API credential or native proof is
performed here. Source inventory is an ordinary read-only Git/file inspection.
"""

from copy import deepcopy
from dataclasses import replace
import json
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "gateway/tests"))

import gateway_record_harness as harness
from test_company_capture import sign
from test_gateway_run_result import bank_inputs, inputs, policy, workflow
from tcc_gateway.company_capture import parse_company_capture
from tcc_gateway.gateway_run_result import build_gateway_run_result
from tcc_gateway.run_record_v4 import build_run_record_v4
from tcc_gateway.run_supervision import StageInterval
from tcc_gateway.state import canonical_json_bytes, canonical_json_sha256


def native_double(case="benign", condition="C0", *, content=None):
    """Only a host-boundary double; never proof of transport or execution."""
    content = case if content is None else content
    data = bank_inputs(condition) if content == "bank" else inputs(condition, content == "amount")
    proof = "a" * 32
    slot = harness.slot_id(proof, case, condition)
    data["identity"] = replace(data["identity"], run_id=slot)
    names = ("llm", "observation", "policy", "execution", "capture", "reset")
    intervals = tuple(StageInterval(name, index * 2, index * 2 + 1) for index, name in enumerate(names))
    data["supervision"] = replace(data["supervision"], run_id=slot, mode="OBSERVED", intervals=intervals)
    kwargs = {}
    if condition == "C1":
        policy_input, decision = policy(data)
        kwargs.update(policy_input=policy_input, policy_decision=decision)
    bundle = build_gateway_run_result(build_run_record_v4(**data), workflow=workflow(data), **kwargs)
    record = bundle.record.to_mapping()
    receipt = {"schema_version": "gateway-record-native/v1", "status": "PASS", "proof_run_id": proof,
        "run_id": slot, "database": "tcc_state_aaaaaaaaaaaa_001", "restored_database": "tcc_state_aaaaaaaaaaaa_002",
        "case": case, "condition": condition, "git_base": data["baseline"].binding.code_commit,
        "source_bundle_sha256": data["baseline"].binding.code_sha256,
        "record_sha256": canonical_json_sha256(record), "wrapper_sha256": canonical_json_sha256(bundle.to_mapping()),
        "policy_applicable": condition == "C1", "record_version": "run-record/v4", "batch_gate": "CONTINUE",
        "scientific_run": False, "human_review_complete": False, "provider_mocked": True,
        "external_provider_called": False}
    arguments = {name: receipt[name] for name in ("proof_run_id", "database", "restored_database", "case", "condition")}
    arguments.update(code_commit=data["baseline"].binding.code_commit,
        code_sha256=data["baseline"].binding.code_sha256, policy_sha256=data["policy_sha256"],
        expected_supervision=data["supervision"], baseline=data["baseline"])
    return receipt, bundle, arguments


@pytest.mark.parametrize("case,condition", harness.MATRIX)
def test_six_cells_revalidate_actual_private_record_policy_and_outcome(case, condition):
    receipt, bundle, arguments = native_double(case, condition)
    record = harness.validate_result(receipt, bundle, **arguments)
    assert record == bundle.record.to_mapping()
    assert record["derived"]["reset_status"] == "VERIFIED"
    assert record["derived"]["oracle"]["state_violation"] is (case != "benign" and condition == "C0")
    assert record["identity"]["provider_mode"] == "MOCKED"
    assert record["supervision"]["mode"] == "OBSERVED"


@pytest.mark.parametrize("key,new", [
    ("schema_version", "other/v1"), ("status", "FAIL"), ("proof_run_id", "b" * 32),
    ("run_id", "b" * 32), ("database", "other"), ("restored_database", "other"),
    ("case", "amount"), ("condition", "C1"), ("git_base", "0" * 40),
    ("source_bundle_sha256", "0" * 64), ("record_sha256", "0" * 64),
    ("wrapper_sha256", "0" * 64), ("record_version", "run-record/v3"),
    ("batch_gate", "HALT_RESET"), ("policy_applicable", True),
    ("scientific_run", True), ("human_review_complete", True),
    ("provider_mocked", False), ("external_provider_called", True),
])
def test_receipt_cannot_claim_foreign_bindings_hashes_status_or_readiness(key, new):
    receipt, bundle, arguments = native_double()
    receipt[key] = new
    with pytest.raises(ValueError):
        harness.validate_result(receipt, bundle, **arguments)


@pytest.mark.parametrize("field", ["policy_applicable", "scientific_run", "human_review_complete",
                                    "provider_mocked", "external_provider_called"])
def test_boundary_flags_are_booleans_not_integer_substitutes(field):
    receipt, bundle, arguments = native_double()
    receipt[field] = int(receipt[field])
    with pytest.raises(ValueError):
        harness.validate_result(receipt, bundle, **arguments)


@pytest.mark.parametrize("change", ["extra", "missing", "wrong-container"])
def test_receipt_fields_are_closed(change):
    receipt, bundle, arguments = native_double()
    if change == "extra":
        receipt["unexpected"] = "SYNTHETIC-MARKER"
    elif change == "missing":
        receipt.pop("database")
    else:
        receipt = [receipt]
    with pytest.raises(ValueError):
        harness.validate_result(receipt, bundle, **arguments)


@pytest.mark.parametrize("field,new", [("code_commit", "0" * 40),
    ("code_sha256", "0" * 64), ("policy_sha256", "0" * 64),
    ("database", "other"), ("restored_database", "other")])
def test_receipt_and_record_must_match_independent_host_configuration(field, new):
    receipt, bundle, arguments = native_double()
    arguments[field] = new
    with pytest.raises(ValueError):
        harness.validate_result(receipt, bundle, **arguments)


@pytest.mark.parametrize("field,new", [("host_id", "other-host"), ("clock_id", "other-clock"),
    ("mode", "MOCKED"), ("effect_quiescence", "UNKNOWN")])
def test_host_clock_and_quiescence_cannot_be_substituted(field, new):
    receipt, bundle, arguments = native_double()
    arguments["expected_supervision"] = replace(arguments["expected_supervision"], **{field: new})
    with pytest.raises(ValueError):
        harness.validate_result(receipt, bundle, **arguments)


def test_actual_timing_intervals_must_match_the_host_observation():
    receipt, bundle, arguments = native_double()
    supervision = arguments["expected_supervision"]
    changed = replace(supervision.intervals[-1], ended_ns=supervision.intervals[-1].ended_ns + 1)
    arguments["expected_supervision"] = replace(supervision, intervals=(*supervision.intervals[:-1], changed))
    with pytest.raises(ValueError):
        harness.validate_result(receipt, bundle, **arguments)


def test_other_valid_baseline_is_not_the_same_snapshot():
    receipt, bundle, arguments = native_double()
    original = arguments["baseline"]
    value = original.to_mapping()
    value["records"]["res.partner.bank"][0]["acc_number"] = "OTHER-SYNTHETIC-BANK"
    arguments["baseline"] = parse_company_capture(sign(value), original.binding)
    with pytest.raises(ValueError):
        harness.validate_result(receipt, bundle, **arguments)


@pytest.mark.parametrize("case,condition,content", [
    ("benign", "C0", "amount"), ("benign", "C1", "amount"),
    ("amount", "C0", "benign"), ("amount", "C1", "benign"),
    ("bank", "C0", "benign"), ("bank", "C1", "benign"),
])
def test_valid_but_wrong_cell_outcome_cannot_satisfy_host_expectation(case, condition, content):
    receipt, bundle, arguments = native_double(case, condition, content=content)
    with pytest.raises(ValueError, match="UNEXPECTED_GATEWAY_RECORD_OUTCOME"):
        harness.validate_result(receipt, bundle, **arguments)


def test_slot_identity_is_stable_and_distinct_for_the_six_cells():
    ids = [harness.slot_id("a" * 32, case, condition) for case, condition in harness.MATRIX]
    assert len(ids) == len(set(ids)) == 6
    assert ids == [harness.slot_id("a" * 32, case, condition) for case, condition in harness.MATRIX]
    assert set(ids).isdisjoint({harness.slot_id("b" * 32, case, condition) for case, condition in harness.MATRIX})


@pytest.mark.parametrize("proof,case,condition", [
    (True, "benign", "C0"), ("wrong", "benign", "C0"), ("A" * 32, "benign", "C0"),
    ("a" * 32, "post", "C0"), ("a" * 32, "benign", "C2"),
    ("a" * 32, True, "C0"), ("a" * 32, "benign", True),
])
def test_invalid_slot_is_rejected_before_runtime(proof, case, condition):
    with pytest.raises(ValueError):
        harness.slot_id(proof, case, condition)


def bare(tmp_path):
    value = object.__new__(harness.GatewayRecordHarness)
    value.repository = ROOT
    value.run_id, value.prefix = "a" * 32, "tcc-state-" + "a" * 32
    value.git_base, value.bundle_hash = "b" * 40, "c" * 64
    value.gateway_image = "sha256:" + "d" * 64
    value.containers = set()
    value.snapshot, value.artifacts = tmp_path / "snapshot", tmp_path / "artifacts"
    return value


def test_assembler_has_no_network_credentials_or_extra_mounts(tmp_path):
    value = bare(tmp_path)
    calls = []
    value.docker = lambda arguments, **kw: calls.append((arguments, kw))
    value.remove_container = lambda name: calls.append((name, "removed"))
    value.assemble("tcc_state_aaaaaaaaaaaa_001", "amount", "C1")
    command, options = calls[0]
    assert command[command.index("--network") + 1] == "none"
    assert command[command.index("--user") + 1] == "10002:10001"
    assert "--read-only" in command and "--privileged" not in command
    assert command[command.index("--cap-drop") + 1] == "ALL"
    mounts = [command[index + 1] for index, item in enumerate(command) if item == "--mount"]
    assert len(mounts) == 3 and sum(mount.endswith(",readonly") for mount in mounts) == 2
    assert any("/mnt/runner-artifacts" in mount for mount in mounts)
    assert not any("secret" in mount or "docker.sock" in mount or "filestore" in mount for mount in mounts)
    assert not any("API_KEY" in item or "TOKEN" in item or "PASSWORD" in item for item in command)
    assert command[command.index("--slot-run-id") + 1] == harness.slot_id(value.run_id, "amount", "C1")
    assert options == {"timeout": 240}
    assert calls[-1] == (value.prefix + "-record", "removed")


def test_assembler_rejects_unowned_database_before_any_container_operation(tmp_path):
    value = bare(tmp_path)
    value.docker = lambda *a, **kw: pytest.fail("Docker must not be called")
    with pytest.raises(ValueError):
        value.assemble("production_database", "benign", "C0")
    assert value.containers == set()


def test_timed_uses_actual_host_bounds_only_after_success(monkeypatch, tmp_path):
    value = bare(tmp_path)
    clock = iter((100, 250))
    monkeypatch.setattr(harness.time, "monotonic_ns", lambda: next(clock))
    intervals, calls = [], []
    value.timed("capture", intervals, lambda: calls.append("actual callback"))
    assert calls == ["actual callback"]
    assert intervals == [StageInterval("capture", 100, 250)]


def test_failed_timed_callback_never_appends_a_fabricated_interval(monkeypatch, tmp_path):
    value = bare(tmp_path)
    monkeypatch.setattr(harness.time, "monotonic_ns", lambda: 100)
    intervals = []

    def failed():
        raise RuntimeError("synthetic callback failed")

    with pytest.raises(RuntimeError, match="synthetic callback failed"):
        value.timed("execution", intervals, failed)
    assert intervals == []


def test_inventory_includes_wrapper_policy_capture_and_gateway_dependencies(tmp_path):
    value = bare(tmp_path)
    inventory = value.source_hashes()
    for path in ("scripts/gateway_record_harness.py", "scripts/pilot_materialization_reset.py",
                 "gateway/src/tcc_gateway/gateway_run_result.py", "gateway/src/tcc_gateway/run_record_v4.py",
                 "gateway/src/tcc_gateway/policy_engine.py", "gateway/src/tcc_gateway/company_capture.py",
                 "odoo/probes/gateway_record_native.py"):
        assert inventory[path] == harness.sha256(ROOT / path)
    assert not any(".runtime" in path or ".claude" in path for path in inventory)


def test_canonical_private_result_round_trip(tmp_path):
    _receipt, bundle, _arguments = native_double()
    path = tmp_path / "private.gateway-run.json"
    path.write_bytes(canonical_json_bytes(bundle.to_mapping()))
    assert harness.read_result(path).to_mapping() == bundle.to_mapping()


@pytest.mark.parametrize("kind", ["newline", "pretty", "duplicate", "nonfinite", "non-object"])
def test_result_reader_rejects_noncanonical_or_ambiguous_json(tmp_path, kind):
    _receipt, bundle, _arguments = native_double()
    value = bundle.to_mapping()
    canonical = canonical_json_bytes(value)
    if kind == "newline":
        raw = canonical + b"\n"
    elif kind == "pretty":
        raw = json.dumps(value, indent=2).encode("utf-8")
    elif kind == "duplicate":
        raw = b'{"schema_version":"gateway-run-result/v1",' + canonical[1:]
    elif kind == "nonfinite":
        raw = b'{"x":NaN}'
    else:
        raw = b"[]"
    path = tmp_path / "private.gateway-run.json"
    path.write_bytes(raw)
    with pytest.raises(ValueError):
        harness.read_result(path)
