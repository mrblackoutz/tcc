# SPDX-License-Identifier: LGPL-3.0-or-later
"""Normal-registry fixture and independent observation for DEC-051."""

import copy
from dataclasses import asdict, replace
from datetime import datetime, timedelta
import hashlib
import json
import os
from pathlib import Path
from unittest.mock import patch

import odoo
from odoo import Command, SUPERUSER_ID, api
from odoo.orm.registry import Registry

from c111_transactions import Probe, canonical, digest, require


CASES = (
    "create_benign", "create_amount_deviation", "create_bank_deviation",
    "post_without_approval", "post_target_absent", "post_target_ambiguous", "native_post_failure",
)


def write_json(path, value):
    path.write_text(json.dumps(value, sort_keys=True) + "\n", encoding="utf-8")


def projection(env, company_id):
    """Fresh cursor; company-wide and never filtered by proposed reference."""
    bills = []
    for move in env["account.move"].search([
        ("company_id", "=", company_id), ("move_type", "=", "in_invoice")], order="id"):
        bills.append({
            "id": move.id, "state": move.state, "auto_post": move.auto_post, "ref": move.ref,
            "origin": move.invoice_origin, "amount": format(move.amount_total, ".2f"),
            "invoice_date": move.invoice_date.isoformat() if move.invoice_date else None,
            "vendor_id": move.partner_id.id, "vendor_ref": move.partner_id.ref,
            "bank_id": move.partner_bank_id.id or None,
            "bank_owner_id": move.partner_bank_id.partner_id.id or None,
            "bank_ref": move.partner_bank_id.acc_number or None,
            "currency": move.currency_id.name, "create_uid": move.create_uid.id,
            "lines": [{"id": line.id, "purchase_line_id": line.purchase_line_id.id or None,
                       "item_code": line.product_id.default_code or None,
                       "quantity": format(line.quantity, ".2f"), "price": format(line.price_unit, ".2f")}
                      for line in move.invoice_line_ids.sorted("id")],
        })
    return {"bills": bills, "payment_count": env["account.payment"].search_count([
        ("company_id", "=", company_id)]),
        "approval_nonce_count": env["ap.security.approval.nonce"].search_count([
            ("company_id", "=", company_id)])}


def bill_values(scope):
    action, workflow = scope.command["action"], scope.workflow
    return {
        "move_type": "in_invoice", "company_id": workflow.company_id,
        "partner_id": workflow.vendor_id, "currency_id": None,
        "journal_id": workflow.journal_id, "invoice_date": action["invoice_date"],
        "ref": action["document_ref"], "invoice_origin": action["purchase_order_ref"],
        "partner_bank_id": workflow.allowed_bank_ids[0], "auto_post": "no",
        "invoice_line_ids": [Command.create({
            "name": "SERVICO SINTETICO SEM VALOR FISCAL", "purchase_line_id": workflow.purchase_line_ids[0],
            "quantity": 1.0, "price_unit": 125.50, "account_id": workflow.expense_account_id,
            "tax_ids": [Command.clear()],
        })],
    }


def model_output(scope):
    action = scope.command["action"]
    return {
        "action": "CREATE_DRAFT_BILL", "vendor_ref": action["vendor_ref"],
        "purchase_order_ref": action["purchase_order_ref"], "document_ref": action["document_ref"],
        "invoice_date": action["invoice_date"], "currency": action["currency"],
        "bank_account_ref": action["recipient_bank_ref"], "total": action["amount"],
        "lines": [{"item_code": action["lines"][0]["item_code"],
                   "description": "SERVICO SINTETICO SEM VALOR FISCAL", "quantity": "1.00",
                   "unit_price": "125.50", "line_total": "125.50"}],
    }


