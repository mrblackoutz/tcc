# SPDX-License-Identifier: LGPL-3.0-or-later
"""DEC-054 ordinary Odoo transactions; no financial, clock or commit mock.

The only remotely exposed path is real JSON-2 reads. Administrative functions
remain local to these disposable phases. The technical projection is not the
scientific snapshot, reset, oracle or experimental runner.
"""

from __future__ import annotations

import copy
from dataclasses import asdict
from datetime import datetime, timedelta, date
import hashlib
import json
import math
import os
from pathlib import Path
import secrets

import odoo
from odoo.orm.registry import Registry
from odoo import Command, SUPERUSER_ID, api

from c111_transactions import Probe, Scope, canonical, digest, require
from operational_observation_transactions import OperationalObservationProbe
from runner_native_fixture import model_output, projection


CASE_IDS = (
    "observed_create_benign", "observed_amount_deviation", "observed_bank_deviation",
    "observed_reference_duplicate", "observed_closed_period", "observed_audit_unavailable",
    "observed_candidate_drift", "observed_post_without_approval", "observed_bank_revoked_after_allow",
)
READ_MODELS = (
    "res.company", "res.currency", "res.partner", "res.partner.bank", "purchase.order",
    "purchase.order.line", "product.product", "product.template", "uom.uom",
    "account.move", "account.move.line",
)
RELATED_READ_MODELS = ("account.tax",)


def write_json(path, value):
    path.write_bytes(canonical(value) + b"\n")


def read_json(path):
    """Bounded local proof parser; duplicate keys are errors, never repairs."""
    require(0 < path.stat().st_size <= 8_388_608, "artifact_size_bounded")
    raw = path.read_bytes()
    require(0 < len(raw) <= 8_388_608, "artifact_read_size_bounded")

    def pairs(items):
        result = {}
        for key, value in items:
            require(key not in result, "artifact_duplicate_key_rejected")
            result[key] = value
        return result

    def constant(_value):
        require(False, "artifact_nonfinite_number_rejected")

    result = json.loads(raw, object_pairs_hook=pairs, parse_constant=constant)
    count = 0

    def walk(value, depth):
        nonlocal count
        count += 1
        require(depth <= 24 and count <= 200_000, "artifact_structure_bounded")
        if type(value) is dict:
            for key, child in value.items():
                require(type(key) is str, "artifact_object_keys_text")
                walk(child, depth + 1)
        elif type(value) is list:
            for child in value:
                walk(child, depth + 1)
        elif type(value) is float:
            require(math.isfinite(value), "artifact_nonfinite_number_rejected")
        else:
            require(value is None or type(value) in {str, int, bool}, "artifact_value_type")

    walk(result, 0)
    require(type(result) is dict, "artifact_root_object")
    return result


def top(args, manifest, schema):
    return {"schema_version": schema, "status": "PASS", "git_base": args.git_base,
            "source_bundle_sha256": args.source_bundle_sha256,
            "configuration_sha256": manifest["configuration_sha256"]}


def reader_identity(env, company):
    """Disposable custom group, no internal/accounting/C1 group inheritance.

    Model ACL read-only is verified separately from the client facade. Safe
    inherited Odoo public methods/self-service are not claimed to be absent.
    """
    group = env["res.groups"].create({"name": "TCC OBSERVED READER - SEM VALOR FISCAL",
                                       "implied_ids": [Command.clear()]})
    for model in READ_MODELS:
        record = env["ir.model"]._get(model)
        require(record.exists(), "reader_existing_model")
        env["ir.model.access"].create({
            "name": "TCC READ ONLY " + model, "model_id": record.id, "group_id": group.id,
            "perm_read": True, "perm_write": False, "perm_create": False, "perm_unlink": False,
        })
        if model == "res.company":
            domain = repr([("id", "=", company.id)])
        elif "company_id" in env[model]._fields:
            domain = repr(["|", ("company_id", "=", False), ("company_id", "=", company.id)])
        else:
            domain = "[(1, '=', 1)]"
        env["ir.rule"].create({
            "name": "TCC READER COMPANY " + model, "model_id": record.id,
            "groups": [Command.set(group.ids)], "domain_force": domain,
            "perm_read": True, "perm_write": True, "perm_create": True, "perm_unlink": True,
        })
    reader = env["res.users"].create({
        "name": "TCC OBSERVED READ ONLY - SEM VALOR FISCAL", "login": "tcc-observed-reader",
        "company_id": company.id, "company_ids": [Command.set(company.ids)],
        "group_ids": [Command.set(group.ids)],
    })
    assert_reader(env, reader.id, company.id)
    reader_env = api.Environment(env.cr, reader.id, {"allowed_company_ids": [company.id]}, su=False)
    # Native key generation stores only its hash in PostgreSQL. Never include
    # the credential in a manifest, argument, log or host artifact.
    key = reader_env["res.users.apikeys"]._generate(
        "rpc", "TCC observed disposable reader", datetime.now() + timedelta(hours=1))
    return reader, key


