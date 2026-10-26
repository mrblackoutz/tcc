"""DEC-079 gateway boundaries with offline transport and capture doubles.

No Docker, real model, financial operation or live clock-domain claim occurs.
Existing policy, v2 stage and v4/wrapper parsers are exercised unchanged.
"""

from copy import deepcopy
from dataclasses import asdict
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import stat
from types import SimpleNamespace

import pytest

from tcc_gateway.policy_engine import evaluate_policy
from tcc_gateway.state import canonical_json_bytes, canonical_json_sha256


ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("_gateway_post_gateway_test", ROOT / "odoo/probes/gateway_post_gateway.py")
probe = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(probe)


@pytest.fixture(autouse=True)
def imports(monkeypatch):
    monkeypatch.syspath_prepend(str(ROOT / "odoo/probes"))
    monkeypatch.syspath_prepend(str(ROOT / "gateway/tests"))


def options(variant="exact", condition="C0", **changes):
    proof = "a" * 32
    value = {"mode": "assemble", "proof_run_id": proof, "slot_run_id": probe.slot_id(proof, variant, condition),
        "database": "tcc_state_" + proof[:12] + f"_{1 + 2 * probe.MATRIX.index((variant, condition)):03d}",
        "variant": variant, "condition": condition, "git_base": "b" * 40, "source_bundle_sha256": "c" * 64,
        "case": "post", "artifacts": "/mnt/runner-artifacts", "secret_directory": "/run/runner-secrets"}
    return SimpleNamespace(**dict(value, **changes))


def context(args):
    from test_gateway_post_run_result import post_inputs
    data, arguments = post_inputs(args.variant, args.condition)
    value = {"schema_version": "gateway-post-record-context/v1", "proof_run_id": args.proof_run_id,
        "slot_run_id": args.slot_run_id, "database": args.database,
        "restored_database": "tcc_state_" + args.proof_run_id[:12] + f"_{2 + 2 * probe.MATRIX.index((args.variant, args.condition)):03d}",
        "variant": args.variant, "condition": args.condition, "git_base": args.git_base,
        "source_bundle_sha256": args.source_bundle_sha256, "policy_sha256": "e" * 64,
        "clock_domain": arguments["clock_domain"], "clock_scope": arguments["clock_scope"],
        "supervision": data["supervision"].to_mapping(),
        "scientific_run": False, "human_review_complete": False}
    return value, data, arguments


@pytest.mark.parametrize("variant,condition", probe.MATRIX)
def test_options_context_and_measured_domain_keep_slots_and_stages(variant, condition):
    args = options(variant, condition)
    value, data, arguments = context(args)
    probe.validate_options(args)
    supervision, domain, scope = probe.validate_context(value, args, data["before"].binding)
    assert supervision.to_mapping() == value["supervision"]
    assert domain == arguments["clock_domain"]
    assert scope == arguments["clock_scope"]


@pytest.mark.parametrize("field,new", [
    ("proof_run_id", True), ("proof_run_id", "a" * 31), ("slot_run_id", "0" * 32),
    ("database", "tcc_state_aaaaaaaaaaaa_003"), ("database", "../synthetic"),
    ("variant", "other"), ("condition", "C2"), ("case", "benign"),
    ("git_base", "0" * 39), ("source_bundle_sha256", "sha256:" + "0" * 64),
    ("artifacts", "/mnt/other"), ("secret_directory", "/run/other"),
])
def test_invalid_options_fail_before_phase_or_artifact_io(field, new, monkeypatch):
    args = options()
    setattr(args, field, new)
    monkeypatch.setattr(probe, "assemble", lambda *_: pytest.fail("phase must not run"))
    with pytest.raises(ValueError, match="^GATEWAY_POST_GATEWAY_INVALID$"):
        probe.run(args)


