# SPDX-License-Identifier: LGPL-3.0-or-later
"""Source gates for the disposable POST proof, not native execution evidence."""

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
HARNESS = ROOT / "scripts/test_c1_scaffold.ps1"
PROBE = ROOT / "odoo/probes/registered_post_transactions.py"


def test_workflow_mode_snapshots_new_probe_before_running_it():
    source = HARNESS.read_text(encoding="utf-8")
    snapshot = source.index("'odoo/probes/registered_post_transactions.py'")
    invocation = source.index("'python', '/mnt/c1-probe/registered_post_transactions.py'")
    assert snapshot < invocation
    assert "--source-bundle-sha256" in source and "--configuration-sha256" in source
    assert "[StringComparer]::Ordinal" in source
    assert "registeredPostProof.source_bundle_sha256 -cne $workflowSourceBundleHash" in source


def test_harness_requires_exact_orm_names_and_six_native_cases():
    source = HARNESS.read_text(encoding="utf-8")
    assert "Starting TestRegisteredPostExecution" in source
    assert "($registeredPostNames -join '|') -cne ($expectedRegisteredPostNames -join '|')" in source
    assert "$postCases.Count -ne 6" in source
    assert "($postCaseNames -join '|') -cne ($expectedRegisteredPostCases -join '|')" in source
    assert "$postCase.status -ne 'PASS'" in source
    assert "Registered POST transaction check failed" in source


def test_harness_binds_provenance_and_rejects_test_mode_or_scientific_claim():
    source = HARNESS.read_text(encoding="utf-8")
    for name in ("normal_registry -ne $true", "test_cursor_used -ne $false",
                 "mocked_sql_commit -ne $false", "scientific_run -ne $false",
                 "human_review_complete -ne $false", "git_base -cne $workflowGitBase"):
        assert "$registeredPostProof." + name in source
    assert "'registered_post_transaction_evidence_sha256'" in source
    assert "'workflow-registration-probe-evidence/v2'" in source


def test_probe_has_no_direct_native_financial_write_or_payment():
    parsed = ast.parse(PROBE.read_text(encoding="utf-8"))
    forbidden = {"action_post", "action_register_payment", "button_draft", "button_cancel",
                 "print_exc", "format_exc", "sleep"}
    assert not any(isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                   and node.func.attr in forbidden for node in ast.walk(parsed))


def test_probe_does_not_override_server_clock_or_mock_financial_dispatch():
    parsed = ast.parse(PROBE.read_text(encoding="utf-8"))
    for node in ast.walk(parsed):
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and isinstance(node.func.value, ast.Name) and node.func.value.id == "patch"):
            continue
        assert node.func.attr == "object"
        assert isinstance(node.args[1], ast.Constant)
        assert node.args[1].value == "_after_registered_post"


def test_fixture_keeps_historical_login_default_and_new_probe_uses_distinct_identity():
    fixture = ast.parse((ROOT / "odoo/probes/c111_transactions.py").read_text(encoding="utf-8"))
    base, = [node for node in fixture.body if isinstance(node, ast.ClassDef) and node.name == "Probe"]
    constructor, = [node for node in base.body if isinstance(node, ast.FunctionDef) and node.name == "__init__"]
    assert [argument.arg for argument in constructor.args.kwonlyargs] == ["executor_login"]
    assert ast.literal_eval(constructor.args.kw_defaults[0]) == "tcc-c111-private-probe"
    provision, = [node for node in ast.walk(constructor) if isinstance(node, ast.Call)
                  and isinstance(node.func, ast.Name) and node.func.id == "provision_executor_identity"]
    assert ast.unparse(next(keyword.value for keyword in provision.keywords if keyword.arg == "login")) == "executor_login"
    probe = ast.parse(PROBE.read_text(encoding="utf-8"))
    call, = [node for node in ast.walk(probe) if isinstance(node, ast.Call)
             and isinstance(node.func, ast.Name) and node.func.id == "Probe"]
    assert ast.literal_eval(next(keyword.value for keyword in call.keywords
                                if keyword.arg == "executor_login")) == "tcc-registered-post-private-probe"


def test_startup_produces_finite_failed_evidence_without_false_native_assertions():
    probe = ast.parse(PROBE.read_text(encoding="utf-8"))
    constants = {node.value for node in ast.walk(probe)
                 if isinstance(node, ast.Constant) and isinstance(node.value, str)}
    assert {"startup_diagnostic", "failure_diagnostic", "registered-post-transactions-evidence/v1"} <= constants
    assert not any(isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                   and node.func.attr in {"format_exc", "print_exc"} for node in ast.walk(probe))
