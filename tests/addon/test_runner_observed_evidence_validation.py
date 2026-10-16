"""DEC-054 gates: synthetic artifacts, never native or scientific evidence.

The gateway fixture evaluates real contracts and policy over an explicit fake
reader. Execution/confirmation records below are synthetic claims to exercise
the validator, not a substitute for the ordinary-cursor Odoo proof.
"""

from copy import deepcopy
from functools import lru_cache
import importlib.util
import json
from pathlib import Path
import sys

import pytest


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "gateway" / "tests"))
SPEC = importlib.util.spec_from_file_location(
    "runner_observed_evidence_validator", ROOT / "scripts" / "validate_runner_observed_evidence.py",
)
validator = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(validator)


def _top(manifest, schema, **fields):
    return {"schema_version": schema, "status": "PASS",
        **{name: manifest[name] for name in validator.DECLARATION_KEYS}, **fields}


@lru_cache(maxsize=1)
def _template():
    # Shared offline gateway helper uses httpx.MockTransport and FakeOdoo only.
    from test_runner_observed_gateway import _offline_artifacts, _evaluated_cases

    manifest, candidates, observations, documents = _offline_artifacts()
    evaluated = _evaluated_cases(manifest, candidates, observations, documents)
    policy = _top(manifest, "runner-observed-policy/v1", cases=evaluated,
        provider_mocked=True, external_provider_called=False, native_json2_not_mocked=True,
        readonly_gateway=True, supervisor_simulated=True, public_c1_executor_opened=False,
        scientific_run=False, human_review=False, test_count=9)
    execution, confirmation = [], []
    for index, name in enumerate(validator.CASE_IDS):
        attempts = []
        if index in {0, 8}:
            statuses = ("CREATED", "REPLAY") if index == 0 else ("REJECTED",)
            for number, status in enumerate(statuses):
                attempts.append({"status": status, "command_sha256": evaluated[index]["command_sha256"],
                    "effect_applied": status == "CREATED", "receipt_id": 77 if index == 0 else None,
                    "move_id": 101 if index == 0 else None,
                    "audit_event_id": 88 + number if index == 0 else None,
                    "reason_codes": ["DRAFT_CONSISTENT" if status in {"CREATED", "REPLAY"} else "BANK_NOT_ALLOWED"],
                    "rejection_boundary": "REGISTERED_WORKFLOW" if status == "REJECTED" else None,
                    "caller_commit_verified": True, "fresh_cursor_verified": True})
        execution.append({"name": name, "status": validator.EXPECTED_NATIVE[index],
            "gateway_decision": evaluated[index]["status"],
            "command_sha256": evaluated[index]["command_sha256"], "attempts": attempts,
            "checks": {check: True for check in validator.EXECUTION_CHECKS}})
        confirmation.append({"name": name, "status": "PASS", "gateway_decision": evaluated[index]["status"],
            "native_status": validator.EXPECTED_NATIVE[index], "snapshot_sha256": "sha256:" + format(index + 1, "064x"),
            "checks": {check: True for check in validator.CONFIRMATION_CHECKS}})
    target = manifest["cases"][7]["target_move_id"]
    baseline = sorted([target, target + 1])
    records = dict(zip(validator.FILENAMES, (
        manifest, candidates, observations, policy,
        _top(manifest, "runner-observed-execution/v1", cases=execution),
        _top(manifest, "runner-observed-confirmation/v1", cases=confirmation,
            company_summary={"bill_count": 3, "draft_bill_count": 3, "posted_bill_count": 0,
                "receipt_count": 2, "audit_event_count": 3, "attachment_count": 2,
                "payment_count": 0, "approval_nonce_count": 0,
                "baseline_bill_ids": baseline, "created_bill_ids": [101]},
            checks={check: True for check in validator.GLOBAL_CHECKS}),
    ), strict=True))
    return records


def _proof():
    return deepcopy(_template())


def _accept(records):
    manifest = records["observed-manifest.json"]
    return validator.validate_bundle(records, git_base=manifest["git_base"],
        source_bundle_sha256=manifest["source_bundle_sha256"])


def _case(records, filename, index=0):
    return records[filename]["cases"][index]


def _write_bundle(directory, records):
    directory.mkdir(parents=True)
    for name, value in records.items():
        (directory / name).write_text(json.dumps(value), encoding="utf-8")


def test_explicit_synthetic_bundle_passes_without_mutation():
    records = _proof()
    before = deepcopy(records)
    result = _accept(records)
    assert result["case_count"] == 9 and result["native_attempt_count"] == 3
    assert result["native_json2_request_count"] > 0
    assert records == before