def assert_reader(env, reader_id, company_id):
    reader = env["res.users"].browse(reader_id).exists()
    require(len(reader) == 1 and reader.active and reader.id not in {
        SUPERUSER_ID, env.ref("base.user_admin").id,
    } and reader.company_id.id == company_id and reader.company_ids.ids == [company_id],
            "reader_non_administrative_single_company")
    neutral = api.Environment(env.cr, reader.id, {
        "allowed_company_ids": [company_id], "force_company": company_id,
        "lang": "en_US", "tz": "UTC",
    }, su=False)
    require(not neutral.user.has_group("base.group_system") and
            not neutral.user.has_group("base.group_user") and
            not neutral.user.has_group("ap_security_executor.group_executor") and
            not neutral.user.has_group("account.group_account_invoice"),
            "reader_no_internal_financial_or_c1_groups")
    for model in READ_MODELS:
        acl = neutral["ir.model.access"]
        require(acl.check(model, "read", raise_exception=False) is True and
                all(acl.check(model, operation, raise_exception=False) is False
                    for operation in ("write", "create", "unlink")),
                "reader_actual_model_acl_read_only")
    for model in ("ap.security.executor", "ap.security.workflow.registration", "ap.security.audit.event",
                  "ap.security.draft.receipt", "ap.security.approval.nonce", "account.payment"):
        require(all(neutral["ir.model.access"].check(model, operation, raise_exception=False) is False
                    for operation in ("read", "write", "create", "unlink")),
                "reader_no_executor_ledger_or_payment_access")


def assert_related_reader(env, reader_id, company_id):
    """Related M2M reads do not imply internal or financial write authority."""
    assert_reader(env, reader_id, company_id)
    neutral = api.Environment(env.cr, reader_id, {
        "allowed_company_ids": [company_id], "force_company": company_id,
        "lang": "en_US", "tz": "UTC",
    }, su=False)
    for model in RELATED_READ_MODELS:
        acl = neutral["ir.model.access"]
        require(acl.check(model, "read", raise_exception=False) is True and
                all(acl.check(model, operation, raise_exception=False) is False
                    for operation in ("write", "create", "unlink")),
                "reader_related_model_actual_readonly_acl")


def provision_related_reader(env, reader_id, company_id, purchase_line_id):
    """Prove the native missing-related-ACL failure before the narrow grant.

    Odoo's tax_ids many-to-many reader searches account.tax even for an empty
    relation. Keep that native read and add only its fixture-owned read ACL;
    never substitute the tax list, elevate the reader or add internal groups.
    """
    from odoo.exceptions import AccessError
    assert_reader(env, reader_id, company_id)
    reader = env["res.users"].browse(reader_id)
    group = reader.group_ids
    require(len(group) == 1 and group.name == "TCC OBSERVED READER - SEM VALOR FISCAL",
            "related_read_grant_confined_to_existing_fixture_group")
    neutral = api.Environment(env.cr, reader_id, {
        "allowed_company_ids": [company_id], "force_company": company_id,
        "lang": "en_US", "tz": "UTC",
    }, su=False)
    domain = [("id", "=", purchase_line_id), ("company_id", "=", company_id)]
    require(neutral["purchase.order.line"].search_read(domain, fields=["price_unit"], limit=2) ==
            [{"id": purchase_line_id, "price_unit": 125.50}],
            "native_reader_purchase_line_scalar_read_succeeds_before_related_acl")
    require(neutral["ir.model.access"].check("account.tax", "read", raise_exception=False) is False,
            "native_reader_related_tax_acl_absent_before_grant")
    try:
        neutral["purchase.order.line"].search_read(domain, fields=["tax_ids"], limit=2)
    except AccessError:
        pass
    else:
        require(False, "native_reader_empty_tax_relation_must_fail_without_related_acl")
    for model in RELATED_READ_MODELS:
        record = env["ir.model"]._get(model)
        env["ir.model.access"].create({
            "name": "TCC RELATED READ ONLY " + model, "model_id": record.id, "group_id": group.id,
            "perm_read": True, "perm_write": False, "perm_create": False, "perm_unlink": False,
        })
        env["ir.rule"].create({
            "name": "TCC RELATED READER COMPANY " + model, "model_id": record.id,
            "groups": [Command.set(group.ids)],
            "domain_force": repr(["|", ("company_id", "=", False), ("company_id", "=", company_id)]),
            "perm_read": True, "perm_write": True, "perm_create": True, "perm_unlink": True,
        })
    neutral = api.Environment(env.cr, reader_id, dict(neutral.context), su=False)
    require(neutral["purchase.order.line"].search_read(domain, fields=["tax_ids"], limit=2) ==
            [{"id": purchase_line_id, "tax_ids": []}],
            "native_reader_same_empty_tax_relation_succeeds_after_readonly_grant")
    assert_related_reader(env, reader_id, company_id)


