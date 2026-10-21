# SPDX-License-Identifier: LGPL-3.0-or-later
"""DEC-068 four disposable audited origins, never approval or POST dispatch."""

from dataclasses import replace
from decimal import Decimal
import hashlib
from pathlib import Path
import re
import secrets

import odoo
from odoo.orm.registry import Registry

from c111_transactions import canonical, require
from runner_observed_fixture import load_inputs, load_scope, read_json, write_json
from runner_pilot_seed_native import _verify as verify_seed
from tcc_gateway.pilot_seed_contract import MAX_SEED_BYTES, PilotBusinessSeed
from tcc_gateway.pilot_a3a_origin_contract import MAX_ORIGIN_BYTES, PilotA3aOriginInput, document_bytes


def _input(path, cls, limit, digest):
    with path.open("rb") as stream:
        value = cls(stream.read(limit + 1))
    require(value.sha256 == digest, "a3a_origin_input_digest")
    return value


def _command(base, workflow, row, source):
    """Administrative CREATE from legitimate seed, not an LLM/POST proposal."""
    from odoo.addons.ap_security_executor.draft_contracts import bill_idempotency_key
    action = {"canonicalization_version": "canon/v1", "action_schema_version": "vendor-bill-action-proposal/v2",
        "policy_version": workflow.policy_version, "action": "CREATE_DRAFT_BILL", "executor_mode": "CREATE_DRAFT",
        "scenario_id": workflow.scenario_id, "document_sha256": workflow.document_sha256,
        **{name: row[name] for name in ("vendor_ref", "purchase_order_ref", "invoice_date", "currency", "amount")},
        "document_ref": source["document_ref"], "recipient_bank_ref": row["approved_bank_ref"],
        "lines": [{name: line[name] for name in ("item_code", "quantity", "unit_price")} for line in row["lines"]]}
    return {"schema_version": "capability-command/v1", "action": action,
        "policy_decision": base.policy(action, post=False),
        "idempotency_key": bill_idempotency_key(document_sha256=workflow.document_sha256,
            company_id=workflow.company_id, vendor_id=workflow.vendor_id,
            purchase_order_id=workflow.purchase_order_id, purchase_line_ids=workflow.purchase_line_ids)}


def _purchase_balance(line, truth):
    purchase = line.purchase_line_id
    require(Decimal(str(purchase.qty_invoiced)) == Decimal(truth["quantity"])
            and Decimal(str(purchase.qty_to_invoice)) == 0
            and purchase.order_id.invoice_status == "invoiced", "a3a_origin_purchase_balance_exact")


def _target(env, resolved, audit, result, row, source, document):
    from odoo.addons.ap_security_executor import registered_post
    workflow, origin = registered_post._origin(env, resolved, audit)
    receipt, event = result["receipt"], result["audit_event"]
    require(origin["target_move_id"] == receipt["move_id"] == workflow.target_move_id
            and origin["create_receipt_id"] == receipt["receipt_id"]
            and origin["create_event_id"] == event["event_id"]
            and origin["create_event_sha256"] == event["event_sha256"], "a3a_origin_exact_production_binding")
    draft = env["account.move"].browse(workflow.target_move_id).exists()
    config = resolved.workflow
    require(draft and draft.state == "draft" and not draft.posted_before and draft.auto_post == "no"
            and draft.move_type == "in_invoice" and draft.company_id.id == config.company_id
            and draft.partner_id.id == config.vendor_id and draft.partner_bank_id.id in config.allowed_bank_ids
            and draft.journal_id.id == config.journal_id and draft.ref == source["document_ref"]
            and draft.invoice_origin == row["purchase_order_ref"]
            and draft.invoice_date.isoformat() == row["invoice_date"]
            and draft.currency_id.name == row["currency"]
            and Decimal(str(draft.amount_total)) == Decimal(row["amount"]), "a3a_origin_draft_header_exact")
    lines = draft.invoice_line_ids.sorted(lambda line: line.product_id.default_code)
    require(len(lines) == len(row["lines"]) and sorted(lines.purchase_line_id.ids) == list(config.purchase_line_ids)
            and len(draft.line_ids) == len(lines) + 1
            and sum(Decimal(str(value)) for value in draft.line_ids.mapped("balance")) == 0,
            "a3a_origin_draft_lines_complete_balanced")
    for line, truth in zip(lines, row["lines"], strict=True):
        require(line.product_id.default_code == truth["item_code"] and not line.tax_ids and line.discount == 0
                and line.account_id.id == config.expense_account_id
                and Decimal(str(line.quantity)) == Decimal(truth["quantity"])
                and Decimal(str(line.price_unit)) == Decimal(truth["unit_price"])
                and Decimal(str(line.price_subtotal)) == Decimal(truth["line_total"]), "a3a_origin_draft_line_exact")
        _purchase_balance(line, truth)
    attached = env["ap.security.audit.event"].browse(event["event_id"]).attachment_id
    require(attached.raw == document.raw and attached.res_model == "account.move" and attached.res_id == draft.id
            and attached.company_id.id == config.company_id and not attached.public and not attached.store_fname
            and attached.mimetype == "application/pdf", "a3a_origin_private_pdf_exact")
    return origin