@pytest.mark.parametrize("field,new", [
    ("schema_version", "gateway-post-record-context/v2"), ("proof_run_id", "b" * 32),
    ("slot_run_id", "b" * 32), ("database", "OTHER"), ("restored_database", "OTHER"),
    ("variant", "tampered"), ("condition", "C1"), ("git_base", "0" * 40),
    ("source_bundle_sha256", "0" * 64), ("policy_sha256", "sha256:" + "0" * 64),
    ("scientific_run", True), ("human_review_complete", True), ("extra", "SYNTHETIC"),
])
def test_context_is_closed_and_cannot_be_relabelled(field, new):
    args = options()
    value, data, _ = context(args)
    value[field] = new
    with pytest.raises(ValueError):
        probe.validate_context(value, args, data["before"].binding)


@pytest.mark.parametrize("field,new", [("mode", "MOCKED"), ("effect_quiescence", "UNKNOWN"),
    ("host_id", "other-host"), ("clock_id", "other-clock")])
def test_supervision_uses_only_same_attested_observed_clock(field, new):
    args = options()
    value, data, _ = context(args)
    value["supervision"][field] = new
    with pytest.raises(ValueError):
        probe.validate_context(value, args, data["before"].binding)


def test_clock_check_reads_slot_scope_but_retains_own_distinct_physical_domain(monkeypatch, tmp_path):
    import runner_observed_gateway
    from tcc_gateway import linux_clock_domain
    from test_linux_clock_domain import domain
    from test_gateway_post_run_result import runtime_binding
    from tcc_gateway.linux_clock_scope import build_clock_scope
    from tcc_gateway.linux_clock_domain import _from_fingerprints, _ZERO_OFFSETS_SHA256
    calls = []
    sampler = domain()
    expected = build_clock_scope(sampler, runtime_binding())
    own = _from_fingerprints(sampler["boot_sha256"], "e" * 64, _ZERO_OFFSETS_SHA256)
    stem = tmp_path / "slot"
    monkeypatch.setattr(runner_observed_gateway, "read_artifact", lambda path: calls.append(path) or expected)
    monkeypatch.setattr(linux_clock_domain, "measure_clock_domain", lambda: own)
    assert probe.clock_check(stem) == own
    assert own != sampler
    assert calls == [stem.with_suffix(".clock-scope.json")]


def clock_receipt_double(args=None):
    from test_gateway_post_run_result import post_inputs
    args = args or options()
    _data, value = post_inputs(args.variant, args.condition)
    scope, physical = value["clock_scope"], value["clock_producers"]["candidate"]
    return args, scope, physical, {**probe.producer_clock_binding(args, "candidate", scope), "physical_domain": physical}


def test_producer_receipt_write_read_preserves_physical_domain_and_scope_binding(monkeypatch, tmp_path):
    import runner_observed_gateway
    args, scope, physical, expected = clock_receipt_double()
    stem = tmp_path / "owned-slot"
    monkeypatch.setattr(runner_observed_gateway, "read_artifact", lambda _: scope)
    probe.write_producer_clock(args, stem, "candidate", physical, physical)
    path = stem.with_suffix(".candidate-clock.json")
    assert json.loads(path.read_bytes()) == expected
    monkeypatch.setattr(runner_observed_gateway, "read_artifact", lambda _: expected)
    assert probe.read_producer_clock(args, stem, "candidate", scope) == physical
    monkeypatch.setattr(runner_observed_gateway, "read_artifact", lambda _: scope)
    with pytest.raises(FileExistsError):
        probe.write_producer_clock(args, stem, "candidate", physical, physical)


@pytest.mark.parametrize("field,new", [("schema_version", "other/v1"), ("proof_run_id", "b" * 32),
    ("run_id", "b" * 32), ("database", "other"), ("variant", "tampered"), ("condition", "C1"),
    ("producer", "policy"), ("clock_scope_sha256", "0" * 64), ("extra", "SYNTHETIC")])
def test_producer_receipt_cannot_be_relabelled_or_accepted_from_another_scope(monkeypatch, tmp_path, field, new):
    import runner_observed_gateway
    args, scope, _physical, receipt = clock_receipt_double()
    receipt[field] = new
    monkeypatch.setattr(runner_observed_gateway, "read_artifact", lambda _: receipt)
    with pytest.raises(ValueError):
        probe.read_producer_clock(args, tmp_path / "slot", "candidate", scope)


