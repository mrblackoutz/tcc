"""DEC-079 native phase boundaries with explicit Odoo/clock/financial doubles.

No Docker, native accounting, real signature or provider request occurs here.
The source assertions supplement executable tests; they do not prove ACLs or
the common Linux clock domain used by the separate disposable native proof.
"""

import ast
import builtins
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import stat
import sys
from types import ModuleType, SimpleNamespace

import pytest

from tcc_gateway import linux_clock_domain as clock
from tcc_gateway import linux_clock_scope as scope_contract


ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "odoo/probes/gateway_post_native.py"


def load_probe():
    spec = importlib.util.spec_from_file_location("_tcc_gateway_post_native_test", SOURCE)
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


native = load_probe()


@pytest.fixture(autouse=True)
def probe_paths(monkeypatch):
    monkeypatch.syspath_prepend(str(ROOT / "odoo/probes"))


def options(variant="exact", condition="C0", mode="prepare", **changes):
    proof = "a" * 32
    valid_pair = (variant, condition) if (variant, condition) in native.MATRIX else ("exact", "C0")
    generation = 1 + 2 * native.MATRIX.index(valid_pair)
    values = dict(proof_run_id=proof, slot_run_id=native.slot_id(proof, *valid_pair),
        database="tcc_state_" + proof[:12] + f"_{generation:03d}", variant=variant, condition=condition,
        mode=mode, git_base="b" * 40, source_bundle_sha256="c" * 64, case="post",
        config="/etc/odoo/runner.conf", artifacts="/mnt/runner-artifacts", secret_directory="/run/runner-secrets")
    return SimpleNamespace(**dict(values, **changes))


def cli(args):
    names = ("database", "git_base", "source_bundle_sha256", "proof_run_id", "slot_run_id", "variant",
             "condition", "config", "artifacts")
    return [args.mode, *[part for name in names for part in ("--" + name.replace("_", "-"), getattr(args, name))]]


