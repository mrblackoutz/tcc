"""DEC-075 native wiring and actual retention hook, without a fabricated ERP."""

import ast
import builtins
from copy import deepcopy
from dataclasses import asdict
import importlib.util
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest

from test_pilot_approval_native import approval, fixture as approval_fixture
from test_pilot_post_custody import capsule, custody


ROOT = Path(__file__).resolve().parents[2]
ENTRY = ROOT / "odoo/probes/pilot_approved_post_native.py"
ISSUER = ROOT / "odoo/probes/pilot_approval_native.py"
SPEC = importlib.util.spec_from_file_location("_pilot_approved_post_native_test", ENTRY)
native = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(native)


@pytest.mark.parametrize("field,value", [
    ("mode", "materialize"), ("with_approved_post", False), ("with_approved_post", 1),
    ("with_approved_post", "true"), ("with_approval_binding", False), ("with_approval_binding", 1),
    ("fixture_ref", None), ("fixture_ref", True),
])
def test_private_execution_optin_is_closed_before_native_or_custody_access(field, value):
    options = {"mode": "approved-post", "with_approved_post": True,
               "with_approval_binding": True, "fixture_ref": "FIX-00"}
    options[field] = value
    with pytest.raises(ValueError, match="^PILOT_APPROVED_POST_INVALID$"):
        native.run(SimpleNamespace(**options), object())


def retention_hook():
    tree = ast.parse(ISSUER.read_text(encoding="utf-8"))
    run = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "run")
    hook = next(node for node in run.body if isinstance(node, ast.If)
                and "with_approved_post" in ast.unparse(node.test))
    return compile(ast.Module(body=[hook], type_ignores=[]), str(ISSUER), "exec")


def hook_namespace(*, enabled=None, omitted=False):
    command, options = approval_fixture()
    value = capsule()
    value["command"] = command
    value["authority"] = asdict(options["authority"])
    value["key_material"] = options["key"].material.hex()
    value["scenario_id"] = command["action"]["scenario_id"]
    value["document_sha256"] = command["action"]["document_sha256"]
    args = SimpleNamespace(database=value["clone_binding"]["target_database"],
                           git_base=value["git_base"], source_bundle_sha256=value["source_bundle_sha256"])
    if not omitted:
        args.with_approved_post = enabled
    scope = SimpleNamespace(post_command=command, authority=options["authority"], key=options["key"])
    namespace = {"args": args, "deepcopy": deepcopy, "_require": native._require, "_hash": native._hash,
        "link": value["clone_binding"],
        "proof": {name: value[name] for name in ("cohort_sha256", "codebook_sha256")},
        "source": {"document": {name: value[name] for name in ("scenario_id", "document_sha256")}},
        "base": SimpleNamespace(company_id=value["company_id"], user_id=value["executor_user_id"]),
        "context": {"registration": SimpleNamespace(registration_id=value["registration_id"],
                        registration_sha256=value["registration_sha256"]), "result": value["create_result"]},
        "origin": value["origin"], "scope": scope, "before": {"synthetic_projection": True},
        "inventory": {"inventory_sha256": value["identity_sha256"]}}
    return namespace


@pytest.mark.parametrize("omitted,enabled", [(True, None), (False, False)])
def test_default_issuer_does_not_even_import_private_capsule_custody(omitted, enabled):
    namespace = hook_namespace(enabled=enabled, omitted=omitted)
    imports = []
    def forbidden_import(name, *_args, **_kwargs):
        imports.append(name)
        pytest.fail("Legacy approval must not access private custody")
    namespace["__builtins__"] = dict(vars(builtins), __import__=forbidden_import)
    exec(retention_hook(), namespace)
    assert imports == []


def test_optin_retention_transfers_the_actual_original_create_and_signed_command_once():
    namespace = hook_namespace(enabled=True)
    original_command = custody._canonical(namespace["scope"].post_command)
    original_create = custody._canonical(namespace["context"]["result"])
    saved = []
    module = ModuleType("pilot_post_custody")
    module.VERSION = custody.VERSION
    def write(database, value):
        saved.append((database, custody.validate_capsule(value)))
    module.write_capsule = write
    def import_module(name, *args, **kwargs):
        return module if name == "pilot_post_custody" else builtins.__import__(name, *args, **kwargs)
    namespace["__builtins__"] = dict(vars(builtins), __import__=import_module)
    exec(retention_hook(), namespace)
    assert len(saved) == 1 and saved[0][0] == namespace["args"].database
    result = saved[0][1]
    assert bool(custody._canonical(result["command"]) == original_command)
    assert bool(custody._canonical(result["create_result"]) == original_create)
    assert result["before_projection_sha256"] == native._hash(namespace["before"])
    assert result["identity_sha256"] == namespace["inventory"]["inventory_sha256"]
    assert result["origin"] is not namespace["origin"]


def test_hashing_is_identical_to_the_existing_approval_snapshot_hash():
    spec = importlib.util.spec_from_file_location("_pilot_approval_hash_test", ISSUER)
    issuer = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(issuer)
    observed = {"company": "TCC PROTEÇÃO", "facts": [None, True, "125.50"], "native_id": 123}
    assert native._hash(observed) == issuer._hash(observed)


def test_executor_never_imports_an_issuer_or_writes_a_new_capsule():
    tree = ast.parse(ENTRY.read_text(encoding="utf-8"))
    calls = {node.func.attr if isinstance(node.func, ast.Attribute) else node.func.id
        for node in ast.walk(tree) if isinstance(node, ast.Call)
        and isinstance(node.func, (ast.Attribute, ast.Name))}
    assert not calls & {"prepare_post", "issue_approval_fixture", "write_capsule", "write_text", "write_bytes",
                        "open", "action_post", "create", "unlink"}
    assert "read_capsule" in calls and "post_registered_bill_audited" in calls
    persisted = [node for node in ast.walk(tree) if isinstance(node, ast.Call)
                 and isinstance(node.func, ast.Name) and node.func.id == "write_json"]
    assert len(persisted) == 1
    keys = {key.value for key in persisted[0].args[1].keys if isinstance(key, ast.Constant)}
    assert not keys & {"key", "key_material", "nonce", "signature", "authority", "approval", "command", "create_result"}