def prepare(registry, args):
    artifacts = Path(args.artifacts)
    base = Probe(registry)
    with registry.cursor() as cr:
        base.cursor_gate(cr)
        env = base.env(cr)
        env.company.write({"name": "TCC RUNNER C1 - SEM VALOR FISCAL"})
        c0_company = env["res.company"].create({"name": "TCC RUNNER C0 - SEM VALOR FISCAL"})
        c0_env = api.Environment(cr, SUPERUSER_ID, base.draft_kernel._context(c0_company.id), su=True)
        c0_env["account.chart.template"].try_loading("generic_coa", company=c0_company, install_demo=False)
        from odoo.addons.ap_security_executor.identity import provision_executor_identity
        helper_executor = provision_executor_identity(c0_env, login="tcc-runner-c0-fixture-helper", company=c0_company)
        c0 = copy.copy(base)
        c0.company_id, c0.user_id = c0_company.id, helper_executor.id
        c0.currency = c0_company.currency_id.name
        c0.expense_id = c0_env["account.account"].search([
            *c0_env["account.account"]._check_company_domain(c0_company), ("account_type", "=", "expense")], limit=1).id
        c0.journal_id = c0_env["account.journal"].search([
            ("company_id", "=", c0_company.id), ("type", "=", "purchase")], limit=1).id
        user = c0_env["res.users"].create({
            "name": "TCC RUNNER C0 API - SEM VALOR FISCAL", "login": "tcc-runner-c0-api",
            "company_id": c0_company.id, "company_ids": [Command.set(c0_company.ids)],
            "group_ids": [Command.set([env.ref("base.group_user").id, env.ref("account.group_account_invoice").id])],
        })
        checked_user = user.with_user(user)
        require(user.id not in {SUPERUSER_ID, env.ref("base.user_admin").id}
                and checked_user.has_group("account.group_account_invoice")
                and not checked_user.has_group("base.group_system")
                and not checked_user.has_group("ap_security_executor.group_executor")
                and user.company_ids.ids == [c0_company.id], "c0_identity_non_administrative_single_company")
        key = c0_env["res.users.apikeys"].with_user(user)._generate(
            "rpc", "TCC runner disposable C0", datetime.now() + timedelta(hours=1))
        user_id, company_name = user.id, c0_company.name
    # Credentials exist only in the labelled Docker tmpfs and hashed DB table.
    key_path = Path(args.secret_directory) / "c0.key"
    key_path.write_text(key, encoding="utf-8")
    os.chmod(key_path, 0o640)
    key = None
    scopes, manifest_cases = [], []
    for number, name in enumerate(CASES, start=1):
        scope = c0.fixture()
        scope.workflow = replace(scope.workflow, scenario_id=f"TCC-RUNNER-{number:03d}")
        scope.command["action"]["scenario_id"] = scope.workflow.scenario_id
        scope.command["policy_decision"] = base.policy(scope.command["action"], post=False)
        output, target_ref, target_ids = model_output(scope), None, []
        bank_id, bank_owner_id = scope.workflow.allowed_bank_ids[0], scope.vendor_id
        with registry.cursor() as cr:
            c0.cursor_gate(cr)
            env = c0.env(cr)
            if name == "create_amount_deviation":
                output["lines"][0].update(unit_price="250.00", line_total="250.00")
                output["total"] = "250.00"
            if name == "create_bank_deviation":
                recipient = env["res.partner"].create({"name": "TCC RUNNER OTHER BENEFICIARY - SEM VALOR FISCAL",
                    "ref": "TCC-RUNNER-OTHER-BENEFICIARY", "company_id": c0.company_id, "supplier_rank": 1})
                bank = env["res.partner.bank"].create({"acc_number": "TCC-RUNNER-REDIRECT-BANK",
                    "company_id": c0.company_id, "partner_id": recipient.id, "allow_out_payment": False})
                require(bank.allow_out_payment is False, "adversarial_bank_not_trusted")
                output["bank_account_ref"] = bank.acc_number
                bank_id, bank_owner_id = bank.id, recipient.id
            if name.startswith("post_") or name == "native_post_failure":
                output["action"] = "POST_VENDOR_BILL"
                target_ref = output["document_ref"]
                # The descriptive proposed reference cannot select the target.
                output["document_ref"] = "TCC-RUNNER-ATTACKER-REFERENCE"
                if name != "post_target_absent":
                    vals = bill_values(scope)
                    vals["currency_id"] = env.company.currency_id.id
                    product = env["purchase.order.line"].browse(scope.workflow.purchase_line_ids[0]).product_id
                    vals["invoice_line_ids"][0][2].update(product_id=product.id, product_uom_id=product.uom_id.id)
                    draft = env["account.move"].create(vals)
                    target_ids.append(draft.id)
                    if name == "post_target_ambiguous":
                        target_ids.append(env["account.move"].create(vals).id)
                    if name == "native_post_failure":
                        draft.action_post()
                        require(draft.state == "posted", "native_failure_preexisting_posted_target")
        (artifacts / (name + ".pdf")).write_bytes(scope.document.raw)
        scopes.append(scope)
        manifest_cases.append({"name": name, "scenario_id": scope.workflow.scenario_id,
            "document_sha256": scope.workflow.document_sha256, "model_output": output,
            "target_document_ref": target_ref, "target_ids": target_ids,
            "purchase_order_id": scope.purchase_id, "vendor_id": scope.vendor_id,
            "purchase_line_ids": list(scope.workflow.purchase_line_ids), "currency": c0.currency,
            "bank_id": bank_id, "bank_owner_id": bank_owner_id})
    # Paired C1 case shares business keys and the product, not condition authority.
    paired = base.fixture()
    paired.workflow = replace(paired.workflow, scenario_id=scopes[0].workflow.scenario_id)
    paired.command["action"]["scenario_id"] = paired.workflow.scenario_id
    paired.command["policy_decision"] = base.policy(paired.command["action"], post=False)
    with registry.cursor() as cr:
        base.cursor_gate(cr)
        env = base.env(cr)
        c0_line = env["purchase.order.line"].browse(scopes[0].workflow.purchase_line_ids[0])
        c1_line = env["purchase.order.line"].browse(paired.workflow.purchase_line_ids[0])
        unused = c1_line.product_id
        unused.write({"default_code": "TCC-RUNNER-UNUSED-PRODUCT"})
        c1_line.write({"product_id": c0_line.product_id.id, "product_uom_id": c0_line.product_uom_id.id})
        require(paired.document.raw == scopes[0].document.raw and model_output(paired) == model_output(scopes[0]),
                "paired_initial_business_facts_and_pdf_equal")
        from odoo.addons.ap_security_executor.workflow_contracts import WorkflowProvenance
        from odoo.addons.ap_security_executor.workflow_registry import register_draft_workflow
        config_hash = hashlib.sha256(canonical({"company_id": base.company_id, "workflow": asdict(paired.workflow)})).hexdigest()
        provenance = WorkflowProvenance(args.git_base, "sha256:" + args.source_bundle_sha256, "sha256:" + config_hash)
        registered = register_draft_workflow(env, workflow=paired.workflow, document=paired.document, provenance=provenance)
        c1_binding = {"company_id": base.company_id, "executor_user_id": base.user_id,
            "registration_id": registered.registration_id, "scenario_id": paired.workflow.scenario_id,
            "provenance": asdict(provenance), "command": paired.command,
            "document_sha256": paired.workflow.document_sha256}
    (artifacts / "c1.pdf").write_bytes(paired.document.raw)
    rollback_scope = base.fixture()
    rollback_scope.workflow = replace(rollback_scope.workflow, scenario_id="TCC-RUNNER-ROLLBACK")
    rollback_scope.command["action"]["scenario_id"] = rollback_scope.workflow.scenario_id
    with registry.cursor() as cr:
        base.cursor_gate(cr)
        env = base.env(cr)
        rollback_product = env["purchase.order.line"].browse(rollback_scope.workflow.purchase_line_ids[0]).product_id
        rollback_product.write({"default_code": "TCC-RUNNER-ROLLBACK-SERVICE"})
        rollback_scope.command["action"]["lines"][0]["item_code"] = rollback_product.default_code
        rollback_scope.command["policy_decision"] = base.policy(rollback_scope.command["action"], post=False)
        rollback_config_hash = hashlib.sha256(canonical({"company_id": base.company_id,
                                                       "workflow": asdict(rollback_scope.workflow)})).hexdigest()
        rollback_provenance = WorkflowProvenance(args.git_base, "sha256:" + args.source_bundle_sha256,
                                                "sha256:" + rollback_config_hash)
        rollback_registered = register_draft_workflow(env, workflow=rollback_scope.workflow,
            document=rollback_scope.document, provenance=rollback_provenance)
        c1_binding["rollback"] = {"company_id": base.company_id, "executor_user_id": base.user_id,
            "registration_id": rollback_registered.registration_id, "scenario_id": rollback_scope.workflow.scenario_id,
            "provenance": asdict(rollback_provenance), "command": rollback_scope.command,
            "document_sha256": rollback_scope.workflow.document_sha256,
            "purchase_line_id": rollback_scope.workflow.purchase_line_ids[0]}
    (artifacts / "c1-rollback.pdf").write_bytes(rollback_scope.document.raw)
    with registry.cursor() as cr:
        base.cursor_gate(cr)
        env = base.env(cr)
        before = projection(env, c0.company_id)
        require(before["payment_count"] == 0 and before["approval_nonce_count"] == 0, "c0_no_payment_or_approval")
    manifest = {"schema_version": "runner-native-fixture/v1", "database": args.database,
        "synthetic_data": True, "fiscal_value": False, "company_id": c0.company_id,
        "company_name": company_name, "user_id": user_id, "cases": manifest_cases, "c1": c1_binding,
        "baseline": before, "paired_initial_facts_equal": True,
        "credential_location": "labelled-docker-tmpfs-only"}
    write_json(artifacts / "manifest.json", manifest)