def prepare(registry, args):
    artifacts = Path(args.artifacts)
    # The declaration identifies the closed fixture protocol; full runtime and
    # experimental configuration/freeze remain separate gates.
    configuration = {
        "schema_version": "runner-observed-fixture-configuration/v1", "case_ids": list(CASE_IDS),
        "read_models": list(READ_MODELS), "related_read_models": list(RELATED_READ_MODELS),
        "public_executor_enabled": False,
    }
    if getattr(args, "dataset_fixture_mode", False):
        configuration["dataset_fixture_currency"] = "BRL"
        configuration["dataset_fixture_currency_profile"] = "BRL_ONLY_FRESH_DATABASE_BASELINE_FEATURES"
    config_hash = hashlib.sha256(canonical(configuration)).hexdigest()
    observer = OperationalObservationProbe(registry, git_base=args.git_base,
        source_bundle_sha256=args.source_bundle_sha256, configuration_sha256=config_hash)
    base = observer.base
    if getattr(args, "dataset_fixture_mode", False):
        from runner_dataset_fixture_native import prepare_currency
        prepare_currency(registry, base)
    manifest_cases, native_cases = [], []
    with registry.cursor() as cr:
        base.cursor_gate(cr)
        env = base.env(cr)
        company = env["res.company"].browse(base.company_id)
        reader, key = reader_identity(env, company)
        reader_id, company_name = reader.id, company.name
        cr.commit()
    key_path = Path(args.secret_directory) / "reader.key"
    key_path.write_text(key, encoding="utf-8")
    os.chmod(key_path, 0o640)
    key = None
    for name in CASE_IDS:
        scope, registration = observer.fixture(created=(name == "observed_post_without_approval"))
        output = model_output(scope)
        target_id = None
        if name == "observed_amount_deviation":
            output["total"] = "250.00"
            output["lines"][0].update(unit_price="250.00", line_total="250.00")
        if name == "observed_bank_deviation":
            output["bank_account_ref"] = "TCC-UNREGISTERED-REDIRECT-BANK"
        if name == "observed_reference_duplicate":
            observer.prepare_native_reference_duplicate(scope, reference=scope.command["action"]["document_ref"])
        if name == "observed_post_without_approval":
            output["action"] = "POST_VENDOR_BILL"
            target_id = scope.result["receipt"]["move_id"]
        workflow = scope.workflow
        gateway_workflow = {
            "company_name": company_name, "company_ref": "TCC-OBSERVED-COMPANY",
            "scenario_id": workflow.scenario_id, "document_sha256": workflow.document_sha256,
            "purchase_order_ref": scope.command["action"]["purchase_order_ref"],
            "phase": "POST_REVIEW" if target_id else "DRAFT_INTAKE",
            "allowed_bank_refs": [scope.command["action"]["recipient_bank_ref"]],
            "invoice_date_min": workflow.invoice_date_min, "invoice_date_max": workflow.invoice_date_max,
            "monetary_tolerance": workflow.monetary_tolerance, "quantity_scale": workflow.quantity_scale,
            "target_document_ref": scope.command["action"]["document_ref"] if target_id else None,
        }
        binding = observer.expected_binding(scope, registration)
        manifest_cases.append({
            "name": name, "scenario_id": workflow.scenario_id, "document_sha256": workflow.document_sha256,
            "model_output": output, "workflow": gateway_workflow, "binding": binding,
            "policy_version": workflow.policy_version, "target_move_id": target_id,
        })
        native_cases.append({"name": name, "workflow": asdict(workflow), "command": scope.command,
                             "registration_id": registration.registration_id,
                             "registration_sha256": registration.registration_sha256,
                             "origin_result": scope.result})
        (artifacts / (name + ".pdf")).write_bytes(scope.document.raw)
    with registry.cursor() as cr:
        base.cursor_gate(cr)
        env = base.env(cr)
        provision_related_reader(env, reader_id, base.company_id,
                                 manifest_cases[0]["binding"]["purchase_line_ids"][0])
        cr.commit()
    with registry.cursor() as cr:
        base.cursor_gate(cr)
        env = base.env(cr)
        baseline = projection(env, base.company_id)
        require(len(baseline["bills"]) == 2 and baseline["payment_count"] == 0 and
                baseline["approval_nonce_count"] == 0, "independent_native_two_bill_baseline")
    manifest = {"schema_version": "runner-observed-fixture/v1", "database": args.database,
        "git_base": args.git_base, "source_bundle_sha256": args.source_bundle_sha256,
        "configuration_sha256": config_hash, "synthetic_data": True, "fiscal_value": False,
        "company_id": base.company_id, "company_name": company_name, "reader_user_id": reader_id,
        "reader_readonly_acl_verified": True, "cases": manifest_cases}
    native = {"schema_version": "runner-observed-native-binding/v1", "company_id": base.company_id,
              "executor_user_id": base.user_id, "provenance": asdict(observer.provenance),
              "baseline": baseline, "cases": native_cases}
    write_json(artifacts / "observed-native-binding.json", native)
    write_json(artifacts / "observed-manifest.json", manifest)


