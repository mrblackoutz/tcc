# SPDX-License-Identifier: LGPL-3.0-or-later
"""Source regression gates for the private registered POST handoff.

AST checks cover interface and delegation shape only. They do not authenticate
the caller, exercise PostgreSQL, verify an approval, or prove rollback. Native
ORM and ordinary-cursor lifecycle tests remain necessary under DEC-052.
"""

from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
ADDON = ROOT / "odoo/addons/ap_security_executor"
SOURCE = ADDON / "registered_post.py"
ENTRY = "post_registered_bill_audited"


def tree() -> ast.Module:
    return ast.parse(SOURCE.read_text(encoding="utf-8"))


def function(name: str, *, source: Path = SOURCE) -> ast.FunctionDef:
    module = tree() if source == SOURCE else ast.parse(source.read_text(encoding="utf-8"))
    matches = [node for node in module.body if isinstance(node, ast.FunctionDef) and node.name == name]
    assert len(matches) == 1
    return matches[0]


def calls(node: ast.AST, name: str) -> list[ast.Call]:
    """Match either a qualified call or its terminal name, ordered by source."""
    return sorted(
        [child for child in ast.walk(node) if isinstance(child, ast.Call)
         and (ast.unparse(child.func) == name or (
             isinstance(child.func, ast.Attribute) and child.func.attr == name))],
        key=lambda child: child.lineno,
    )


def statements_without_docstring(node: ast.FunctionDef) -> list[ast.stmt]:
    body = node.body
    if (body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant)
            and isinstance(body[0].value.value, str)):
        body = body[1:]
    return body


def string_constants(node: ast.AST) -> set[str]:
    return {child.value for child in ast.walk(node)
            if isinstance(child, ast.Constant) and isinstance(child.value, str)}


def reached_local_helpers(entry: ast.FunctionDef) -> ast.Module:
    """Follow local function calls; splitting checks into helpers is allowed.

    This is a bounded static call graph, not a claim about runtime execution.
    External API delegation is checked explicitly where its contract matters.
    """
    available = {node.name: node for node in tree().body if isinstance(node, ast.FunctionDef)}
    pending = [entry]
    reached = {}
    while pending:
        current = pending.pop()
        if current.name in reached:
            continue
        reached[current.name] = current
        for node in ast.walk(current):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                target = available.get(node.func.id)
                if target is not None:
                    pending.append(target)
    return ast.Module(body=list(reached.values()), type_ignores=[])


def test_registered_post_entry_has_no_authority_target_workflow_or_clock_override():
    entry = function(ENTRY)
    assert [argument.arg for argument in entry.args.args] == ["env"]
    assert [argument.arg for argument in entry.args.kwonlyargs] == [
        "registration_id", "expected_company_id", "expected_executor_user_id",
        "expected_scenario_id", "command", "audit", "document", "authority", "key",
    ]
    assert entry.args.vararg is None and entry.args.kwarg is None
    assert not entry.args.posonlyargs and not entry.args.defaults
    assert all(default is None for default in entry.args.kw_defaults)
    assert not entry.decorator_list


def test_real_registrar_is_the_first_operation_before_savepoint_or_elevation():
    entry = function(ENTRY)
    first = statements_without_docstring(entry)[0]
    assert isinstance(first, ast.Expr) and isinstance(first.value, ast.Call)
    assert ast.unparse(first.value.func) == "workflow_registry._registrar"
    assert [ast.unparse(value) for value in first.value.args] == ["env"]
    assert not first.value.keywords
    assert not calls(entry, "sudo") and not calls(entry, "with_user")
    points = calls(entry, "env.cr.savepoint")
    assert points and first.lineno < min(point.lineno for point in points)


def test_module_does_not_add_a_public_model_or_rpc_entry():
    module = tree()
    classes = [node for node in module.body if isinstance(node, ast.ClassDef)]
    for node in classes:
        assert not any("Model" in ast.unparse(base) for base in node.bases)
        assert not any(isinstance(child, ast.FunctionDef) and child.name == "execute"
                       for child in node.body)
    public = {node.name for node in module.body if isinstance(node, ast.FunctionDef)
              and not node.name.startswith("_")}
    assert public == {ENTRY}
    assert not calls(module, "route") and not calls(module, "evaluate_oracle")


