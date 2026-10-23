"""DEC-077 development issuer principal selection, with real MAC verification.

Only the issuer methods are AST-isolated from the Odoo-dependent probe. These
tests exercise their actual source and native contracts, not live ORM effects.
"""

import ast
from contextlib import nullcontext
import copy
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
import hashlib
import hmac
import importlib.util
import json
from pathlib import Path
import secrets
import sys
from types import ModuleType

import pytest


ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "odoo/probes/c111_transactions.py"
ADDON = ROOT / "odoo/addons/ap_security_executor"
PACKAGE = "_tcc_c111_principal_contracts"
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
draft = load(PACKAGE + ".draft_contracts", ADDON / "draft_contracts.py")
post = load(PACKAGE + ".post_contracts", ADDON / "post_contracts.py")
approval = load(PACKAGE + ".approval", ADDON / "approval.py")


def issuer_source():
    tree = ast.parse(SOURCE.read_text(encoding="utf-8"))
    names = {"ProbeFailure", "require", "canonical", "digest", "Scope"}
    nodes = [node for node in tree.body if isinstance(node, (ast.ClassDef, ast.FunctionDef))
             and node.name in names]
    probe = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "Probe")
    probe.body = [node for node in probe.body if isinstance(node, ast.FunctionDef)
                  and node.name in {"policy", "prepare_post"}]
    nodes.append(probe)
    module = ModuleType("_tcc_c111_principal_issuer")
    sys.modules[module.__name__] = module
    module.__dict__.update(copy=copy, dataclass=dataclass, datetime=datetime, timedelta=timedelta,
                          timezone=timezone, hashlib=hashlib, hmac=hmac, json=json, secrets=secrets)
    exec(compile(ast.Module(body=nodes, type_ignores=[]), str(SOURCE), "exec"), module.__dict__)
    return module


native = issuer_source()


def fixture(*, has_receipt=True):
    vector = json.loads((ROOT / "gateway/tests/fixtures/canonical_action_v1.vector.json").read_text(encoding="utf-8"))
    action = copy.deepcopy(vector["action"])
    workflow = draft.TrustedDraftWorkflow(
        company_id=11, executor_user_id=22, purchase_order_id=33, vendor_id=44,
        journal_id=55, expense_account_id=66, purchase_line_ids=(77,), allowed_bank_ids=(88,),
        scenario_id=action["scenario_id"], document_sha256=action["document_sha256"],
        policy_version=action["policy_version"], phase="DRAFT_INTAKE", invoice_date_min="2026-09-01",
        invoice_date_max="2026-09-30", quantity_scale=2, monetary_tolerance="0.00")
    command = {"schema_version": "capability-command/v1", "action": action,
               "policy_decision": native.Probe.policy(action, post=False),
               "idempotency_key": "sha256:" + "c" * 64}
    result = {"status": "CREATED", "receipt": {"move_id": 123}} if has_receipt else None
    scope = native.Scope(workflow, command, object(), workflow.vendor_id,
                         workflow.purchase_order_id, result=result)
    base = native.Probe()
    base.company_id, base.user_id = workflow.company_id, workflow.executor_user_id
    base.ApprovalKey, base.ApprovalAuthority = approval.ApprovalKey, approval.ApprovalAuthority
    base.TrustedPostWorkflow, base.approval_domain = post.TrustedPostWorkflow, approval.APPROVAL_DOMAIN
    return base, scope


def verify(scope):
    return approval.verify_approval(scope.post_command, trusted_action=scope.post_command["action"],
        authority=scope.authority, key=scope.key, now=datetime.now(timezone.utc))


@pytest.mark.parametrize("explicit_none", [False, True])
def test_historical_principal_default_preserves_registered_scope_and_create_receipt(explicit_none):
    base, scope = fixture()
    workflow, result, command = scope.workflow, scope.result, copy.deepcopy(scope.command)
    returned = base.prepare_post(scope, **({"executor_user_id": None} if explicit_none else {}))
    assert returned is scope
    assert scope.authority.executor_user_id == base.user_id == workflow.executor_user_id == 22
    assert scope.workflow is workflow and scope.result is result and scope.command == command
    assert scope.post_workflow.draft == workflow and scope.post_workflow.target_move_id == 123
    assert verify(scope).action_hash == native.digest(scope.post_command["action"])