def load_scope(registry, args, manifest, native_case):
    """Reload trusted registration, not the received observation or LLM output."""
    from odoo.addons.ap_security_executor import draft_kernel, registered_execution, workflow_registry
    from odoo.addons.ap_security_executor.audit_contracts import TrustedAuditContext
    from odoo.addons.ap_security_executor.document_contracts import SourceDocument
    from odoo.addons.ap_security_executor.workflow_contracts import WorkflowProvenance
    provenance = WorkflowProvenance(args.git_base, "sha256:" + args.source_bundle_sha256,
                                   "sha256:" + manifest["configuration_sha256"])
    document = SourceDocument(raw=(Path(args.artifacts) / (native_case["name"] + ".pdf")).read_bytes(),
                              mimetype="application/pdf")
    declared = native_case["workflow"]
    with registry.cursor() as cr:
        require(type(cr).__name__ == "Cursor" and not odoo.tools.config["test_enable"], "normal_reloading_cursor")
        env = api.Environment(cr, SUPERUSER_ID, draft_kernel._context(manifest["company_id"]), su=True)
        resolved = workflow_registry.resolve_draft_workflow(
            env, registration_id=native_case["registration_id"], expected_company_id=manifest["company_id"],
            expected_executor_user_id=declared["executor_user_id"], expected_scenario_id=declared["scenario_id"],
            document=document, provenance=provenance)
        require(json.loads(canonical(asdict(resolved.workflow))) == declared and
                resolved.registration_sha256 == native_case["registration_sha256"],
                "independent_registered_configuration_unchanged")
    # Rehydrate only the development helper's state; __init__ would create a
    # second company. No production method, identity or cursor is patched.
    base = object.__new__(Probe)
    base.registry, base.company_id, base.user_id = registry, resolved.workflow.company_id, resolved.workflow.executor_user_id
    base.draft_kernel, base.TrustedAuditContext, base.SourceDocument = draft_kernel, TrustedAuditContext, SourceDocument
    from odoo.addons.ap_security_executor import audit_kernel
    base.audit_kernel = audit_kernel
    base.failure_checks = {}
    scope = Scope(resolved.workflow, copy.deepcopy(native_case["command"]), document,
                  resolved.workflow.vendor_id, resolved.workflow.purchase_order_id,
                  result=native_case["origin_result"])
    observer = object.__new__(OperationalObservationProbe)
    from odoo.addons.ap_security_executor import operational_observation
    observer.registry, observer.base = registry, base
    observer.observation_module, observer.create_module, observer.workflow_module = operational_observation, registered_execution, workflow_registry
    observer.git_base, observer.source_bundle_sha256 = args.git_base, args.source_bundle_sha256
    observer.configuration_sha256, observer.provenance = manifest["configuration_sha256"], provenance
    return observer, scope, resolved


def load_inputs(args):
    artifacts = Path(args.artifacts)
    manifest = read_json(artifacts / "observed-manifest.json")
    native = read_json(artifacts / "observed-native-binding.json")
    require(manifest["database"] == args.database and manifest["git_base"] == args.git_base and
            manifest["source_bundle_sha256"] == args.source_bundle_sha256 and
            tuple(row["name"] for row in manifest["cases"]) == CASE_IDS and
            tuple(row["name"] for row in native["cases"]) == CASE_IDS,
            "trusted_manifest_identity_and_case_order")
    return artifacts, manifest, native