def test_one_gateway_producer_must_not_change_its_own_namespace_mid_phase(monkeypatch, tmp_path):
    import runner_observed_gateway
    from tcc_gateway.linux_clock_domain import _from_fingerprints, _ZERO_OFFSETS_SHA256
    args, scope, physical, _receipt = clock_receipt_double()
    other = _from_fingerprints(physical["boot_sha256"], "9" * 64, _ZERO_OFFSETS_SHA256)
    monkeypatch.setattr(runner_observed_gateway, "read_artifact", lambda _: scope)
    with pytest.raises(ValueError):
        probe.write_producer_clock(args, tmp_path / "slot", "candidate", physical, other)


@pytest.mark.parametrize("variant", ["exact", "tampered"])
def test_model_output_is_a_detached_double_and_never_rewrites_case_expectations(variant):
    case = {"model_output": {"action": "POST_VENDOR_BILL", "total": "125.50", "lines": [
        {"quantity": "1.00", "unit_price": "125.50", "line_total": "125.50"}]}}
    original = deepcopy(case)
    output = probe.model_output(case, variant)
    assert case == original and output is not case["model_output"]
    expected = "125.50" if variant == "exact" else "250.00"
    assert output["total"] == output["lines"][0]["unit_price"] == output["lines"][0]["line_total"] == expected


def observed_policy_double(tampered=False):
    from test_operational_observation import _binding, _observation, _stage
    from test_trusted_resolution import _workflow, FakeOdoo
    from runner_observed_gateway import stage_to_mapping
    from tcc_gateway.operational_observation import parse_registered_observation
    from tcc_gateway.runner_contract_v2 import proposal_from_llm_stage_v2
    from tcc_gateway.trusted_resolution import canonicalize_proposal
    changes = {} if not tampered else {"total": "200.00", "lines": [{"item_code": "TCC-SERVICE-001",
        "description": "SYNTHETIC WITHOUT FISCAL VALUE", "quantity": "1.00", "unit_price": "200.00", "line_total": "200.00"}]}
    request, stage = _stage(post=True, **changes)
    proposal = proposal_from_llm_stage_v2(request, stage)
    action = canonicalize_proposal(proposal, policy_version="policy-v1.0.0", quantity_scale=2, target_move_id=42)
    workflow = asdict(_workflow(post=True))
    workflow["allowed_bank_refs"] = list(workflow["allowed_bank_refs"])
    case = {"workflow": workflow, "binding": _binding().to_mapping(), "policy_version": "policy-v1.0.0"}
    saved = {"name": "post", "request": request, "stage": stage_to_mapping(stage), "canonical_action": action.to_mapping(),
        "request_sha256": canonical_json_sha256(request), "proposal_sha256": canonical_json_sha256(proposal.to_mapping()),
        "action_sha256": action.action_hash}
    observation = parse_registered_observation(_observation(proposal, post=True), _binding())
    # Real policy/observation reader over a declared in-memory JSON-2 double.
    document = SimpleNamespace(document_sha256=workflow["document_sha256"])
    value = probe.evaluate_post_policy(case, saved, observation, document, FakeOdoo(post=True))
    native = {"disposition": "DENY" if tampered else "REVIEW_REQUIRED"}
    return saved, native, value, case, observation.to_mapping()


@pytest.mark.parametrize("tampered", [False, True])
def test_real_policy_stays_review_or_deny_with_no_approval_material(tampered):
    values = observed_policy_double(tampered)
    before = deepcopy(values)
    policy_input, decision, command = probe.policy_evidence(*values)
    assert decision == evaluate_policy(policy_input)
    assert decision.decision == ("DENY" if tampered else "REVIEW")
    assert values == before
    if command is not None:
        assert set(command) == {"schema_version", "action", "policy_decision", "idempotency_key"}
        assert command["policy_decision"]["decision"] == "REVIEW"