def forbid_odoo(monkeypatch):
    original = builtins.__import__

    def guarded(name, *args, **kwargs):
        if name == "odoo" or name.startswith("odoo."):
            pytest.fail("Options must fail before Odoo is loaded")
        return original(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", guarded)


def domain():
    return clock._from_fingerprints("a" * 64, "b" * 64, clock._ZERO_OFFSETS_SHA256)


def clock_scope():
    return scope_contract.build_clock_scope(domain(), {"schema_version": "local-linux-runtime/v1",
        "daemon_sha256": "1" * 64, "kernel_sha256": "2" * 64, "runtime": "runc",
        "endpoint_kind": "local-npipe", "os_type": "linux", "platform": "linux/amd64"})


def digest(value):
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def module(monkeypatch, name, **members):
    value = ModuleType(name)
    value.__dict__.update(members)
    monkeypatch.setitem(sys.modules, name, value)
    return value


def odoo_modules(monkeypatch, **approval):
    root = module(monkeypatch, "odoo", SUPERUSER_ID=1,
        tools=SimpleNamespace(config={"data_dir": "/var/lib/odoo"}))
    addons = module(monkeypatch, "odoo.addons")
    package = module(monkeypatch, "odoo.addons.ap_security_executor")
    root.addons, addons.ap_security_executor = addons, package
    package.approval = module(monkeypatch, "odoo.addons.ap_security_executor.approval", **approval)
    package.post_contracts = module(monkeypatch, "odoo.addons.ap_security_executor.post_contracts",
                                   TrustedPostWorkflow=object)
    return root, package


def test_module_import_has_no_odoo_or_runtime_side_effect(monkeypatch):
    forbid_odoo(monkeypatch)
    assert load_probe().MATRIX == (("exact", "C0"), ("exact", "C1"), ("tampered", "C0"), ("tampered", "C1"))


@pytest.mark.parametrize("variant,condition", native.MATRIX)
@pytest.mark.parametrize("mode", ["prepare", "observe", "confirm"])
def test_options_bind_every_phase_to_its_exact_clone(variant, condition, mode, monkeypatch):
    forbid_odoo(monkeypatch)
    assert native.validate_options(options(variant, condition, mode)) is None


@pytest.mark.parametrize("variant", ["exact", "tampered"])
def test_only_c1_may_enter_native_financial_execution(variant):
    assert native.validate_options(options(variant, "C1", "execute")) is None
    with pytest.raises(ValueError, match="^GATEWAY_POST_NATIVE_INVALID$"):
        native.validate_options(options(variant, "C0", "execute"))


@pytest.mark.parametrize("key,value", [
    ("proof_run_id", True), ("proof_run_id", "A" * 32), ("proof_run_id", "a" * 31),
    ("slot_run_id", "d" * 32), ("slot_run_id", "d" * 32 + "\n"),
    ("git_base", "b" * 39), ("source_bundle_sha256", "sha256:" + "c" * 64),
    ("database", "tcc_state_" + "a" * 12 + "_003"),
    ("database", "tcc_state_" + "d" * 12 + "_001"), ("database", "../private"),
    ("database", "tcc_state_" + "a" * 12 + "_0001"),
    ("variant", True), ("variant", "foreign"), ("condition", "C2"), ("condition", True),
    ("mode", "replay"), ("case", "benign"), ("config", "/etc/odoo/../other.conf"),
    ("artifacts", "/mnt/runner-artifacts/../private"), ("secret_directory", "/run/runner-secrets/")])
def test_invalid_options_fail_before_fixture_or_odoo_import(key, value, monkeypatch):
    forbid_odoo(monkeypatch)
    monkeypatch.setattr(native, "loaded", lambda *_: pytest.fail("No fixture may be loaded"))
    with pytest.raises(ValueError, match="^GATEWAY_POST_NATIVE_INVALID$"):
        native.run(options(**{key: value}), registry=None)


@pytest.mark.parametrize("proof,variant,condition", [("wrong", "exact", "C0"),
    (True, "exact", "C0"), ("A" * 32, "exact", "C0"), ("a" * 32, "other", "C0"),
    ("a" * 32, "exact", "C2"), ("a" * 32, True, "C0")])
def test_slot_identity_has_no_noncanonical_or_unknown_alternative(proof, variant, condition):
    with pytest.raises(ValueError, match="^GATEWAY_POST_NATIVE_INVALID$"):
        native.slot_id(proof, variant, condition)


def test_slots_are_distinct_for_both_proposal_variants_and_conditions():
    slots = {native.slot_id("a" * 32, variant, condition) for variant, condition in native.MATRIX}
    assert len(slots) == 4
    assert slots.isdisjoint({native.slot_id("d" * 32, variant, condition) for variant, condition in native.MATRIX})


def test_capsule_binding_uses_configured_clone_identity_not_model_data():
    args = options("tampered", "C0")
    manifest = {"configuration_sha256": "d" * 64}
    binding = {"fixture_manifest_sha256": "e" * 64, "company_id": 11}
    assert native.capsule_binding(args, manifest, binding, 17) == {
        "proof_run_id": args.proof_run_id, "run_id": args.slot_run_id, "database": args.database,
        "variant": "tampered", "condition": "C0", "git_base": args.git_base,
        "source_bundle_sha256": args.source_bundle_sha256, "configuration_sha256": "d" * 64,
        "fixture_manifest_sha256": "e" * 64, "company_id": 11, "principal_id": 17}


@pytest.mark.parametrize("mode", ["prepare", "observe", "execute", "confirm"])
def test_run_routes_only_the_selected_phase_and_reads_custody_only_after_prepare(mode, monkeypatch):
    args = options(condition="C1", mode=mode)
    values, registry, calls = object(), object(), []
    monkeypatch.setattr(native, "loaded", lambda given, reg: (calls.append(("load", given, reg)), values)[1])
    monkeypatch.setattr(native, "private", lambda given, loaded: (calls.append(("private", given, loaded)), "saved")[1])
    for name in ("prepare", "observe", "execute", "confirm"):
        monkeypatch.setattr(native, name, lambda *received, name=name: calls.append((name, received)))
    assert native.run(args, registry) is None
    assert calls[0] == ("load", args, registry)
    if mode == "prepare":
        assert calls == [("load", args, registry), ("prepare", (args, values))]
    else:
        assert calls[1:] == [("private", args, values), (mode, (args, registry, values, "saved"))]


def test_main_emits_only_finite_diagnostic_for_private_runtime_failure(monkeypatch, capsys):
    args = options()
    configuration_calls, saved = [], []
    fake_odoo, _ = odoo_modules(monkeypatch)
    fake_odoo.tools.config = SimpleNamespace(parse_config=lambda *a, **kw: configuration_calls.append((a, kw)))
    orm = module(monkeypatch, "odoo.orm")
    orm.registry = module(monkeypatch, "odoo.orm.registry", Registry=lambda database: object())
    fake_odoo.orm = orm

    def failed(*_):
        raise ValueError("PRIVATE-SYNTHETIC-RUNTIME-MARKER")

    monkeypatch.setattr(native, "run", failed)
    monkeypatch.setattr(native, "write_once", lambda path, value: saved.append((path, value)))
    assert native.main(cli(args)) == 1
    output = capsys.readouterr()
    assert output.out == "GATEWAY_POST_NATIVE_FAILED\n" and output.err == ""
    assert "PRIVATE-SYNTHETIC-RUNTIME-MARKER" not in json.dumps(saved[0][1])
    assert set(saved[0][1]) == {"status", "code", "source_line"}
    assert saved[0][1]["code"] == "GATEWAY_POST_NATIVE_FAILED"
    assert configuration_calls and saved[0][0].name.endswith(".prepare.failure.json")


class Cursor:
    def __init__(self, events):
        self.events = events

    def __enter__(self):
        self.events.append("cursor-enter")
        return self

    def __exit__(self, *args):
        self.events.append("cursor-exit")

    def execute(self, query):
        self.events.append(query)

    def commit(self):
        self.events.append("commit")


def parts(tmp_path, condition="C1"):
    args = options(condition=condition)
    events = []
    registry = SimpleNamespace(cursor=lambda: Cursor(events))
    env = SimpleNamespace(uid=1, su=True)
    base = SimpleNamespace(env=lambda cr: env, cursor_gate=lambda cr: events.append("cursor-gate"),
        success=lambda result, status: native.require(result["status"] == status))
    scope = SimpleNamespace(workflow=SimpleNamespace(scenario_id="SCN-POST", document_sha256="d" * 64),
        authority=SimpleNamespace(nonce="SYNTHETIC-NONCE"), key=SimpleNamespace(material=b"X" * 32),
        document=SimpleNamespace(raw=b"SYNTHETIC WITHOUT FISCAL VALUE"),
        result={"status": "CREATED", "effect_applied": True, "receipt": {"move_id": 31}})
    manifest = {"configuration_sha256": "e" * 64}
    binding = {"company_id": 11, "fixture_manifest_sha256": "f" * 64}
    observer = SimpleNamespace(base=base)
    principal, audit, origin = 17, object(), {"target_move_id": 31}
    stem = tmp_path / (args.database + "-post-" + condition)
    values = (tmp_path, stem, manifest, binding, observer, scope, SimpleNamespace(registration_id=23),
              domain(), principal, audit, origin)
    return args, registry, values, events, env


@dataclass
class FakeAuthority:
    executor_user_id: int
    company_id: int


def prepare_doubles(monkeypatch, tmp_path, condition="C0"):
    args, registry, values, events, _ = parts(tmp_path, condition)
    scope, principal = values[5], values[-3]
    reference = {"action": {"target_move_id": 31, "amount": "125.50"},
        "policy_decision": {"decision": "REVIEW", "input_sha256": "sha256:" + "b" * 64},
        "approval": {"fixture_id": "SYNTHETIC-PREISSUED"}}
    calls, capsules, public = [], [], []
    odoo_modules(monkeypatch, APPROVAL_DOMAIN=b"SYNTHETIC-DOMAIN", ApprovalAuthority=FakeAuthority, ApprovalKey=object)

    def issue(given_scope, *, executor_user_id):
        calls.append((given_scope, executor_user_id))
        given_scope.authority = FakeAuthority(executor_user_id, 11)
        given_scope.key = SimpleNamespace(material=b"X" * 32)
        given_scope.post_command = deepcopy(reference)

    values[4].base.prepare_post = issue
    measured = {"schema_version": "linux-clock-sample/v1", "domain": domain(),
        "monotonic_ns": 123, "utc": "2026-10-24T12:00:00.000000Z"}
    monkeypatch.setattr(clock, "sample_clock", lambda: deepcopy(measured))
    module(monkeypatch, "runner_observed_fixture", read_json=lambda _: clock_scope())
    monkeypatch.setattr(native, "sha", digest)
    import gateway_post_custody
    monkeypatch.setattr(gateway_post_custody, "write_capsule", lambda run_id, value: capsules.append((run_id, deepcopy(value))))
    monkeypatch.setattr(native, "write_once", lambda path, value: public.append((path, deepcopy(value))))
    return SimpleNamespace(args=args, values=values, scope=scope, principal=principal, calls=calls,
        capsules=capsules, writes=public, measured=measured, reference=reference)


@pytest.mark.parametrize("condition", ["C0", "C1"])
def test_prepare_issues_once_for_preconfigured_principal_before_any_candidate(condition, monkeypatch, tmp_path):
    value = prepare_doubles(monkeypatch, tmp_path, condition)
    native.prepare(value.args, value.values)
    assert value.calls == [(value.scope, value.principal)]
    assert len(value.capsules) == len(value.writes) == 1
    run_id, saved = value.capsules[0]
    assert run_id == value.args.slot_run_id and saved["reference_command"] == value.reference
    assert saved["binding"]["principal_id"] == saved["authority"]["executor_user_id"] == value.principal
    preissued = value.writes[0][1]
    assert preissued == saved["preissued"]
    assert preissued["preissued_at_ns"] == 123 and preissued["preissued_at_utc"] == value.measured["utc"]
    assert preissued["reference_command_sha256"] == digest(value.reference)
    assert preissued["approval_sha256"] == digest(value.reference["approval"])
    assert preissued["reference_action"] == value.reference["action"]
    assert preissued["clock_domain"] == domain() and preissued["clock_scope"] == clock_scope()
    assert "approval" not in preissued and "key_material" not in preissued and "authority" not in preissued
    assert value.writes[0][0].name.endswith(".preissued.json")


def test_prepare_refuses_late_issuance_after_a_candidate_exists(monkeypatch, tmp_path):
    value = prepare_doubles(monkeypatch, tmp_path)
    value.values[1].with_suffix(".candidate.json").write_bytes(b"SYNTHETIC-EXISTING-CANDIDATE")
    with pytest.raises(ValueError, match="^GATEWAY_POST_NATIVE_INVALID$"):
        native.prepare(value.args, value.values)
    assert value.calls == value.capsules == value.writes == []


def test_prepare_does_not_publish_issuance_in_a_foreign_clock_domain(monkeypatch, tmp_path):
    value = prepare_doubles(monkeypatch, tmp_path)
    value.measured["domain"] = clock._from_fingerprints("d" * 64, "b" * 64, clock._ZERO_OFFSETS_SHA256)
    with pytest.raises(clock.LinuxClockDomainError):
        native.prepare(value.args, value.values)
    assert len(value.calls) == 1 and value.capsules == value.writes == []


@pytest.mark.parametrize("changed", ["principal", "company", "target"])
def test_prepare_cannot_silently_remap_a_preissued_principal_or_target(changed, monkeypatch, tmp_path):
    value = prepare_doubles(monkeypatch, tmp_path)
    original_issue = value.values[4].base.prepare_post

    def wrong(scope, **kwargs):
        original_issue(scope, **kwargs)
        if changed == "principal":
            scope.authority.executor_user_id += 1
        elif changed == "company":
            scope.authority.company_id += 1
        else:
            scope.post_command["action"]["target_move_id"] += 1

    value.values[4].base.prepare_post = wrong
    with pytest.raises(ValueError, match="^GATEWAY_POST_NATIVE_INVALID$"):
        native.prepare(value.args, value.values)
    assert value.capsules == value.writes == []


def execute_doubles(monkeypatch, tmp_path, decision="REVIEW", *, uid=1, su=True):
    args, registry, values, events, env = parts(tmp_path)
    env.uid, env.su = uid, su
    action = {"action": "POST_VENDOR_BILL", "target_move_id": 31, "amount": "125.50"}
    actual_decision = {"decision": decision, "evaluated_at": "2020-01-01T00:00:00Z",
        "expires_at": "2099-01-01T00:00:00Z", "input_sha256": "sha256:" + "9" * 64}
    policy_input = {"action": deepcopy(action), "trusted_state": {"synthetic": True}}
    unsigned = {"schema_version": "capability-command/v1", "action": deepcopy(action),
        "policy_decision": deepcopy(actual_decision), "idempotency_key": "sha256:" + "8" * 64}
    policy = {"status": decision, "decision": actual_decision, "action_sha256": "sha256:" + "7" * 64,
        "policy_input": policy_input, "policy_input_sha256": digest(policy_input),
        "unsigned_command": unsigned if decision == "REVIEW" else None,
        "unsigned_command_sha256": digest(unsigned).removeprefix("sha256:") if decision == "REVIEW" else None}
    candidate = {"action_sha256": policy["action_sha256"], "canonical_action": deepcopy(action)}
    approval = {"fixture_id": "SYNTHETIC-APPROVAL", "decision": "APPROVE"}
    reference = {"action": deepcopy(action), "approval": deepcopy(approval),
        "policy_decision": {"input_sha256": "sha256:" + "b" * 64, "decision": "REVIEW"}}
    saved = {"preissued": {"reference_action": deepcopy(action)}, "reference_command": reference}
    values[5].post_command = deepcopy(reference)
    _, package = odoo_modules(monkeypatch)
    calls, writes = [], []

    def post(env, **kwargs):
        calls.append((env, deepcopy(kwargs)))
        return {"result": {"status": "POSTED"}, "caller_transaction_pending": True, "origin": values[-1]}

    package.registered_post = module(monkeypatch, "odoo.addons.ap_security_executor.registered_post",
                                      post_registered_bill_audited=post)
    artifacts = {".post-policy.json": policy, ".candidate.json": candidate, ".clock-scope.json": clock_scope()}
    module(monkeypatch, "runner_observed_fixture", read_json=lambda path: deepcopy(next(
        value for suffix, value in artifacts.items() if str(path).endswith(suffix))))
    monkeypatch.setattr(native, "sha", digest)
    monkeypatch.setattr(clock, "measure_clock_domain", domain)
    ticks = iter((100, 200))
    monkeypatch.setattr(native.time, "monotonic_ns", lambda: next(ticks))
    monkeypatch.setattr(native, "write_once", lambda path, value: writes.append((path, deepcopy(value))))
    return SimpleNamespace(args=args, registry=registry, values=values, saved=saved, events=events,
        env=env, policy=policy, candidate=candidate, calls=calls, writes=writes, approval=approval)


def test_real_review_is_preserved_and_original_fixture_attached_once(monkeypatch, tmp_path):
    value = execute_doubles(monkeypatch, tmp_path)
    original = deepcopy((value.policy, value.candidate, value.saved))
    native.execute(value.args, value.registry, value.values, value.saved)
    assert len(value.calls) == 1 and value.events.count("commit") == 1
    env, call = value.calls[0]
    assert env is value.env and call["expected_executor_user_id"] == 17
    assert call["command"]["policy_decision"] == value.policy["decision"]
    assert call["command"]["policy_decision"] != value.saved["reference_command"]["policy_decision"]
    assert call["command"]["approval"] == value.approval
    assert call["command"]["action"] == value.candidate["canonical_action"]
    assert (value.policy, value.candidate, value.saved) == original
    evidence = value.writes[0][1]
    assert evidence["policy_sha256"] == digest(value.policy)
    assert evidence["clock_scope"] == clock_scope() and evidence["clock_domain"] == domain()
    assert evidence["effect_command_sha256"] == digest(call["command"])
    assert evidence["execution_identity"] == {"uid": 1, "su": True}
    assert evidence["timing"]["started_ns"] == 100 and evidence["timing"]["finished_ns"] == 200
    assert "approval" not in evidence and "key_material" not in evidence


def test_real_policy_deny_never_constructs_a_financial_attempt(monkeypatch, tmp_path):
    value = execute_doubles(monkeypatch, tmp_path, "DENY")
    native.execute(value.args, value.registry, value.values, value.saved)
    assert value.calls == [] and "commit" not in value.events
    assert value.writes[0][1]["result"] is value.writes[0][1]["timing"] is None
    assert value.writes[0][1]["effect_command_sha256"] is value.writes[0][1]["execution_identity"] is None


@pytest.mark.parametrize("uid,su", [(2, True), (1, False), (True, True), (1, 1)])
def test_actual_native_environment_is_checked_before_financial_call(uid, su, monkeypatch, tmp_path):
    value = execute_doubles(monkeypatch, tmp_path, uid=uid, su=su)
    with pytest.raises(ValueError, match="^GATEWAY_POST_NATIVE_INVALID$"):
        native.execute(value.args, value.registry, value.values, value.saved)
    assert value.calls == [] and "commit" not in value.events and value.writes == []


@pytest.mark.parametrize("change", ["input-hash", "candidate-hash", "candidate-action", "unsigned-hash",
    "different-decision", "approval-in-unsigned", "reference-action", "expired", "deny-command"])
def test_handoff_cannot_replace_real_policy_action_or_reference_approval(change, monkeypatch, tmp_path):
    value = execute_doubles(monkeypatch, tmp_path, "DENY" if change == "deny-command" else "REVIEW")
    if change == "input-hash":
        value.policy["policy_input_sha256"] = "sha256:" + "0" * 64
    elif change == "candidate-hash":
        value.candidate["action_sha256"] = "sha256:" + "0" * 64
    elif change == "candidate-action":
        value.candidate["canonical_action"]["amount"] = "999.00"
    elif change == "unsigned-hash":
        value.policy["unsigned_command_sha256"] = "0" * 64
    elif change == "different-decision":
        value.policy["unsigned_command"]["policy_decision"]["input_sha256"] = "sha256:" + "0" * 64
        value.policy["unsigned_command_sha256"] = digest(value.policy["unsigned_command"]).removeprefix("sha256:")
    elif change == "approval-in-unsigned":
        value.policy["unsigned_command"]["approval"] = value.approval
    elif change == "reference-action":
        value.saved["preissued"]["reference_action"]["amount"] = "999.00"
    elif change == "expired":
        value.policy["decision"]["expires_at"] = "2020-01-01T00:05:00Z"
        value.policy["unsigned_command"]["policy_decision"] = deepcopy(value.policy["decision"])
        value.policy["unsigned_command_sha256"] = digest(value.policy["unsigned_command"]).removeprefix("sha256:")
    else:
        value.policy["unsigned_command"] = {}
    with pytest.raises(ValueError, match="^GATEWAY_POST_NATIVE_INVALID$"):
        native.execute(value.args, value.registry, value.values, value.saved)
    assert value.calls == [] and "commit" not in value.events and value.writes == []


@pytest.mark.parametrize("after_commit", [False, True])
def test_clock_drift_is_not_relabelled_or_reported_as_success(after_commit, monkeypatch, tmp_path):
    value = execute_doubles(monkeypatch, tmp_path)
    foreign = clock._from_fingerprints("d" * 64, "b" * 64, clock._ZERO_OFFSETS_SHA256)
    measured = iter((domain(), foreign) if after_commit else (foreign,))
    monkeypatch.setattr(clock, "measure_clock_domain", lambda: next(measured))
    with pytest.raises(clock.LinuxClockDomainError):
        native.execute(value.args, value.registry, value.values, value.saved)
    assert len(value.calls) == int(after_commit) and value.events.count("commit") == int(after_commit)
    assert value.writes == []


def observe_doubles(monkeypatch, tmp_path, *, available=True, status="VERIFIED", drift=False):
    args, registry, values, events, _ = parts(tmp_path, "C0")
    nonce_model = SimpleNamespace(search_count=lambda domain: int(not available))

    class Env:
        def __getitem__(self, name):
            assert name == "ap.security.approval.nonce"
            return nonce_model

    values[4].base.env = lambda cr: Env()
    scope = values[5]
    scope.post_command = {"action": {"target_move_id": 31}, "approval": {"fixture_id": "SYNTHETIC"},
        "policy_decision": {"evaluated_at": "2020-01-01T00:00:00Z", "expires_at": "2099-01-01T00:00:00Z"}}
    original = deepcopy(scope.post_command)
    saved = {"preissued": {"reference_action": deepcopy(scope.post_command["action"])}}
    before = {"capture_sha256": "d" * 64, "synthetic": True}
    collected, checks, writes = [], [], []
    odoo_modules(monkeypatch, NONCE_DOMAIN=b"SYNTHETIC-NONCE-DOMAIN")

    def collect(env, binding, filestore):
        collected.append((binding, filestore))
        return {**before, **({"synthetic": False} if drift and len(collected) == 2 else {})}

    def begin(**kwargs):
        checks.append(deepcopy(kwargs))
        return {"verification": {"status": status}, "synthetic_observation": True}

    module(monkeypatch, "company_capture_native", collect=collect)
    module(monkeypatch, "approval_observation_native", begin_approval_observation=begin)
    module(monkeypatch, "runner_observed_fixture", read_json=lambda path: clock_scope()
           if str(path).endswith(".clock-scope.json") else deepcopy(before))
    measurements = []
    monkeypatch.setattr(clock, "measure_clock_domain", lambda: (measurements.append(True), domain())[1])
    monkeypatch.setattr(native, "write_once", lambda path, value: writes.append((path, deepcopy(value))))
    return SimpleNamespace(args=args, registry=registry, values=values, saved=saved, collected=collected,
        checks=checks, writes=writes, events=events, measurements=measurements, original=original)


@pytest.mark.parametrize("status", ["VERIFIED", "REJECTED", "ABSENT", "INDETERMINATE"])
@pytest.mark.parametrize("available", [True, False])
def test_c0_observes_rejected_or_reused_approval_without_becoming_an_execution_gate(status, available, monkeypatch, tmp_path):
    value = observe_doubles(monkeypatch, tmp_path, available=available, status=status)
    native.observe(value.args, value.registry, value.values, value.saved)
    assert len(value.checks) == 1 and value.checks[0]["nonce_available"] is available
    assert value.checks[0]["command"] == value.original == value.values[5].post_command
    assert value.checks[0]["binding"]["host_id"] == domain()["host_id"]
    assert value.checks[0]["binding"]["clock_id"] == clock_scope()["clock_id"] != domain()["clock_id"]
    assert len(value.collected) == 2 and value.measurements == [True]
    assert value.events[1] == "SET TRANSACTION READ ONLY" and "commit" not in value.events
    assert value.writes[0][1]["verification"]["status"] == status


def test_pure_observation_refuses_any_capture_mutation(monkeypatch, tmp_path):
    value = observe_doubles(monkeypatch, tmp_path, drift=True)
    with pytest.raises(ValueError, match="^GATEWAY_POST_NATIVE_INVALID$"):
        native.observe(value.args, value.registry, value.values, value.saved)
    assert value.writes == []


def test_observation_does_not_publish_an_unproven_clock_domain(monkeypatch, tmp_path):
    value = observe_doubles(monkeypatch, tmp_path)
    foreign = clock._from_fingerprints("d" * 64, "b" * 64, clock._ZERO_OFFSETS_SHA256)
    monkeypatch.setattr(clock, "measure_clock_domain", lambda: foreign)
    with pytest.raises(clock.LinuxClockDomainError):
        native.observe(value.args, value.registry, value.values, value.saved)
    assert value.writes == []


def test_issuance_occurs_only_in_prepare_and_single_financial_call_only_in_execute():
    tree = ast.parse(SOURCE.read_text(encoding="utf-8"))
    issuers, financial = [], []
    functions = {node.name: node for node in tree.body if isinstance(node, ast.FunctionDef)}
    for name, function in functions.items():
        for node in ast.walk(function):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                if node.func.attr == "prepare_post":
                    issuers.append(name)
                if node.func.attr == "post_registered_bill_audited":
                    financial.append(name)
    assert issuers == ["prepare"] and financial == ["execute"]
    for name in ("loaded", "observe", "confirm"):
        assert any(isinstance(node, ast.Constant) and node.value == "SET TRANSACTION READ ONLY"
                   for node in ast.walk(functions[name]))
    assert not any(isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "action_post"
                   for node in ast.walk(tree))


@pytest.fixture
def native_writer(monkeypatch):
    # The actual native helper imports only this existing stdlib canonicalizer;
    # the Odoo environment itself is not loaded by this filesystem fixture.
    def canonical(value):
        return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
                          allow_nan=False, default=str).encode("utf-8")

    module(monkeypatch, "c111_transactions", canonical=canonical)
    return canonical


