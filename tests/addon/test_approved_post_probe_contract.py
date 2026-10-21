"""DEC-069 offline preservation/isolated-wiring guards, not ORM execution."""

import ast
from copy import deepcopy
import json
from pathlib import Path
from types import SimpleNamespace as NS

import pytest

ROOT = Path(__file__).resolve().parents[2]
NATIVE = ROOT / "odoo/probes/runner_approved_post_native.py"
HARNESS = (ROOT / "scripts/test_runner_native.ps1").read_text(encoding="utf-8")


def check():
    def require(value, _code):
        if not value:
            raise ValueError("finite probe failure")
    module = ast.parse(NATIVE.read_text(encoding="utf-8"))
    function = next(node for node in module.body if isinstance(node, ast.FunctionDef) and node.name == "_unchanged_except_audit")
    namespace = {"require": require, "canonical": lambda value: json.dumps(value, sort_keys=True)}
    exec(compile(ast.Module(body=[function], type_ignores=[]), str(NATIVE), "exec"), namespace)
    return namespace["_unchanged_except_audit"]


def state():
    return {"account.move": [{"id": 1, "state": "posted"}], "ap.security.approval.nonce": [{"id": 2, "state": "consumed"}],
        "ap.security.audit.event": [{"id": 3, "status": "POSTED"}],
        "ap.security.po.guard": [{"id": 4, "po_id": [20, "X"], "revision": 7, "write_date": "before"}],
        "ap.security.vendor.guard": [{"id": 5, "vendor_id": [30, "X"], "revision": 8, "write_date": "before"}]}


@pytest.mark.parametrize("status", ["DENIED", "REPLAY"])
def test_only_one_audit_and_exact_replay_guard_increments_are_admitted(status):
    before, after = state(), state()
    after["ap.security.audit.event"].append({"id": 9, "status": status})
    if status == "REPLAY":
        for name in ("ap.security.po.guard", "ap.security.vendor.guard"):
            after[name][0]["revision"] += 1
            after[name][0]["write_date"] = "after"
    check()(before, after, status, workflow=NS(purchase_order_id=20, vendor_id=30))
    assert before == state()


@pytest.mark.parametrize("mutation", ["extra-bill", "nonce", "old-audit", "extra-audit", "wrong-status", "guard-jump", "guard-subject"])
def test_no_replay_or_denial_can_hide_undeclared_effects(mutation):
    before, after = state(), state()
    after["ap.security.audit.event"].append({"id": 9, "status": "DENIED"})
    if mutation == "extra-bill":
        after["account.move"].append({"id": 99})
    elif mutation == "nonce":
        after["ap.security.approval.nonce"][0]["state"] = "available"
    elif mutation == "old-audit":
        after["ap.security.audit.event"][0]["status"] = "REPLAY"
    elif mutation == "extra-audit":
        after["ap.security.audit.event"].append({"id": 99, "status": "DENIED"})
    elif mutation == "wrong-status":
        after["ap.security.audit.event"][-1]["status"] = "CREATED"
    elif mutation == "guard-jump":
        after["ap.security.po.guard"][0]["revision"] += 1
    elif mutation == "guard-subject":
        after["ap.security.po.guard"][0]["po_id"][0] = 99
    with pytest.raises(ValueError):
        check()(before, after, "DENIED")


def test_optin_guard_snapshot_and_execution_order():
    assert HARNESS.index("if ($WithApprovedPost -and -not $WithObserved)") < HARNESS.index("New-Item -ItemType Directory")
    assert "'odoo/probes/runner_approved_post_native.py'" in HARNESS
    assert HARNESS.index("Invoke-NativeMode 'approved-post-prepare'") > HARNESS.index("'pilot_a3a_origin_result_sha256'")
    assert HARNESS.index("'approved-post-policy')") < HARNESS.index("Invoke-NativeMode 'approved-post-execute'")
    assert "runner-approved-post-evidence/v1" in HARNESS and "'DEC-069'" in HARNESS
    assert "$serverSecretMount = if ($WithApprovedPost)" in HARNESS
    assert "$odooBase + $serverSecretMount" in HARNESS


def test_secrets_do_not_enter_persistent_result_and_no_public_financial_rpc():
    text = NATIVE.read_text(encoding="utf-8")
    module = ast.parse(text)
    outputs = [node for node in ast.walk(module) if isinstance(node, ast.Call) and ast.unparse(node.func) == "write_json"]
    assert len(outputs) == 2
    for node in outputs:
        mapping = node.args[1]
        keys = {key.value for key in mapping.keys if isinstance(key, ast.Constant)}
        assert not keys & {"approval", "key_material", "authority", "nonce", "signature"}
    assert 'Path("/tmp/tcc-approved-post-private.json")' in text and '0o600' in text and '0o640' in text
    assert '"identity_sha256": identity["inventory_sha256"]' in text and '"identity": identity' not in text
    assert "registered_post.post_registered_bill_audited" in text
    assert "action_post(" not in text and "api_key" not in text
