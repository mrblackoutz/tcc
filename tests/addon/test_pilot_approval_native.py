"""DEC-074 real verifier checks with in-memory synthetic authorization only."""

import ast
from copy import deepcopy
from dataclasses import asdict
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
from pathlib import Path
import secrets
import sys
from types import ModuleType, SimpleNamespace

import pytest

from tcc_gateway.approval import ApprovalKey, issue_approval_fixture
from tcc_gateway.policy_contracts import CanonicalAction


ROOT = Path(__file__).resolve().parents[2]
ENTRY = ROOT / "odoo/probes/pilot_approval_native.py"
ADDON = ROOT / "odoo/addons/ap_security_executor"
PACKAGE = "_tcc_pilot_approval_verifier_offline"
package = ModuleType(PACKAGE)
package.__path__ = [str(ADDON)]
sys.modules[PACKAGE] = package


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


load(PACKAGE + ".contracts", ADDON / "contracts.py")
load(PACKAGE + ".draft_contracts", ADDON / "draft_contracts.py")
approval = load(PACKAGE + ".approval", ADDON / "approval.py")
native = load("_pilot_approval_native_test", ENTRY)


def fingerprint(value):
    raw = json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()
    return hashlib.sha256(raw).hexdigest()


def fixture():
    vector = json.loads((ROOT / "gateway/tests/fixtures/canonical_action_v1.vector.json").read_text(encoding="utf-8"))
    action_value = dict(vector["action"], action_schema_version="vendor-bill-action-proposal/v2",
                        action="POST_VENDOR_BILL", executor_mode="POST_APPROVED", target_move_id=123)
    action = CanonicalAction.from_mapping(action_value)
    key = ApprovalKey(company_id=11, key_id="tcc-pilot-binding-test-v1", material=secrets.token_bytes(32))
    fields = {"company_id": 11, "executor_user_id": 22, "fixture_id": "TCC-PILOT-APR-TEST",
        "scenario_id": action.scenario_id, "approver_ref": "TCC-SYNTHETIC-APPROVER",
        "nonce": secrets.token_urlsafe(24), "issued_at": "2026-10-01T12:00:00Z",
        "expires_at": "2026-10-01T12:10:00Z", "key_id": key.key_id}
    token = issue_approval_fixture(action, company_id=fields["company_id"], fixture_id=fields["fixture_id"],
        approver_ref=fields["approver_ref"], nonce=fields["nonce"], issued_at=fields["issued_at"],
        expires_at=fields["expires_at"], key=key)
    command = {"schema_version": "capability-command/v1", "action": action.to_mapping(),
        "idempotency_key": "sha256:" + "c" * 64, "approval": token.to_mapping(),
        "policy_decision": {"schema_version": "policy-decision/v1", "decision": "REVIEW",
            "reason_codes": ["CRITICAL_ACTION_REQUIRES_APPROVAL"],
            "proposed_action_hash": action.action_hash, "input_sha256": "sha256:" + "d" * 64,
            "policy_version": action.policy_version, "allowed_executor": "post_bill_executor", "deny_class": None,
            "evaluated_at": fields["issued_at"], "expires_at": fields["expires_at"]}}
    options = {"trusted_action": action.to_mapping(), "authority": approval.ApprovalAuthority(**fields),
        "key": approval.ApprovalKey(**asdict(key)), "now": datetime(2026, 10, 1, 12, 5, tzinfo=timezone.utc)}
    return command, options


def test_all_twenty_negative_vectors_reach_the_independent_real_verifier_without_mutation():
    command, options = fixture()
    baseline = fingerprint(command), fingerprint(options["trusted_action"])
    authority, key, now = options["authority"], options["key"], options["now"]
    assert approval.verify_approval(command, **options).action_hash == command["policy_decision"]["proposed_action_hash"]
    outcomes = []

    def verify(body, **kwargs):
        try:
            result = approval.verify_approval(body, **kwargs)
        except approval.ApprovalVerificationError as error:
            outcomes.append(error.code)
            raise
        outcomes.append("UNEXPECTED_ACCEPT")
        return result

    count = native._negative_checks(command, **options, verify=verify,
                                    error_type=approval.ApprovalVerificationError)
    assert count == len(outcomes) == 20
    assert "UNEXPECTED_ACCEPT" not in outcomes
    assert {"SIGNATURE_INVALID", "NOT_YET_VALID", "EXPIRED"} <= set(outcomes)
    assert set(outcomes) <= {"CONTRACT_INVALID", "BINDING_MISMATCH", "SIGNATURE_INVALID",
                             "NOT_YET_VALID", "EXPIRED", "DEPENDENCY_UNAVAILABLE"}
    assert (fingerprint(command), fingerprint(options["trusted_action"])) == baseline
    assert options["authority"] == authority and options["key"] == key and options["now"] == now
    assert approval.verify_approval(command, **options).action_hash == command["policy_decision"]["proposed_action_hash"]