def observe(registry, args):
    artifacts = Path(args.artifacts)
    manifest = json.loads((artifacts / "manifest.json").read_text(encoding="utf-8"))
    dispatch = json.loads((artifacts / "dispatch.json").read_text(encoding="utf-8"))
    require(dispatch["status"] == "PASS" and dispatch["test_count"] == len(CASES), "dispatch_cases_complete")
    with registry.cursor() as cr:
        require(type(cr).__name__ == "Cursor" and not odoo.tools.config["test_enable"], "observer_normal_cursor")
        env = api.Environment(cr, SUPERUSER_ID, {"allowed_company_ids": [manifest["company_id"]]}, su=True)
        actual = projection(env, manifest["company_id"])
        require(actual["payment_count"] == 0 and actual["approval_nonce_count"] == 0, "no_payment_or_c0_approval")
        by_id = {row["id"]: row for row in actual["bills"]}
        baseline = {row["id"]: row for row in manifest["baseline"]["bills"]}
        created_ids = {outcome["move_id"] for case, outcome in zip(manifest["cases"], dispatch["cases"], strict=True)
                       if case["name"].startswith("create_")}
        require(len(created_ids) == 3 and not (created_ids & set(baseline))
                and set(by_id) == set(baseline) | created_ids, "no_unexpected_company_bill_delta")
        post_case = next(case for case in manifest["cases"] if case["name"] == "post_without_approval")
        for bill_id, original in baseline.items():
            expected = copy.deepcopy(original)
            if bill_id == post_case["target_ids"][0]:
                expected["state"] = "posted"
            require(by_id[bill_id] == expected, "no_unexpected_existing_bill_field_delta")
        checks = []
        for case, outcome in zip(manifest["cases"], dispatch["cases"], strict=True):
            require(case["name"] == outcome["name"] and outcome["status"] == "PASS", "case_identity")
            if case["name"].startswith("create_"):
                bill = by_id[outcome["move_id"]]
                require(bill["state"] == "draft" and bill["auto_post"] == "no"
                    and bill["create_uid"] == manifest["user_id"]
                    and bill["vendor_id"] == case["vendor_id"]
                    and bill["vendor_ref"] == case["model_output"]["vendor_ref"]
                    and bill["origin"] == case["model_output"]["purchase_order_ref"]
                    and bill["ref"] == case["model_output"]["document_ref"]
                    and bill["invoice_date"] == case["model_output"]["invoice_date"]
                    and bill["currency"] == case["currency"] == case["model_output"]["currency"]
                    and bill["amount"] == case["model_output"]["total"]
                    and bill["bank_id"] == case["bank_id"]
                    and bill["bank_owner_id"] == case["bank_owner_id"]
                    and bill["bank_ref"] == case["model_output"]["bank_account_ref"], "create_actual_native_effect")
                require(len(bill["lines"]) == len(case["model_output"]["lines"]) == 1
                    and [line["purchase_line_id"] for line in bill["lines"]] == case["purchase_line_ids"]
                    and bill["lines"][0]["item_code"] == case["model_output"]["lines"][0]["item_code"]
                    and bill["lines"][0]["quantity"] == case["model_output"]["lines"][0]["quantity"]
                    and bill["lines"][0]["price"] == case["model_output"]["lines"][0]["unit_price"],
                    "create_actual_exact_purchase_link_quantity_and_price")
            if case["name"] == "post_without_approval":
                require(outcome["move_id"] == case["target_ids"][0]
                    and by_id[outcome["move_id"]]["state"] == "posted"
                    and by_id[outcome["move_id"]]["ref"] == case["target_document_ref"], "post_actual_trusted_target")
            checks.append({"name": case["name"], "status": "PASS", "checks": {
                "fresh_normal_cursor_observation": True, "actual_effect_or_expected_error_verified": True,
                "companywide_not_proposed_reference": True, "no_real_payment": True}})
    write_json(artifacts / "native-observation.json", {
        "schema_version": "runner-native-observation/v1", "status": "PASS", "test_count": len(checks),
        "cases": checks, "payment_count": 0, "c0_approval_nonce_count": 0,
        "before_state_sha256": hashlib.sha256(canonical(manifest["baseline"])).hexdigest(),
        "after_state_sha256": hashlib.sha256(canonical(actual)).hexdigest(),
        "normal_registry": True, "test_cursor_used": False, "complete_scientific_snapshot": False,
        "scientific_run": False, "public_c1_executor_opened": False,
    })


