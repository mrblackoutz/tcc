# SPDX-License-Identifier: LGPL-3.0-or-later
"""Structural gates for the disposable observer proof, not native evidence."""

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
PROBE = ROOT / "odoo/probes/operational_observation_transactions.py"
HARNESS = ROOT / "scripts/test_c1_scaffold.ps1"


def parsed_probe():
    return ast.parse(PROBE.read_text(encoding="utf-8"))


def methods():
    probe, = [node for node in parsed_probe().body
              if isinstance(node, ast.ClassDef) and node.name == "OperationalObservationProbe"]
    return {node.name: node for node in probe.body if isinstance(node, ast.FunctionDef)}


def test_probe_declares_exact_eight_native_readonly_cases():
    case_ids, = [node for node in parsed_probe().body if isinstance(node, ast.Assign)
                 and any(isinstance(target, ast.Name) and target.id == "CASE_IDS" for target in node.targets)]
    assert ast.literal_eval(case_ids.value) == (
        "observe_create_open_clean_readonly", "observe_ledger_duplicate_changed_reference",
        "observe_native_reference_duplicate", "observe_closed_period_executor_identity",
        "observe_post_origin_not_duplicate", "observe_post_additional_reference_duplicate",
        "observe_audit_preflight_unavailable", "observe_candidate_hash_changes_with_reference_and_date",
    )


def test_probe_uses_distinct_synthetic_identity_and_real_registry():
    tree = parsed_probe()
    probe_call, = [node for node in ast.walk(tree) if isinstance(node, ast.Call)
                   and isinstance(node.func, ast.Name) and node.func.id == "Probe"]
    assert ast.literal_eval(next(keyword.value for keyword in probe_call.keywords
                                if keyword.arg == "executor_login")) == "tcc-operational-private-probe"
    assert any(isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
               and node.func.id == "Registry" for node in ast.walk(tree))
    assert "test_cursor_used" in PROBE.read_text(encoding="utf-8")


def test_probe_bootstraps_odoo_orm_before_importing_public_shortcuts():
    compile(parsed_probe(), str(PROBE), "exec")
    imports = [node for node in parsed_probe().body if isinstance(node, ast.ImportFrom)]
    registry, = [node for node in imports if node.module == "odoo.orm.registry"]
    shortcuts, = [node for node in imports if node.module == "odoo"]
    assert [alias.name for alias in registry.names] == ["Registry"]
    assert {alias.name for alias in shortcuts.names} == {"Command", "SUPERUSER_ID"}
    assert registry.lineno < shortcuts.lineno
    assert not any(isinstance(node, ast.Expr) and isinstance(node.value, ast.Call)
                   and isinstance(node.value.func, ast.Name) and node.value.func.id == "Registry"
                   for node in parsed_probe().body)


def test_probe_does_not_patch_financial_dispatch_clock_cursor_or_commit():
    tree = parsed_probe()
    forbidden_names = {"patch", "sleep", "freeze_time", "mock", "MagicMock"}
    forbidden_methods = {"action_post", "action_register_payment", "button_draft", "button_cancel",
                         "print_exc", "format_exc", "set_test_mode", "enter_test_mode"}
    assert not any(isinstance(node, ast.Call) and (
        isinstance(node.func, ast.Name) and node.func.id in forbidden_names or
        isinstance(node.func, ast.Attribute) and node.func.attr in forbidden_methods
    ) for node in ast.walk(tree))


def test_observation_path_only_calls_native_readonly_producer_and_parent_commit():
    method = methods()["observe"]
    forbidden = {"create", "write", "unlink", "set_param", "create_registered_draft_audited",
                 "post_registered_bill_audited", "create_draft_audited", "post_bill_audited"}
    assert not any(isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                   and node.func.attr in forbidden for node in ast.walk(method))
    observer, = [node for node in ast.walk(method) if isinstance(node, ast.Call)
                 and isinstance(node.func, ast.Attribute) and node.func.attr == "observe_registered_policy_state"]
    assert {keyword.arg for keyword in observer.keywords} == {
        "registration_id", "expected_company_id", "expected_executor_user_id", "expected_scenario_id",
        "document", "provenance", "canonical_action",
    }
    assert any(isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
               and node.func.attr == "commit" and ast.unparse(node.func.value) == "cr"
               for node in ast.walk(method))


