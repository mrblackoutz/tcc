"""DEC-070 offline doubles and guards; native proof is separately required."""

import ast
import importlib.util
from pathlib import Path
import sys
from types import SimpleNamespace as NS

import pytest

ROOT = Path(__file__).resolve().parents[2]
NATIVE = ROOT / "odoo/probes/runner_pilot_alternatives_native.py"
HARNESS = (ROOT / "scripts/test_runner_native.ps1").read_text(encoding="utf-8")


def helper(name):
    module = ast.parse(NATIVE.read_text(encoding="utf-8"))
    return next(node for node in module.body if isinstance(node, ast.FunctionDef) and node.name == name)


def require(value, _code):
    if not value:
        raise ValueError("finite native failure")


class Rows(list):
    def filtered(self, predicate):
        return Rows(row for row in self if predicate(row))


def load_helper(name, **values):
    namespace = {"require": require, **values}
    exec(compile(ast.Module(body=[helper(name)], type_ignores=[]), str(NATIVE), "exec"), namespace)
    return namespace[name]


@pytest.mark.parametrize("count", [0, 1, 2])
def test_order_line_compatibility_measured_without_repair_or_favorable_default(count):
    lines = Rows([NS(display_type=False, product_id=NS(default_code="REQUIRED")) for _ in range(count)])
    lines += [NS(display_type="line_note", product_id=NS(default_code="REQUIRED")),
              NS(display_type=False, product_id=NS(default_code="OTHER"))]
    po = NS(state="purchase", currency_id=NS(name="BRL"), order_line=lines)
    queries = []
    def one(*args):
        queries.append(args[1:])
        return po
    check = {"purchase_order_ref": "PO-ALT", "item_codes": ["REQUIRED"]}
    result = load_helper("_line_gaps", _one=one)(object(), [check])
    assert result == ([] if count == 1 else [{"purchase_order_ref": "PO-ALT", "item_code": "REQUIRED", "matching_line_count": count}])
    assert queries == [("purchase.order", "name", "PO-ALT")]
    assert len(lines) == count + 2


@pytest.mark.parametrize("state,currency", [("draft", "BRL"), ("cancel", "BRL"), ("purchase", "USD")])
def test_order_exists_but_invalid_status_or_currency_is_not_a_relation_gap(state, currency):
    po = NS(state=state, currency_id=NS(name=currency))
    with pytest.raises(ValueError):
        load_helper("_line_gaps", _one=lambda *_args: po)(object(), [{"purchase_order_ref": "PO", "item_codes": ["ITEM"]}])


@pytest.mark.parametrize("kind", ["valid", "owner", "bank-id", "active", "trust", "supplier", "autopost", "bindings"])
def test_exact_bank_owner_and_trust_never_expand_legitimate_allowlist(kind):
    owner = NS(active=True, supplier_rank=1, autopost_bills="never")
    bank = NS(id=20, partner_id=owner, active=True, allow_out_payment=True)
    value = {"vendor_refs": ["VENDOR"], "banks": [{"owner_vendor_ref": "VENDOR", "bank_ref": "BANK"}]}
    bindings = [{"bank_id": 20}]
    if kind == "owner":
        bank.partner_id = object()
    elif kind == "bank-id":
        bank.id = 21
    elif kind == "active":
        bank.active = False
    elif kind == "trust":
        bank.allow_out_payment = False
    elif kind == "supplier":
        owner.supplier_rank = 0
    elif kind == "autopost":
        owner.autopost_bills = "always"
    elif kind == "bindings":
        bindings.clear()
    verify = load_helper("_verify_catalog", _one=lambda _env, model, *_args: bank if model == "res.partner.bank" else owner)
    if kind == "valid":
        verify(object(), value, bindings)
    else:
        with pytest.raises(ValueError):
            verify(object(), value, bindings)
    assert "allowed_bank_refs" not in value


def test_native_only_creates_declared_banks_reuses_seed_and_verifies_after_commit():
    source = ast.unparse(helper("run"))
    for expected in ("base.administrative_bank(", "validate_alternatives(", "cr.commit()", "pilot_alternative_absent_banks_no_repair",
                     "pilot_alternative_only_declared_banks_added", "pilot_alternative_existing_masters_exact",
                     "pilot_alternative_inputs_unchanged", "loaded['source_bundle_sha256'] == args.source_bundle_sha256"):
        assert expected in source
    assert source.count("registry.cursor()") == 2
    assert source.count("_verify_catalog(env, value, bindings)") == 2
    assert source.count("verify_business(env, business['fixtures'], loaded['bindings'])") == 3
    assert source.index("search_count(") < source.index("base.administrative_bank(")
    for forbidden in ("action_post", "create_registered", "post_registered", "issue_approval", "expected_action", "attack_family",
                      "adversarial_note", ".sudo(", ".execute(", ".patch(", "po.write("):
        assert forbidden not in source


def test_harness_explicit_mode_and_diagnosis_dont_promote_incomplete_fixture():
    assert HARNESS.index("if ($PilotAlternativesFile -and -not $PilotSeedFile)") < HARNESS.index("New-Item")
    assert HARNESS.index("Invoke-NativeMode 'pilot-alternatives'") > HARNESS.index("Invoke-NativeMode 'pilot-business-seed'")
    assert HARNESS.index("Invoke-NativeMode 'pilot-alternatives'") < HARNESS.index("Invoke-NativeMode 'pilot-a3a-origins'")
    assert "Pilot alternatives changed during snapshot" in HARNESS
    assert "runner_pilot_alternatives_native.py" in HARNESS
    assert "technical_resolution_complete -ne ($catalogResult.purchase_order_line_gap_count -eq 0)" in HARNESS
    assert "runner-pilot-alternatives-evidence/v1" in HARNESS


@pytest.mark.parametrize("digest,seed,flag", [(None, "a" * 64, True), ("B" * 64, "a" * 64, True),
    ("c" * 64, None, True), ("c" * 64, "a" * 64, False)])
def test_entrypoint_refuses_implicit_or_incomplete_alternative_mode(monkeypatch, digest, seed, flag):
    path = ROOT / "odoo/probes/runner_observed_native.py"
    spec = importlib.util.spec_from_file_location("catalog_native_entry", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    args = [str(path), "pilot-alternatives", "--database", "tcc_runner_" + "a" * 12,
            "--git-base", "a" * 40, "--source-bundle-sha256", "b" * 64]
    for option, value in (("--pilot-seed-sha256", seed), ("--pilot-alternatives-sha256", digest)):
        if value is not None:
            args += [option, value]
    if flag:
        args.append("--dataset-fixture-mode")
    monkeypatch.setattr(sys, "argv", args)
    monkeypatch.setitem(sys.modules, "runner_pilot_alternatives_native", NS(run=lambda _args: pytest.fail("must not dispatch")))
    with pytest.raises(SystemExit, match="RUNNER_OBSERVED_INVALID_CONFIGURATION"):
        module.main()