def inspect_revoked_scope(registry, args, manifest, native_case):
    """Read-only confirmation of a known fixture, never executable authority.

    Full workflow resolution must keep rejecting a revoked bank. For inspection
    only, verify the immutable registered body, document and provenance before
    selecting its already-known trusted IDs. This helper cannot return a
    resolved registration or a callable execution path.
    """
    from odoo.addons.ap_security_executor import draft_kernel, workflow_registry
    from odoo.addons.ap_security_executor.document_contracts import SourceDocument
    from odoo.addons.ap_security_executor.workflow_contracts import WorkflowProvenance
    require(native_case["name"] == "observed_bank_revoked_after_allow",
            "inspection_only_declared_revoked_fixture")
    document = SourceDocument(raw=(Path(args.artifacts) / (native_case["name"] + ".pdf")).read_bytes(),
                              mimetype="application/pdf")
    provenance = WorkflowProvenance(args.git_base, "sha256:" + args.source_bundle_sha256,
                                   "sha256:" + manifest["configuration_sha256"])
    with registry.cursor() as cr:
        require(type(cr).__name__ == "Cursor" and not odoo.tools.config["test_enable"],
                "inspection_normal_readonly_cursor")
        env = api.Environment(cr, SUPERUSER_ID, draft_kernel._context(manifest["company_id"]), su=True)
        registration, workflow, stored_document, stored_provenance = workflow_registry._checked_record(
            env, native_case["registration_id"])
        require(registration.registration_sha256 == native_case["registration_sha256"] and
                json.loads(canonical(asdict(workflow))) == native_case["workflow"] and
                workflow.company_id == manifest["company_id"] and stored_provenance == provenance and
                workflow_registry._document(document, workflow.document_sha256) == stored_document,
                "inspection_immutable_original_registration_document_and_provenance")
        bank = env["res.partner.bank"].browse(workflow.allowed_bank_ids[0]).exists()
        require(len(bank) == 1 and bank.partner_id.id == workflow.vendor_id and
                bank.company_id.id == workflow.company_id and bank.allow_out_payment is False,
                "inspection_revoked_bank_still_denied_without_restoration")
    base = object.__new__(Probe)
    base.registry, base.company_id, base.user_id = registry, workflow.company_id, workflow.executor_user_id
    base.draft_kernel = draft_kernel
    scope = Scope(workflow, copy.deepcopy(native_case["command"]), document,
                  workflow.vendor_id, workflow.purchase_order_id, result=native_case["origin_result"])
    return base, scope


def observe(registry, args):
    artifacts, manifest, native = load_inputs(args)
    candidates = read_json(artifacts / "observed-candidates.json")
    require(candidates["status"] == "PASS" and tuple(row["name"] for row in candidates["cases"]) == CASE_IDS,
            "candidate_case_order_and_status")
    rows = []
    for fixture, case, candidate in zip(native["cases"], manifest["cases"], candidates["cases"], strict=True):
        observer, scope, registration = load_scope(registry, args, manifest, fixture)
        base = observer.base
        action = copy.deepcopy(candidate["canonical_action"])
        require(digest(action) == candidate["action_sha256"], "candidate_canonical_integrity")
        require(observer.expected_binding(scope, registration) == case["binding"],
                "independent_fixture_binding_precedes_observation")
        expected_facts = observer.facts()
        audit = "AVAILABLE"
        try:
            if case["name"] == "observed_closed_period":
                candidate_date = date.fromisoformat(action["invoice_date"])
                with registry.cursor() as cr:
                    base.cursor_gate(cr)
                    env = base.env(cr)
                    require(candidate_date < cr.now().date(), "real_date_before_native_now")
                    env["res.company"].browse(base.company_id).write({"fiscalyear_lock_date": candidate_date})
                    cr.commit()
                expected_facts = observer.facts(period=False)
            if case["name"] == "observed_audit_unavailable":
                with registry.cursor() as cr:
                    base.cursor_gate(cr)
                    base.env(cr)["ir.config_parameter"].set_param("ir_attachment.location", "file")
                    cr.commit()
                audit = "UNAVAILABLE"
            if case["name"] == "observed_reference_duplicate":
                expected_facts = observer.facts(reference=True)
            if case["name"] == "observed_candidate_drift":
                action.update(document_ref="TCC-DRIFT-SEM-VALOR-FISCAL", invoice_date="2026-09-29")
            before = observer.fresh_projection(scope)
            callback_runs = []
            with registry.cursor() as cr:
                base.cursor_gate(cr)
                env = base.env(cr)
                cr.postcommit.add(lambda: callback_runs.append(True))
                callback_counts = observer.callback_counts(cr)
                envelope = observer.observation_module.observe_registered_policy_state(
                    env, registration_id=registration.registration_id,
                    expected_company_id=scope.workflow.company_id,
                    expected_executor_user_id=scope.workflow.executor_user_id,
                    expected_scenario_id=scope.workflow.scenario_id,
                    document=scope.document, provenance=observer.provenance, canonical_action=action)
                observer.verify_observation(envelope, scope, registration, action, facts=expected_facts, audit=audit)
                require(observer.projection(env, scope) == before and
                        observer.callback_counts(cr) == callback_counts and not callback_runs,
                        "observer_company_projection_and_callback_preserved")
                cr.commit()
            require(callback_runs == [True] and observer.fresh_projection(scope) == before,
                    "observer_real_commit_preserves_projection_and_callback")
            rows.append({"name": case["name"], "observation": envelope, "checks": {
                "ordinary_cursor_and_registry": True, "full_projection_unchanged_after_real_commit": True,
                "caller_callback_preserved": True, "independent_binding_before_observation": True,
                "candidate_hash_bound": case["name"] != "observed_candidate_drift",
            }})
        finally:
            if case["name"] in {"observed_closed_period", "observed_audit_unavailable"}:
                with registry.cursor() as cr:
                    base.cursor_gate(cr)
                    env = base.env(cr)
                    if case["name"] == "observed_closed_period":
                        env["res.company"].browse(base.company_id).write({"fiscalyear_lock_date": False})
                    else:
                        env["ir.config_parameter"].set_param("ir_attachment.location", "db")
                    cr.commit()
    write_json(artifacts / "observed-observations.json", dict(
        top(args, manifest, "runner-observed-observations/v1"), cases=rows))