def test_explicit_c0_principal_is_preissued_without_rewriting_c1_configuration():
    base, scope = fixture()
    workflow, result, command = scope.workflow, scope.result, copy.deepcopy(scope.command)
    base.prepare_post(scope, executor_user_id=99)
    assert scope.authority.executor_user_id == 99
    assert base.user_id == workflow.executor_user_id == 22
    assert scope.workflow is workflow and scope.result is result and scope.command == command
    assert scope.post_workflow.draft == workflow
    assert scope.post_command["action"] == dict(command["action"], action="POST_VENDOR_BILL",
        executor_mode="POST_APPROVED", target_move_id=result["receipt"]["move_id"])
    assert verify(scope).scenario_id == workflow.scenario_id


def test_two_principals_receive_independent_fresh_grants_for_the_same_legitimate_action():
    base, restricted = fixture()
    _, functional = fixture()
    base.prepare_post(restricted)
    preserved_authority = asdict(restricted.authority)
    preserved_command = copy.deepcopy(restricted.post_command)
    base.prepare_post(functional, executor_user_id=99)
    assert restricted.post_command["action"] == functional.post_command["action"]
    assert restricted.authority.executor_user_id == 22 and functional.authority.executor_user_id == 99
    assert restricted.authority.nonce != functional.authority.nonce
    assert restricted.key.material != functional.key.material
    assert verify(restricted).action_hash == verify(functional).action_hash
    assert verify(restricted).approval_sha256 != verify(functional).approval_sha256
    assert asdict(restricted.authority) == preserved_authority and restricted.post_command == preserved_command


@pytest.mark.parametrize("principal", [False, True, 0, -1, 1.0, "99", [], {}, object()],
                         ids=["false", "true", "zero", "negative", "float", "text", "list", "dict", "object"])
def test_invalid_principal_fails_before_create_clock_key_or_scope_mutation(principal, monkeypatch):
    base, scope = fixture(has_receipt=False)
    sentinel = object()
    scope.key = scope.authority = scope.post_command = scope.post_workflow = sentinel
    original = scope.workflow, scope.command, scope.document, scope.result

    def forbidden(*_args, **_kwargs):
        pytest.fail("Invalid principal must fail before issuance or CREATE")

    base.create = base.cursor_gate = base.env = forbidden
    monkeypatch.setattr(native, "datetime", type("ForbiddenClock", (), {"now": staticmethod(forbidden)}))
    monkeypatch.setattr(native.secrets, "token_bytes", forbidden)
    monkeypatch.setattr(native.secrets, "token_urlsafe", forbidden)
    with pytest.raises(native.ProbeFailure) as caught:
        base.prepare_post(scope, executor_user_id=principal)
    assert str(caught.value) == "approval_principal_positive_id"
    assert (scope.workflow, scope.command, scope.document, scope.result) == original
    assert scope.key is scope.authority is scope.post_command is scope.post_workflow is sentinel
    assert base.user_id == 22


def test_historical_default_can_still_create_a_missing_receipt_in_its_original_branch():
    base, scope = fixture(has_receipt=False)
    calls = []
    cursor = object()
    base.registry = type("RegistryDouble", (), {"cursor": lambda _self: nullcontext(cursor)})()
    base.cursor_gate = lambda value: calls.append(("cursor", value is cursor))
    base.env = lambda value: value

    def create(env, selected):
        calls.append(("create", env is cursor and selected is scope))
        return {"status": "CREATED", "receipt": {"move_id": 123}}

    base.create = create
    base.success = lambda result, status: calls.append((status, result["status"] == status))
    base.prepare_post(scope)
    assert calls == [("cursor", True), ("create", True), ("CREATED", True)]
    assert scope.result["receipt"]["move_id"] == 123
    assert scope.authority.executor_user_id == 22
    assert verify(scope).action_hash == native.digest(scope.post_command["action"])


def test_explicit_identity_does_not_implicitly_become_native_post_workflow_identity():
    base, scope = fixture()
    base.prepare_post(scope, executor_user_id=99)
    # The native caller must validate execution identity independently. This
    # issuer option is not a grant of C1 ACLs and never registers a new workflow.
    assert scope.authority.executor_user_id != scope.post_workflow.draft.executor_user_id
    assert scope.post_workflow.draft.executor_user_id == base.user_id == 22
