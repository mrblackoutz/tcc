"""Offline structure/CLI checks; these are not native execution evidence."""

import ast
import importlib.util
from pathlib import Path
import sys

import pytest


ROOT = Path(__file__).resolve().parents[2]
ENTRY = ROOT / "odoo/probes/state_oracle_native.py"
GATEWAY = ROOT / "odoo/probes/state_oracle_gateway.py"


def functions():
    return {node.name: node for node in ast.parse(ENTRY.read_text(encoding="utf-8")).body
            if isinstance(node, ast.FunctionDef)}


def source(name):
    return ast.unparse(functions()[name])


def test_all_new_sources_compile_without_importing_odoo():
    for path in (ENTRY, GATEWAY):
        compile(path.read_text(encoding="utf-8"), str(path), "exec")


def test_capture_new_readonly_cursor_and_trusted_scope_no_candidate_filter():
    text = source("capture")
    assert "with registry.cursor() as cr:" in text
    assert "SET TRANSACTION READ ONLY" in text
    assert text.index("SET TRANSACTION READ ONLY") < text.index("api.Environment(") < text.index("collect(")
    assert "capture-binding.json" in text
    assert "candidate" not in text and "proposal" not in text
    assert ".commit(" not in text and ".unlink(" not in text


def test_collector_scopes_preexisting_company_actors_before_message_discovery():
    collector = ast.parse((ROOT / "odoo/probes/company_capture_native.py").read_text(encoding="utf-8"))
    roots = next(node for node in collector.body if isinstance(node, ast.FunctionDef) and node.name == "_roots")
    text = ast.unparse(roots)
    assert "ids['res.users'].update" in text
    assert "env['res.users'].search([('company_ids', 'in', [company_id])]" in text
    assert "proposal" not in text and "candidate" not in text
    contract_tree = ast.parse((ROOT / "gateway/src/tcc_gateway/company_capture.py").read_text(encoding="utf-8"))
    assignments = {node.target.id: ast.literal_eval(node.value) for node in contract_tree.body
                   if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name)
                   and node.target.id in {"ROW_FIELDS", "RELATIONS"}}
    assert "partner_id" in assignments["ROW_FIELDS"]["res.users"]
    assert assignments["RELATIONS"]["res.users"]["partner_id"] == "res.partner"


def test_only_registered_c1_create_after_exact_gateway_allow_and_parent_commit():
    text = source("execute")
    assert "policy['status'] == 'ALLOW'" in text
    assert "create_registered_draft_audited" in text
    assert "expected_company_id=scope.workflow.company_id" in text
    assert "expected_scenario_id=scope.workflow.scenario_id" in text
    assert "command=copy.deepcopy(command)" in text
    assert "caller_transaction_pending" in text
    assert text.index("cr.commit()") < text.index("actual_committed_effect_identity")
    assert "receipt.command_sha256 == 'sha256:' + policy['command_sha256']" in text
    assert "receipt.move_id.id == move.id" in text


def test_native_observation_checks_the_prefixed_canonical_action_hash():
    text = source("observe")
    assert "digest(action) == candidate['action_sha256']" in text
    assert "from c111_transactions import digest, require" in text
    assert ".hexdigest() == candidate['action_sha256']" not in text


def test_no_private_approval_no_public_execute_no_business_deletion():
    for path in (ENTRY, GATEWAY):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        prohibited = {"unlink", "button_cancel", "button_draft", "action_register_payment",
                      "create_approval", "issue_approval", "reset", "patch", "print_exc", "format_exc"}
        assert not any(isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                       and node.func.attr in prohibited for node in ast.walk(tree))
        assert "ap.security.executor" not in path.read_text(encoding="utf-8")


def test_setup_real_file_attachment_orphan_and_database_storage_restored():
    text = source("prepare")
    assert "'ir_attachment.location', 'file'" in text
    assert "'ir_attachment.location', 'db'" in text
    assert "tcc-orphan-proof" in text
    assert "attachment.store_fname" in text and "attachment.raw" in text
    assert "fixture(created=True)" in text


@pytest.mark.parametrize("database", ["existing_lab", "tcc_state_0123456789ab", "tcc_state_0123456789ab_001-extra", "../data"])
def test_invalid_database_refused_before_odoo_import(monkeypatch, database):
    spec = importlib.util.spec_from_file_location("state_oracle_entry_test", ENTRY)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(sys, "argv", [str(ENTRY), "capture", "--database", database,
        "--git-base", "a" * 40, "--source-bundle-sha256", "b" * 64])
    with pytest.raises(SystemExit, match="STATE_ORACLE_INVALID_CONFIGURATION"):
        module.main()


def test_diagnostic_does_not_expose_exception_message_or_payload():
    text = source("main")
    assert "str(error)" not in text and "repr(error)" not in text
    assert "source_line" in text and "source_file" in text and "category" in text
    assert "logging.disable(logging.CRITICAL)" in text


def test_gateway_groundtruth_only_evaluator_not_policy_or_candidate():
    tree = ast.parse(GATEWAY.read_text(encoding="utf-8"))
    methods = {node.name: ast.unparse(node) for node in tree.body if isinstance(node, ast.FunctionDef)}
    assert '"expected_effects"' not in methods["policy"] and "expected_effects" not in methods["candidate"]
    assert "native_cases" in methods["evaluate"] and "ExpectedEffect" in methods["evaluate"]
    assert "evaluate_captured_oracle" in methods["evaluate"] and "assert_restored" in methods["evaluate"]
