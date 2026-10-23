"""Offline boundaries of DEC-077's development-only native probe.

The identity doubles exercise the probe's checks, not Odoo ACLs. The final AST
check establishes a source invariant only; real accounting effects and reset
are covered by the separately executed native proof.
"""

import ast
import builtins
from copy import deepcopy
import importlib.util
import json
from pathlib import Path
import sys
from types import ModuleType, SimpleNamespace

import pytest


ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "odoo/probes/live_approval_native.py"


def load_probe():
    spec = importlib.util.spec_from_file_location("_tcc_live_approval_native_test", SOURCE)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


native = load_probe()


def options(**changes):
    values = dict(proof_run_id="a" * 32, slot_run_id="b" * 32,
        git_base="c" * 40, source_bundle_sha256="d" * 64,
        database="tcc_state_" + "a" * 12 + "_001", condition="C0", grant_mode="valid",
        case="post", config="/etc/odoo/runner.conf", artifacts="/mnt/runner-artifacts",
        secret_directory="/run/runner-secrets")
    return SimpleNamespace(**dict(values, **changes))


def cli_args(args):
    names = ("database", "git_base", "source_bundle_sha256", "proof_run_id", "slot_run_id",
             "condition", "grant_mode", "config", "artifacts", "secret_directory")
    return [value for name in names for value in ("--" + name.replace("_", "-"), getattr(args, name))]