def test_native_writer_round_trips_exact_canonical_bytes_without_gateway_store(native_writer, monkeypatch, tmp_path):
    value = {"z": 1, "a": "SINTÉTICO SEM VALOR FISCAL", "flag": False}
    original_import = builtins.__import__

    def guarded(name, *args, **kwargs):
        if name == "jsonschema" or name.startswith("jsonschema.") or "run_record_store" in name:
            pytest.fail("Native artifact writing must not load gateway/jsonschema storage")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", guarded)
    target = tmp_path / "synthetic.native.json"
    native.write_once(target, value)
    assert target.read_bytes() == native_writer(value)
    assert not target.read_bytes().endswith(b"\n")


def test_native_writer_is_exclusive_and_preserves_existing_content(native_writer, tmp_path):
    target = tmp_path / "exclusive.native.json"
    original = {"synthetic": True}
    native.write_once(target, original)
    with pytest.raises(FileExistsError):
        native.write_once(target, {"replacement": True})
    assert target.read_bytes() == native_writer(original)


@pytest.mark.parametrize("kind", ["relative", "parent", "space", "newline", "empty-name"])
def test_native_writer_rejects_nonlocal_or_unbounded_artifact_names(kind, native_writer, tmp_path):
    target = {"relative": Path("relative.native.json"), "parent": tmp_path / ".." / "escape.native.json",
        "space": tmp_path / "synthetic name.json", "newline": tmp_path / "synthetic\nname.json",
        "empty-name": Path("/")}[kind]
    with pytest.raises(ValueError, match="^GATEWAY_POST_NATIVE_INVALID$"):
        native.write_once(target, {"synthetic": True})


