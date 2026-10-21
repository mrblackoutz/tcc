"""DEC-068 offline probes of preservation/closed wiring, not native Odoo tests."""

import ast
from copy import deepcopy
from decimal import Decimal
import json
from pathlib import Path
from types import SimpleNamespace as NS

import pytest

ROOT = Path(__file__).resolve().parents[2]
NATIVE = ROOT / "odoo/probes/runner_pilot_a3a_origin_native.py"
HARNESS = (ROOT / "scripts/test_runner_native.ps1").read_text(encoding="utf-8")


def preserved():
    def require(value, _check):
        if not value:
            raise ValueError("finite probe failure")
    module = ast.parse(NATIVE.read_text(encoding="utf-8"))
    function = next(node for node in module.body if isinstance(node, ast.FunctionDef) and node.name == "_preserved")
    namespace = {"require": require, "canonical": lambda value: json.dumps(value, sort_keys=True)}
    exec(compile(ast.Module(body=[function], type_ignores=[]), str(NATIVE), "exec"), namespace)
    return namespace["_preserved"]


def example():
    before = {name: [] for name in ("account.move", "account.move.line", "ap.security.draft.receipt",
        "ap.security.audit.event", "ap.security.po.guard", "ap.security.vendor.guard", "ap.security.workflow.registration",
        "attachments", "purchase.order", "purchase.order.line", "res.partner", "res.partner.bank", "ap.security.approval.nonce")}
    before["account.move"] = [{"id": 1, "state": "draft"}]
    before["auxiliary_counts"] = {"mail.message": 10, "ir.attachment": 0, "account.payment": 0, "mail.mail": 0, "mail.notification": 0}
    for index in range(4):
        before["purchase.order"].append({"id": 201 + index, "invoice_status": "to invoice", "amount_total": 10})
        before["purchase.order.line"].append({"id": 401 + index, "qty_invoiced": 0, "qty_to_invoice": 1, "price_unit": 10})
    after = deepcopy(before)
    contexts = []
    for index in range(4):
        target, receipt, event = 11 + index, 21 + index, 31 + index
        contexts.append({"workflow": NS(purchase_order_id=201 + index, purchase_line_ids=(401 + index,), vendor_id=301 + index),
            "result": {"receipt": {"move_id": target, "receipt_id": receipt}, "audit_event": {"event_id": event}},
            "registration": NS(registration_id=41 + index), "other_registration": NS(registration_id=51 + index)})
        for name, row in (("account.move", {"id": target, "state": "draft"}),
            ("account.move.line", {"id": 61 + index, "move_id": [target, "X"]}),
            ("ap.security.draft.receipt", {"id": receipt, "executor_mode": "CREATE_DRAFT"}),
            ("ap.security.audit.event", {"id": event, "status": "CREATED"}),
            ("ap.security.po.guard", {"id": 71 + index, "po_id": [201 + index, "X"]}),
            ("ap.security.vendor.guard", {"id": 81 + index, "vendor_id": [301 + index, "X"]}),
            ("ap.security.workflow.registration", {"id": 41 + index}),
            ("ap.security.workflow.registration", {"id": 51 + index}),
            ("attachments", {"id": 91 + index, "target": target})):
            after[name].append(row)
        after["purchase.order"][index]["invoice_status"] = "invoiced"
        after["purchase.order.line"][index].update(qty_invoiced=1, qty_to_invoice=0)
    after["auxiliary_counts"].update({"mail.message": 14, "ir.attachment": 4})
    return before, after, contexts


def test_four_new_drafts_and_audit_allowed_but_not_existing_effects():
    before, after, contexts = example()
    preserved()(before, after, contexts)
    assert before == example()[0]


@pytest.mark.parametrize("mutation", ["old-posted", "new-posted", "new-target", "old-deleted", "extra-receipt",
    "post-receipt", "post-event", "extra-registration", "foreign-line", "foreign-guard", "foreign-vendor",
    "missing-pdf", "foreign-pdf", "payment", "email", "notification", "chatter-deleted", "new-business",
    "changed-po", "changed-price", "approval", "master", "shape"])