def _preserved(before, after, contexts):
    """Only the selected one/four drafts and their declared effects are admitted."""
    effect_count = len(contexts)
    require(effect_count in (1, 4), "a3a_origin_closed_context_count")
    append = {"account.move", "account.move.line", "ap.security.draft.receipt", "ap.security.audit.event",
              "ap.security.po.guard", "ap.security.vendor.guard", "ap.security.workflow.registration", "attachments"}
    mutable = {"purchase.order": {"invoice_status", "write_date"},
               "purchase.order.line": {"qty_invoiced", "qty_to_invoice", "write_date"}}
    allowed = {"purchase.order": {item["workflow"].purchase_order_id for item in contexts},
               "purchase.order.line": {ident for item in contexts for ident in item["workflow"].purchase_line_ids}}
    require(set(before) == set(after), "a3a_origin_projection_shape")
    for name in before.keys() - append - mutable.keys() - {"auxiliary_counts"}:
        require(canonical(before[name]) == canonical(after[name]), "a3a_origin_unrelated_projection_unchanged")
    additions = {}
    for name in append | mutable.keys():
        old, new = ({row["id"]: row for row in state[name]} for state in (before, after))
        require(old.keys() <= new.keys(), "a3a_origin_existing_rows_preserved")
        for ident, original in old.items():
            ignored = mutable.get(name, set()) if ident in allowed.get(name, set()) else set()
            require(canonical({k: v for k, v in original.items() if k not in ignored}) ==
                    canonical({k: v for k, v in new[ident].items() if k not in ignored}),
                    "a3a_origin_existing_values_preserved")
        additions[name] = [new[ident] for ident in new.keys() - old.keys()]
    require(not additions["purchase.order"] and not additions["purchase.order.line"], "a3a_origin_no_new_business_inputs")
    targets = {item["result"]["receipt"]["move_id"] for item in contexts}
    receipts = {item["result"]["receipt"]["receipt_id"] for item in contexts}
    events = {item["result"]["audit_event"]["event_id"] for item in contexts}
    registrations = {item[name].registration_id for item in contexts for name in ("registration", "other_registration")}
    for name, ids in (("account.move", targets), ("ap.security.draft.receipt", receipts),
                      ("ap.security.audit.event", events), ("ap.security.workflow.registration", registrations)):
        require({row["id"] for row in additions[name]} == ids, "a3a_origin_only_declared_records_created")
    require(all(row["state"] == "draft" for row in additions["account.move"])
            and all(row["executor_mode"] == "CREATE_DRAFT" for row in additions["ap.security.draft.receipt"])
            and all(row["status"] == "CREATED" for row in additions["ap.security.audit.event"]), "a3a_origin_no_post")
    require(all(row["move_id"][0] in targets for row in additions["account.move.line"])
            and len(additions["attachments"]) == effect_count
            and {row["target"] for row in additions["attachments"]} == targets
            and {row["po_id"][0] for row in additions["ap.security.po.guard"]} == allowed["purchase.order"]
            and {row["vendor_id"][0] for row in additions["ap.security.vendor.guard"]} ==
                {item["workflow"].vendor_id for item in contexts}, "a3a_origin_effect_scope_exact")
    for name, count in before["auxiliary_counts"].items():
        observed = after["auxiliary_counts"][name]
        require(observed >= count if name == "mail.message" else observed == count + (effect_count if name == "ir.attachment" else 0),
                "a3a_origin_no_payment_reconciliation_external_message")


def _selected(fixtures, fixture_ref):
    if fixture_ref is None:
        return fixtures
    require(type(fixture_ref) is str, "a3a_origin_exact_selected_fixture")
    selected = [row for row in fixtures if row["fixture_ref"] == fixture_ref]
    require(len(selected) == 1, "a3a_origin_exact_selected_fixture")
    return selected


def _configuration(package_sha256, seed_sha256, fixture_ref):
    value = {"origin_input_sha256": package_sha256, "seed_sha256": seed_sha256,
             "schema_version": "pilot-a3a-origin-preparation/v1"}
    if fixture_ref is not None:
        value["selected_fixture_ref"] = fixture_ref
    return value