@pytest.mark.parametrize("raw", [b"", b"S" * (2 * 1024 * 1024 + 1)], ids=["empty", "oversized"])
def test_native_writer_bounds_serialized_payload_before_creating_file(raw, native_writer, monkeypatch, tmp_path):
    monkeypatch.setattr(sys.modules["c111_transactions"], "canonical", lambda value: raw)
    target = tmp_path / "bounded.native.json"
    with pytest.raises(ValueError, match="^GATEWAY_POST_NATIVE_INVALID$"):
        native.write_once(target, {"synthetic": True})
    assert not target.exists()


@pytest.mark.parametrize("kind", ["symlink", "reparse", "non-directory"])
def test_native_writer_rejects_unsafe_parent_chain(kind, native_writer, monkeypatch, tmp_path):
    original_lstat = Path.lstat
    target = tmp_path / "parent-check.native.json"

    def changed(path, *args, **kwargs):
        info = original_lstat(path, *args, **kwargs)
        if path != tmp_path:
            return info
        return SimpleNamespace(st_mode=(stat.S_IFLNK if kind == "symlink" else stat.S_IFREG if kind == "non-directory"
            else stat.S_IFDIR) | 0o750, st_dev=info.st_dev, st_ino=info.st_ino,
            st_file_attributes=getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 1024) if kind == "reparse" else 0)

    monkeypatch.setattr(Path, "lstat", changed)
    with pytest.raises(ValueError):
        native.write_once(target, {"synthetic": True})
    assert not target.exists()