@pytest.mark.parametrize("filename", validator.FILENAMES)
def test_all_artifacts_have_closed_top_level_keys(filename):
    records = _proof()
    records[filename]["unexpected"] = "UNTRUSTED-ARTIFACT-MARKER"
    with pytest.raises(ValueError):
        _accept(records)


@pytest.mark.parametrize("filename", validator.FILENAMES[1:])
@pytest.mark.parametrize("field", sorted(validator.DECLARATION_KEYS))
def test_every_artifact_is_bound_to_identical_provenance(filename, field):
    records = _proof()
    records[filename][field] = "9" * (40 if field == "git_base" else 64)
    with pytest.raises(ValueError):
        _accept(records)


@pytest.mark.parametrize("filename", validator.FILENAMES)
@pytest.mark.parametrize("mutation", ["missing", "duplicate", "reordered"])
def test_exact_finite_case_order_is_required(filename, mutation):
    records = _proof()
    cases = records[filename]["cases"]
    if mutation == "missing":
        cases.pop()
    elif mutation == "duplicate":
        cases[1] = deepcopy(cases[0])
    else:
        cases[0], cases[1] = cases[1], cases[0]
    with pytest.raises(ValueError):
        _accept(records)


@pytest.mark.parametrize("field", ["provider_mocked", "external_provider_called", "native_json2_not_mocked",
    "readonly_gateway", "supervisor_simulated", "public_c1_executor_opened", "scientific_run", "human_review"])
@pytest.mark.parametrize("invalid", [0, 1, "false", "true", None])
def test_scope_flags_are_exact_booleans_not_truthy_values(field, invalid):
    records = _proof()
    records["observed-policy.json"][field] = invalid
    with pytest.raises(ValueError):
        _accept(records)


@pytest.mark.parametrize("invalid", [True, "9", 9.0, None])
def test_policy_count_is_strict_integer(invalid):
    records = _proof()
    records["observed-policy.json"]["test_count"] = invalid
    with pytest.raises(ValueError):
        _accept(records)


@pytest.mark.parametrize("filename", ["observed-observations.json", "observed-policy.json",
    "observed-execution.json", "observed-confirmation.json"])
@pytest.mark.parametrize("mutation", ["empty", "false", "numeric", "string", "extra"])
def test_native_policy_and_confirmation_checks_are_closed_exact_booleans(filename, mutation):
    records = _proof()
    checks = _case(records, filename)["checks"]
    name = next(iter(checks))
    if mutation == "empty":
        checks.clear()
    elif mutation == "extra":
        checks["unused"] = True
    else:
        checks[name] = {"false": False, "numeric": 1, "string": "true"}[mutation]
    with pytest.raises(ValueError):
        _accept(records)


@pytest.mark.parametrize("field", ["request_sha256", "proposal_sha256", "action_sha256"])
def test_candidate_integrity_is_recomputed_not_trusted(field):
    records = _proof()
    value = _case(records, "observed-candidates.json")
    value[field] = ("sha256:" if field == "action_sha256" else "") + "f" * 64
    with pytest.raises(ValueError):
        _accept(records)


def test_manifest_model_output_rejects_extra_instructions_even_when_candidates_are_valid():
    records = _proof()
    _case(records, "observed-manifest.json")["model_output"]["unexpected"] = "not-authority"
    with pytest.raises(ValueError):
        _accept(records)


@pytest.mark.parametrize("field,value", [("registration_id", True), ("company_id", "1"),
    ("executor_user_id", False), ("purchase_line_ids", [True]), ("allowed_bank_ids", [999]),
    ("code_commit", "f" * 40), ("configuration_sha256", "sha256:" + "f" * 64)])
def test_independent_binding_cannot_be_coerced_or_replaced(field, value):
    records = _proof()
    _case(records, "observed-manifest.json")["binding"][field] = value
    with pytest.raises(ValueError):
        _accept(records)


@pytest.mark.parametrize("index", [3, 4, 5, 6, 7])
def test_clean_native_observation_does_not_substitute_for_named_negative(index):
    records = _proof()
    _case(records, "observed-observations.json", index)["observation"] = deepcopy(
        _case(records, "observed-observations.json")["observation"])
    with pytest.raises(ValueError):
        _accept(records)


@pytest.mark.parametrize("field", ["observation_sha256", "policy_input_sha256", "command_sha256"])
def test_policy_hash_crosslinks_must_match_actual_content(field):
    records = _proof()
    _case(records, "observed-policy.json")[field] = ("sha256:" if field == "observation_sha256" else "") + "f" * 64
    with pytest.raises(ValueError):
        _accept(records)


