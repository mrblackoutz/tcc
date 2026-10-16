# SPDX-License-Identifier: LGPL-3.0-or-later
"""Offline structural/CLI gates for DEC-054, not native Odoo evidence."""

import ast
import importlib.util
import json
import math
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest


ROOT = Path(__file__).resolve().parents[2]
ENTRY = ROOT / "odoo/probes/runner_observed_native.py"
FIXTURE = ROOT / "odoo/probes/runner_observed_fixture.py"
CASE_IDS = (
    "observed_create_benign", "observed_amount_deviation", "observed_bank_deviation",
    "observed_reference_duplicate", "observed_closed_period", "observed_audit_unavailable",
    "observed_candidate_drift", "observed_post_without_approval", "observed_bank_revoked_after_allow",
)


def tree(path=FIXTURE):
    return ast.parse(path.read_text(encoding="utf-8"))


def functions(path=FIXTURE):
    return {node.name: node for node in tree(path).body if isinstance(node, ast.FunctionDef)}


def source(name):
    return ast.unparse(functions()[name])


def calls(name, attribute):
    return [node for node in ast.walk(functions()[name]) if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute) and node.func.attr == attribute]


def literal(name):
    assignment, = [node for node in tree().body if isinstance(node, ast.Assign)
                   and any(isinstance(target, ast.Name) and target.id == name for target in node.targets)]
    return ast.literal_eval(assignment.value)


def test_exact_nine_synthetic_cases_and_existing_orm_bootstrap():
    assert literal("CASE_IDS") == CASE_IDS
    imports = [node for node in tree().body if isinstance(node, ast.ImportFrom)]
    registry, = [node for node in imports if node.module == "odoo.orm.registry"]
    shortcuts, = [node for node in imports if node.module == "odoo"]
    assert registry.lineno < shortcuts.lineno
    assert {alias.name for alias in shortcuts.names} == {"Command", "SUPERUSER_ID", "api"}
    assert not any(isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                   and node.func.id == "Registry" for node in tree().body)


def test_native_probe_never_patches_financial_methods_clock_or_transactions():
    forbidden = {"patch", "mock", "MagicMock", "freeze_time", "set_test_mode", "enter_test_mode",
                 "action_post", "button_draft", "button_cancel", "action_register_payment",
                 "print_exc", "format_exc", "sleep"}
    for path in (ENTRY, FIXTURE):
        compile(tree(path), str(path), "exec")
        assert not any(isinstance(node, ast.Call) and (
            isinstance(node.func, ast.Name) and node.func.id in forbidden or
            isinstance(node.func, ast.Attribute) and node.func.attr in forbidden)
            for node in ast.walk(tree(path)))


def test_manifest_configuration_digest_stays_unprefixed_until_typed_boundary():
    prepared = source("prepare")
    assert "config_hash = hashlib.sha256(canonical(" in prepared
    assert ").hexdigest()" in prepared
    assert "configuration_sha256=config_hash" in prepared
    assert "'configuration_sha256': config_hash" in prepared
    assert "'sha256:' + manifest['configuration_sha256']" in source("load_scope")


def test_reader_uses_own_readonly_group_and_single_company_without_internal_inheritance():
    created = source("reader_identity")
    checked = source("assert_reader")
    assert "'implied_ids': [Command.clear()]" in created
    assert "'group_ids': [Command.set(group.ids)]" in created
    assert "'company_ids': [Command.set(company.ids)]" in created
    for name in ("perm_write", "perm_create", "perm_unlink"):
        assert f"'{name}': False" in created
    for group in ("base.group_system", "base.group_user", "ap_security_executor.group_executor",
                  "account.group_account_invoice"):
        assert f"not neutral.user.has_group('{group}')" in checked
    assert "reader.company_ids.ids == [company_id]" in checked
    assert "su=False" in checked
    assert "acl.check(model, 'read', raise_exception=False) is True" in checked
    assert "acl.check(model, operation, raise_exception=False) is False" in checked
    for model in ("ap.security.executor", "ap.security.workflow.registration", "ap.security.audit.event",
                  "ap.security.draft.receipt", "ap.security.approval.nonce", "account.payment"):
        assert repr(model) in checked


