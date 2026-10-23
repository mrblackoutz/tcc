"""DEC-076 observer tests using the real independent native verifier, offline."""

import ast
from copy import deepcopy
from dataclasses import asdict, replace
from datetime import datetime, timedelta, timezone
import hashlib
import hmac
import importlib.util
import json
from pathlib import Path
import secrets
import subprocess
import sys
from types import ModuleType

import pytest

from tcc_gateway.approval_observation import (
    ApprovalObservationError, parse_approval_observation, reference_action_sha256,
)


ROOT = Path(__file__).resolve().parents[2]
ENTRY = ROOT / "odoo/probes/approval_observation_native.py"
ADDON = ROOT / "odoo/addons/ap_security_executor"
PACKAGE = "_tcc_approval_observation_real_verifier"
package = ModuleType(PACKAGE)
package.__path__ = [str(ADDON)]
sys.modules[PACKAGE] = package


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


contracts = load(PACKAGE + ".contracts", ADDON / "contracts.py")
approval = load(PACKAGE + ".approval", ADDON / "approval.py")
native = load("_approval_observation_native_under_test", ENTRY)


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def options():
    """All references are synthetic; no runtime files, credentials or Odoo."""
    action = {
        "canonicalization_version": "canon/v1", "action_schema_version": "vendor-bill-action-proposal/v2",
        "policy_version": "policy-v1.0.0", "action": "POST_VENDOR_BILL", "executor_mode": "POST_APPROVED",
        "scenario_id": "SYNTHETIC-01", "document_sha256": "3" * 64, "vendor_ref": "SYNTHETIC-VENDOR",
        "purchase_order_ref": "SYNTHETIC-PO", "document_ref": "SYNTHETIC-DOC", "invoice_date": "2026-10-01",
        "currency": "BRL", "amount": "100.00", "recipient_bank_ref": "SYNTHETIC-BANK",
        "lines": [{"item_code": "SYNTHETIC-ITEM", "quantity": "4.00", "unit_price": "25.00"}],
        "target_move_id": 101,
    }
    authority = approval.ApprovalAuthority(company_id=11, executor_user_id=22,
        fixture_id="SYNTHETIC-APR", scenario_id=action["scenario_id"], approver_ref="SYNTHETIC-APPROVER",
        nonce=secrets.token_urlsafe(24), issued_at="2026-10-01T12:00:00Z",
        expires_at="2026-10-01T12:10:00Z", key_id="synthetic-observer-v1")
    key = approval.ApprovalKey(authority.company_id, authority.key_id, secrets.token_bytes(32))
    window = {"evaluated_at": authority.issued_at, "expires_at": authority.expires_at}
    unsigned = {name: getattr(authority, name) for name in
        ("fixture_id", "scenario_id", "approver_ref", "nonce", "issued_at", "expires_at", "key_id")}
    unsigned.update(decision="APPROVE", canonical_action_hash=reference_action_sha256(action))
    preimage = approval.APPROVAL_DOMAIN + canonical({"company_id": authority.company_id, "approval": unsigned})
    token = dict(unsigned, signature=approval.SIGNATURE_PREFIX + hmac.new(key.material, preimage, hashlib.sha256).hexdigest())
    command = {"schema_version": "capability-command/v1", "action": deepcopy(action), "approval": token,
        "idempotency_key": "sha256:" + "a" * 64,
        "policy_decision": {"schema_version": "policy-decision/v1", "decision": "REVIEW",
            "reason_codes": ["CRITICAL_ACTION_REQUIRES_APPROVAL"],
            "proposed_action_hash": reference_action_sha256(action), "input_sha256": "sha256:" + "b" * 64,
            "policy_version": action["policy_version"], "allowed_executor": "post_bill_executor",
            "deny_class": None, **window}}
    binding = {"run_id": "1" * 32, "condition": "C0", "company_id": authority.company_id,
        "executor_user_id": authority.executor_user_id, "scenario_id": action["scenario_id"],
        "document_sha256": action["document_sha256"], "code_commit": "4" * 40,
        "configuration_sha256": "2" * 64, "before_capture_sha256": "5" * 64,
        "host_id": "synthetic-host", "clock_id": "synthetic-monotonic"}
    return dict(binding=binding, reference_action=action, command=command, authority=authority, key=key,
        now=datetime(2026, 10, 1, 12, 5, tzinfo=timezone.utc), nonce_available=True, decision_window=window)