def forbid_odoo_import(monkeypatch):
    original = builtins.__import__

    def guarded(name, *args, **kwargs):
        if name == "odoo" or name.startswith("odoo."):
            pytest.fail("Invalid options must fail before importing Odoo")
        return original(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", guarded)


def test_import_is_independent_of_odoo_and_has_no_runtime_side_effect(monkeypatch):
    forbid_odoo_import(monkeypatch)
    assert load_probe().VERSION == "live-approval-native/v1"


@pytest.mark.parametrize("condition,grant", [("C0", "valid"), ("C1", "invalid-mac")])
def test_valid_options_accept_each_condition_without_loading_odoo(condition, grant, monkeypatch):
    forbid_odoo_import(monkeypatch)
    assert native.validate_options(options(condition=condition, grant_mode=grant)) is None


@pytest.mark.parametrize("field,value", [
    ("proof_run_id", "A" * 32), ("proof_run_id", "a" * 31),
    ("slot_run_id", True), ("slot_run_id", "b" * 32 + "\n"),
    ("git_base", "c" * 39), ("source_bundle_sha256", "sha256:" + "d" * 64),
    ("database", "tcc_state_" + "e" * 12 + "_001"),
    ("database", "tcc_state_" + "a" * 12 + "_0001"),
    ("database", "../tcc_state_" + "a" * 12 + "_001"),
    ("condition", "c0"), ("grant_mode", "absent"), ("case", "create"),
    ("config", "/etc/odoo/../other.conf"), ("artifacts", "/mnt/runner-artifacts/../private"),
    ("secret_directory", "/run/runner-secrets/"),
], ids=["uppercase-proof", "short-proof", "boolean-slot", "newline-slot", "short-commit",
         "prefixed-bundle", "foreign-database", "oversized-database-slot", "database-traversal",
         "unknown-condition", "unknown-grant", "wrong-case", "config-path", "artifact-path", "secret-path"])
def test_invalid_options_fail_before_any_odoo_import(field, value, monkeypatch):
    forbid_odoo_import(monkeypatch)
    with pytest.raises(ValueError, match="^LIVE_APPROVAL_NATIVE_INVALID$"):
        native.run(options(**{field: value}), registry=None)


def command(signature=None):
    return {"approval": {"signature": signature or "hmac-sha256/v1:" + "a" * 64,
                         "opaque": {"retained_only_in_memory": ["synthetic-private-marker"]}},
            "action": {"target_move_id": 123, "lines": [{"quantity": "1.00", "unit_price": "17.00"}]},
            "policy_decision": {"evaluated_at": "2026-10-23T12:00:00Z"}}


@pytest.mark.parametrize("mode", ["valid", "invalid-mac"])
def test_grant_selection_deepcopies_without_changing_original_or_action(mode):
    original = command()
    preserved = deepcopy(original)
    selected = native.command_for_grant(original, mode)
    assert original == preserved and selected is not original
    assert selected["action"] == original["action"] and selected["action"] is not original["action"]
    assert selected["policy_decision"] == original["policy_decision"]
    assert selected["approval"]["opaque"] == original["approval"]["opaque"]
    if mode == "valid":
        assert selected == original
    else:
        assert selected["approval"]["signature"][:-1] == original["approval"]["signature"][:-1]
        assert selected["approval"]["signature"][-1] != original["approval"]["signature"][-1]
    selected["approval"]["opaque"]["retained_only_in_memory"].clear()
    selected["action"]["lines"][0]["quantity"] = "2.00"
    assert original == preserved


def test_invalid_mac_also_changes_an_original_zero_without_lengthening_signature():
    original = command("hmac-sha256/v1:" + "0" * 64)
    selected = native.command_for_grant(original, "invalid-mac")
    assert selected["approval"]["signature"] == "hmac-sha256/v1:" + "0" * 63 + "1"
    assert original["approval"]["signature"] == "hmac-sha256/v1:" + "0" * 64


@pytest.mark.parametrize("signature", [None, False, True, 123, "hmac-sha256/v1:" + "A" * 64,
    "hmac-sha256/v1:" + "a" * 63, "hmac-sha256/v1:" + "a" * 65,
    "hmac-sha256/v1:" + "a" * 64 + "\n", "synthetic-not-a-signature"])
def test_unbounded_or_noncanonical_signature_is_rejected_without_exposing_input(signature):
    original = command()
    original["approval"]["signature"] = signature
    preserved = deepcopy(original)
    with pytest.raises(ValueError) as caught:
        native.command_for_grant(original, "invalid-mac")
    assert str(caught.value) == "LIVE_APPROVAL_NATIVE_INVALID"
    assert original == preserved


@pytest.mark.parametrize("mode", [True, "reissue"])
def test_unknown_grant_modes_do_not_modify_the_original_command(mode):
    original = command()
    preserved = deepcopy(original)
    with pytest.raises(ValueError, match="^LIVE_APPROVAL_NATIVE_INVALID$"):
        native.command_for_grant(original, mode)
    assert original == preserved


def install_identity_doubles(monkeypatch, **overrides):
    values = dict(principal=99, active=True, membership=[11], company=11, count=1,
                  groups={"account.group_account_invoice"}, actual_uid=99, actual_su=False)
    values.update(overrides)
    state = SimpleNamespace(**values, environment_calls=[], identity_calls=[], group_calls=[])

    class User:
        active = state.active
        company_id = SimpleNamespace(id=state.company)
        company_ids = SimpleNamespace(ids=state.membership)

        def exists(self):
            return self

        def __len__(self):
            return state.count

        def has_group(self, name):
            state.group_calls.append(name)
            return name in state.groups

    user = User()
    company = SimpleNamespace(id=11)

    class Env:
        cr = object()

        def __getitem__(self, model):
            value = {"res.users": user, "res.company": company}[model]
            return SimpleNamespace(browse=lambda _identifier: value)

        def ref(self, name):
            assert name == "base.user_admin"
            return SimpleNamespace(id=2)

    def environment(cr, uid, context, *, su):
        state.environment_calls.append((cr, uid, context, su))
        return SimpleNamespace(uid=state.actual_uid, su=state.actual_su, user=user)

    def assert_identity(env, selected_user, *, company):
        state.identity_calls.append((env, selected_user, company))

    for name in ("odoo", "odoo.addons", "odoo.addons.ap_security_executor"):
        package = ModuleType(name)
        package.__path__ = []
        monkeypatch.setitem(sys.modules, name, package)
    sys.modules["odoo"].SUPERUSER_ID = 1
    sys.modules["odoo"].api = SimpleNamespace(Environment=environment)
    identity = ModuleType("odoo.addons.ap_security_executor.identity")
    identity.assert_executor_identity = assert_identity
    monkeypatch.setitem(sys.modules, identity.__name__, identity)
    return Env(), state


def test_c0_uses_real_functional_uid_explicit_su_false_and_single_company_context(monkeypatch):
    env, state = install_identity_doubles(monkeypatch)
    native._identity(env, principal=99, condition="C0", company_id=11)
    assert state.identity_calls == []
    assert state.environment_calls == [(env.cr, 99, {"allowed_company_ids": [11], "force_company": 11,
                                                  "lang": "en_US", "tz": "UTC"}, False)]
    assert state.group_calls == ["account.group_account_invoice", "base.group_system",
                                 "ap_security_executor.group_executor"]


@pytest.mark.parametrize("changes", [
    {"active": False}, {"company": 12}, {"membership": [11, 12]}, {"count": 0},
    {"groups": set()}, {"groups": {"account.group_account_invoice", "base.group_system"}},
    {"groups": {"account.group_account_invoice", "ap_security_executor.group_executor"}},
    {"actual_uid": 1}, {"actual_su": True},
], ids=["inactive", "foreign-company", "multiple-companies", "missing-user", "no-accounting-role",
         "system-role", "restricted-executor-role", "wrong-actual-uid", "sudo-environment"])
def test_c0_identity_rejects_wrong_membership_privilege_or_actual_environment(changes, monkeypatch):
    env, state = install_identity_doubles(monkeypatch, **changes)
    with pytest.raises(ValueError, match="^LIVE_APPROVAL_NATIVE_INVALID$"):
        native._identity(env, principal=99, condition="C0", company_id=11)
    assert state.identity_calls == []


@pytest.mark.parametrize("principal", [1, 2])
def test_administrative_principals_are_rejected_before_functional_environment(principal, monkeypatch):
    env, state = install_identity_doubles(monkeypatch)
    with pytest.raises(ValueError, match="^LIVE_APPROVAL_NATIVE_INVALID$"):
        native._identity(env, principal=principal, condition="C0", company_id=11)
    assert state.environment_calls == state.identity_calls == []


def test_c1_delegates_to_existing_restricted_identity_guard_not_c0_roles(monkeypatch):
    env, state = install_identity_doubles(monkeypatch, groups=set())
    native._identity(env, principal=99, condition="C1", company_id=11)
    assert len(state.identity_calls) == 1
    assert state.identity_calls[0][0] is env
    assert state.identity_calls[0][2].id == 11
    assert state.environment_calls == state.group_calls == []


def test_c1_cannot_ignore_a_rejection_from_the_existing_identity_guard(monkeypatch):
    env, _state = install_identity_doubles(monkeypatch)

    def deny(*_args, **_kwargs):
        raise ValueError("SYNTHETIC_IDENTITY_REJECTED")

    monkeypatch.setattr(sys.modules["odoo.addons.ap_security_executor.identity"],
                        "assert_executor_identity", deny)
    with pytest.raises(ValueError, match="^SYNTHETIC_IDENTITY_REJECTED$"):
        native._identity(env, principal=99, condition="C1", company_id=11)


def test_main_failure_diagnostic_does_not_serialize_exception_or_private_values(monkeypatch, capsys):
    marker = "synthetic-private-error-marker"
    written = []
    monkeypatch.setattr(native.logging, "disable", lambda _level: None)
    odoo = ModuleType("odoo")
    odoo.__path__ = []
    odoo.tools = SimpleNamespace(config=SimpleNamespace(parse_config=lambda *_args, **_kwargs: None))
    registry = ModuleType("odoo.orm.registry")

    def failing_registry(_database):
        raise ValueError(marker)

    registry.Registry = failing_registry
    monkeypatch.setitem(sys.modules, "odoo", odoo)
    monkeypatch.setitem(sys.modules, "odoo.orm.registry", registry)

    class OutputPath:
        def __truediv__(self, filename):
            assert filename == options().database + "-C0-valid.failure.json"
            return self

        def write_text(self, value, *, encoding):
            assert encoding == "utf-8"
            written.append(value)

    monkeypatch.setattr(native, "Path", lambda value: OutputPath() if value == "/mnt/runner-artifacts" else Path(value))
    assert native.main(cli_args(options())) == 1
    output = capsys.readouterr()
    assert output.out == "LIVE_APPROVAL_NATIVE_FAILED\n" and output.err == ""
    assert len(written) == 1 and marker not in written[0]
    diagnostic = json.loads(written[0])
    assert set(diagnostic) == {"schema_version", "status", "category", "source_file", "source_line"}
    assert diagnostic["status"] == "FAIL" and diagnostic["category"] == "ValueError"
    assert diagnostic["source_file"] == "live_approval_native.py"
    assert type(diagnostic["source_line"]) is int


def test_c0_financial_call_source_does_not_branch_on_observer_or_grant_outcome():
    """AST-only regression: this does not assert an actual successful POST."""
    tree = ast.parse(SOURCE.read_text(encoding="utf-8"))
    calls = [node for node in ast.walk(tree) if isinstance(node, ast.Call)
             and isinstance(node.func, ast.Attribute) and node.func.attr == "action_post"]
    assert len(calls) == 1
    branch = next(node for node in ast.walk(tree) if isinstance(node, ast.If)
                  and any(child is calls[0] for statement in node.body for child in ast.walk(statement)))
    assert ast.unparse(branch.test) == "args.condition == 'C0'"
    assert len(branch.body) == 1 and isinstance(branch.body[0], ast.Expr)
    assert branch.body[0].value is calls[0]
    assert ast.unparse(calls[0]) == "execution_env['account.move'].browse(target).action_post()"