def test_reader_credential_is_tmpfs_only_not_part_of_public_manifest():
    prepared = source("prepare")
    assert "Path(args.secret_directory) / 'reader.key'" in prepared
    assert "key_path.write_text(key, encoding='utf-8')" in prepared
    assert "os.chmod(key_path, 416)" in prepared  # 0o640
    assert "key = None" in prepared
    manifest, = [node for node in ast.walk(functions()["prepare"]) if isinstance(node, ast.Assign)
                 and any(isinstance(target, ast.Name) and target.id == "manifest" for target in node.targets)]
    assert not any(isinstance(node, ast.Name) and node.id in {"key", "token", "password"}
                   for node in ast.walk(manifest.value))


def test_related_tax_acl_is_narrow_fixture_only_and_part_of_configuration():
    assert literal("RELATED_READ_MODELS") == ("account.tax",)
    assert "account.tax" not in literal("READ_MODELS")
    assert "'related_read_models': list(RELATED_READ_MODELS)" in source("prepare")
    granted = source("provision_related_reader")
    assert "group = reader.group_ids" in granted
    assert "len(group) == 1" in granted
    assert "group.name == 'TCC OBSERVED READER - SEM VALOR FISCAL'" in granted
    assert "'group_id': group.id" in granted
    for field in ("perm_write", "perm_create", "perm_unlink"):
        # The rule's operation mask does not grant an ACL; the only model ACL
        # must explicitly keep all mutation operations false.
        acl_create, = [node for node in calls("provision_related_reader", "create")
                       if ast.unparse(node.func.value) == "env['ir.model.access']"]
        acl_values = {ast.literal_eval(key): value for key, value in zip(acl_create.args[0].keys, acl_create.args[0].values)}
        assert ast.literal_eval(acl_values[field]) is False
    assert "'perm_read': True" in granted
    assert "('company_id', '=', False), ('company_id', '=', company_id)" in granted
    assert "group_user" not in granted and "group_account" not in granted


def test_native_related_read_proves_missing_acl_before_grant_and_same_query_after():
    granted = source("provision_related_reader")
    assert "fields=['price_unit']" in granted
    assert "'price_unit': 125.5" in granted
    assert "check('account.tax', 'read', raise_exception=False) is False" in granted
    assert "except AccessError:" in granted
    first, second = [node for node in calls("provision_related_reader", "search_read")
                     if any(keyword.arg == "fields" and ast.literal_eval(keyword.value) == ["tax_ids"]
                            for keyword in node.keywords)]
    acl_create, = [node for node in calls("provision_related_reader", "create")
                   if ast.unparse(node.func.value) == "env['ir.model.access']"]
    assert first.lineno < acl_create.lineno < second.lineno
    assert ast.unparse(first.args[0]) == ast.unparse(second.args[0]) == "domain"
    assert "{'id': purchase_line_id, 'tax_ids': []}" in granted
    assert "su=False" in granted
    assert "sudo(" not in granted


def test_related_grant_rechecks_all_original_and_related_readonly_permissions_after_commit():
    checked = source("assert_related_reader")
    assert "assert_reader(env, reader_id, company_id)" in checked
    assert "for model in RELATED_READ_MODELS:" in checked
    assert "acl.check(model, 'read', raise_exception=False) is True" in checked
    assert "acl.check(model, operation, raise_exception=False) is False" in checked
    assert "('write', 'create', 'unlink')" in checked
    assert "su=False" in checked
    prepared = source("prepare")
    assert "provision_related_reader(env, reader_id, base.company_id, manifest_cases[0]['binding']['purchase_line_ids'][0])" in prepared
    assert "assert_related_reader(env, manifest['reader_user_id'], manifest['company_id'])" in source("confirm")