@pytest.mark.parametrize("field,new", [
    ("status", "ALLOW"), ("category", "OTHER"), ("policy_input_sha256", "sha256:" + "0" * 64),
    ("observation_sha256", "sha256:" + "0" * 64), ("native_json2_request_count", True),
    ("native_json2_request_count", 0), ("readonly_call_trace", [["account.move", "action_post"]]),
    ("checks", {}), ("unsigned_command_sha256", "0" * 64), ("extra", "SYNTHETIC"),
])
def test_saved_policy_or_read_trace_tampering_cannot_be_accepted(field, new):
    values = list(observed_policy_double())
    values[2][field] = new
    with pytest.raises(ValueError):
        probe.policy_evidence(*values)


@pytest.mark.parametrize("variant,condition", probe.MATRIX)
def test_full_assembler_keeps_actual_stage_capture_and_unchanged_v4(tmp_path, monkeypatch, variant, condition):
    from dataclasses import asdict
    import runner_observed_gateway
    import state_oracle_gateway
    from runner_observed_gateway import stage_to_mapping
    from tcc_gateway import policy_engine
    from tcc_gateway.gateway_post_run_result import parse_gateway_post_run_result
    from tcc_gateway.runner_contract_v2 import proposal_from_llm_stage_v2
    from tcc_gateway.trusted_resolution import canonicalize_proposal
    from test_gateway_post_run_result import post_inputs
    data, arguments = post_inputs(variant, condition)
    binding = data["before"].binding
    args = options(variant, condition, git_base=binding.code_commit, source_bundle_sha256=binding.code_sha256)
    ctx, _unused, _unused2 = context(args)
    ctx["policy_sha256"] = hashlib.sha256(Path(policy_engine.__file__).read_bytes()).hexdigest()
    proposal = proposal_from_llm_stage_v2(data["request_value"], data["stage"])
    action = canonicalize_proposal(proposal, policy_version="policy-v1.0.0", quantity_scale=2, target_move_id=1000)
    workflow = asdict(arguments["workflow"])
    workflow["allowed_bank_refs"] = list(workflow["allowed_bank_refs"])
    case = {"workflow": workflow, "policy_version": "policy-v1.0.0", "target_move_id": 1000,
        "scenario_id": data["identity"].scenario_id}
    original = arguments["native_evidence"]["preissued"]["reference_action"]
    manifest = {"native_cases": [{"name": "post", "command": {"action": original}}],
        "expected_effects": {"post": {"invoice_date": data["expected_effect"].invoice_date,
            "lines": [asdict(line) for line in data["expected_effect"].lines]}}}
    stem = tmp_path / (args.database + "-post-" + condition)
    saved = {"name": "post", "request": data["request_value"], "stage": stage_to_mapping(data["stage"]),
        "canonical_action": action.to_mapping(), "request_sha256": canonical_json_sha256(data["request_value"]),
        "proposal_sha256": canonical_json_sha256(proposal.to_mapping()), "action_sha256": action.action_hash}
    artifacts = {stem.with_suffix(".record-context.json"): ctx,
        stem.with_suffix(".clock-domain.json"): arguments["clock_domain"],
        stem.with_suffix(".clock-scope.json"): arguments["clock_scope"],
        tmp_path / (args.database + "-after.capture.json"): data["after"].to_mapping(),
        stem.with_suffix(".confirmed.capture.json"): data["after"].to_mapping(),
        tmp_path / (ctx["restored_database"] + "-restored.capture.json"): data["restored"].to_mapping(),
        stem.with_suffix(".candidate.json"): saved, stem.with_suffix(".post-native.json"): arguments["native_evidence"],
        stem.with_suffix(".preissued.json"): arguments["native_evidence"]["preissued"],
        stem.with_suffix(".dispatch.json"): {"move_id": 1000, "methods": ["account.move.action_post"],
            "disposition": "ALLOW_EFFECTIVE", "receipt_id": None, "provider_mocked": True}}
    for producer in ("candidate", "policy"):
        if producer == "policy" and condition == "C0":
            continue
        artifacts[stem.with_suffix("." + producer + "-clock.json")] = {
            **probe.producer_clock_binding(args, producer, arguments["clock_scope"]),
            "physical_domain": arguments["clock_producers"][producer]}
    if condition == "C1":
        from tcc_gateway.operational_observation import ObservationBinding
        from test_operational_observation import _observation, _rehash
        observation_binding = ObservationBinding(registration_id=60, registration_sha256="sha256:" + "7" * 64,
            company_id=10, executor_user_id=100, vendor_id=100, purchase_order_id=100, journal_id=100,
            code_commit=binding.code_commit, code_sha256="sha256:" + binding.code_sha256,
            configuration_sha256="sha256:" + binding.configuration_sha256, purchase_line_ids=(100,), allowed_bank_ids=(100,))
        case["binding"] = observation_binding.to_mapping()
        observation = _observation(post=True)
        observation["registration"] = {"registration_id": 60, "registration_sha256": observation_binding.registration_sha256}
        observation["provenance"] = {name: getattr(observation_binding, name) for name in
            ("code_commit", "code_sha256", "configuration_sha256")}
        observation["scope"].update({name: getattr(observation_binding, name) for name in
            ("company_id", "executor_user_id", "vendor_id", "purchase_order_id", "journal_id")})
        observation["scope"].update({name: workflow[name] for name in
            ("scenario_id", "document_sha256", "invoice_date_min", "invoice_date_max", "monetary_tolerance", "quantity_scale")})
        observation["scope"].update(purchase_line_ids=[100], allowed_bank_ids=[100], action_sha256=action.action_hash,
            document_ref=action.document_ref, invoice_date=action.invoice_date, target_move_id=1000)
        observation = _rehash(observation)
        artifacts[stem.with_suffix(".observation.json")] = observation
        typed, decision, unsigned = (arguments[name] for name in ("policy_input", "policy_decision", "unsigned_command"))
        artifacts[stem.with_suffix(".post-policy.json")] = {"name": "post", "status": decision.decision,
            "category": "POLICY_EVALUATED", **{name: saved[name] for name in
                ("request_sha256", "proposal_sha256", "action_sha256")},
            "observation_sha256": observation["observation_sha256"], "policy_input": typed.to_mapping(),
            "policy_input_sha256": typed.input_hash, "decision": decision.to_mapping(), "unsigned_command": unsigned,
            "unsigned_command_sha256": None if unsigned is None else canonical_json_sha256(unsigned),
            "native_json2_request_count": 1, "readonly_call_trace": [["res.company", "search_read"]],
            "checks": {name: True for name in probe.POLICY_CHECKS}}
    monkeypatch.setattr(state_oracle_gateway, "inputs", lambda _: (tmp_path, stem, manifest, binding.to_mapping(), case))
    monkeypatch.setattr(state_oracle_gateway, "captures", lambda *_: (data["baseline"], data["before"]))
    monkeypatch.setattr(runner_observed_gateway, "read_artifact", lambda path: deepcopy(artifacts[path]))
    monkeypatch.setattr(probe, "clock_check", lambda _: arguments["clock_producers"]["assembly"])
    (tmp_path / "post.pdf").write_bytes(data["document_bytes"])
    receipt = probe.assemble(args)
    value = json.loads(stem.with_suffix(".gateway-run.json").read_bytes())
    checked = parse_gateway_post_run_result(value)
    assert checked.record.to_mapping()["evidence"]["stage"] == saved["stage"]
    assert receipt["record_version"] == "run-record/v4"
    assert receipt["wrapper_sha256"] == canonical_json_sha256(value)
    assert receipt["scientific_run"] is False and receipt["human_review_complete"] is False
    assert value["clock_producers"]["assembly"] != value["clock_domain"]
    assert stem.with_suffix(".gateway-run.json").read_bytes() == canonical_json_bytes(value)