@pytest.fixture(autouse=True)
def real_verifier(monkeypatch):
    # Only import routing is substituted; all crypto and structural checks are real.
    monkeypatch.setattr(native, "_dependencies", lambda: (
        approval.verify_approval, approval.ApprovalVerificationError, contracts.canonical_action_bytes))


def test_observer_authenticates_real_approval_without_mutating_or_exposing_authority():
    value = options()
    original_command = deepcopy(value["command"])
    original_action = deepcopy(value["reference_action"])
    observed = native.begin_approval_observation(**value)
    assert observed["verification"]["status"] == "VERIFIED"
    verified = approval.verify_approval(value["command"], trusted_action=value["reference_action"],
        authority=value["authority"], key=value["key"], now=value["now"])
    assert observed["verification"]["metadata"] == asdict(verified)
    assert value["command"] == original_command and value["reference_action"] == original_action
    encoded = canonical(observed).decode()
    for forbidden in (value["key"].material.hex(), value["authority"].nonce,
                      value["command"]["approval"]["signature"]):
        assert forbidden not in encoded and forbidden not in repr(observed)
    assert observed["timing"]["checked_at"] == "2026-10-01T12:05:00Z"
    assert observed["timing"]["started_ns"] is None
    value["binding"]["condition"] = "C1"
    value["reference_action"]["amount"] = "999.00"
    assert observed["binding"]["condition"] == "C0" and observed["reference_action"]["amount"] == "100.00"


@pytest.mark.parametrize("condition", ["C0", "C1"])
@pytest.mark.parametrize("nonce_available", [True, False, None])
def test_observation_is_symmetric_and_does_not_turn_prior_nonce_read_into_consumption(condition, nonce_available):
    value = options()
    value["binding"]["condition"] = condition
    value["nonce_available"] = nonce_available
    observed = native.begin_approval_observation(**value)
    assert observed["verification"]["status"] == "VERIFIED"
    assert observed["nonce_available"] is nonce_available
    assert "nonce_consumed" not in observed


@pytest.mark.parametrize("missing", ["command", "approval"])
@pytest.mark.parametrize("condition", ["C0", "C1"])
def test_missing_approval_is_observed_without_raising_execution_veto(missing, condition):
    value = options()
    value["binding"]["condition"] = condition
    if missing == "command":
        value["command"] = None
    else:
        del value["command"]["approval"]
    observed = native.begin_approval_observation(**value)
    assert observed["verification"] == {"status": "ABSENT", "reason_code": "APPROVAL_ABSENT", "metadata": None}


@pytest.mark.parametrize("condition", ["C0", "C1"])
def test_invalid_mac_returns_rejection_not_exception_and_cannot_reveal_mac(condition):
    value = options()
    value["binding"]["condition"] = condition
    signature = value["command"]["approval"]["signature"]
    value["command"]["approval"]["signature"] = signature[:-1] + ("1" if signature[-1] != "1" else "2")
    observed = native.begin_approval_observation(**value)
    assert observed["verification"] == {"status": "REJECTED", "reason_code": "SIGNATURE_INVALID", "metadata": None}
    assert signature not in repr(observed)


@pytest.mark.parametrize("field", ["company_id", "executor_user_id", "scenario_id"])
def test_authority_must_be_configured_for_actual_executing_identity(field):
    value = options()
    replacement = "SYNTHETIC-OTHER" if field == "scenario_id" else getattr(value["authority"], field) + 1
    value["authority"] = replace(value["authority"], **{field: replacement})
    assert native.begin_approval_observation(**value)["verification"] == {
        "status": "INDETERMINATE", "reason_code": "IDENTITY_INVALID", "metadata": None}


@pytest.mark.parametrize("offset,reason", [(-301, "NOT_YET_VALID"), (300, "EXPIRED")])
def test_real_verifier_preserves_finite_clock_rejection(offset, reason):
    value = options()
    value["now"] += timedelta(seconds=offset)
    assert native.begin_approval_observation(**value)["verification"] == {
        "status": "REJECTED", "reason_code": reason, "metadata": None}


def test_reference_is_independent_of_candidate_and_mutation_is_not_signed():
    value = options()
    value["command"]["action"]["document_ref"] = "SYNTHETIC-ALTERED"
    value["command"]["policy_decision"]["proposed_action_hash"] = reference_action_sha256(value["command"]["action"])
    original_signature = value["command"]["approval"]["signature"]
    verification = native.begin_approval_observation(**value)["verification"]
    assert verification["status"] == "REJECTED" and verification["metadata"] is None
    assert verification["reason_code"] in {"CONTRACT_INVALID", "BINDING_MISMATCH"}
    assert value["command"]["approval"]["signature"] == original_signature