@pytest.mark.parametrize("stage", [1, 2, 3])
def test_native_writer_rejects_additional_link_at_each_descriptor_check(stage, native_writer, monkeypatch, tmp_path):
    original_fstat, calls = os.fstat, []

    def changed(descriptor):
        info = original_fstat(descriptor)
        calls.append(descriptor)
        if len(calls) != stage:
            return info
        return SimpleNamespace(st_mode=info.st_mode, st_nlink=2, st_size=info.st_size,
                               st_dev=info.st_dev, st_ino=info.st_ino)

    monkeypatch.setattr(native.os, "fstat", changed)
    with pytest.raises(ValueError, match="^GATEWAY_POST_NATIVE_INVALID$"):
        native.write_once(tmp_path / "link-check.native.json", {"synthetic": True})
    assert len(calls) >= stage


def test_native_writer_rejects_nonregular_created_descriptor(native_writer, monkeypatch, tmp_path):
    original_fstat = os.fstat

    def changed(descriptor):
        info = original_fstat(descriptor)
        return SimpleNamespace(st_mode=stat.S_IFIFO | 0o640, st_nlink=1, st_size=info.st_size,
                               st_dev=info.st_dev, st_ino=info.st_ino)

    monkeypatch.setattr(native.os, "fstat", changed)
    with pytest.raises(ValueError, match="^GATEWAY_POST_NATIVE_INVALID$"):
        native.write_once(tmp_path / "nonregular.native.json", {"synthetic": True})