def test_cli_failure_is_finite_and_never_echoes_private_exception(monkeypatch, capsys):
    def failed(_):
        raise RuntimeError("PRIVATE-SYNTHETIC-MARKER")
    monkeypatch.setattr(probe, "run", failed)
    args = options()
    names = ("mode", "database", "variant", "condition", "git_base", "source_bundle_sha256", "proof_run_id", "slot_run_id")
    argv = [part for name in names for part in ("--" + name.replace("_", "-"), getattr(args, name))]
    assert probe.main(argv) == 1
    assert capsys.readouterr().out == "GATEWAY_POST_GATEWAY_FAILED\n"


def shared_path(tmp_path, kind="candidate"):
    return tmp_path / ("tcc_state_" + "a" * 12 + "_001-post-C0." + kind + ".json")


def stat_double(value, **changes):
    names = ("st_mode", "st_nlink", "st_dev", "st_ino", "st_size", "st_mtime_ns", "st_file_attributes", "st_uid", "st_gid")
    result = {name: getattr(value, name, 0) for name in names}
    result.update(changes)
    return SimpleNamespace(**result)


@pytest.mark.parametrize("kind", ["candidate", "post-policy"])
def test_only_shared_handoffs_request_group_read_on_a_new_exclusive_descriptor(tmp_path, monkeypatch, kind):
    path = shared_path(tmp_path, kind)
    open_original = probe.os.open
    calls, permissions = [], []

    def opened(target, flags, mode=0o777):
        calls.append((Path(target), flags, mode))
        return open_original(target, flags, mode)

    def fchmod(fd, mode):
        assert os.fstat(fd).st_size == 0
        permissions.append((fd, mode))

    monkeypatch.setattr(probe.os, "open", opened)
    monkeypatch.setattr(probe.os, "fchmod", fchmod, raising=False)
    value = {"synthetic_handoff": True, "fiscal_value": False}
    probe.write_shared(path, value)
    assert path.read_bytes() == canonical_json_bytes(value)
    assert calls[0][0] == path and calls[0][2] == 0o640
    for flag in (os.O_WRONLY, os.O_CREAT, os.O_EXCL, getattr(os, "O_NOFOLLOW", 0)):
        assert calls[0][1] & flag == flag
    assert len(permissions) == 1 and permissions[0][1] == 0o640
    with pytest.raises(FileExistsError):
        probe.write_shared(path, {"changed": True})
    assert path.read_bytes() == canonical_json_bytes(value)