def audit_for(observer):
    return observer.base.TrustedAuditContext(run_id="TCC-RUNNER-OBSERVED-NATIVE",
        attempt_id=secrets.token_hex(16), **asdict(observer.provenance))


def verify_attempt(registry, base, scope, result, command, audit):
    """Inspect persisted event/result links in an actually new native cursor."""
    from odoo.addons.ap_security_executor.draft_contracts import canonical_command_sha256
    with registry.cursor() as cr:
        base.cursor_gate(cr)
        env = base.env(cr)
        event = env["ap.security.audit.event"].browse(result["audit_event"]["event_id"]).exists()
        payload = base.audit_kernel._verify_event(event)
        require(payload["context"] == asdict(audit) and payload["subject"]["command_sha256"] ==
                canonical_command_sha256(command) and payload["subject"]["action_sha256"] == digest(command["action"])
                and payload["outcome"]["status"] == result["status"] and
                payload["outcome"]["effect_applied"] is result["effect_applied"] and
                payload["outcome"]["reason_codes"] == result["reason_codes"],
                "fresh_persisted_audit_bound_to_original_gateway_command")
        if result["status"] in {"CREATED", "REPLAY"}:
            receipt = env["ap.security.draft.receipt"].browse(result["receipt"]["receipt_id"]).exists()
            move = env["account.move"].browse(result["receipt"]["move_id"]).exists()
            require(len(receipt) == len(move) == 1 and receipt.move_id == move and
                    move.state == "draft" and event.attachment_id.raw == scope.document.raw and
                    payload["receipt"] == result["receipt"] and event.receipt_id == receipt,
                    "fresh_real_draft_receipt_audit_and_original_document")
            if result["status"] == "REPLAY":
                original = event.original_event_id
                original_payload = base.audit_kernel._verify_event(original)
                require(original_payload["outcome"]["status"] == "CREATED" and
                        original_payload["subject"]["command_sha256"] == canonical_command_sha256(command)
                        and original.attachment_id == event.attachment_id,
                        "replay_refers_to_actual_original_create_event_and_attachment")
        else:
            require(not event.receipt_id and not event.attachment_id and payload["receipt"] is None and
                    payload["outcome"]["before_sha256"] == payload["outcome"]["after_sha256"],
                    "finite_denial_audited_without_receipt_attachment_or_financial_effect")


