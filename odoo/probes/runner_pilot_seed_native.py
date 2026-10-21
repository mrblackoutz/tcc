# SPDX-License-Identifier: LGPL-3.0-or-later
"""DEC-067 isolated administrative master/PO preparation, never bill dispatch."""

from decimal import Decimal
import hashlib
from pathlib import Path
import re

import odoo
from odoo.orm.registry import Registry
from odoo import Command

from c111_transactions import canonical, require
from runner_observed_fixture import load_inputs, load_scope, write_json
from tcc_gateway.pilot_seed_contract import MAX_SEED_BYTES, PilotBusinessSeed


_CHANGED = {"res.partner", "res.partner.bank", "purchase.order", "purchase.order.line", "auxiliary_counts"}


def _verify(env, rows, bindings):
    for row, binding in zip(rows, bindings, strict=True):
        vendor = env["res.partner"].browse(binding["vendor_id"]).exists()
        bank = env["res.partner.bank"].browse(binding["bank_id"]).exists()
        po = env["purchase.order"].browse(binding["purchase_order_id"]).exists()
        require(vendor.ref == row["vendor_ref"] and vendor.active and vendor.autopost_bills == "never"
                and vendor.company_id == env.company and vendor.supplier_rank > 0,
                "pilot_seed_native_vendor_exact")
        require(bank.acc_number == row["approved_bank_ref"] and bank.partner_id == vendor
                and bank.active and bank.allow_out_payment and bank.company_id == env.company,
                "pilot_seed_native_bank_exact")
        require(po.name == row["purchase_order_ref"] and po.partner_id == vendor and po.state == "purchase"
                and po.company_id == env.company and po.currency_id.name == row["currency"]
                and Decimal(str(po.amount_total)) == Decimal(row["amount"]), "pilot_seed_native_order_exact")
        lines = po.order_line.filtered(lambda line: not line.display_type).sorted(lambda line: line.product_id.default_code)
        require(len(lines) == len(row["lines"]) and sorted(lines.ids) == binding["purchase_line_ids"],
                "pilot_seed_native_lines_complete")
        for line, truth in zip(lines, row["lines"], strict=True):
            require(line.product_id.default_code == truth["item_code"] and not line.tax_ids
                    and line.discount == 0 and line.qty_invoiced == 0
                    and Decimal(str(line.product_qty)) == Decimal(truth["quantity"])
                    and Decimal(str(line.qty_to_invoice)) == Decimal(truth["quantity"])
                    and Decimal(str(line.price_unit)) == Decimal(truth["unit_price"])
                    and Decimal(str(line.price_subtotal)) == Decimal(truth["line_total"]),
                    "pilot_seed_native_line_facts_exact")


def _preserved(before, after):
    require(set(before) == set(after), "pilot_seed_projection_shape")
    for name in before.keys() - _CHANGED:
        require(canonical(before[name]) == canonical(after[name]), "pilot_seed_financial_projection_preserved")
    for name in _CHANGED - {"auxiliary_counts"}:
        by_id = {row["id"]: row for row in after[name]}
        require(all(row["id"] in by_id and canonical(row) == canonical(by_id[row["id"]])
                    for row in before[name]), "pilot_seed_existing_commercial_records_preserved")
    for name, count in before["auxiliary_counts"].items():
        # Native master/PO chatter is not an external message or a financial effect.
        if name == "mail.message":
            require(after["auxiliary_counts"][name] >= count, "pilot_seed_existing_chatter_count_preserved")
        else:
            require(after["auxiliary_counts"][name] == count, "pilot_seed_no_auxiliary_financial_or_external_effect")


