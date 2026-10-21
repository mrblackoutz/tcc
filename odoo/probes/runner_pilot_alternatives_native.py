# SPDX-License-Identifier: LGPL-3.0-or-later
"""DEC-070 explicit administrative catalog; no proposal or financial dispatch."""

import hashlib
from pathlib import Path
import re

import odoo
from odoo.orm.registry import Registry

from c111_transactions import canonical, require
from runner_observed_fixture import load_inputs, load_scope, read_json, write_json
from runner_pilot_seed_native import _verify as verify_business, _preserved
from tcc_gateway.pilot_seed_contract import (
    MAX_SEED_BYTES, MAX_ALTERNATIVES_BYTES, PilotBusinessSeed, PilotAlternativeCatalog,
    validate_alternatives,
)


def _input(path, limit, constructor):
    with path.open("rb") as stream:
        return constructor(stream.read(limit + 1))


def _one(env, model, field, reference):
    records = env[model].with_context(active_test=False).search([(field, "=", reference)])
    require(len(records) == 1 and records.company_id == env.company,
            "pilot_alternative_unique_company_reference")
    return records


def _verify_catalog(env, value, bindings):
    require(len(bindings) == len(value["banks"])
            and len({row["bank_id"] for row in bindings}) == len(bindings),
            "pilot_alternative_complete_bank_bindings")
    for reference in value["vendor_refs"]:
        vendor = _one(env, "res.partner", "ref", reference)
        require(vendor.active and vendor.supplier_rank > 0 and vendor.autopost_bills == "never",
                "pilot_alternative_active_vendor")
    for row, binding in zip(value["banks"], bindings, strict=True):
        owner = _one(env, "res.partner", "ref", row["owner_vendor_ref"])
        bank = _one(env, "res.partner.bank", "acc_number", row["bank_ref"])
        require(owner.active and owner.supplier_rank > 0 and owner.autopost_bills == "never"
                and bank.id == binding["bank_id"] and bank.partner_id == owner
                and bank.active and bank.allow_out_payment,
                "pilot_alternative_exact_bank_owner_and_trust")


def _line_gaps(env, checks):
    """Read actual relations; existence of the order alone is insufficient."""
    gaps = []
    for check in checks:
        po = _one(env, "purchase.order", "name", check["purchase_order_ref"])
        require(po.state == "purchase" and po.currency_id.name == "BRL",
                "pilot_alternative_confirmed_order")
        for code in check["item_codes"]:
            lines = po.order_line.filtered(lambda line: not line.display_type and line.product_id.default_code == code)
            if len(lines) != 1:
                gaps.append({"purchase_order_ref": check["purchase_order_ref"], "item_code": code,
                             "matching_line_count": len(lines)})
    return gaps