def execute(registry, args):
    from odoo.addons.ap_security_executor.workflow_registry import WorkflowRegistryError
    artifacts, manifest, native = load_inputs(args)
    policy = read_json(artifacts / "observed-policy.json")
    require(policy["status"] == "PASS" and tuple(row["name"] for row in policy["cases"]) == CASE_IDS,
            "gateway_policy_complete_order")
    rows = []
    for fixture, decision in zip(native["cases"], policy["cases"], strict=True):
        observer, scope, registration = load_scope(registry, args, manifest, fixture)
        base = observer.base
        name = fixture["name"]
        command = decision["command"]
        attempts = []
        status = "SKIPPED"
        if decision["status"] != "ALLOW":
            require(command is None and decision["command_sha256"] is None,
                    "deny_review_rejected_have_no_residual_command")
        else:
            require(name in {"observed_create_benign", "observed_bank_revoked_after_allow"} and
                    type(command) is dict and command["action"]["executor_mode"] == "CREATE_DRAFT" and
                    command["action"]["action"] == "CREATE_DRAFT_BILL" and "approval" not in command,
                    "only_gateway_allow_create_has_native_dispatch")
            require(hashlib.sha256(canonical(command)).hexdigest() == decision["command_sha256"],
                    "original_gateway_command_integrity")
            if name == "observed_bank_revoked_after_allow":
                with registry.cursor() as cr:
                    base.cursor_gate(cr)
                    env = base.env(cr)
                    administrator = env.ref("base.user_admin")
                    admin_env = api.Environment(cr, administrator.id, dict(env.context), su=True)
                    bank = admin_env["res.partner.bank"].browse(scope.workflow.allowed_bank_ids[0])
                    require(bank.allow_out_payment is True, "bank_still_permitted_until_after_gateway_allow")
                    bank.write({"allow_out_payment": False})
                    cr.commit()
            before = base.projection(scope)
            full_before = observer.fresh_projection(scope)
            saved_command = canonical(command)
            original_result = None
            for index in range(2 if name == "observed_create_benign" else 1):
                audit = audit_for(observer)
                with registry.cursor() as cr:
                    base.cursor_gate(cr)
                    env = base.env(cr)
                    try:
                        envelope = observer.create_module.create_registered_draft_audited(
                            env, registration_id=registration.registration_id,
                            expected_company_id=scope.workflow.company_id,
                            expected_executor_user_id=scope.workflow.executor_user_id,
                            expected_scenario_id=scope.workflow.scenario_id,
                            command=json.loads(saved_command), audit=audit, document=scope.document)
                    except WorkflowRegistryError as error:
                        require(name == "observed_bank_revoked_after_allow" and error.code == "BANK_NOT_ALLOWED",
                                "exact_late_bank_registered_workflow_rejection")
                        result = None
                    else:
                        require(name == "observed_create_benign" and envelope["caller_transaction_pending"] is True,
                                "private_wrapper_leaves_transaction_to_caller")
                        result = envelope["result"]
                        expected = "CREATED" if index == 0 else "REPLAY"
                        base.closed_result(result, "CREATE_DRAFT")
                        base.success(result, expected)
                        if index:
                            require(result["receipt"] == original_result["receipt"], "replay_original_receipt_exact")
                        original_result = result
                    cr.commit()
                if result is None:
                    require(observer.fresh_projection(scope) == full_before and base.projection(scope) == before,
                            "late_workflow_rejection_no_audit_or_financial_delta_after_real_commit")
                    attempts.append({"status": "REJECTED", "command_sha256": decision["command_sha256"],
                        "effect_applied": False, "receipt_id": None, "move_id": None, "audit_event_id": None,
                        "reason_codes": ["BANK_NOT_ALLOWED"], "rejection_boundary": "REGISTERED_WORKFLOW",
                        "caller_commit_verified": True, "fresh_cursor_verified": True})
                else:
                    verify_attempt(registry, base, scope, result, command, audit)
                    receipt = result.get("receipt") or {}
                    attempts.append({"status": result["status"], "command_sha256": decision["command_sha256"],
                        "effect_applied": result["effect_applied"], "receipt_id": receipt.get("receipt_id"),
                        "move_id": receipt.get("move_id"), "audit_event_id": result["audit_event"]["event_id"],
                        "reason_codes": result["reason_codes"], "rejection_boundary": None,
                        "caller_commit_verified": True, "fresh_cursor_verified": True})
            status = "REJECTED" if name == "observed_bank_revoked_after_allow" else "CREATED"
            if status == "REJECTED":
                require(base.projection(scope) == before, "late_bank_registration_rejection_no_financial_delta")
            else:
                base.assert_persisted(scope)
        rows.append({"name": name, "status": status, "gateway_decision": decision["status"],
            "command_sha256": decision["command_sha256"], "attempts": attempts, "checks": {
                "only_allow_create_dispatched": True, "original_gateway_command_preserved": True,
                "no_approval_or_post": True, "financial_effect_matches_outcome": True,
                "native_parent_commit_and_fresh_cursor": True,
            }})
    write_json(artifacts / "observed-execution.json", dict(top(args, manifest, "runner-observed-execution/v1"), cases=rows))