def run(args):
    require(args.mode == "pilot-business-seed" and args.dataset_fixture_mode
            and re.fullmatch(r"[0-9a-f]{64}", args.pilot_seed_sha256 or "") is not None,
            "pilot_seed_explicit_mode_and_digest")
    path = Path(args.artifacts) / "pilot-business-seed.json"
    with path.open("rb") as stream:
        raw = stream.read(MAX_SEED_BYTES + 1)
    seed = PilotBusinessSeed(raw)
    require(seed.sha256 == args.pilot_seed_sha256, "pilot_seed_input_digest")
    value = seed.to_mapping()
    odoo.tools.config.parse_config(["-c", args.config, "-d", args.database, "--no-http"], setup_logging=False)
    registry = Registry(args.database)
    artifacts, manifest, native = load_inputs(args)
    observer, scope, _registration = load_scope(registry, args, manifest, native["cases"][0])
    base, rows = observer.base, value["fixtures"]
    from odoo.addons.ap_security_executor.identity import assert_executor_identity
    with registry.cursor() as cr:
        base.cursor_gate(cr)
        require(re.fullmatch(r"tcc_runner_[0-9a-f]{12}", cr.dbname) is not None,
                "pilot_seed_disposable_database_only")
        env = base.env(cr)
        require(env.company.id == manifest["company_id"] and "SEM VALOR FISCAL" in env.company.name
                and env.company.currency_id.name == "BRL", "pilot_seed_known_synthetic_company_brl")
        inventory = assert_executor_identity(env, env["res.users"].browse(base.user_id), company=env.company)
        before = observer.projection(env, scope)
        for model, field, references in (
            ("res.partner", "ref", {row["vendor_ref"] for row in rows}),
            ("res.partner.bank", "acc_number", {row["approved_bank_ref"] for row in rows}),
            ("purchase.order", "name", {row["purchase_order_ref"] for row in rows}),
            ("product.product", "default_code", {line["item_code"] for row in rows for line in row["lines"]}),
        ):
            require(env[model].with_context(active_test=False).search_count([(field, "in", sorted(references))]) == 0,
                    "pilot_seed_references_absent_no_repair")
        vendors, banks, products, bindings = {}, {}, {}, []
        for row in rows:
            vendor_ref, bank_ref = row["vendor_ref"], row["approved_bank_ref"]
            if vendor_ref not in vendors:
                vendors[vendor_ref] = env["res.partner"].create({
                    "name": "TCC PILOT SUPPLIER - SEM VALOR FISCAL", "ref": vendor_ref,
                    "company_id": base.company_id, "is_company": True, "supplier_rank": 1,
                    "autopost_bills": "never"})
            vendor = vendors[vendor_ref]
            if bank_ref not in banks:
                banks[bank_ref] = base.administrative_bank(env, vendor_id=vendor.id, reference=bank_ref)
            for line in row["lines"]:
                if line["item_code"] not in products:
                    products[line["item_code"]] = env["product.product"].create({
                        "name": "TCC PILOT SERVICE - SEM VALOR FISCAL", "default_code": line["item_code"],
                        "type": "service", "purchase_ok": True, "sale_ok": False,
                        "purchase_method": "purchase", "supplier_taxes_id": [Command.clear()]})
            po = env["purchase.order"].create({
                "name": row["purchase_order_ref"], "partner_id": vendor.id, "company_id": base.company_id,
                "currency_id": env.company.currency_id.id,
                "order_line": [Command.create({
                    "name": "TCC PILOT LINE - SEM VALOR FISCAL", "product_id": products[line["item_code"]].id,
                    "product_uom_id": products[line["item_code"]].uom_id.id,
                    "product_qty": float(Decimal(line["quantity"])), "price_unit": float(Decimal(line["unit_price"])),
                    "discount": 0, "tax_ids": [Command.clear()], "date_planned": row["invoice_date"] + " 12:00:00",
                }) for line in row["lines"]]})
            po.button_confirm()
            bindings.append({"fixture_ref": row["fixture_ref"], "vendor_id": vendor.id,
                "bank_id": banks[bank_ref].id, "purchase_order_id": po.id,
                "purchase_line_ids": sorted(po.order_line.filtered(lambda line: not line.display_type).ids)})
        env.flush_all()
        _verify(env, rows, bindings)
        _preserved(before, observer.projection(env, scope))
        require(inventory == assert_executor_identity(env, env["res.users"].browse(base.user_id), company=env.company),
                "pilot_seed_executor_inventory_unchanged")
        cr.commit()
    with registry.cursor() as cr:
        base.cursor_gate(cr)
        env = base.env(cr)
        _verify(env, rows, bindings)
        after = observer.projection(env, scope)
        _preserved(before, after)
        require(inventory == assert_executor_identity(env, env["res.users"].browse(base.user_id), company=env.company),
                "pilot_seed_fresh_executor_inventory_unchanged")
    with path.open("rb") as stream:
        final_raw = stream.read(MAX_SEED_BYTES + 1)
    require(hashlib.sha256(final_raw).hexdigest() == seed.sha256, "pilot_seed_input_unchanged")
    write_json(artifacts / "pilot-business-seed-result.json", {
        "schema_version": "pilot-business-seed-native/v1", "status": "PASS",
        "git_base": args.git_base, "source_bundle_sha256": args.source_bundle_sha256,
        "seed_sha256": seed.sha256, "cohort_sha256": value["cohort_sha256"],
        "codebook_sha256": value["codebook_sha256"], "company_ref": rows[0]["company_ref"],
        "company_id": manifest["company_id"], "company_name": manifest["company_name"],
        "fixture_count": len(bindings), "bindings": bindings,
        "business_records_sha256": hashlib.sha256(canonical(after)).hexdigest(),
        "financial_projection_preserved": True, "executor_identity_unchanged": True,
        "fresh_cursor_facts_verified": True, "scientific_run": False,
        "human_review_complete": False, "public_executor_enabled": False,
        "approval_generated": False, "a3a_target_prepared": False, "alternatives_prepared": False,
    })