def test_registration_and_binding_are_independent_of_observation_and_model_output():
    loaded = source("load_scope")
    assert "workflow_registry.resolve_draft_workflow(" in loaded
    assert "document=document, provenance=provenance" in loaded
    assert "asdict(resolved.workflow)" in loaded
    assert "native_case['registration_sha256']" in loaded
    resolver, = calls("load_scope", "resolve_draft_workflow")
    assert not any(isinstance(node, ast.Name) and node.id in {"observation", "candidate", "proposal"}
                   for node in ast.walk(resolver))
    observed = source("observe")
    assert observed.index("observer.expected_binding(scope, registration) == case['binding']") < observed.index(
        "observer.observation_module.observe_registered_policy_state(")
    producer, = calls("observe", "observe_registered_policy_state")
    assert {keyword.arg for keyword in producer.keywords} == {
        "registration_id", "expected_company_id", "expected_executor_user_id", "expected_scenario_id",
        "document", "provenance", "canonical_action",
    }


def test_native_observer_preserves_full_projection_and_real_caller_callbacks():
    observed = source("observe")
    assert "observer.projection(env, scope) == before" in observed
    assert "observer.callback_counts(cr) == callback_counts" in observed
    assert "not callback_runs" in observed
    assert "callback_runs == [True]" in observed
    assert "observer.fresh_projection(scope) == before" in observed
    assert calls("observe", "commit")
    assert not calls("observe", "create_registered_draft_audited")


def test_closed_period_storage_and_candidate_drift_are_explicit_named_negatives():
    observed = source("observe")
    assert "candidate_date < cr.now().date()" in observed
    assert "{'fiscalyear_lock_date': candidate_date}" in observed
    assert "observer.facts(period=False)" in observed
    assert "set_param('ir_attachment.location', 'file')" in observed
    assert "set_param('ir_attachment.location', 'db')" in observed
    assert "{'fiscalyear_lock_date': False}" in observed
    assert "finally:" in observed
    assert "action.update(document_ref='TCC-DRIFT-SEM-VALOR-FISCAL', invoice_date='2026-09-29')" in observed
    assert "copy.deepcopy(candidate['canonical_action'])" in observed
    assert "digest(action) == candidate['action_sha256']" in observed


def test_only_actual_allow_create_saved_command_reaches_private_wrapper():
    executed = source("execute")
    assert "if decision['status'] != 'ALLOW':" in executed
    assert "command is None and decision['command_sha256'] is None" in executed
    assert "command['action']['executor_mode'] == 'CREATE_DRAFT'" in executed
    assert "command['action']['action'] == 'CREATE_DRAFT_BILL'" in executed
    assert "'approval' not in command" in executed
    assert "saved_command = canonical(command)" in executed
    dispatch, = calls("execute", "create_registered_draft_audited")
    assert ast.unparse(next(key.value for key in dispatch.keywords if key.arg == "command")) == "json.loads(saved_command)"
    assert "range(2 if name == 'observed_create_benign' else 1)" in executed
    assert "result['receipt'] == original_result['receipt']" in executed
    assert "'REPLAY'" in executed
    assert not calls("execute", "post_registered_bill_audited")
    assert not calls("execute", "prepare_c1_observed_draft_command_v2")


def test_execution_uses_real_parent_commit_then_new_cursor_and_original_audit_links():
    executed = source("execute")
    assert executed.index("cr.commit()", executed.index("create_registered_draft_audited(")) < executed.index(
        "verify_attempt(registry, base, scope, result, command, audit)")
    verified = source("verify_attempt")
    assert "with registry.cursor() as cr:" in verified
    assert "base.cursor_gate(cr)" in verified
    assert "canonical_command_sha256(command)" in verified
    assert "payload['context'] == asdict(audit)" in verified
    assert "event.attachment_id.raw == scope.document.raw" in verified
    assert "original_payload['outcome']['status'] == 'CREATED'" in verified
    assert "original.attachment_id == event.attachment_id" in verified


def test_confirmation_is_companywide_and_checks_baseline_effects_and_public_closed():
    confirmed = source("confirm")
    assert "actual = projection(env, manifest['company_id'])" in confirmed
    assert "set(by_id) == set(baseline) | {created_id}" in confirmed
    assert "all((by_id[row_id] == row for row_id, row in baseline.items()))" in confirmed
    assert "neutral['ap.security.executor'].execute(public_command)" in confirmed
    assert "scope.result['receipt']['move_id'] in baseline" in confirmed
    assert "decision['status'] == 'REVIEW'" in confirmed and "decision['command'] is None" in confirmed
    assert "not state['moves'] and (not state['lines'])" in confirmed
    assert "not state['successful_audits']" in confirmed