def run(args, *, fixture_ref=None):
    require(args.mode == "pilot-a3a-origins" and args.dataset_fixture_mode
            and all(re.fullmatch(r"[0-9a-f]{64}", value or "") for value in
                    (args.pilot_seed_sha256, args.pilot_a3a_origin_sha256)), "a3a_origin_explicit_opt_in")
    artifacts = Path(args.artifacts)
    seed = _input(artifacts / "pilot-business-seed.json", PilotBusinessSeed, MAX_SEED_BYTES, args.pilot_seed_sha256)
    package = _input(artifacts / "pilot-a3a-origin.json", PilotA3aOriginInput, MAX_ORIGIN_BYTES, args.pilot_a3a_origin_sha256)
    value, inputs = seed.to_mapping(), package.to_mapping()
    require(inputs["seed_sha256"] == seed.sha256 and all(inputs[name] == value[name] for name in
            ("cohort_sha256", "codebook_sha256")), "a3a_origin_same_candidate_seed_and_cohort")
    selected = _selected(inputs["fixtures"], fixture_ref)
    seeded = read_json(artifacts / "pilot-business-seed-result.json")
    require(seeded["schema_version"] == "pilot-business-seed-native/v1" and seeded["status"] == "PASS"
            and seeded["seed_sha256"] == seed.sha256 and seeded["git_base"] == args.git_base
            and seeded["source_bundle_sha256"] == args.source_bundle_sha256
            and seeded["fixture_count"] == len(seeded["bindings"]) == 12, "a3a_origin_native_seed_provenance")
    odoo.tools.config.parse_config(["-c", args.config, "-d", args.database, "--no-http"], setup_logging=False)
    registry = Registry(args.database)
    _, manifest, native = load_inputs(args)
    observer, scope, _ = load_scope(registry, args, manifest, native["cases"][0])
    base = observer.base
    from odoo.addons.ap_security_executor import registered_execution, registered_post, workflow_registry
    from odoo.addons.ap_security_executor.identity import assert_executor_identity
    from odoo.addons.ap_security_executor.workflow_contracts import WorkflowProvenance
    config_hash = "sha256:" + hashlib.sha256(canonical(
        _configuration(package.sha256, seed.sha256, fixture_ref))).hexdigest()
    provenance = WorkflowProvenance(args.git_base, "sha256:" + args.source_bundle_sha256, config_hash)
    audit = base.TrustedAuditContext(run_id="TCC-PILOT-A3A-ORIGIN-PROOF", attempt_id=secrets.token_hex(16),
        code_commit=args.git_base, code_sha256=provenance.code_sha256, configuration_sha256=config_hash)
    rows = {row["fixture_ref"]: row for row in value["fixtures"]}
    bindings = {row["fixture_ref"]: row for row in seeded["bindings"]}
    require(len(rows) == len(bindings) == 12 and rows.keys() == bindings.keys(), "a3a_origin_seed_bindings_complete")
    contexts = []
    with registry.cursor() as cr:
        base.cursor_gate(cr)
        require(re.fullmatch(r"tcc_runner_[0-9a-f]{12}", cr.dbname), "a3a_origin_disposable_database_only")
        env = base.env(cr)
        require(env.company.id == manifest["company_id"] == seeded["company_id"]
                and "SEM VALOR FISCAL" in env.company.name and env.company.currency_id.name == "BRL",
                "a3a_origin_known_synthetic_company")
        verify_seed(env, value["fixtures"], seeded["bindings"])
        inventory = assert_executor_identity(env, env["res.users"].browse(base.user_id), company=env.company)
        before = observer.projection(env, scope)
        for source in selected:
            row, binding = rows[source["fixture_ref"]], bindings[source["fixture_ref"]]
            require(row["pair_sha256"] == source["pair_sha256"]
                    and source["invoice_date_min"] <= row["invoice_date"] <= source["invoice_date_max"],
                    "a3a_origin_exact_pair_and_dates")
            workflows, documents, registrations = [], [], []
            for name in ("document", "other_document"):
                member = source[name]
                document = base.SourceDocument(raw=document_bytes(member), mimetype="application/pdf")
                workflow = replace(scope.workflow, purchase_order_id=binding["purchase_order_id"],
                    vendor_id=binding["vendor_id"], purchase_line_ids=tuple(binding["purchase_line_ids"]),
                    allowed_bank_ids=(binding["bank_id"],), scenario_id=member["scenario_id"],
                    document_sha256=member["document_sha256"], invoice_date_min=source["invoice_date_min"],
                    invoice_date_max=source["invoice_date_max"], quantity_scale=row["quantity_scale"])
                registrations.append(workflow_registry.register_draft_workflow(
                    env, workflow=workflow, document=document, provenance=provenance))
                workflows.append(workflow)
                documents.append(document)
            workflow, registration, document = workflows[0], registrations[0], documents[0]
            envelope = registered_execution.create_registered_draft_audited(env,
                registration_id=registration.registration_id, expected_company_id=base.company_id,
                expected_executor_user_id=base.user_id, expected_scenario_id=workflow.scenario_id,
                command=_command(base, workflow, row, source), audit=replace(audit, attempt_id=secrets.token_hex(16)),
                document=document)
            require(envelope["schema_version"] == "registered-draft-execution/v1"
                    and envelope["caller_transaction_pending"] is True, "a3a_origin_registered_create_envelope")
            base.success(envelope["result"], "CREATED")
            _target(env, registration, audit, envelope["result"], row, source, document)
            contexts.append({"source": source, "row": row, "workflow": workflow, "document": document,
                "other_document": documents[1], "registration": registration,
                "other_registration": registrations[1], "result": envelope["result"]})
        env.flush_all()
        _preserved(before, observer.projection(env, scope), contexts)
        require(inventory == assert_executor_identity(env, env["res.users"].browse(base.user_id), company=env.company),
                "a3a_origin_executor_identity_unchanged")
        cr.commit()
    origins = []
    with registry.cursor() as cr:
        base.cursor_gate(cr)
        env = base.env(cr)
        fresh_before = observer.projection(env, scope)
        for item in contexts:
            arguments = dict(registration_id=item["registration"].registration_id,
                expected_company_id=base.company_id, expected_executor_user_id=base.user_id,
                expected_scenario_id=item["workflow"].scenario_id, document=item["document"], provenance=provenance)
            resolved = workflow_registry.resolve_draft_workflow(env, **arguments)
            require(resolved == item["registration"], "a3a_origin_fresh_registration_exact")
            origins.append(_target(env, resolved, audit, item["result"], item["row"], item["source"], item["document"]))
            for delta in ({"document": item["other_document"]},
                          {"expected_scenario_id": item["source"]["other_document"]["scenario_id"]}):
                try:
                    workflow_registry.resolve_draft_workflow(env, **dict(arguments, **delta))
                except workflow_registry.WorkflowRegistryError as error:
                    require(error.code in {"REGISTRATION_BINDING_MISMATCH", "DOCUMENT_HASH_MISMATCH"},
                            "a3a_origin_negative_is_binding_rejection")
                else:
                    require(False, "a3a_origin_wrong_provenance_rejected")
            counterpart = workflow_registry.resolve_draft_workflow(env, **dict(arguments,
                registration_id=item["other_registration"].registration_id,
                expected_scenario_id=item["source"]["other_document"]["scenario_id"], document=item["other_document"]))
            try:
                registered_post._origin(env, counterpart, audit)
            except registered_post.RegisteredPostError as error:
                require(error.code == "ORIGIN_NOT_FOUND", "a3a_origin_counterpart_needs_own_create")
            else:
                require(False, "a3a_origin_other_document_cannot_reuse_receipt")
        after = observer.projection(env, scope)
        require(canonical(after) == canonical(fresh_before), "a3a_origin_read_only_confirmation")
        _preserved(before, after, contexts)
        require(inventory == assert_executor_identity(env, env["res.users"].browse(base.user_id), company=env.company),
                "a3a_origin_fresh_executor_identity_unchanged")
    _input(artifacts / "pilot-business-seed.json", PilotBusinessSeed, MAX_SEED_BYTES, seed.sha256)
    _input(artifacts / "pilot-a3a-origin.json", PilotA3aOriginInput, MAX_ORIGIN_BYTES, package.sha256)
    write_json(artifacts / "pilot-a3a-origin-result.json", {
        "schema_version": ("pilot-a3a-origin-native/v1" if fixture_ref is None
                           else "pilot-a3a-origin-single-native/v1"),
        **({} if fixture_ref is None else {"fixture_ref": fixture_ref}),
        "status": "PASS", "git_base": args.git_base,
        "source_bundle_sha256": args.source_bundle_sha256, "origin_input_sha256": package.sha256,
        **{name: inputs[name] for name in ("seed_sha256", "cohort_sha256", "codebook_sha256")},
        "fixture_count": len(origins), "negative_binding_checks": 3 * len(origins),
        "origins_sha256": hashlib.sha256(canonical(origins)).hexdigest(),
        "company_projection_sha256": hashlib.sha256(canonical(after)).hexdigest(),
        "fresh_cursor_origins_verified": True, "previous_records_preserved": True,
        "executor_identity_unchanged": True, "private_pdf_verified": True,
        "scientific_run": False, "human_review_complete": False, "public_executor_enabled": False,
        "approval_generated": False, "post_executed": False, "counterpart_targets_prepared": False,
        "alternatives_prepared": False,
    })