def test_validly_rehashed_capability_cannot_change_registered_idempotency_identity():
    records = _proof()
    case = _case(records, "observed-policy.json")
    case["command"]["idempotency_key"] = "sha256:" + "f" * 64
    case["command_sha256"] = validator.canonical_json_sha256(case["command"])
    validator.CapabilityCommand.from_mapping(case["command"]).validate_binding(
        validator.PolicyInput.from_mapping(case["policy_input"]))
    with pytest.raises(ValueError):
        _accept(records)


def test_validly_rebound_but_fabricated_policy_decision_is_recomputed():
    records = _proof()
    case = _case(records, "observed-policy.json", 1)
    decision = case["decision"]
    # Still a valid typed DENY with exact action/input/timestamp binding, but
    # invent a reason not produced by the actual evaluator for this state.
    decision["reason_codes"] = ["BANK_NOT_ALLOWED"]
    validator.PolicyDecision.from_mapping(decision).validate_binding(
        validator.PolicyInput.from_mapping(case["policy_input"]))
    with pytest.raises(ValueError):
        _accept(records)


@pytest.mark.parametrize("field,invalid", [("native_json2_request_count", True),
    ("native_json2_request_count", "1"), ("readonly_call_trace", [["account.move", "create"]]),
    ("readonly_call_trace", [["res.users", "search_read"]])])
def test_trace_requires_positive_typed_count_and_readonly_finite_methods(field, invalid):
    records = _proof()
    _case(records, "observed-policy.json")[field] = invalid
    with pytest.raises(ValueError):
        _accept(records)


@pytest.mark.parametrize("index", [1, 2, 3, 4, 5, 6, 7])
def test_deny_review_and_drift_cannot_dispatch_even_valid_other_command(index):
    records = _proof()
    policy = _case(records, "observed-policy.json", index)
    source = _case(records, "observed-policy.json")
    policy["command"], policy["command_sha256"] = deepcopy(source["command"]), source["command_sha256"]
    with pytest.raises(ValueError):
        _accept(records)


@pytest.mark.parametrize("field,value", [("effect_applied", 1), ("receipt_id", True),
    ("audit_event_id", "88"), ("caller_commit_verified", "true"), ("fresh_cursor_verified", False),
    ("reason_codes", ["IDEMPOTENT_REPLAY"]), ("command_sha256", "f" * 64)])
def test_financial_attempts_need_exact_types_outcomes_and_command_binding(field, value):
    records = _proof()
    _case(records, "observed-execution.json")["attempts"][0][field] = value
    with pytest.raises(ValueError):
        _accept(records)


@pytest.mark.parametrize("field", ["move_id", "receipt_id", "audit_event_id"])
def test_replay_refers_to_same_receipt_and_move_but_different_event(field):
    records = _proof()
    first, replay = _case(records, "observed-execution.json")["attempts"]
    replay[field] = first[field] if field == "audit_event_id" else first[field] + 1
    with pytest.raises(ValueError):
        _accept(records)


@pytest.mark.parametrize("attempt_index", [0, 1])
@pytest.mark.parametrize("invented", ["DRAFT_CREATED", "IDEMPOTENT_REPLAY"])
def test_create_and_replay_require_actual_kernel_policy_reason_not_invented_status_codes(attempt_index, invented):
    records = _proof()
    _case(records, "observed-execution.json")["attempts"][attempt_index]["reason_codes"] = [invented]
    with pytest.raises(ValueError):
        _accept(records)


@pytest.mark.parametrize("field,value", [("status", "DENIED"), ("effect_applied", True),
    ("rejection_boundary", None), ("rejection_boundary", "AUDITED_KERNEL"),
    ("audit_event_id", 99), ("receipt_id", 77), ("move_id", 101),
    ("reason_codes", ["DRAFT_CREATED"]), ("fresh_cursor_verified", "true")])
def test_late_revocation_is_exact_registry_rejection_without_fabricated_audit(field, value):
    records = _proof()
    _case(records, "observed-execution.json", 8)["attempts"][0][field] = value
    with pytest.raises(ValueError):
        _accept(records)


@pytest.mark.parametrize("mutation", ["wrong-created", "same-baseline", "target-missing", "payment", "bool-count"])
def test_companywide_confirmation_is_linked_to_actual_create_and_origin(mutation):
    records = _proof()
    summary = records["observed-confirmation.json"]["company_summary"]
    if mutation == "wrong-created":
        summary["created_bill_ids"] = [999]
    elif mutation == "same-baseline":
        summary["baseline_bill_ids"] = sorted([summary["baseline_bill_ids"][0], 101])
    elif mutation == "target-missing":
        summary["baseline_bill_ids"] = [301, 302]
    elif mutation == "payment":
        summary["payment_count"] = 1
    else:
        summary["posted_bill_count"] = False
    with pytest.raises(ValueError):
        _accept(records)