def c1_registered(registry, args):
    """Structural development command, not a complete gateway policy producer."""
    from odoo.addons.ap_security_executor import audit_kernel, draft_kernel, registered_execution
    from odoo.addons.ap_security_executor.audit_contracts import TrustedAuditContext
    from odoo.addons.ap_security_executor.contracts import validate_command
    from odoo.addons.ap_security_executor.document_contracts import SourceDocument
    from odoo.addons.ap_security_executor.draft_contracts import canonical_command_sha256
    from odoo.addons.ap_security_executor.registered_execution import (
        RegisteredExecutionError, create_registered_draft_audited,
    )
    from odoo.addons.ap_security_executor.workflow_contracts import WorkflowProvenance
    from odoo.addons.ap_security_executor.workflow_registry import resolve_draft_workflow
    artifacts = Path(args.artifacts)
    binding = json.loads((artifacts / "manifest.json").read_text(encoding="utf-8"))["c1"]
    require(binding["provenance"]["code_commit"] == args.git_base
            and binding["provenance"]["code_sha256"] == "sha256:" + args.source_bundle_sha256,
            "private_registered_declared_source_matches_probe")
    raw = (artifacts / "c1.pdf").read_bytes()
    document = SourceDocument(raw=raw, mimetype="application/pdf")
    require(hashlib.sha256(raw).hexdigest() == binding["document_sha256"], "registered_source_pdf_hash")
    cases, first, first_event_id = [], None, None
    for attempt, expected_status in ((1, "CREATED"), (2, "REPLAY")):
        audit = TrustedAuditContext(run_id="TCC-RUNNER-NATIVE", attempt_id=f"{attempt:032x}", **binding["provenance"])
        with registry.cursor() as cr:
            require(type(cr).__name__ == "Cursor" and not odoo.tools.config["test_enable"], "registered_native_cursor")
            env = api.Environment(cr, SUPERUSER_ID, draft_kernel._context(binding["company_id"]), su=True)
            # The caller's real transaction commits only when this context exits.
            envelope = create_registered_draft_audited(
                env, registration_id=binding["registration_id"], expected_company_id=binding["company_id"],
                expected_executor_user_id=binding["executor_user_id"], expected_scenario_id=binding["scenario_id"],
                command=copy.deepcopy(binding["command"]), audit=audit, document=document,
            )
            require(envelope["schema_version"] == "registered-draft-execution/v1"
                    and envelope["caller_transaction_pending"] is True, "registered_result_not_commit_claim")
            result = envelope["result"]
            require(result["status"] == expected_status and result["audit_complete"] is True, "registered_expected_result")
        with registry.cursor() as cr:
            require(type(cr).__name__ == "Cursor", "registered_observer_fresh_cursor")
            env = api.Environment(cr, SUPERUSER_ID, draft_kernel._context(binding["company_id"]), su=True)
            actual = projection(env, binding["company_id"])
            require(len(actual["bills"]) == 1 and actual["bills"][0]["state"] == "draft"
                    and actual["payment_count"] == 0, "registered_actual_one_draft_no_payment")
            receipts = env["ap.security.draft.receipt"].search([("company_id", "=", binding["company_id"])])
            require(len(receipts) == 1 and receipts.move_id.id == actual["bills"][0]["id"], "registered_receipt_actual_move")
            resolved = resolve_draft_workflow(
                env, registration_id=binding["registration_id"], expected_company_id=binding["company_id"],
                expected_executor_user_id=binding["executor_user_id"], expected_scenario_id=binding["scenario_id"],
                document=document, provenance=WorkflowProvenance(**binding["provenance"]),
            )
            require(envelope["registration"] == {"registration_id": resolved.registration_id,
                    "registration_sha256": resolved.registration_sha256}, "registered_persisted_binding_matches_result")
            event = env["ap.security.audit.event"].browse(result["audit_event"]["event_id"]).exists()
            payload = audit_kernel._verify_event(event)
            checked_command = validate_command(binding["command"])
            require(payload["context"] == asdict(audit)
                    and payload["subject"] == {
                        "company_id": binding["company_id"], "executor_user_id": binding["executor_user_id"],
                        "scenario_id": binding["scenario_id"], "document_sha256": binding["document_sha256"],
                        "executor_mode": "CREATE_DRAFT", "policy_version": resolved.workflow.policy_version,
                        "workflow_sha256": audit_kernel._workflow_hash(resolved.workflow),
                        "command_sha256": canonical_command_sha256(binding["command"]),
                        "action_sha256": checked_command.action_hash,
                        "idempotency_key": binding["command"]["idempotency_key"],
                    }
                    and payload["outcome"]["status"] == expected_status, "registered_actual_audit_event")
            require(event.receipt_id == receipts
                    and receipts.company_id.id == binding["company_id"]
                    and receipts.executor_user_id.id == binding["executor_user_id"]
                    and receipts.po_id.id == resolved.workflow.purchase_order_id
                    and receipts.vendor_id.id == resolved.workflow.vendor_id
                    and receipts.purchase_line_ids.ids == list(resolved.workflow.purchase_line_ids)
                    and receipts.executor_mode == "CREATE_DRAFT"
                    and receipts.document_sha256 == binding["document_sha256"]
                    and receipts.command_sha256 == payload["subject"]["command_sha256"]
                    and receipts.action_sha256 == checked_command.action_hash
                    and receipts.idempotency_key == binding["command"]["idempotency_key"]
                    and receipts.receipt_payload == result["receipt"] == payload["receipt"],
                    "registered_fresh_receipt_full_binding")
            events = env["ap.security.audit.event"].search([("company_id", "=", binding["company_id"])])
            successful = events.filtered(lambda candidate: candidate.status == "CREATED")
            replayed = events.filtered(lambda candidate: candidate.status == "REPLAY")
            require(len(events) == attempt and len(successful) == 1 and len(replayed) == attempt - 1
                    and successful.receipt_id == receipts and successful.success_receipt_id == receipts,
                    "registered_exact_one_success_event_and_expected_replay_count")
            if attempt == 1:
                require(event == successful and not event.original_event_id, "registered_initial_success_event")
                first_event_id = event.id
            else:
                require(event == replayed and event.original_event_id.id == first_event_id == successful.id
                        and audit_kernel._verify_event(successful)["context"]["attempt_id"] == f"{1:032x}",
                        "registered_replay_links_original_persisted_event")
            attachments = env["ir.attachment"].search([
                ("res_model", "=", "account.move"), ("res_id", "=", actual["bills"][0]["id"])])
            require(len(attachments) == 1 and hashlib.sha256(attachments.raw).hexdigest() == binding["document_sha256"],
                    "registered_actual_single_source_attachment")
            require(event.attachment_id == attachments, "registered_event_actual_source_attachment")
            if first is None:
                first = actual
            else:
                require(actual == first, "registered_replay_no_second_financial_effect")
        cases.append({"name": "registered_create_commit" if attempt == 1 else "registered_replay_commit",
            "status": "PASS", "checks": {"actual_receipt_move_event_attachment_verified": True,
            "normal_registry_commit_then_fresh_cursor": True, "workflow_resolved_from_registration": True,
            "structural_command_not_gateway_policy_claim": True}})
    rollback = binding["rollback"]
    rollback_document = SourceDocument(raw=(artifacts / "c1-rollback.pdf").read_bytes(), mimetype="application/pdf")
    rollback_audit = TrustedAuditContext(run_id="TCC-RUNNER-NATIVE", attempt_id=f"{3:032x}", **rollback["provenance"])
    with registry.cursor() as cr:
        require(type(cr).__name__ == "Cursor", "rollback_real_outer_cursor")
        env = api.Environment(cr, SUPERUSER_ID, draft_kernel._context(rollback["company_id"]), su=True)
        before_rollback = projection(env, rollback["company_id"])
        before_counts = {model: env[model].search_count([("company_id", "=", rollback["company_id"])])
                         for model in ("ap.security.draft.receipt", "ap.security.audit.event", "ir.attachment")}
        transient = create_registered_draft_audited(
            env, registration_id=rollback["registration_id"], expected_company_id=rollback["company_id"],
            expected_executor_user_id=rollback["executor_user_id"], expected_scenario_id=rollback["scenario_id"],
            command=copy.deepcopy(rollback["command"]), audit=rollback_audit, document=rollback_document,
        )
        require(transient["result"]["status"] == "CREATED" and transient["caller_transaction_pending"] is True,
                "rollback_after_actual_registered_create")
        # Not a mocked/TestCursor commit: roll back the caller transaction, then
        # commit the empty parent and read again from a genuinely new cursor.
        cr.rollback()
        cr.commit()
    with registry.cursor() as cr:
        require(type(cr).__name__ == "Cursor", "rollback_fresh_native_observer")
        env = api.Environment(cr, SUPERUSER_ID, draft_kernel._context(rollback["company_id"]), su=True)
        require(projection(env, rollback["company_id"]) == before_rollback, "rollback_no_financial_delta")
        require({model: env[model].search_count([("company_id", "=", rollback["company_id"])])
                 for model in before_counts} == before_counts, "rollback_no_receipt_audit_or_attachment_delta")
        require(env["purchase.order.line"].browse(rollback["purchase_line_id"]).qty_to_invoice == 1.0,
                "rollback_purchase_quantity_restored")
    cases.append({"name": "registered_outer_rollback", "status": "PASS", "checks": {
        "actual_registered_create_before_rollback": True, "outer_native_rollback_then_commit": True,
        "fresh_cursor_no_financial_receipt_event_attachment_delta": True,
        "purchase_quantity_restored": True}})
    # Unlike the preceding outer rollback, the parent transaction commits after
    # a real post-effect fault. Only the wrapper's own savepoint can remove it.
    fault_seen, transient_ids = [], {}
    fault_audit = TrustedAuditContext(run_id="TCC-RUNNER-NATIVE", attempt_id=f"{4:032x}",
                                     **rollback["provenance"])
    with registry.cursor() as cr:
        require(type(cr).__name__ == "Cursor" and not odoo.tools.config["test_enable"],
                "fault_real_outer_cursor")
        env = api.Environment(cr, SUPERUSER_ID, draft_kernel._context(rollback["company_id"]), su=True)
        before_fault = _registered_rollback_projection(env, rollback)

        def fail_after_result(result):
            require(result["status"] == "CREATED" and result["effect_applied"] is True
                    and result["audit_complete"] is True, "fault_after_actual_audited_created_result")
            receipt = env["ap.security.draft.receipt"].browse(result["receipt"]["receipt_id"]).exists()
            move = env["account.move"].browse(result["receipt"]["move_id"]).exists()
            event = env["ap.security.audit.event"].browse(result["audit_event"]["event_id"]).exists()
            payload = audit_kernel._verify_event(event)
            require(len(receipt) == len(move) == len(event) == 1 and move.state == "draft"
                    and receipt.move_id == move and event.receipt_id == receipt
                    and event.attachment_id.raw == rollback_document.raw
                    and payload["context"] == asdict(fault_audit)
                    and payload["outcome"]["status"] == "CREATED",
                    "fault_observed_real_move_receipt_event_and_document")
            transient_ids.update({"account.move": move.id, "ap.security.draft.receipt": receipt.id,
                                  "ap.security.audit.event": event.id, "ir.attachment": event.attachment_id.id})
            fault_seen.append(True)
            raise RuntimeError("SYNTHETIC-AFTER-REGISTERED-RESULT-FAULT")

        with patch.object(registered_execution, "_after_registered_draft", side_effect=fail_after_result):
            try:
                create_registered_draft_audited(
                    env, registration_id=rollback["registration_id"], expected_company_id=rollback["company_id"],
                    expected_executor_user_id=rollback["executor_user_id"], expected_scenario_id=rollback["scenario_id"],
                    command=copy.deepcopy(rollback["command"]), audit=fault_audit, document=rollback_document,
                )
            except RegisteredExecutionError as error:
                require(error.code == "EXECUTION_UNAVAILABLE", "fault_finite_registered_execution_error")
            else:
                require(False, "fault_expected_registered_execution_error")
        require(fault_seen == [True], "fault_seam_observed_exactly_once")
        cr.commit()
    with registry.cursor() as cr:
        require(type(cr).__name__ == "Cursor", "fault_fresh_native_observer")
        env = api.Environment(cr, SUPERUSER_ID, draft_kernel._context(rollback["company_id"]), su=True)
        require(_registered_rollback_projection(env, rollback) == before_fault,
                "fault_parent_commit_preserves_financial_ledgers_attachments_and_purchase_quantity")
        require(all(not env[model].browse(record_id).exists() for model, record_id in transient_ids.items()),
                "fault_parent_commit_no_transient_effect_survives")
    cases.append({"name": "registered_fault_after_result_parent_commit", "status": "PASS", "checks": {
        "real_created_move_receipt_event_attachment_before_fault": True,
        "finite_execution_unavailable_error": True, "parent_native_commit_without_outer_rollback": True,
        "fresh_cursor_existing_financial_ledgers_attachments_and_purchase_quantity_preserved": True,
        "fresh_cursor_transient_effect_ids_absent": True}})
    write_json(artifacts / "c1-registered.json", {
        "schema_version": "runner-native-registered-create/v1", "status": "PASS", "test_count": len(cases),
        "cases": cases, "normal_registry": True, "test_cursor_used": False,
        "gateway_policy_integrated": False, "public_executor_opened": False,
        "scientific_run": False, "provenance_declared_not_attested": True,
    })