def test_preparation_cannot_hide_undeclared_effects(mutation):
    before, after, contexts = example()
    if mutation == "old-posted":
        after["account.move"][0]["state"] = "posted"
    elif mutation == "new-posted":
        after["account.move"][1]["state"] = "posted"
    elif mutation == "new-target":
        after["account.move"].append({"id": 999, "state": "draft"})
    elif mutation == "old-deleted":
        after["account.move"].pop(0)
    elif mutation == "extra-receipt":
        after["ap.security.draft.receipt"].append({"id": 999, "executor_mode": "CREATE_DRAFT"})
    elif mutation == "post-receipt":
        after["ap.security.draft.receipt"][0]["executor_mode"] = "POST_APPROVED"
    elif mutation == "post-event":
        after["ap.security.audit.event"][0]["status"] = "POSTED"
    elif mutation == "extra-registration":
        after["ap.security.workflow.registration"].append({"id": 999})
    elif mutation == "foreign-line":
        after["account.move.line"][0]["move_id"][0] = 999
    elif mutation == "foreign-guard":
        after["ap.security.po.guard"][0]["po_id"][0] = 999
    elif mutation == "foreign-vendor":
        after["ap.security.vendor.guard"][0]["vendor_id"][0] = 999
    elif mutation == "missing-pdf":
        after["attachments"].pop()
    elif mutation == "foreign-pdf":
        after["attachments"][0]["target"] = 999
    elif mutation in {"payment", "email", "notification"}:
        after["auxiliary_counts"][{"payment": "account.payment", "email": "mail.mail", "notification": "mail.notification"}[mutation]] = 1
    elif mutation == "chatter-deleted":
        after["auxiliary_counts"]["mail.message"] = 9
    elif mutation == "new-business":
        after["purchase.order"].append({"id": 999})
    elif mutation == "changed-po":
        after["purchase.order"][0]["amount_total"] = 99
    elif mutation == "changed-price":
        after["purchase.order.line"][0]["price_unit"] = 99
    elif mutation == "approval":
        after["ap.security.approval.nonce"].append({"id": 999})
    elif mutation == "master":
        after["res.partner"].append({"id": 999})
    elif mutation == "shape":
        after.pop("res.partner")
    with pytest.raises(ValueError):
        preserved()(before, after, contexts)


def test_native_source_uses_existing_private_kernels_and_no_critical_dispatch():
    text = NATIVE.read_text(encoding="utf-8")
    module = ast.parse(text)
    calls = {ast.unparse(node.func) for node in ast.walk(module) if isinstance(node, ast.Call)}
    assert "registered_execution.create_registered_draft_audited" in calls
    assert "registered_post._origin" in calls and "workflow_registry.resolve_draft_workflow" in calls
    assert not any("post_bill_audited" in name or "post_registered_bill" in name or "prepare_post" in name
                   or "ApprovalKey" in name or "hmac" in name or name.endswith(".unlink") for name in calls)
    assert "fresh_cursor_origins_verified" in text and '"ORIGIN_NOT_FOUND"' in text
    assert "Registry(args.database)" in text and "test_enable" not in text


def test_harness_optin_before_resource_creation_and_after_seed_validation():
    assert HARNESS.index("if ($PilotA3aOriginFile -and -not $PilotSeedFile)") < HARNESS.index("New-Item -ItemType Directory")
    assert HARNESS.index("A3a origin input provenance mismatch") < HARNESS.index("'network', 'create'")
    assert HARNESS.index("Invoke-NativeMode 'pilot-a3a-origins'") > HARNESS.index("'pilot_seed_result_sha256'")
    assert "runner-pilot-a3a-origin-evidence/v1" in HARNESS and "'DEC-068'" in HARNESS
    assert "'counterpart_targets_prepared'" in HARNESS and "'approval_generated'" in HARNESS


@pytest.mark.parametrize("invoiced,remaining,status,valid", [("2.50", "0", "invoiced", True),
    ("0", "2.50", "to invoice", False), ("9.00", "0", "invoiced", False),
    ("2.50", "0.01", "invoiced", False), ("2.50", "0", "to invoice", False),
    ("2.50", "-0.01", "invoiced", False)])
def test_purchase_balance_not_just_a_permitted_projection_delta(invoiced, remaining, status, valid):
    def require(value, _check):
        if not value:
            raise ValueError("finite probe failure")
    module = ast.parse(NATIVE.read_text(encoding="utf-8"))
    function = next(node for node in module.body if isinstance(node, ast.FunctionDef) and node.name == "_purchase_balance")
    namespace = {"require": require, "Decimal": Decimal}
    exec(compile(ast.Module(body=[function], type_ignores=[]), str(NATIVE), "exec"), namespace)
    line = NS(purchase_line_id=NS(qty_invoiced=invoiced, qty_to_invoice=remaining, order_id=NS(invoice_status=status)))
    if valid:
        namespace["_purchase_balance"](line, {"quantity": "2.50"})
    else:
        with pytest.raises(ValueError):
            namespace["_purchase_balance"](line, {"quantity": "2.50"})