@pytest.mark.parametrize("raw", [b'{"same":1,"same":2}', b'[NaN]', b'[Infinity]', b'[-Infinity]', b'\xff'])
def test_disk_parser_rejects_duplicate_keys_nonfinite_numbers_and_non_utf8(tmp_path, raw):
    path = tmp_path / "bad.json"
    path.write_bytes(raw)
    with pytest.raises((ValueError, UnicodeError)):
        validator.read_json(path)


def test_disk_parser_checks_byte_depth_and_node_budgets(tmp_path, monkeypatch):
    path = tmp_path / "bounded.json"
    monkeypatch.setattr(validator, "_MAX_BYTES", 32)
    path.write_bytes(b" " * 33)
    with pytest.raises(ValueError):
        validator.read_json(path)
    monkeypatch.setattr(validator, "_MAX_BYTES", 1024)
    monkeypatch.setattr(validator, "_MAX_DEPTH", 2)
    path.write_text("[[[0]]]", encoding="utf-8")
    with pytest.raises(ValueError):
        validator.read_json(path)
    monkeypatch.setattr(validator, "_MAX_DEPTH", 24)
    monkeypatch.setattr(validator, "_MAX_NODES", 2)
    path.write_text("[0,1]", encoding="utf-8")
    with pytest.raises(ValueError):
        validator.read_json(path)


def test_parser_does_not_trust_stat_when_the_file_grows(monkeypatch):
    from io import BytesIO
    from types import SimpleNamespace

    monkeypatch.setattr(validator, "_MAX_BYTES", 32)
    observed = []

    class GrowingPath:
        def stat(self):
            return SimpleNamespace(st_size=1)

        def open(self, mode):
            assert mode == "rb"

            class BoundedStream(BytesIO):
                def read(self, size=-1):
                    observed.append(size)
                    return super().read(size)

            return BoundedStream(b" " * 100)

    with pytest.raises(ValueError):
        validator.read_json(GrowingPath())
    assert observed == [33]


def test_in_memory_cycles_are_rejected_without_mutating_them():
    value = []
    value.append(value)
    with pytest.raises(ValueError):
        validator._shape(value)
    assert value[0] is value


def test_cli_validates_only_ignored_artifacts_and_emits_finite_sanitized_result(tmp_path, monkeypatch, capsys):
    records = _proof()
    monkeypatch.setattr(validator, "ROOT", tmp_path)
    directory = tmp_path / ".runtime" / "runner-native" / "synthetic" / "artifacts"
    _write_bundle(directory, records)
    manifest = records["observed-manifest.json"]
    output = directory / "observed-validation.json"
    assert validator.main(["--artifacts", str(directory), "--git-base", manifest["git_base"],
        "--source-bundle-sha256", manifest["source_bundle_sha256"], "--output", str(output)]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result == json.loads(output.read_text(encoding="utf-8"))
    assert result["status"] == "PASS" and set(result["artifact_sha256"]) == set(validator.FILENAMES)
    assert result["scientific_run"] is False and result["human_review_complete"] is False


@pytest.mark.parametrize("mutation", ["outside-input", "outside-output", "wrong-output-name", "bad-json"])
def test_cli_rejects_path_escape_or_untrusted_json_without_exposing_it(tmp_path, monkeypatch, capsys, mutation):
    records = _proof()
    monkeypatch.setattr(validator, "ROOT", tmp_path)
    directory = tmp_path / ".runtime" / "runner-native" / "synthetic" / "artifacts"
    if mutation == "outside-input":
        directory = tmp_path / "outside" / "artifacts"
    _write_bundle(directory, records)
    output = directory / "observed-validation.json"
    if mutation == "outside-output":
        output = tmp_path / "observed-validation.json"
    elif mutation == "wrong-output-name":
        output = directory / "other.json"
    elif mutation == "bad-json":
        (directory / validator.FILENAMES[0]).write_text('{"UNTRUSTED-ARTIFACT-MARKER":NaN}', encoding="utf-8")
    manifest = records["observed-manifest.json"]
    assert validator.main(["--artifacts", str(directory), "--git-base", manifest["git_base"],
        "--source-bundle-sha256", manifest["source_bundle_sha256"], "--output", str(output)]) == 1
    stdout = capsys.readouterr().out
    result = json.loads(stdout)
    assert result["status"] == "FAIL" and result["case_count"] == 0
    assert "UNTRUSTED-ARTIFACT-MARKER" not in stdout and "Traceback" not in stdout
    if mutation != "bad-json":
        assert not output.exists()