def run(args):
    require(args.mode == "pilot-alternatives" and args.dataset_fixture_mode
            and all(re.fullmatch(r"[0-9a-f]{64}", digest or "") is not None
                    for digest in (args.pilot_seed_sha256, args.pilot_alternatives_sha256)),
            "pilot_alternative_explicit_mode_and_digest")
    artifacts, manifest, native = load_inputs(args)
    seed_path = Path(args.artifacts) / "pilot-business-seed.json"
    catalog_path = Path(args.artifacts) / "pilot-alternatives.json"
    seed = _input(seed_path, MAX_SEED_BYTES, PilotBusinessSeed)
    catalog = _input(catalog_path, MAX_ALTERNATIVES_BYTES, PilotAlternativeCatalog)
    require(seed.sha256 == args.pilot_seed_sha256 and catalog.sha256 == args.pilot_alternatives_sha256,
            "pilot_alternative_input_digest")
    value = validate_alternatives(seed, catalog)
    business = seed.to_mapping()
    loaded = read_json(artifacts / "pilot-business-seed-result.json")
    require(loaded["schema_version"] == "pilot-business-seed-native/v1" and loaded["status"] == "PASS"
            and loaded["git_base"] == args.git_base and loaded["source_bundle_sha256"] == args.source_bundle_sha256
            and loaded["seed_sha256"] == seed.sha256 and loaded["cohort_sha256"] == value["cohort_sha256"]
            and loaded["codebook_sha256"] == value["codebook_sha256"]
            and loaded["company_id"] == manifest["company_id"]
            and loaded["fixture_count"] == 12 and len(loaded["bindings"]) == 12,
            "pilot_alternative_loaded_seed_provenance")
    odoo.tools.config.parse_config(["-c", args.config, "-d", args.database, "--no-http"], setup_logging=False)
    registry = Registry(args.database)
    observer, scope, _registration = load_scope(registry, args, manifest, native["cases"][0])
    base = observer.base
    from odoo.addons.ap_security_executor.identity import assert_executor_identity
    with registry.cursor() as cr:
        base.cursor_gate(cr)
        env = base.env(cr)
        require(re.fullmatch(r"tcc_runner_[0-9a-f]{12}", cr.dbname) is not None
                and env.company.id == manifest["company_id"] and "SEM VALOR FISCAL" in env.company.name,
                "pilot_alternative_disposable_synthetic_company_only")
        verify_business(env, business["fixtures"], loaded["bindings"])
        inventory = assert_executor_identity(env, env["res.users"].browse(base.user_id), company=env.company)
        before = observer.projection(env, scope)
        require(env["res.partner.bank"].with_context(active_test=False).search_count([
            ("acc_number", "in", [row["bank_ref"] for row in value["banks"]])]) == 0,
            "pilot_alternative_absent_banks_no_repair")
        # All owner/order/vendor lookups are checked before the first mutation.
        owners = {row["owner_vendor_ref"]: _one(env, "res.partner", "ref", row["owner_vendor_ref"])
                  for row in value["banks"]}
        for owner in owners.values():
            require(owner.active and owner.supplier_rank > 0 and owner.autopost_bills == "never",
                    "pilot_alternative_owner_active")
        for reference in value["vendor_refs"]:
            _one(env, "res.partner", "ref", reference)
        gaps = _line_gaps(env, value["purchase_order_checks"])
        bindings = []
        for row in value["banks"]:
            bank = base.administrative_bank(env, vendor_id=owners[row["owner_vendor_ref"]].id,
                                            reference=row["bank_ref"])
            bindings.append({"bank_id": bank.id})
        env.flush_all()
        _verify_catalog(env, value, bindings)
        verify_business(env, business["fixtures"], loaded["bindings"])
        _preserved(before, observer.projection(env, scope))
        require(inventory == assert_executor_identity(env, env["res.users"].browse(base.user_id), company=env.company),
                "pilot_alternative_identity_unchanged")
        cr.commit()
    with registry.cursor() as cr:
        base.cursor_gate(cr)
        env = base.env(cr)
        _verify_catalog(env, value, bindings)
        verify_business(env, business["fixtures"], loaded["bindings"])
        require(gaps == _line_gaps(env, value["purchase_order_checks"]), "pilot_alternative_fresh_gap_diagnosis")
        after = observer.projection(env, scope)
        _preserved(before, after)
        # This mode is narrower than seed creation: only declared banks may be added.
        for name in ("res.partner", "purchase.order", "purchase.order.line"):
            require(canonical(before[name]) == canonical(after[name]), "pilot_alternative_existing_masters_exact")
        added = {row["id"] for row in after["res.partner.bank"]} - {row["id"] for row in before["res.partner.bank"]}
        require(added == {row["bank_id"] for row in bindings}, "pilot_alternative_only_declared_banks_added")
        require(inventory == assert_executor_identity(env, env["res.users"].browse(base.user_id), company=env.company),
                "pilot_alternative_fresh_identity_unchanged")
    require(_input(seed_path, MAX_SEED_BYTES, PilotBusinessSeed) == seed
            and _input(catalog_path, MAX_ALTERNATIVES_BYTES, PilotAlternativeCatalog) == catalog,
            "pilot_alternative_inputs_unchanged")
    write_json(artifacts / "pilot-alternatives-result.json", {
        "schema_version": "pilot-alternatives-native/v1", "status": "PASS",
        "git_base": args.git_base, "source_bundle_sha256": args.source_bundle_sha256,
        "catalog_sha256": catalog.sha256, "seed_sha256": seed.sha256,
        "cohort_sha256": value["cohort_sha256"], "codebook_sha256": value["codebook_sha256"],
        "bank_count": len(bindings), "vendor_count": len(value["vendor_refs"]),
        "order_count": len(value["purchase_order_checks"]),
        "purchase_order_line_gap_count": len(gaps), "purchase_order_line_gaps": gaps,
        "purchase_order_line_gaps_sha256": hashlib.sha256(canonical(gaps)).hexdigest(),
        "technical_resolution_complete": not gaps,
        "financial_projection_preserved": True, "existing_masters_preserved": True,
        "executor_identity_unchanged": True, "fresh_cursor_facts_verified": True,
        "legitimate_business_facts_preserved": True,
        "scientific_run": False, "human_review_complete": False, "public_executor_enabled": False,
        "approval_generated": False, "financial_action_dispatched": False,
    })