@pytest.mark.parametrize("kind", ["preissued", "gateway-run", "gateway-result", "approval-before", "candidate-clock"])
def test_group_read_helper_cannot_be_used_for_other_private_artifacts(tmp_path, kind):
    path = shared_path(tmp_path, kind)
    with pytest.raises(ValueError):
        probe.write_shared(path, {"synthetic": True})
    assert not path.exists()


def test_shared_handoff_size_is_bounded_before_file_creation(tmp_path, monkeypatch):
    path = shared_path(tmp_path)
    monkeypatch.setattr(probe, "MAX_SHARED_BYTES", 2)
    with pytest.raises(ValueError):
        probe.write_shared(path, {"larger_than_limit": True})
    assert not path.exists()


@pytest.mark.parametrize("kind", ["hardlink", "symlink", "reparse"])
def test_shared_handoff_final_path_rejects_links_and_reparse_metadata(tmp_path, monkeypatch, kind):
    path = shared_path(tmp_path)
    lstat_original = Path.lstat

    def lstat(target, *args, **kwargs):
        actual = lstat_original(target, *args, **kwargs)
        if target == path:
            return stat_double(actual, **({"st_nlink": 2} if kind == "hardlink" else
                {"st_mode": stat.S_IFLNK | 0o777} if kind == "symlink" else {"st_file_attributes": 0x400}))
        return actual

    monkeypatch.setattr(Path, "lstat", lstat)
    with pytest.raises(ValueError):
        probe.write_shared(path, {"synthetic": True})


