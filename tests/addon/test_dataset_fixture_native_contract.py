"""DEC-066 offline structure guards; not execution of native Odoo."""

import ast
from pathlib import Path

import pytest


SOURCE = Path(__file__).resolve().parents[2] / "odoo/probes/runner_dataset_fixture_native.py"


def parsed():
    return ast.parse(SOURCE.read_text(encoding="utf-8"))


def function(name):
    return next(node for node in parsed().body if isinstance(node, ast.FunctionDef) and node.name == name)


def test_exact_two_development_cases_and_no_registry_at_import():
    module = parsed()
    cases = next(node for node in module.body if isinstance(node, ast.Assign)
                 and any(isinstance(target, ast.Name) and target.id == "CASES" for target in node.targets))
    assert ast.literal_eval(cases.value) == ("observed_create_benign", "observed_post_without_approval")
    assert not any(isinstance(node, ast.Expr) and isinstance(node.value, ast.Call) for node in module.body)
    compile(module, str(SOURCE), "exec")


def test_preparation_uses_independent_command_and_native_operational_observer():
    body = ast.unparse(function("prepare"))
    assert "scope.command['action']" in body
    assert "model_output" not in body and "candidate" not in body
    assert "observer.observe(" in body and "facts=observer.facts()" in body
    assert "observer.expected_binding(scope, registration)" in body
    assert "line.product_id.default_code" in body and "line.product_id.id" in body
    assert "before == after" in body


def test_confirm_uses_fresh_projection_and_independent_reader_acl_check():
    body = ast.unparse(function("confirm"))
    assert "load_scope(" in body and "check_reader(observer, manifest)" in body
    assert "observer.fresh_projection(scope)" in body
    assert "observed == prepared['projection_before'] == prepared['projection_after']" in body
    reader = ast.unparse(function("check_reader"))
    assert "registry.cursor()" in reader and "assert_related_reader(" in reader


@pytest.mark.parametrize("name", ["prepare", "confirm", "run"])
def test_no_financial_dispatch_tokens_or_patching_in_native_mode(name):
    forbidden = {"write", "create", "unlink", "action_post", "create_registered_draft_audited",
                 "post_registered_bill_audited", "issue_approval_fixture", "patch", "sleep"}
    for node in ast.walk(function(name)):
        if isinstance(node, ast.Call):
            called = node.func.attr if isinstance(node.func, ast.Attribute) else (
                node.func.id if isinstance(node.func, ast.Name) else None)
            assert called not in forbidden


def test_explicit_modes_and_normal_registry_configuration():
    body = ast.unparse(function("run"))
    assert "dataset-fixtures-prepare" in body and "dataset-fixtures-confirm" in body
    assert "parse_config(" in body and "Registry(args.database)" in body
    assert "not odoo.tools.config['test_enable']" in body


def test_brl_configuration_precedes_financial_records_and_uses_native_write():
    body = ast.unparse(function("prepare_currency"))
    assert "env.ref('base.BRL')" in body
    for model in ("purchase.order", "account.move", "account.payment", "ap.security.draft.receipt"):
        assert model in body
    assert body.index("search_count(") < body.index("company.write(")
    assert "cr.commit()" in body and "base.currency = 'BRL'" in body
    assert "cr.dbname" in body and "only_two_fresh_known_companies" in body
    assert "main.write(" in body and "previous.write({'active': False})" in body
    assert "assert_executor_identity(" in body
    assert body.index("baseline_identity = assert_executor_identity(") < body.index("company.write(")
    assert body.index("env.flush_all()") < body.index("env.invalidate_all()") < body.index("final_identity = assert_executor_identity(")
    assert "env.registry.clear_all_caches()" in body
    assert "force_deactivate" not in body and "_apply_group" not in body
    assert "pricelist not in group_user.all_implied_ids" in body
    assert "set(group_user.implied_ids.ids) == baseline_implied | {pricelist.id}" in body
    assert "group_user._remove_group(pricelist)" in body
    assert "set(group_user.implied_ids.ids) == baseline_implied" in body
    assert "final_identity == baseline_identity" in body
    assert "== baseline_graph" in body and "complete_group_graph_unchanged" in body
    assert "group_ids':" not in body and "set_values(" not in body and ".execute(" not in body
    historical = SOURCE.with_name("runner_observed_fixture.py").read_text(encoding="utf-8")
    prepare = next(node for node in ast.parse(historical).body
                   if isinstance(node, ast.FunctionDef) and node.name == "prepare")
    rendered = ast.unparse(prepare)
    assert "getattr(args, 'dataset_fixture_mode', False)" in rendered
    assert rendered.index("prepare_currency(registry, base)") < rendered.index("observer.fixture(")