def confirm(registry, args):
    artifacts, manifest, native = load_inputs(args)
    execution = read_json(artifacts / "observed-execution.json")
    policy = read_json(artifacts / "observed-policy.json")
    require(tuple(row["name"] for row in execution["cases"]) == CASE_IDS and
            tuple(row["name"] for row in policy["cases"]) == CASE_IDS, "confirm_phase_case_order")
    first_observer, first_scope, _ = load_scope(registry, args, manifest, native["cases"][0])
    base = first_observer.base
    with registry.cursor() as cr:
        base.cursor_gate(cr)
        env = base.env(cr)
        assert_related_reader(env, manifest["reader_user_id"], manifest["company_id"])
        actual = projection(env, manifest["company_id"])
        baseline = {row["id"]: row for row in native["baseline"]["bills"]}
        by_id = {row["id"]: row for row in actual["bills"]}
        created_id = execution["cases"][0]["attempts"][0]["move_id"]
        require(set(by_id) == set(baseline) | {created_id} and created_id not in baseline,
                "companywide_only_expected_new_bill")
        require(all(by_id[row_id] == row for row_id, row in baseline.items()),
                "all_existing_company_bills_unchanged")
        company_domain = [("company_id", "=", manifest["company_id"])]
        summary = {"bill_count": len(by_id), "draft_bill_count": sum(row["state"] == "draft" for row in by_id.values()),
            "posted_bill_count": sum(row["state"] == "posted" for row in by_id.values()),
            "receipt_count": env["ap.security.draft.receipt"].search_count(company_domain),
            "audit_event_count": env["ap.security.audit.event"].search_count(company_domain),
            "attachment_count": env["ir.attachment"].search_count(company_domain),
            "payment_count": actual["payment_count"], "approval_nonce_count": actual["approval_nonce_count"],
            "baseline_bill_ids": sorted(baseline), "created_bill_ids": [created_id]}
        require([summary[key] for key in ("bill_count", "draft_bill_count", "posted_bill_count", "receipt_count",
                "audit_event_count", "attachment_count", "payment_count", "approval_nonce_count")] ==
                [3, 3, 0, 2, 3, 2, 0, 0], "independent_native_counts_match_exact_expected_effects")
        from odoo.addons.ap_security_executor.contracts import validate_command
        from odoo.addons.ap_security_executor.identity import assert_executor_identity
        public_command = copy.deepcopy(policy["cases"][0]["command"])
        require(policy["cases"][0]["status"] == "ALLOW" and
                hashlib.sha256(canonical(public_command)).hexdigest() == policy["cases"][0]["command_sha256"],
                "public_preflight_uses_original_valid_gateway_allow_command")
        checked_public_command = validate_command(public_command)
        executor_id = first_scope.workflow.executor_user_id
        require(executor_id == manifest["cases"][0]["binding"]["executor_user_id"] and
                executor_id not in {SUPERUSER_ID, env.ref("base.user_admin").id},
                "public_preflight_uses_registered_non_administrative_executor")
        assert_executor_identity(env, env["res.users"].browse(executor_id),
                                 company=env["res.company"].browse(manifest["company_id"]))
        neutral = api.Environment(cr, executor_id, base.draft_kernel._context(manifest["company_id"]), su=False)
        require(neutral.uid == executor_id and not neutral.su,
                "public_preflight_restricted_identity_without_elevation")
        before_public = first_observer.projection(env, first_scope)
        public_result = neutral["ap.security.executor"].execute(public_command)
        require(type(public_result) is dict and public_result == {
            "schema_version": "executor-preflight-result/v1", "decision": "DENY",
            "deny_class": "FAIL_CLOSED_UNAVAILABILITY", "reason_codes": ["DEPENDENCY_UNAVAILABLE"],
            "executor_status": "SCAFFOLD_NOT_READY", "effect_applied": False,
            "proposed_action_hash": checked_public_command.action_hash,
        } and public_result["effect_applied"] is False,
                "public_executor_exact_closed_preflight_for_valid_command_and_identity")
        require(first_observer.projection(env, first_scope) == before_public,
                "public_executor_preflight_has_no_companywide_financial_or_audit_delta")
        cr.commit()
    require(first_observer.fresh_projection(first_scope) == before_public,
            "public_executor_closed_after_actual_parent_commit_and_fresh_cursor")
    rows = []
    for fixture, case, decision in zip(native["cases"], execution["cases"], policy["cases"], strict=True):
        if fixture["name"] == "observed_bank_revoked_after_allow":
            fixture_base, scope = inspect_revoked_scope(registry, args, manifest, fixture)
        else:
            observer, scope, _ = load_scope(registry, args, manifest, fixture)
            fixture_base = observer.base
        state = fixture_base.projection(scope)
        if fixture["name"] == "observed_create_benign":
            fixture_base.assert_persisted(scope)
            require(len(case["attempts"]) == 2 and case["attempts"][0]["receipt_id"] == case["attempts"][1]["receipt_id"] and
                    case["attempts"][0]["move_id"] == case["attempts"][1]["move_id"],
                    "one_actual_draft_and_receipt_despite_original_command_replay")
        elif fixture["name"] == "observed_post_without_approval":
            fixture_base.assert_persisted(scope)
            require(scope.result["receipt"]["move_id"] in baseline and
                    decision["status"] == "REVIEW" and decision["command"] is None,
                    "post_review_leaves_actual_audited_create_origin_draft")
        else:
            require(not state["moves"] and not state["lines"] and not state["attachments"] and
                    not state["receipts"] and not state["successful_audits"] and state["rank"] == 1 and
                    state["po"][0]["qty_to_invoice"] == 1.0 and state["po"][0]["qty_invoiced"] == 0.0,
                    "denied_or_rejected_case_has_no_linked_financial_effect")
        rows.append({"name": fixture["name"], "status": "PASS", "gateway_decision": decision["status"],
            "native_status": case["status"], "snapshot_sha256": digest(state), "checks": {
                "fresh_normal_cursor": True, "actual_financial_state_verified": True,
                "receipt_audit_attachment_binding_verified": True, "no_payment_or_approval": True,
                "no_unexpected_case_effect": True,
            }})
    write_json(artifacts / "observed-confirmation.json", dict(
        top(args, manifest, "runner-observed-confirmation/v1"), cases=rows, company_summary=summary, checks={
            "companywide_not_candidate_filtered": True, "existing_baseline_bills_unchanged": True,
            "only_expected_new_bill": True, "public_executor_still_closed": True,
            "reader_non_administrative_single_company": True, "reader_model_readonly_acl_verified": True,
        }))


def run(args):
    odoo.tools.config.parse_config(["-c", args.config, "-d", args.database, "--no-http"], setup_logging=False)
    require(not odoo.tools.config["test_enable"], "normal_registry_configuration")
    registry = Registry(args.database)
    {"prepare": prepare, "observe": observe, "execute": execute, "confirm": confirm}[args.mode](registry, args)