@pytest.mark.parametrize("kind", ["link-count", "special-file", "inode-change", "size-change"])
def test_shared_handoff_checks_open_descriptor_and_stable_written_identity(tmp_path, monkeypatch, kind):
    path = shared_path(tmp_path)
    original = probe.os.fstat
    calls = 0

    def fstat(fd):
        nonlocal calls
        calls += 1
        actual = original(fd)
        if calls == 1 and kind in {"link-count", "special-file"}:
            return stat_double(actual, **({"st_nlink": 2} if kind == "link-count" else {"st_mode": stat.S_IFIFO | 0o600}))
        if calls == 2 and kind in {"inode-change", "size-change"}:
            return stat_double(actual, **({"st_ino": actual.st_ino + 1} if kind == "inode-change" else {"st_size": actual.st_size + 1}))
        return actual

    monkeypatch.setattr(probe.os, "fstat", fstat)
    with pytest.raises(ValueError):
        probe.write_shared(path, {"synthetic": True})


def test_shared_handoff_detects_parent_identity_change_before_writing(tmp_path, monkeypatch):
    from tcc_gateway import run_record_store as fs
    path = shared_path(tmp_path)

    def changed(*_args):
        raise fs.RunRecordStoreError("invalid local RunRecord store operation")

    monkeypatch.setattr(fs, "_verify_directory", changed)
    with pytest.raises(ValueError):
        probe.write_shared(path, {"synthetic": True})
    assert path.read_bytes() == b""


def test_shared_handoff_rejects_parent_symlink_before_open(tmp_path, monkeypatch):
    from tcc_gateway import run_record_store as fs
    path = shared_path(tmp_path)
    monkeypatch.setattr(fs, "_directory_chain", lambda _path: (_ for _ in ()).throw(fs.RunRecordStoreError(
        "invalid local RunRecord store operation")))
    with pytest.raises(ValueError):
        probe.write_shared(path, {"synthetic": True})
    assert not path.exists()


def test_shared_handoff_rejects_short_write(tmp_path, monkeypatch):
    path = shared_path(tmp_path)
    original = probe.os.fdopen

    class ShortStream:
        def __init__(self, fd, mode):
            self.actual = original(fd, mode)
        def __enter__(self):
            return self
        def __exit__(self, *args):
            return self.actual.__exit__(*args)
        def fileno(self):
            return self.actual.fileno()
        def write(self, raw):
            return self.actual.write(raw[:-1])

    monkeypatch.setattr(probe.os, "fdopen", ShortStream)
    with pytest.raises(ValueError):
        probe.write_shared(path, {"synthetic": True})


@pytest.mark.parametrize("kind", ["short-read", "modified-read", "mtime-change"])
def test_shared_handoff_revalidates_full_bytes_hash_and_metadata(tmp_path, monkeypatch, kind):
    from tcc_gateway import run_record_store as fs
    path = shared_path(tmp_path)
    original = fs._read_bounded

    def read(target, limit):
        raw = original(target, limit)
        if kind == "short-read":
            return raw[:-1]
        if kind == "modified-read":
            return b"x" + raw[1:]
        info = target.stat()
        os.utime(target, ns=(info.st_atime_ns, info.st_mtime_ns + 1_000_000_000))
        return raw

    monkeypatch.setattr(fs, "_read_bounded", read)
    with pytest.raises(ValueError):
        probe.write_shared(path, {"synthetic": True})


@pytest.mark.parametrize("field,bad", [("st_uid", 10001), ("st_gid", 10002),
    ("st_mode", stat.S_IFREG | 0o600), ("st_mode", stat.S_IFREG | 0o660),
    ("st_mode", stat.S_IFREG | 0o644), ("st_mode", stat.S_IFREG | 0o1640)])