def test_external_savepoint_encloses_registration_origin_effect_and_verification():
    entry = function(ENTRY)
    points = [node for node in ast.walk(entry) if isinstance(node, ast.With)
              and any(isinstance(item.context_expr, ast.Call)
                      and ast.unparse(item.context_expr.func) == "env.cr.savepoint"
                      for item in node.items)]
    assert len(points) == 1
    point = points[0]
    resolutions = calls(point, "workflow_registry.resolve_draft_workflow")
    locks = calls(point, "_lock_registration")
    origins = calls(point, "_origin")
    effect = calls(point, "audit_kernel.post_bill_audited")
    fault = calls(point, "_after_registered_post")
    verified = calls(point, "_verified_result")
    assert len(resolutions) >= 3 and len(origins) >= 2
    assert len(locks) == len(effect) == len(fault) == len(verified) == 1
    assert resolutions[0].lineno < locks[0].lineno < resolutions[1].lineno
    assert resolutions[1].lineno < origins[0].lineno < effect[0].lineno
    assert effect[0].lineno < fault[0].lineno < origins[-1].lineno < verified[0].lineno
    returned, = [node for node in ast.walk(point) if isinstance(node, ast.Return)]
    assert verified[0].lineno < returned.lineno


def test_post_delegates_only_to_the_existing_audited_financial_kernel():
    module = tree()
    effect, = calls(function(ENTRY), "audit_kernel.post_bill_audited")
    assert [ast.unparse(value) for value in effect.args] == ["env"]
    arguments = {keyword.arg: keyword.value for keyword in effect.keywords}
    assert set(arguments) == {"command", "workflow", "authority", "key", "audit", "document"}
    for name in {"command", "authority", "key", "audit", "document"}:
        assert ast.unparse(arguments[name]) == name
    assert ast.unparse(arguments["workflow"]) not in {
        argument.arg for argument in function(ENTRY).args.kwonlyargs}
    assert not calls(module, "create_draft_audited")
    assert not calls(module, "post_bill_atomic") and not calls(module, "create_draft_atomic")
    forbidden = {"commit", "rollback", "create", "write", "unlink", "action_post", "sleep",
                 "post", "request", "send", "print", "repr"}
    assert not any(isinstance(node, ast.Call) and (
        isinstance(node.func, ast.Attribute) and node.func.attr in forbidden
        or isinstance(node.func, ast.Name) and node.func.id in forbidden)
        for node in ast.walk(module))
    assert not any(isinstance(node, ast.While) for node in ast.walk(module))
    assert not any(isinstance(node, ast.For) for node in ast.walk(function(ENTRY)))


def test_closed_command_is_detached_validated_and_preserves_post_intent():
    command = function("_command")
    assert len(calls(command, "_snapshot")) == 1
    assert len(calls(command, "validate_command")) == 1
    assert any(isinstance(node, ast.Compare)
               and isinstance(node.left, ast.Attribute) and node.left.attr == "executor_mode"
               and len(node.ops) == 1 and isinstance(node.ops[0], ast.NotEq)
               and isinstance(node.comparators[0], ast.Constant)
               and node.comparators[0].value == "POST_APPROVED" for node in ast.walk(command))
    assert not any(isinstance(node, (ast.Assign, ast.AnnAssign, ast.AugAssign))
                   and any(isinstance(target, ast.Subscript) for target in (
                       node.targets if isinstance(node, ast.Assign) else [node.target]))
                   for node in ast.walk(command))


def test_registration_provenance_is_derived_from_the_checked_audit_context():
    entry = function(ENTRY)
    checked, = calls(entry, "_audit_context")
    provenance, = calls(entry, "WorkflowProvenance")
    assert checked.lineno < provenance.lineno
    assert {keyword.arg: ast.unparse(keyword.value) for keyword in provenance.keywords} == {
        "code_commit": "audit.code_commit", "code_sha256": "audit.code_sha256",
        "configuration_sha256": "audit.configuration_sha256",
    }
    assert provenance.lineno < calls(entry, "workflow_registry.resolve_draft_workflow")[0].lineno


def test_origin_requires_audited_create_receipt_and_registered_idempotency_identity():
    origin = function("_origin")
    reached = reached_local_helpers(origin)
    constants = string_constants(reached)
    assert {"ap.security.draft.receipt", "CREATE_DRAFT", "CREATED"} <= constants
    assert calls(reached, "bill_idempotency_key")
    original, = calls(origin, "audit_kernel._original_event")
    assert {keyword.arg for keyword in original.keywords} >= {"workflow", "audit"}
    assert ast.unparse(next(keyword.value for keyword in original.keywords if keyword.arg == "audit")) == "audit"
    assert calls(origin, "audit_kernel._verify_event")
    delegated = function("_original_event", source=ADDON / "audit_kernel.py")
    assert calls(delegated, "_workflow_hash") and calls(delegated, "_verify_event")
    assert {"code_commit", "code_sha256", "configuration_sha256"} <= string_constants(delegated)
    event_check = function("_verify_event", source=ADDON / "audit_kernel.py")
    assert calls(event_check, "verify_document_attachment")
    # No early receipt FOR UPDATE: the financial kernel retains guard order.
    assert not any("FOR UPDATE" in value.upper() for value in constants)
    assert not calls(origin, "_lock_approval_nonce")


