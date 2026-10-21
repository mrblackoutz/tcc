"""DEC-067 offline helper/entry/harness tests; not execution of Odoo."""

import ast
from copy import deepcopy
import importlib.util
import json
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[2]
NATIVE = ROOT / "odoo/probes/runner_pilot_seed_native.py"
HARNESS = (ROOT / "scripts/test_runner_native.ps1").read_text(encoding="utf-8")


def helper(name):
    module = ast.parse(NATIVE.read_text(encoding="utf-8"))
    return next(node for node in module.body if isinstance(node, ast.FunctionDef) and node.name == name)


def preservation():
    def require(value, _check):
        if not value:
            raise ValueError("finite probe failure")
    namespace = {"require": require, "canonical": lambda x: json.dumps(x, sort_keys=True),
                 "_CHANGED": {"res.partner", "res.partner.bank", "purchase.order", "purchase.order.line", "auxiliary_counts"}}
    exec(compile(ast.Module(body=[helper("_preserved")], type_ignores=[]), str(NATIVE), "exec"), namespace)
    return namespace["_preserved"]


def snapshot():
    return {"account.move": [{"id": 1, "state": "draft"}], "attachments": [],
        "res.partner": [{"id": 1, "ref": "ORIGINAL"}], "res.partner.bank": [],
        "purchase.order": [], "purchase.order.line": [],
        "auxiliary_counts": {"mail.message": 0, "mail.mail": 0, "mail.notification": 0, "account.payment": 0}}


def test_new_masters_and_native_chatter_allowed_but_existing_data_unchanged():
    before = snapshot()
    after = deepcopy(before)
    after["res.partner"].append({"id": 2, "ref": "NEW"})
    after["purchase.order"].append({"id": 3, "state": "purchase"})
    after["auxiliary_counts"]["mail.message"] = 5
    preservation()(before, after)
    assert before == snapshot()


@pytest.mark.parametrize("mutation", ["financial", "attachment", "existing", "missing-existing",
                                    "payment", "email", "notification", "chatter-deletion", "shape"])
def test_preparation_cannot_hide_financial_or_existing_record_change(mutation):
    before = snapshot()
    after = deepcopy(before)
    if mutation == "financial":
        after["account.move"][0]["state"] = "posted"
    elif mutation == "attachment":
        after["attachments"].append({"id": 2})
    elif mutation == "existing":
        after["res.partner"][0]["ref"] = "CHANGED"
    elif mutation == "missing-existing":
        after["res.partner"].clear()
    elif mutation == "shape":
        after.pop("attachments")
    elif mutation == "chatter-deletion":
        before["auxiliary_counts"]["mail.message"] = 1
    else:
        after["auxiliary_counts"][{"payment": "account.payment", "email": "mail.mail", "notification": "mail.notification"}[mutation]] = 1
    with pytest.raises(ValueError):
        preservation()(before, after)


def test_native_only_prepares_masters_and_po_without_financial_dispatch_or_patch():
    source = ast.unparse(helper("run"))
    for forbidden in ("action_post", "create_registered_draft", "post_registered_bill", "issue_approval", "patch", "sleep"):
        assert forbidden not in source
    assert "base.administrative_bank(" in source and "po.button_confirm()" in source
    assert "pilot_seed_references_absent_no_repair" in source
    assert source.index("search_count(") < source.index(".create(")
    assert source.count("registry.cursor()") == 2 and "cr.commit()" in source
    assert source.count("_verify(env, rows, bindings)") == 2
    assert "inventory == assert_executor_identity(" in source
    assert '"SEM VALOR FISCAL"' in NATIVE.read_text(encoding="utf-8")
    assert "dataset_fixture_mode" in source and "cr.dbname" in source
    full_source = NATIVE.read_text(encoding="utf-8")
    assert full_source.index("from odoo.orm.registry import Registry") < full_source.index("from odoo import Command")
    for forbidden in ("model_output", "expected_action", "attack_family", "adversarial_note"):
        assert forbidden not in source


def test_native_verifies_persisted_quantity_amount_bank_owner_and_fresh_cursor():
    source = ast.unparse(helper("_verify"))
    for expected in ("vendor.ref", "bank.partner_id == vendor", "bank.allow_out_payment", "po.amount_total",
                     "line.product_qty", "line.qty_to_invoice", "line.price_unit", "line.price_subtotal",
                     "not line.tax_ids", "line.discount == 0"):
        assert expected in source


def test_harness_opt_in_order_snapshot_and_strict_limits_preserve_old_envelopes():
    guard = "if ($PilotSeedFile -and -not ($WithObserved -and $WithDatasetFixtures))"
    assert HARNESS.index(guard) < HARNESS.index("New-Item")
    assert HARNESS.index("'pilot-business-seed'") > HARNESS.index("$result = [ordered]@{")
    assert HARNESS.index("Invoke-NativeMode 'pilot-business-seed'") > HARNESS.index("'Observed runner validation limits")
    for name in ("odoo/probes/runner_pilot_seed_native.py", "scripts/prepare_pilot_business_seed.py"):
        assert name in HARNESS
    assert "Pilot seed changed during snapshot" in HARNESS
    assert "PYTHONPATH=/opt/odoo:/mnt/runner-gateway/src" in HARNESS
    assert "'runner-pilot-business-seed-evidence/v1'" in HARNESS
    for previous in ("runner-native-probe-evidence/v1", "runner-observed-probe-evidence/v1", "runner-dataset-fixture-probe-evidence/v1"):
        assert previous in HARNESS
    assert "seedResult.fixture_count -isnot [int]" in HARNESS
    assert "$seedResult.$name -isnot [bool]" in HARNESS


@pytest.mark.parametrize("with_flag,digest", [(False, None), (True, None), (True, "not-a-hash"), (False, "a" * 64)])
def test_pilot_cli_rejects_missing_flag_or_digest_before_import(monkeypatch, with_flag, digest):
    path = ROOT / "odoo/probes/runner_observed_native.py"
    spec = importlib.util.spec_from_file_location("pilot_seed_cli_test", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    args = [str(path), "pilot-business-seed", "--database", "tcc_runner_" + "a" * 12,
            "--git-base", "a" * 40, "--source-bundle-sha256", "b" * 64]
    if with_flag:
        args.append("--dataset-fixture-mode")
    if digest is not None:
        args.extend(["--pilot-seed-sha256", digest])
    monkeypatch.setattr(sys, "argv", args)
    monkeypatch.setitem(sys.modules, "runner_pilot_seed_native", SimpleNamespace(run=lambda _args: pytest.fail("must not dispatch")))
    with pytest.raises(SystemExit, match="RUNNER_OBSERVED_INVALID_CONFIGURATION"):
        module.main()


def test_pilot_cli_dispatches_only_explicit_valid_native_mode(monkeypatch, capsys):
    path = ROOT / "odoo/probes/runner_observed_native.py"
    spec = importlib.util.spec_from_file_location("pilot_seed_cli_valid_test", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    observed = []
    monkeypatch.setattr(sys, "argv", [str(path), "pilot-business-seed", "--database", "tcc_runner_" + "a" * 12,
        "--git-base", "a" * 40, "--source-bundle-sha256", "b" * 64,
        "--dataset-fixture-mode", "--pilot-seed-sha256", "c" * 64])
    monkeypatch.setitem(sys.modules, "runner_pilot_seed_native", SimpleNamespace(run=lambda args: observed.append(args.pilot_seed_sha256)))
    module.main()
    assert observed == ["c" * 64] and capsys.readouterr().out == "RUNNER_OBSERVED_PASS_PILOT-BUSINESS-SEED\n"