def test_public_closure_uses_valid_original_command_and_real_restricted_identity_not_exception():
    confirmed = source("confirm")
    assert "public_command = copy.deepcopy(policy['cases'][0]['command'])" in confirmed
    assert "validate_command(public_command)" in confirmed
    assert "policy['cases'][0]['status'] == 'ALLOW'" in confirmed
    assert "executor_id == manifest['cases'][0]['binding']['executor_user_id']" in confirmed
    assert "executor_id not in {SUPERUSER_ID, env.ref('base.user_admin').id}" in confirmed
    assert "assert_executor_identity(" in confirmed
    assert "api.Environment(cr, executor_id, base.draft_kernel._context(manifest['company_id']), su=False)" in confirmed
    assert "neutral.uid == executor_id and (not neutral.su)" in confirmed
    assert "neutral['ap.security.executor'].execute(public_command)" in confirmed
    assert "execute({})" not in confirmed
    assert not any(isinstance(node, ast.ExceptHandler) for node in ast.walk(functions()["confirm"]))


def test_public_valid_preflight_is_exact_denial_and_has_no_effect_after_actual_commit():
    confirmed = source("confirm")
    for field in (
        "'schema_version': 'executor-preflight-result/v1'", "'decision': 'DENY'",
        "'deny_class': 'FAIL_CLOSED_UNAVAILABILITY'", "'reason_codes': ['DEPENDENCY_UNAVAILABLE']",
        "'executor_status': 'SCAFFOLD_NOT_READY'", "'effect_applied': False",
        "'proposed_action_hash': checked_public_command.action_hash",
    ):
        assert field in confirmed
    assert "type(public_result) is dict and public_result ==" in confirmed
    assert "public_result['effect_applied'] is False" in confirmed
    assert "first_observer.projection(env, first_scope) == before_public" in confirmed
    assert "first_observer.fresh_projection(first_scope) == before_public" in confirmed
    public_call, = [node for node in calls("confirm", "execute")]
    later_commit, = [node for node in calls("confirm", "commit") if node.lineno > public_call.lineno]
    fresh, = calls("confirm", "fresh_projection")
    assert public_call.lineno < later_commit.lineno < fresh.lineno


def test_late_bank_change_is_finite_registered_rejection_not_fabricated_audit_denial():
    executed = source("execute")
    assert "except WorkflowRegistryError as error:" in executed
    assert "name == 'observed_bank_revoked_after_allow' and error.code == 'BANK_NOT_ALLOWED'" in executed
    assert "'rejection_boundary': 'REGISTERED_WORKFLOW'" in executed
    assert "'status': 'REJECTED'" in executed
    assert "'audit_event_id': None" in executed
    assert "'receipt_id': None" in executed and "'move_id': None" in executed
    assert "observer.fresh_projection(scope) == full_before" in executed
    assert "base.projection(scope) == before" in executed
    assert "base.denied(" not in executed
    assert "[3, 3, 0, 2, 3, 2, 0, 0]" in source("confirm")


def test_revoked_inspection_is_separate_readonly_confirmation_not_execution_authority():
    inspected = source("inspect_revoked_scope")
    assert "native_case['name'] == 'observed_bank_revoked_after_allow'" in inspected
    assert "workflow_registry._checked_record(" in inspected
    assert "stored_provenance == provenance" in inspected
    assert "workflow_registry._document(document, workflow.document_sha256) == stored_document" in inspected
    assert "bank.allow_out_payment is False" in inspected
    assert "return (base, scope)" in inspected
    assert not calls("inspect_revoked_scope", "resolve_draft_workflow")
    assert not calls("inspect_revoked_scope", "create_registered_draft_audited")
    assert not any(isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                   and node.func.attr in {"write", "create", "unlink", "commit", "set_param"}
                   for node in ast.walk(functions()["inspect_revoked_scope"]))
    assert "inspect_revoked_scope(" not in source("execute")
    assert "load_scope(registry, args, manifest, fixture)" in source("execute")