def test_declared_decision_window_must_match_original_command_window():
    value = options()
    value["decision_window"] = dict(value["decision_window"], expires_at="2026-10-01T12:20:00Z")
    assert native.begin_approval_observation(**value)["verification"] == {
        "status": "INDETERMINATE", "reason_code": "DECISION_WINDOW_MISMATCH", "metadata": None}


def test_financial_canonical_validation_uses_native_helper_not_structural_parser():
    value = options()
    value["reference_action"]["amount"] = "99.00"
    assert native.begin_approval_observation(**value)["verification"] == {
        "status": "INDETERMINATE", "reason_code": "DEPENDENCY_UNAVAILABLE", "metadata": None}


def test_unavailable_dependency_is_not_absence_and_arbitrary_text_never_escapes(monkeypatch):
    value = options()
    private_marker = "PRIVATE-DEPENDENCY-MARKER"
    def unavailable():
        raise RuntimeError(private_marker)
    monkeypatch.setattr(native, "_dependencies", unavailable)
    observed = native.begin_approval_observation(**value)
    assert observed["verification"] == {
        "status": "INDETERMINATE", "reason_code": "DEPENDENCY_UNAVAILABLE", "metadata": None}
    assert private_marker not in repr(observed)


def test_finish_returns_detached_evidence_without_claiming_interval_validity():
    value = options()
    observed = native.begin_approval_observation(**value)
    finished = native.finish_approval_observation(observed, call_started_at=value["now"] + timedelta(seconds=1),
        call_finished_at=value["now"] + timedelta(seconds=2), started_ns=10, finished_ns=20)
    assert observed["timing"]["started_ns"] is None
    assert finished["timing"]["started_ns"] == 10
    assert finished["verification"] == observed["verification"]


@pytest.mark.parametrize("start,end,start_ns,end_ns", [
    (None, None, None, None), (None, 2, 10, 20), (1, None, 10, None),
    (2, 1, 20, 10), (-1, 1, 10, 20), (600, 601, 10, 20),
])
def test_uncertain_intervals_are_preserved_for_assessor_not_repaired(start, end, start_ns, end_ns):
    value = options()
    observed = native.begin_approval_observation(**value)
    instant = lambda offset: None if offset is None else value["now"] + timedelta(seconds=offset)
    finished = native.finish_approval_observation(observed,
        call_started_at=instant(start), call_finished_at=instant(end), started_ns=start_ns, finished_ns=end_ns)
    assert finished["verification"]["status"] == "VERIFIED"
    assert finished["timing"]["started_ns"] == start_ns and finished["timing"]["finished_ns"] == end_ns


@pytest.mark.parametrize("now", [None, "2026-10-01T12:05:00Z", datetime(2026, 10, 1),
    datetime(2026, 10, 1, tzinfo=timezone(timedelta(hours=1)))])
def test_invalid_clock_cannot_be_represented_as_verified(now):
    value = options()
    value["now"] = now
    with pytest.raises(ApprovalObservationError, match="^invalid sanitized approval observation$"):
        native.begin_approval_observation(**value)


def test_observer_ast_has_no_financial_database_filesystem_clock_or_issuer_calls():
    tree = ast.parse(ENTRY.read_text(encoding="utf-8"))
    calls = {node.func.attr if isinstance(node.func, ast.Attribute) else node.func.id
        for node in ast.walk(tree) if isinstance(node, ast.Call) and isinstance(node.func, (ast.Attribute, ast.Name))}
    assert not calls & {"cursor", "execute", "commit", "rollback", "create", "write", "unlink", "open", "now",
        "write_bytes", "write_text", "issue_approval_fixture", "approval_transaction", "action_post", "print"}


def test_parser_and_native_module_import_without_odoo_or_optional_gateway_dependencies():
    program = """
import importlib.abc, importlib.util, sys
class Block(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split('.')[0] in {'odoo', 'jsonschema', 'httpx', 'pypdf'}:
            raise ImportError('optional dependency blocked')
sys.meta_path.insert(0, Block())
from tcc_gateway.approval_observation import parse_approval_observation
spec = importlib.util.spec_from_file_location('observer', sys.argv[1])
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
"""
    run = subprocess.run([sys.executable, "-c", program, str(ENTRY)], capture_output=True, text=True, check=False)
    assert run.returncode == 0, "stdlib observer import unexpectedly depended on optional runtime"