def test_native_writer_rejects_parent_replacement_after_write(native_writer, monkeypatch, tmp_path):
    import gateway_post_custody
    original_chain, checks = gateway_post_custody._chain, []

    def changed(path):
        value = original_chain(path)
        checks.append(path)
        return value if len(checks) == 1 else [*value[:-1], (0, 0)]

    monkeypatch.setattr(gateway_post_custody, "_chain", changed)
    with pytest.raises(ValueError, match="^GATEWAY_POST_NATIVE_INVALID$"):
        native.write_once(tmp_path / "changed-parent.native.json", {"synthetic": True})


def test_native_writer_rejects_final_file_identity_substitution(native_writer, monkeypatch, tmp_path):
    original_lstat = Path.lstat
    target = tmp_path / "changed-file.native.json"

    def changed(path, *args, **kwargs):
        info = original_lstat(path, *args, **kwargs)
        if path != target:
            return info
        return SimpleNamespace(st_mode=info.st_mode, st_nlink=info.st_nlink, st_size=info.st_size,
                               st_dev=info.st_dev, st_ino=info.st_ino + 1)

    monkeypatch.setattr(Path, "lstat", changed)
    with pytest.raises(ValueError, match="^GATEWAY_POST_NATIVE_INVALID$"):
        native.write_once(target, {"synthetic": True})