def test_direct_financial_creation_is_confined_to_named_synthetic_fixture_setup():
    creates = []
    for name, method in methods().items():
        for node in ast.walk(method):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "create":
                creates.append((name, ast.unparse(node.func.value)))
    assert creates == [
        ("prepare_native_reference_duplicate", "env['account.move']"),
        ("prepare_native_reference_duplicate", "Command"),
        ("closed_period", "env['account.lock_exception']"),
    ]
    fixture = ast.unparse(methods()["prepare_native_reference_duplicate"])
    assert "'state': 'draft'" in fixture and "'auto_post': 'no'" in fixture
    assert "SEM VALOR FISCAL" in fixture and "purchase_line_id" in fixture


def test_probe_snapshot_covers_registry_finance_auxiliary_and_caller_callbacks():
    source = PROBE.read_text(encoding="utf-8")
    for field in (
        '"ap.security.po.guard"', '"ap.security.vendor.guard"', '"ap.security.draft.receipt"',
        '"ap.security.approval.nonce"', '"ap.security.audit.event"', '"ap.security.workflow.registration"',
        '"purchase.order.line"', '"qty_invoiced"', '"qty_to_invoice"', '"supplier_rank"',
        '"mail.message"', '"account.payment"', '"attachments"', '"precommit"', '"postcommit"',
    ):
        assert field in source
    observe = ast.unparse(methods()["observe"])
    assert "self.fresh_projection(scope) == before" in observe
    assert "self.callback_counts(cr) == callback_counts" in observe
    assert "callbacks == [True]" in observe


def test_period_case_uses_real_executor_and_real_service_only_exception():
    source = ast.unparse(methods()["closed_period"])
    assert "company.with_user(scope.workflow.executor_user_id).sudo()" in source
    assert "company.with_user(SUPERUSER_ID).sudo()" in source
    assert "not service_company._get_violated_lock_dates" in source
    assert "executor_company._get_violated_lock_dates" in source
    assert "candidate_date < cr.now().date()" in source
    assert "'user_id': SUPERUSER_ID" in source


def test_evidence_retains_nine_observations_with_independent_binding_and_finite_startup():
    source = PROBE.read_text(encoding="utf-8")
    assert "expected_binding = self.expected_binding(scope, registration)" in source
    assert source.index("expected_binding = self.expected_binding(scope, registration)") < source.index(
        "observation = self.observation_module.observe_registered_policy_state(")
    binding_source = ast.unparse(methods()["expected_binding"])
    assert "'purchase_line_ids': list(workflow.purchase_line_ids)" in binding_source
    assert "'allowed_bank_ids': list(workflow.allowed_bank_ids)" in binding_source
    assert "observation" not in binding_source
    assert '"observation_records": self.observation_records' in source
    assert '"record_count": len(self.observation_records)' in source
    assert "len(probe.observation_records) == 9" in source
    assert '"operational-observation-transactions-evidence/v1"' in source
    assert '"private-registered-operational-observation-readonly-only"' in source
    assert '"startup_diagnostic"' in source and '"real_api_used": False' in source
    diagnostic, = [node for node in parsed_probe().body
                   if isinstance(node, ast.FunctionDef) and node.name == "failure_diagnostic"]
    assert not any(isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                   and node.func.id in {"str", "repr"} and node.args
                   and ast.unparse(node.args[0]) == "error"
                   for node in ast.walk(diagnostic))


def test_observation_mode_harness_binds_source_exact_cases_and_readonly_flags():
    source = HARNESS.read_text(encoding="utf-8")
    assert "[switch]$WithOperational" in source
    assert "'odoo/probes/operational_observation_transactions.py'" in source
    assert "'python', '/mnt/c1-probe/operational_observation_transactions.py'" in source
    assert "operational-observation-transactions-evidence/v1" in source
    assert "$observationCases.Count -ne 8" in source
    assert "$observationProof.record_count -ne 9" in source
    for field in ("normal_registry -ne $true", "test_cursor_used -ne $false", "mocked_sql_commit -ne $false",
                  "mocked_clock -ne $false", "scientific_run -ne $false", "human_review_complete -ne $false"):
        assert "$observationProof." + field in source