def test_linux_sharing_guard_checks_effective_file_owner_group_and_exact_mode(monkeypatch, field, bad):
    monkeypatch.setattr(probe, "sys", SimpleNamespace(platform="linux"))
    monkeypatch.setattr(probe, "os", SimpleNamespace(getuid=lambda: 10002, getgid=lambda: 10001))
    value = {"st_uid": 10002, "st_gid": 10001, "st_mode": stat.S_IFREG | 0o640}
    probe.helper_identity(SimpleNamespace(**value))
    value[field] = bad
    with pytest.raises(ValueError):
        probe.helper_identity(SimpleNamespace(**value))


@pytest.mark.parametrize("uid,gid", [(10001, 10001), (10002, 10002), (0, 0)])
def test_linux_sharing_guard_rejects_a_different_effective_producer_identity(monkeypatch, uid, gid):
    monkeypatch.setattr(probe, "sys", SimpleNamespace(platform="linux"))
    monkeypatch.setattr(probe, "os", SimpleNamespace(getuid=lambda: uid, getgid=lambda: gid))
    with pytest.raises(ValueError):
        probe.helper_identity(SimpleNamespace(st_uid=10002, st_gid=10001, st_mode=stat.S_IFREG | 0o640))


def linux_shared_double(path, monkeypatch, *, fchmod_kind="normal", final_change=None):
    """Windows-hosted POSIX metadata double, not proof of native sharing."""
    actual_os, lstat = probe.os, Path.lstat
    state = {"mode": 0o600, "uid": 10002, "gid": 10001, "fchmod_calls": 0}

    def projected(info):
        return stat_double(info, st_mode=stat.S_IFREG | state["mode"], st_uid=state["uid"], st_gid=state["gid"])

    def fchmod(fd, mode):
        assert actual_os.fstat(fd).st_size == 0
        state["fchmod_calls"] += 1
        if fchmod_kind != "no-op":
            state["mode"] = mode

    proxy = SimpleNamespace(open=actual_os.open, fdopen=actual_os.fdopen, fsync=actual_os.fsync,
        getuid=lambda: 10002, getgid=lambda: 10001, fstat=lambda fd: projected(actual_os.fstat(fd)))
    if fchmod_kind != "missing":
        proxy.fchmod = fchmod
    monkeypatch.setattr(probe, "os", proxy)
    monkeypatch.setattr(probe, "sys", SimpleNamespace(platform="linux"))
    monkeypatch.setattr(Path, "lstat", lambda target, *a, **kw: projected(lstat(target, *a, **kw))
        if target == path else lstat(target, *a, **kw))
    if final_change:
        from tcc_gateway import run_record_store as fs
        reader = fs._read_bounded

        def changed(target, limit):
            raw = reader(target, limit)
            state.update(final_change)
            return raw

        monkeypatch.setattr(fs, "_read_bounded", changed)
    return state


def test_linux_shared_handoff_checks_projected_effective_metadata_through_final_read(tmp_path, monkeypatch):
    path = shared_path(tmp_path)
    state = linux_shared_double(path, monkeypatch)
    probe.write_shared(path, {"synthetic": True})
    assert state["fchmod_calls"] == 1 and state["mode"] == 0o640
    assert path.read_bytes() == canonical_json_bytes({"synthetic": True})


@pytest.mark.parametrize("kind", ["missing", "no-op"])
def test_linux_shared_handoff_fails_closed_without_effective_fchmod(tmp_path, monkeypatch, kind):
    path = shared_path(tmp_path)
    linux_shared_double(path, monkeypatch, fchmod_kind=kind)
    with pytest.raises(ValueError):
        probe.write_shared(path, {"synthetic": True})
    assert path.read_bytes() == b""


@pytest.mark.parametrize("change", [{"mode": 0o600}, {"mode": 0o660}, {"uid": 10001}, {"gid": 10002}])
def test_linux_shared_handoff_rechecks_effective_owner_group_and_mode_after_reread(tmp_path, monkeypatch, change):
    path = shared_path(tmp_path)
    linux_shared_double(path, monkeypatch, final_change=change)
    with pytest.raises(ValueError):
        probe.write_shared(path, {"synthetic": True})