def test_native_writer_rechecks_persisted_bytes(native_writer, monkeypatch, tmp_path):
    original_fdopen = os.fdopen

    class ChangedRead:
        def __init__(self, stream):
            self.stream = stream

        def __enter__(self):
            self.stream.__enter__()
            return self

        def __exit__(self, *args):
            return self.stream.__exit__(*args)

        def fileno(self):
            return self.stream.fileno()

        def read(self, limit):
            self.stream.read(limit)
            return b"SYNTHETIC-CHANGED-CONTENT"

    def changed(descriptor, mode, *args, **kwargs):
        stream = original_fdopen(descriptor, mode, *args, **kwargs)
        return ChangedRead(stream) if mode == "rb" else stream

    monkeypatch.setattr(native.os, "fdopen", changed)
    with pytest.raises(ValueError, match="^GATEWAY_POST_NATIVE_INVALID$"):
        native.write_once(tmp_path / "changed-content.native.json", {"synthetic": True})


def test_native_imports_remain_free_of_gateway_storage_and_jsonschema():
    tree = ast.parse(SOURCE.read_text(encoding="utf-8"))
    imports = [node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)]
    imports += [alias.name for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names]
    assert not any(name and ("jsonschema" in name or "run_record_store" in name) for name in imports)
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            assert all(alias.name != "run_record_store" for alias in node.names)


def test_confirm_witness_hashes_use_actual_gateway_policy_not_reference_helper_policy():
    tree = ast.parse(SOURCE.read_text(encoding="utf-8"))
    confirm = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "confirm")
    assignments = {node.targets[0].id: node.value for node in ast.walk(confirm)
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name)
        and node.targets[0].id in {"policy_input_hash", "decision_hash", "unsigned_hash"}}
    expected = {"policy_input_hash": 'policy["policy_input_sha256"]',
        "decision_hash": 'sha(policy["decision"])',
        "unsigned_hash": 'None if policy["unsigned_command"] is None else sha(policy["unsigned_command"])'}
    for name, expression in expected.items():
        assert ast.dump(assignments[name]) == ast.dump(ast.parse(expression, mode="eval").body)


def test_scope_accepts_a_distinct_zero_offset_physical_producer_without_renaming_it(monkeypatch, tmp_path):
    own = clock._from_fingerprints("a" * 64, "c" * 64, clock._ZERO_OFFSETS_SHA256)
    original, reads = deepcopy(own), []
    stem = tmp_path / "synthetic-post-C0"
    module(monkeypatch, "runner_observed_fixture", read_json=lambda path: (reads.append(path), clock_scope())[1])
    assert native.load_scope(stem, own) == clock_scope()
    assert own == original and own != domain()
    assert reads == [stem.with_suffix(".clock-scope.json")]
    assert own["clock_id"] != clock_scope()["clock_id"]
    with pytest.raises(clock.LinuxClockDomainError):
        clock.require_same_domain(own, domain())


@pytest.mark.parametrize("kind", ["boot", "offset", "implementation", "runtime", "scope-hash"])
def test_scope_rejects_nonzero_or_unproven_cross_producer_evidence(kind, monkeypatch, tmp_path):
    own, expected = domain(), clock_scope()
    if kind == "boot":
        own = clock._from_fingerprints("d" * 64, "c" * 64, clock._ZERO_OFFSETS_SHA256)
    elif kind == "offset":
        own["offsets_sha256"] = "d" * 64
    elif kind == "implementation":
        own["implementation"] = "clock_gettime(CLOCK_MONOTONIC_RAW)"
    elif kind == "runtime":
        expected["runtime_binding"]["runtime"] = "runsc"
    else:
        expected["scope_sha256"] = "d" * 64
    module(monkeypatch, "runner_observed_fixture", read_json=lambda _: expected)
    with pytest.raises(scope_contract.LinuxClockScopeError):
        native.load_scope(tmp_path / "synthetic-post-C0", own)


def test_same_scope_never_allows_the_native_producer_itself_to_change_namespace(monkeypatch, tmp_path):
    value = execute_doubles(monkeypatch, tmp_path)
    moved = clock._from_fingerprints("a" * 64, "c" * 64, clock._ZERO_OFFSETS_SHA256)
    assert scope_contract.require_clock_in_scope(moved, clock_scope()) == clock_scope()
    sequence = iter((domain(), moved))
    monkeypatch.setattr(clock, "measure_clock_domain", lambda: next(sequence))
    with pytest.raises(clock.LinuxClockDomainError):
        native.execute(value.args, value.registry, value.values, value.saved)
    assert len(value.calls) == value.events.count("commit") == 1 and value.writes == []


@pytest.mark.parametrize("kind", ["physical-producer", "runtime-binding"])
def test_private_custody_preserves_original_physical_producer_and_runtime_scope(kind, monkeypatch, tmp_path):
    value = prepare_doubles(monkeypatch, tmp_path)
    native.prepare(value.args, value.values)
    saved = deepcopy(value.capsules[0][1])
    if kind == "physical-producer":
        saved["preissued"]["clock_domain"] = clock._from_fingerprints("a" * 64, "c" * 64, clock._ZERO_OFFSETS_SHA256)
    else:
        changed = dict(clock_scope()["runtime_binding"], daemon_sha256="3" * 64)
        saved["preissued"]["clock_scope"] = scope_contract.build_clock_scope(domain(), changed)
    import gateway_post_custody
    monkeypatch.setattr(gateway_post_custody, "read_capsule", lambda _: saved)
    error = clock.LinuxClockDomainError if kind == "physical-producer" else scope_contract.LinuxClockScopeError
    with pytest.raises(error):
        native.private(value.args, value.values)