def extracted_parser():
    node = functions()["read_json"]

    def require(condition, check):
        if not condition:
            raise ValueError(check)

    namespace = {"json": json, "math": math, "require": require}
    exec(compile(ast.Module(body=[node], type_ignores=[]), str(FIXTURE), "exec"), namespace)
    return namespace["read_json"]


def test_native_parser_accepts_valid_objects_without_coercing_finite_values(tmp_path):
    path = tmp_path / "artifact.json"
    path.write_text('{"float":1.5,"flag":false,"integer":1,"null":null}', encoding="utf-8")
    assert extracted_parser()(path) == {"float": 1.5, "flag": False, "integer": 1, "null": None}


@pytest.mark.parametrize("raw", [
    '{"a":1,"a":2}', '{"nested":{"a":true,"a":false}}', '{"x":NaN}',
    '{"x":Infinity}', '{"x":-Infinity}', '{"x":1e999}', "[]", "null", '"text"',
    '{"nested":' + "[" * 25 + "0" + "]" * 25 + "}",
])
def test_native_parser_rejects_ambiguous_unbounded_or_nonfinite_artifacts(tmp_path, raw):
    path = tmp_path / "artifact.json"
    path.write_text(raw, encoding="utf-8")
    with pytest.raises(ValueError):
        extracted_parser()(path)


def entry_module():
    spec = importlib.util.spec_from_file_location("observed_native_cli_test", ENTRY)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def arguments(mode="prepare"):
    return [str(ENTRY), mode, "--database", "tcc_runner_" + "a" * 12,
            "--git-base", "a" * 40, "--source-bundle-sha256", "b" * 64]


@pytest.mark.parametrize("mode", ["prepare", "observe", "execute", "confirm", "candidate", "policy"])
def test_cli_dispatches_only_declared_phase_and_emits_finite_success(monkeypatch, capsys, mode):
    observed = []
    monkeypatch.setitem(sys.modules, "runner_observed_fixture", SimpleNamespace(run=lambda args: observed.append(args.mode)))
    monkeypatch.setitem(sys.modules, "runner_observed_gateway", SimpleNamespace(run=lambda args: observed.append(args.mode)))
    monkeypatch.setattr(sys, "argv", arguments(mode))
    entry_module().main()
    assert observed == [mode]
    assert capsys.readouterr().out == "RUNNER_OBSERVED_PASS_" + mode.upper() + "\n"


@pytest.mark.parametrize("suffix", [
    ["--database", "production"], ["--config", "/etc/other.conf"],
    ["--artifacts", "/tmp/elsewhere"], ["--secret-directory", "/tmp/keys"],
    ["--git-base", "not-a-commit"], ["--source-bundle-sha256", "sha256:" + "b" * 64],
])
def test_cli_rejects_scope_drift_before_importing_runtime(monkeypatch, suffix):
    monkeypatch.setattr(sys, "argv", arguments() + suffix)
    with pytest.raises(SystemExit, match="RUNNER_OBSERVED_INVALID_CONFIGURATION"):
        entry_module().main()


def test_cli_failure_diagnostic_never_echoes_unknown_type_message_or_trace(monkeypatch, capsys):
    private_marker = "private-runtime-body-must-not-leak"

    class UnlistedExceptionWithPrivateName(Exception):
        pass

    def fail(_args):
        raise UnlistedExceptionWithPrivateName(private_marker)

    written = []
    monkeypatch.setitem(sys.modules, "runner_observed_fixture", SimpleNamespace(run=fail))
    monkeypatch.setattr(sys, "argv", arguments())
    monkeypatch.setattr(Path, "write_text", lambda _path, body, **_kwargs: written.append(body))
    with pytest.raises(SystemExit) as caught:
        entry_module().main()
    assert caught.value.code == 1
    assert capsys.readouterr().out == "RUNNER_OBSERVED_FAILED_PREPARE\n"
    diagnostic, = map(json.loads, written)
    assert set(diagnostic) == {"schema_version", "status", "mode", "category", "source_file", "source_line"}
    assert diagnostic["category"] == "OTHER_RUNTIME_FAILURE"
    assert diagnostic["source_file"] in {"runner_observed_native.py", "external-runtime"}
    assert private_marker not in written[0]
    assert "UnlistedExceptionWithPrivateName" not in written[0]