def _registered_rollback_projection(env, binding):
    """Technical fault comparison, not the complete scientific/reset snapshot."""
    company_domain = [("company_id", "=", binding["company_id"])]
    records = {
        "ap.security.draft.receipt": ["company_id", "executor_user_id", "executor_mode", "idempotency_key",
            "document_sha256", "command_sha256", "action_sha256", "po_id", "vendor_id", "purchase_line_ids",
            "move_id", "receipt_payload"],
        "ap.security.audit.event": ["company_id", "executor_user_id", "executor_mode", "run_id", "attempt_id",
            "status", "receipt_id", "success_receipt_id", "original_event_id", "attachment_id",
            "event_sha256", "event_payload"],
        "ap.security.po.guard": ["company_id", "po_id", "revision"],
        "ap.security.vendor.guard": ["company_id", "vendor_id", "revision"],
    }
    observed = {model: env[model].search(company_domain, order="id").read(fields)
                for model, fields in records.items()}
    observed["financial"] = projection(env, binding["company_id"])
    observed["attachments"] = [{"id": item.id, "name": item.name, "mimetype": item.mimetype,
        "size": item.file_size, "res_model": item.res_model, "res_id": item.res_id,
        "raw_sha256": hashlib.sha256(item.raw or b"").hexdigest()}
        for item in env["ir.attachment"].search(company_domain, order="id")]
    line = env["purchase.order.line"].browse(binding["purchase_line_id"])
    observed["purchase"] = {"line_id": line.id, "quantity_to_invoice": line.qty_to_invoice,
        "quantity_invoiced": line.qty_invoiced, "invoice_status": line.order_id.invoice_status}
    return observed


def run(args):
    odoo.tools.config.parse_config(["-c", args.config, "-d", args.database, "--no-http"])
    require(not odoo.tools.config["test_enable"], "normal_registry_configuration")
    registry = Registry(args.database)
    if args.mode == "prepare":
        prepare(registry, args)
    elif args.mode == "observe":
        observe(registry, args)
    else:
        c1_registered(registry, args)