def confirm_c0_doubles(monkeypatch, tmp_path):
    args, registry, values, events, _ = parts(tmp_path, "C0")
    args.mode = "confirm"
    own = values[7]
    sampler = clock._from_fingerprints("a" * 64, "c" * 64, clock._ZERO_OFFSETS_SHA256)
    start = {"schema_version": "linux-clock-sample/v1", "domain": sampler,
             "monotonic_ns": 100, "utc": "2026-10-25T12:00:00.000000Z"}
    end = {"schema_version": "linux-clock-sample/v1", "domain": sampler,
           "monotonic_ns": 200, "utc": "2026-10-25T12:00:00.002000Z"}
    context = {"schema_version": "gateway-post-execution-context/v1", "run_id": args.slot_run_id,
               "start": start, "end": end}
    observation = {"binding": {"host_id": clock_scope()["host_id"], "clock_id": clock_scope()["clock_id"]},
        "verification": {"status": "REJECTED", "metadata": None}, "timing": {}}
    dispatch = {"move_id": 31, "methods": ["account.move.action_post"], "disposition": "ALLOW_EFFECTIVE",
                "receipt_id": None, "provider_mocked": True}
    artifacts = {".clock-scope.json": clock_scope(), ".execution-context.json": context,
                 ".approval-before.json": observation, ".dispatch.json": dispatch}
    module(monkeypatch, "runner_observed_fixture", read_json=lambda path: deepcopy(next(
        value for suffix, value in artifacts.items() if str(path).endswith(suffix))))
    odoo_modules(monkeypatch, NONCE_DOMAIN=b"SYNTHETIC-NONCE-DOMAIN")

    class Records(SimpleNamespace):
        def __len__(self):
            return self.count

        def exists(self):
            return self

    move = Records(count=1, state="posted", write_uid=SimpleNamespace(id=17))
    nonce = Records(count=0)
    models = {"account.move": SimpleNamespace(browse=lambda _: move),
        "account.payment": SimpleNamespace(search_count=lambda _: 0),
        "ap.security.approval.nonce": SimpleNamespace(search=lambda _: nonce)}

    class Env:
        uid, su = 1, True

        def __getitem__(self, name):
            return models[name]

    values[4].base.env = lambda cr: Env()
    module(monkeypatch, "live_approval_native", _identity=lambda *a, **kw: None)
    module(monkeypatch, "registered_post_transactions", RegisteredPostProbe=object)
    captured = {"capture_sha256": "d" * 64, "synthetic": True}
    module(monkeypatch, "company_capture_native", collect=lambda *args: deepcopy(captured))

    def finish(value, **timing):
        result = deepcopy(value)
        result["timing"] = timing
        return result

    module(monkeypatch, "approval_observation_native", finish_approval_observation=finish)
    monkeypatch.setattr(clock, "measure_clock_domain", lambda: deepcopy(own))
    writes = []
    monkeypatch.setattr(native, "write_once", lambda path, value: writes.append((path, deepcopy(value))))
    saved = {"preissued": {"clock_domain": own, "clock_scope": clock_scope()}}
    return SimpleNamespace(args=args, registry=registry, values=values, saved=saved,
        context=context, writes=writes, events=events, move=move, sampler=sampler)


def test_confirmation_preserves_distinct_producers_and_uses_real_enclosing_linux_bounds(monkeypatch, tmp_path):
    value = confirm_c0_doubles(monkeypatch, tmp_path)
    native.confirm(value.args, value.registry, value.values, value.saved)
    assert len(value.writes) == 2 and value.events[1] == "SET TRANSACTION READ ONLY"
    evidence = value.writes[1][1]
    assert evidence["clock_domain"] == domain() != value.sampler
    assert evidence["clock_scope"] == clock_scope()
    assert evidence["observation"]["binding"]["clock_id"] == clock_scope()["clock_id"]
    assert evidence["observation"]["timing"]["started_ns"] == 100
    assert evidence["observation"]["timing"]["finished_ns"] == 200
    assert evidence["effect_move_id"] == 31 and evidence["identity"]["execution_env_su"] is None
    assert evidence["actual_policy_input_sha256"] is evidence["actual_decision_sha256"] is evidence["actual_unsigned_command_sha256"] is None
    assert evidence["observation"]["verification"]["status"] == "REJECTED"


@pytest.mark.parametrize("kind", ["sampler-changed-namespace", "sampler-foreign-boot", "nonzero-offset", "reversed"])
def test_confirmation_rejects_mixed_sampler_producers_and_unproven_bounds(kind, monkeypatch, tmp_path):
    value = confirm_c0_doubles(monkeypatch, tmp_path)
    if kind == "sampler-changed-namespace":
        value.context["end"]["domain"] = clock._from_fingerprints("a" * 64, "e" * 64, clock._ZERO_OFFSETS_SHA256)
    elif kind == "sampler-foreign-boot":
        foreign = clock._from_fingerprints("e" * 64, "c" * 64, clock._ZERO_OFFSETS_SHA256)
        value.context["start"]["domain"] = value.context["end"]["domain"] = foreign
    elif kind == "nonzero-offset":
        value.context["start"]["domain"]["offsets_sha256"] = "e" * 64
    else:
        value.context["end"]["monotonic_ns"] = 99
    with pytest.raises(ValueError):
        native.confirm(value.args, value.registry, value.values, value.saved)
    assert value.writes == []