def test_unexpected_acceptance_of_a_negative_cannot_be_recorded_as_success():
    command, options = fixture()
    with pytest.raises(ValueError):
        native._negative_checks(command, **options, verify=lambda *_args, **_kwargs: object(),
                                error_type=approval.ApprovalVerificationError)


def test_unrelated_verifier_failure_is_not_counted_as_the_expected_negative():
    command, options = fixture()
    def incorrect_rejection(*_args, **_kwargs):
        raise approval.ApprovalVerificationError("SIGNATURE_INVALID")
    with pytest.raises(ValueError):
        native._negative_checks(command, **options, verify=incorrect_rejection,
                                error_type=approval.ApprovalVerificationError)


def test_negative_checks_never_mint_a_replacement_approval(monkeypatch):
    command, options = fixture()
    def forbidden(*_args, **_kwargs):
        pytest.fail("Negative verification must not issue an approval")
    monkeypatch.setattr(sys.modules[issue_approval_fixture.__module__], "issue_approval_fixture", forbidden)
    assert native._negative_checks(command, **options, verify=approval.verify_approval,
        error_type=approval.ApprovalVerificationError) == 20


@pytest.mark.parametrize("contexts", [(), ({}, {}), [], None], ids=["none", "two", "list", "null"])
def test_run_requires_one_materialized_context_before_native_dependencies(contexts):
    args = SimpleNamespace(mode="materialize", with_approval_binding=True, fixture_ref="FIX-00")
    with pytest.raises(ValueError):
        native.run(args, object(), contexts)


@pytest.mark.parametrize("enabled", [False, 0, 1, None, "true"],
                         ids=["false", "zero", "one", "none", "text"])
def test_run_requires_explicit_true_not_a_truthy_authority_selector(enabled):
    args = SimpleNamespace(mode="materialize", with_approval_binding=enabled, fixture_ref="FIX-00")
    with pytest.raises(ValueError):
        native.run(args, object(), ({},))


@pytest.mark.parametrize("context", [{}, {"approval": "PRIVATE-MARKER"}, [], None],
                         ids=["missing-fields", "authority-injection", "list", "none"])
def test_context_shape_rejected_before_native_imports(context):
    args = SimpleNamespace(mode="materialize", with_approval_binding=True, fixture_ref="FIX-00")
    with pytest.raises(ValueError) as caught:
        native.run(args, object(), (context,))
    assert "PRIVATE-MARKER" not in str(caught.value)


def test_result_transport_and_probe_cannot_persist_usable_authority():
    tree = ast.parse(ENTRY.read_text(encoding="utf-8"))
    forbidden_calls = {"open", "write_text", "write_bytes", "dump", "dumps", "action_post",
                       "post_registered_bill_audited", "create", "write", "unlink", "approval_transaction"}
    # JSON encoding may hash metadata, but the helper must not create a secret
    # file/ledger or perform any financial operation; output is handled outside.
    actual = {node.func.attr if isinstance(node.func, ast.Attribute) else node.func.id
              for node in ast.walk(tree) if isinstance(node, ast.Call)
              and isinstance(node.func, (ast.Attribute, ast.Name))}
    assert not (actual & (forbidden_calls - {"dumps"}))
    negative = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "_negative_checks")
    negative_calls = {node.func.attr if isinstance(node.func, ast.Attribute) else node.func.id
        for node in ast.walk(negative) if isinstance(node, ast.Call)
        and isinstance(node.func, (ast.Attribute, ast.Name))}
    assert not (negative_calls & {"prepare_post", "issue_approval_fixture", "sign", "new"})


def test_module_is_importable_without_odoo_or_http_pdf_client_dependencies():
    tree = ast.parse(ENTRY.read_text(encoding="utf-8"))
    roots = set()
    for node in tree.body:
        if isinstance(node, ast.Import):
            roots.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            roots.add((node.module or "").split(".")[0])
    assert not roots & {"odoo", "httpx", "pypdf", "jsonschema", "tcc_gateway"}


def test_issuance_does_not_branch_on_condition_attack_label_or_proposed_payload():
    tree = ast.parse(ENTRY.read_text(encoding="utf-8"))
    run = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "run")
    names = {node.attr for node in ast.walk(run) if isinstance(node, ast.Attribute)}
    names.update(node.slice.value for node in ast.walk(run) if isinstance(node, ast.Subscript)
                 and isinstance(node.slice, ast.Constant) and type(node.slice.value) is str)
    assert not names & {"condition", "attack_family", "attack_target", "expected_action",
                        "model_output", "adversarial_note", "benign_note", "payload", "label"}