def test_post_target_is_derived_from_the_verified_origin_receipt_not_the_command():
    origin = function("_origin")
    workflow, = calls(origin, "TrustedPostWorkflow")
    arguments = {keyword.arg: keyword.value for keyword in workflow.keywords}
    assert set(arguments) == {"draft", "target_move_id"}
    target = arguments["target_move_id"]
    assert (isinstance(target, ast.Attribute) and target.attr == "id"
            and isinstance(target.value, ast.Attribute) and target.value.attr == "move_id")
    # _origin cannot choose an origin using the untrusted capability command.
    assert "command" not in {argument.arg for argument in origin.args.args + origin.args.kwonlyargs}
    assert "checked" not in {argument.arg for argument in origin.args.args + origin.args.kwonlyargs}
    assert {"create_receipt_id", "create_event_id", "create_event_sha256",
            "target_move_id", "origin_sha256"} <= string_constants(origin)


def test_result_verification_reads_real_audit_receipt_and_consumed_approval_nonce():
    verified = function("_verified_result")
    reached = reached_local_helpers(verified)
    constants = string_constants(reached)
    assert {"ap.security.draft.receipt", "ap.security.approval.nonce", "POST_APPROVED",
            "POSTED", "REPLAY", "DENIED", "consumed"} <= constants
    assert calls(verified, "_verify_event")
    assert calls(verified, "canonical_command_sha256")
    assert calls(verified, "_financial_snapshot")
    assert calls(reached, "verify_approval")
    assert {"receipt", "before_sha256", "after_sha256", "approval", "context", "subject"} <= constants


def test_signed_approval_is_bound_to_exact_action_and_persisted_nonce_observation():
    result_verification = reached_local_helpers(function("_verified_result"))
    approval, = calls(result_verification, "verify_approval")
    assert [ast.unparse(value) for value in approval.args] == ["command"]
    arguments = {keyword.arg: keyword.value for keyword in approval.keywords}
    assert set(arguments) == {"trusted_action", "authority", "key", "now"}
    assert ast.unparse(arguments["trusted_action"]) == "command['action']"
    assert ast.unparse(arguments["authority"]) == "authority"
    assert ast.unparse(arguments["key"]) == "key"
    assert any(isinstance(node, ast.Attribute) and node.attr == "verified_at"
               for node in ast.walk(arguments["now"]))
    attributes = {node.attr for node in ast.walk(result_verification) if isinstance(node, ast.Attribute)}
    assert {"verified_at", "consumed_at", "expires_at", "company_id", "executor_user_id",
            "action_sha256", "command_sha256", "approval_sha256", "nonce_sha256"} <= attributes
    assert {"consumed", "ledger_id", "key_id", "fixture_id", "scenario_id",
            "approval_sha256", "nonce_sha256", "state"} <= string_constants(result_verification)


def test_database_errors_escape_instead_of_becoming_normal_denials():
    for name in (ENTRY, "_origin", "_verified_result"):
        handlers = [node for node in ast.walk(function(name)) if isinstance(node, ast.ExceptHandler)
                    and node.type is not None and "DatabaseError" in ast.unparse(node.type)]
        assert handlers
        for handler in handlers:
            assert len(handler.body) == 1 and isinstance(handler.body[0], ast.Raise)
            assert handler.body[0].exc is None


def test_private_fault_seam_has_no_caller_supplied_hook_or_side_effect():
    hook = function("_after_registered_post")
    assert [argument.arg for argument in hook.args.args] == ["result"]
    assert hook.args.vararg is None and hook.args.kwarg is None
    assert not any(isinstance(node, ast.Call) for node in ast.walk(hook))
    returned, = [node for node in ast.walk(hook) if isinstance(node, ast.Return)]
    assert isinstance(returned.value, ast.Constant) and returned.value.value is None


def test_envelope_reports_origin_and_pending_transaction_not_a_committed_effect():
    assert "registered-post-execution/v1" in string_constants(tree())
    returned, = [node.value for node in ast.walk(function(ENTRY)) if isinstance(node, ast.Return)]
    assert isinstance(returned, ast.Dict)
    keys = [ast.literal_eval(key) for key in returned.keys]
    assert set(keys) == {"schema_version", "registration", "origin", "result", "caller_transaction_pending"}
    values = dict(zip(keys, returned.values, strict=True))
    assert isinstance(values["caller_transaction_pending"], ast.Constant)
    assert values["caller_transaction_pending"].value is True
    assert ast.unparse(values["result"]) == "result"
