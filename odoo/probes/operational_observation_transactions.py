# SPDX-License-Identifier: LGPL-3.0-or-later
"""Read-only operational observations in a disposable ordinary Odoo registry.

Fixture preparation may register a document or create a synthetic draft using
the existing private kernel. The observer itself may not dispatch a financial
effect, append an audit event, commit or change configuration. No clock,
financial method, cursor or native callback is patched. Metadata and technical
hashes are emitted; approval material and command bodies remain in memory.
"""

from __future__ import annotations

import argparse
import copy
from dataclasses import replace
from datetime import date
import hashlib
import logging
from pathlib import Path
import re
import secrets

import odoo
# Odoo 19 initializes the public shortcuts when its ORM package is loaded.
# Import the Registry class first, without instantiating a registry here.
from odoo.orm.registry import Registry
from odoo import Command, SUPERUSER_ID

from c111_transactions import Probe, ProbeFailure, canonical, digest, require


CASE_IDS = (
    "observe_create_open_clean_readonly",
    "observe_ledger_duplicate_changed_reference",
    "observe_native_reference_duplicate",
    "observe_closed_period_executor_identity",
    "observe_post_origin_not_duplicate",
    "observe_post_additional_reference_duplicate",
    "observe_audit_preflight_unavailable",
    "observe_candidate_hash_changes_with_reference_and_date",
)

_OBSERVATION_DOMAIN = b"tcc-operational-observation/v1\0"
_DIAGNOSTIC_FILES = frozenset({
    "operational_observation_transactions.py", "c111_transactions.py",
    "operational_observation.py", "operational_contracts.py", "workflow_registry.py",
    "registered_execution.py", "registered_post.py", "draft_kernel.py", "audit_kernel.py",
    "attachment_kernel.py", "identity.py",
})
_DIAGNOSTIC_TYPES = frozenset({
    "ProbeFailure", "OperationalObservationError", "OperationalContractError",
    "WorkflowRegistryError", "RegisteredExecutionError", "RegisteredPostError",
    "ValidationError", "AccessError", "KeyError", "AttributeError", "TypeError", "ValueError",
    "AssertionError", "OperationalError", "SerializationFailure", "DeadlockDetected",
    "UniqueViolation",
})


def failure_diagnostic(error):
    """Finite type and allowlisted locations, never messages, values or SQL."""
    frames = []
    trace = error.__traceback__
    while trace is not None:
        filename = Path(trace.tb_frame.f_code.co_filename).name
        if filename in _DIAGNOSTIC_FILES:
            frames.append({"file": filename, "line": trace.tb_lineno})
        trace = trace.tb_next
    name = type(error).__name__
    return {"error_type": name if name in _DIAGNOSTIC_TYPES else "UnexpectedRuntimeError",
            "source_locations": frames[-8:]}


class OperationalObservationProbe:
    def __init__(self, registry, *, git_base, source_bundle_sha256, configuration_sha256):
        from odoo.addons.ap_security_executor import (
            operational_observation, registered_execution, workflow_registry,
        )
        from odoo.addons.ap_security_executor.workflow_contracts import WorkflowProvenance

        self.registry = registry
        self.base = Probe(registry, executor_login="tcc-operational-private-probe")
        self.observation_module = operational_observation
        self.create_module = registered_execution
        self.workflow_module = workflow_registry
        self.git_base = git_base
        self.source_bundle_sha256 = source_bundle_sha256
        self.configuration_sha256 = configuration_sha256
        self.provenance = WorkflowProvenance(
            code_commit=git_base, code_sha256="sha256:" + source_bundle_sha256,
            configuration_sha256="sha256:" + configuration_sha256,
        )
        self.cases = []
        self.observation_records = []

    def audit(self):
        return self.base.TrustedAuditContext(
            run_id="TCC-OPERATIONAL-OBSERVATION-NATIVE", attempt_id=secrets.token_hex(16),
            code_commit=self.provenance.code_commit, code_sha256=self.provenance.code_sha256,
            configuration_sha256=self.provenance.configuration_sha256,
        )

    def fixture(self, *, created=False):
        """Trusted synthetic setup, committed before the read-only observation."""
        scope = self.base.fixture()
        scenario = f"TCC-OBSERVATION-{self.base.counter:03d}"
        scope.workflow = replace(scope.workflow, scenario_id=scenario)
        scope.command = copy.deepcopy(scope.command)
        scope.command["action"]["scenario_id"] = scenario
        scope.command["policy_decision"] = self.base.policy(scope.command["action"], post=False)
        with self.registry.cursor() as cr:
            self.base.cursor_gate(cr)
            env = self.base.env(cr)
            registration = self.workflow_module.register_draft_workflow(
                env, workflow=scope.workflow, document=scope.document, provenance=self.provenance,
            )
            if created:
                envelope = self.create_module.create_registered_draft_audited(
                    env, registration_id=registration.registration_id,
                    expected_company_id=scope.workflow.company_id,
                    expected_executor_user_id=scope.workflow.executor_user_id,
                    expected_scenario_id=scenario, command=copy.deepcopy(scope.command),
                    audit=self.audit(), document=scope.document,
                )
                require(envelope["schema_version"] == "registered-draft-execution/v1" and
                        envelope["caller_transaction_pending"] is True,
                        "fixture_actual_registered_create_pending")
                scope.result = envelope["result"]
                self.base.success(scope.result, "CREATED")
            cr.commit()
        if created:
            self.base.assert_persisted(scope)
        return scope, registration

    def prepare_native_reference_duplicate(self, scope, *, reference):
        """Administrative fixture only: one extra draft, without a PO link."""
        with self.registry.cursor() as cr:
            self.base.cursor_gate(cr)
            env = self.base.env(cr)
            draft = env["account.move"].create({
                "company_id": scope.workflow.company_id, "journal_id": scope.workflow.journal_id,
                "partner_id": scope.workflow.vendor_id, "move_type": "in_invoice", "state": "draft",
                "auto_post": "no", "invoice_date": scope.command["action"]["invoice_date"],
                "date": scope.command["action"]["invoice_date"], "ref": reference,
                "invoice_origin": "TCC-OBSERVATION-REFERENCE-FIXTURE-SEM-VALOR-FISCAL",
                "invoice_line_ids": [Command.create({
                    "name": "TCC REFERENCE FIXTURE - SEM VALOR FISCAL",
                    "account_id": scope.workflow.expense_account_id, "quantity": 1.0,
                    "price_unit": 125.50, "discount": 0.0, "tax_ids": [Command.clear()],
                })],
            })
            env.flush_all()
            require(draft.state == "draft" and draft.ref == reference and
                    draft.partner_id.id == scope.workflow.vendor_id and
                    draft.company_id.id == scope.workflow.company_id and
                    not draft.invoice_line_ids.purchase_line_id,
                    "native_secondary_reference_fixture_without_purchase_consumption")
            cr.commit()

    def projection(self, env, scope):
        """Technical company-wide projection, not a scientific oracle or reset."""
        company_id = scope.workflow.company_id
        result = {}
        for model, fields in (
            ("account.move", ["state", "move_type", "name", "posted_before", "ref", "invoice_date",
                              "date", "partner_id", "partner_bank_id", "journal_id", "amount_total",
                              "invoice_origin", "auto_post", "write_date"]),
            ("account.move.line", ["move_id", "purchase_line_id", "account_id", "quantity", "price_unit",
                                   "debit", "credit", "discount", "tax_ids", "write_date"]),
            ("ap.security.draft.receipt", ["executor_mode", "document_sha256", "idempotency_key", "move_id",
                                          "command_sha256", "action_sha256", "receipt_payload", "write_date"]),
            ("ap.security.audit.event", ["status", "event_payload", "event_sha256", "write_date"]),
            ("ap.security.approval.nonce", ["state", "command_sha256", "action_sha256", "nonce_sha256",
                                           "consumed_at", "write_date"]),
            ("ap.security.po.guard", ["po_id", "revision", "write_date"]),
            ("ap.security.vendor.guard", ["vendor_id", "revision", "write_date"]),
            ("ap.security.workflow.registration", ["registration_payload", "registration_sha256", "write_date"]),
            ("res.partner", ["ref", "active", "supplier_rank", "autopost_bills", "write_date"]),
            ("res.partner.bank", ["partner_id", "active", "acc_number", "allow_out_payment", "write_date"]),
            ("purchase.order", ["state", "partner_id", "currency_id", "amount_total", "invoice_status", "write_date"]),
            ("purchase.order.line", ["order_id", "product_qty", "qty_invoiced", "qty_to_invoice", "price_unit",
                                     "tax_ids", "discount", "write_date"]),
            ("account.lock_exception", ["user_id", "active", "state", "lock_date_field", "lock_date", "write_date"]),
        ):
            result[model] = env[model].with_context(active_test=False).search([
                ("company_id", "=", company_id),
            ], order="id").read(fields)
        result["attachments"] = [{
            "id": row.id, "target": row.res_id, "model": row.res_model,
            "hash": hashlib.sha256(row.raw or b"").hexdigest(), "private": not row.public,
            "storage_db": not row.store_fname, "mime": row.mimetype, "write_date": str(row.write_date),
        } for row in env["ir.attachment"].search([("company_id", "=", company_id)], order="id")]
        result["auxiliary_counts"] = {model: env[model].search_count([]) for model in (
            "account.payment", "account.partial.reconcile", "account.full.reconcile", "account.analytic.line",
            "mail.mail", "mail.notification", "mail.message", "ir.attachment",
        )}
        result["company_locks"] = env["res.company"].browse(company_id).read([
            "fiscalyear_lock_date", "hard_lock_date", "tax_lock_date", "sale_lock_date", "purchase_lock_date",
        ])
        result["attachment_storage"] = env["ir.config_parameter"].get_param("ir_attachment.location")
        return result

    def fresh_projection(self, scope):
        with self.registry.cursor() as cr:
            self.base.cursor_gate(cr)
            return self.projection(self.base.env(cr), scope)

    @staticmethod
    def callback_counts(cr):
        return tuple((len(getattr(cr, name)), len(getattr(cr, name).data))
                     for name in ("precommit", "postcommit", "prerollback", "postrollback"))

    def expected_binding(self, scope, registration):
        """Independent fixture binding, assembled before calling the observer."""
        workflow = scope.workflow
        return {
            "registration_id": registration.registration_id,
            "registration_sha256": registration.registration_sha256,
            "company_id": workflow.company_id, "executor_user_id": workflow.executor_user_id,
            "vendor_id": workflow.vendor_id, "purchase_order_id": workflow.purchase_order_id,
            "journal_id": workflow.journal_id, "purchase_line_ids": list(workflow.purchase_line_ids),
            "allowed_bank_ids": list(workflow.allowed_bank_ids), "code_commit": self.provenance.code_commit,
            "code_sha256": self.provenance.code_sha256,
            "configuration_sha256": self.provenance.configuration_sha256,
        }

    def verify_observation(self, observation, scope, registration, action, *, facts, audit="AVAILABLE"):
        require(type(observation) is dict and set(observation) == {
            "schema_version", "registration", "provenance", "scope", "facts", "preflight",
            "observed_at", "observation_sha256",
        } and observation["schema_version"] == "registered-operational-observation/v1",
                "closed_native_observation_envelope")
        require(observation["registration"] == {
            "registration_id": registration.registration_id,
            "registration_sha256": registration.registration_sha256,
        }, "observation_original_registration_binding")
        require(observation["provenance"] == {
            "code_commit": self.provenance.code_commit, "code_sha256": self.provenance.code_sha256,
            "configuration_sha256": self.provenance.configuration_sha256,
        }, "observation_declared_source_and_configuration_binding")
        workflow = scope.workflow
        expected_scope = {
            "company_id": workflow.company_id, "executor_user_id": workflow.executor_user_id,
            "vendor_id": workflow.vendor_id, "purchase_order_id": workflow.purchase_order_id,
            "purchase_line_ids": list(workflow.purchase_line_ids), "journal_id": workflow.journal_id,
            "allowed_bank_ids": list(workflow.allowed_bank_ids), "scenario_id": workflow.scenario_id,
            "document_sha256": workflow.document_sha256, "policy_version": workflow.policy_version,
            "invoice_date_min": workflow.invoice_date_min, "invoice_date_max": workflow.invoice_date_max,
            "monetary_tolerance": workflow.monetary_tolerance, "quantity_scale": workflow.quantity_scale,
            "executor_mode": action["executor_mode"], "action_sha256": digest(action),
            "document_ref": action["document_ref"], "invoice_date": action["invoice_date"],
            "target_move_id": scope.result["receipt"]["move_id"] if action["executor_mode"] == "POST_APPROVED" else None,
        }
        require(observation["scope"] == expected_scope, "observation_complete_candidate_and_trusted_scope")
        require(observation["facts"] == facts, "real_observed_duplicate_and_period_facts_exact")
        require(observation["preflight"] == {"state": "AVAILABLE", "audit": audit},
                "read_only_preflight_exact_without_favorable_fallback")
        unsigned = {key: value for key, value in observation.items() if key != "observation_sha256"}
        require(observation["observation_sha256"] == "sha256:" + hashlib.sha256(
            _OBSERVATION_DOMAIN + canonical(unsigned),
        ).hexdigest(), "native_observation_domain_integrity_hash_exact")
        require(type(observation["observed_at"]) is str and re.fullmatch(
            r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(?:\.[0-9]{1,6})?Z",
            observation["observed_at"],
        ), "native_server_timestamp_finite_utc")

    def observe(self, case_id, scope, registration, action, *, facts, audit="AVAILABLE"):
        """Verify real read-only behavior before and after the caller commits."""
        expected_binding = self.expected_binding(scope, registration)
        before = self.fresh_projection(scope)
        callbacks = []
        with self.registry.cursor() as cr:
            self.base.cursor_gate(cr)
            env = self.base.env(cr)
            require(self.projection(env, scope) == before, "caller_projection_matches_fresh_baseline")
            cr.postcommit.add(lambda: callbacks.append(True))
            callback_counts = self.callback_counts(cr)
            observation = self.observation_module.observe_registered_policy_state(
                env, registration_id=registration.registration_id,
                expected_company_id=scope.workflow.company_id,
                expected_executor_user_id=scope.workflow.executor_user_id,
                expected_scenario_id=scope.workflow.scenario_id,
                document=scope.document, provenance=self.provenance, canonical_action=copy.deepcopy(action),
            )
            self.verify_observation(observation, scope, registration, action, facts=facts, audit=audit)
            require(self.callback_counts(cr) == callback_counts and not callbacks,
                    "observer_preserves_pending_caller_callback_counts")
            require(self.projection(env, scope) == before,
                    "observer_leaves_company_financial_and_audit_projection_unchanged")
            cr.commit()
        require(callbacks == [True], "observer_preserves_caller_callback_real_commit")
        require(self.fresh_projection(scope) == before,
                "observer_no_effect_or_guard_or_rank_after_parent_native_commit")
        self.observation_records.append({
            "case_id": case_id, "observation": observation, "expected_binding": expected_binding,
        })
        return observation, {
            "ordinary_cursor_and_registry": True, "original_registration_preserved": True,
            "full_company_projection_unchanged_before_and_after_commit": True,
            "financial_receipts_approval_events_attachments_and_guards_unchanged": True,
            "purchase_computeds_and_supplier_rank_unchanged": True,
            "caller_callback_counts_preserved": True, "caller_callback_runs_once_after_real_commit": True,
            "complete_candidate_and_trusted_scope_verified": True,
            "server_observation_integrity_verified": True, "projection_sha256": digest(before),
        }

    @staticmethod
    def facts(*, document=False, reference=False, period=True):
        return {"document_duplicate": document, "reference_duplicate": reference,
                "duplicate_detected": document or reference, "accounting_period_open": period}

    @staticmethod
    def post_action(scope):
        require(scope.result is not None, "post_candidate_has_actual_registered_create_origin")
        return dict(copy.deepcopy(scope.command["action"]), action="POST_VENDOR_BILL",
                    executor_mode="POST_APPROVED", target_move_id=scope.result["receipt"]["move_id"])

    def create_clean(self):
        scope, registration = self.fixture()
        _, checks = self.observe(CASE_IDS[0], scope, registration, scope.command["action"], facts=self.facts())
        return dict(checks, real_open_period_and_no_duplicate=True, no_financial_preparation_needed=True)

    def ledger_duplicate(self):
        scope, registration = self.fixture(created=True)
        action = dict(copy.deepcopy(scope.command["action"]),
                      document_ref="TCC-CHANGED-REF-SEM-VALOR-FISCAL")
        _, checks = self.observe(CASE_IDS[1], scope, registration, action, facts=self.facts(document=True))
        return dict(checks, registered_document_duplicate_survives_changed_reference=True,
                    secondary_reference_not_mistaken_for_document_identity=True)

    def reference_duplicate(self):
        scope, registration = self.fixture()
        self.prepare_native_reference_duplicate(scope, reference=scope.command["action"]["document_ref"])
        _, checks = self.observe(CASE_IDS[2], scope, registration, scope.command["action"],
                                 facts=self.facts(reference=True))
        return dict(checks, real_native_vendor_bill_reference_detected=True,
                    no_ledger_document_receipt_fabricated=True)

    def closed_period(self):
        scope, registration = self.fixture()
        candidate_date = date.fromisoformat(scope.command["action"]["invoice_date"])
        exception_id = None
        with self.registry.cursor() as cr:
            self.base.cursor_gate(cr)
            env = self.base.env(cr)
            require(candidate_date < cr.now().date(), "lock_date_is_before_real_server_fixture_window")
            company = env["res.company"].browse(scope.workflow.company_id)
            company.write({"fiscalyear_lock_date": candidate_date})
            exception = env["account.lock_exception"].create({
                "company_id": scope.workflow.company_id, "user_id": SUPERUSER_ID,
                "fiscalyear_lock_date": False,
                "reason": "TCC OBSERVATION UID1-ONLY EXCEPTION - SEM VALOR FISCAL",
            })
            require(exception.state == "active", "real_uid1_accounting_exception_active")
            exception_id = exception.id
            cr.commit()
        try:
            with self.registry.cursor() as cr:
                self.base.cursor_gate(cr)
                env = self.base.env(cr)
                company = env["res.company"].browse(scope.workflow.company_id)
                journal = env["account.journal"].browse(scope.workflow.journal_id)
                executor_company = company.with_user(scope.workflow.executor_user_id).sudo()
                service_company = company.with_user(SUPERUSER_ID).sudo()
                require(executor_company.env.uid == scope.workflow.executor_user_id and
                        executor_company.env.uid != SUPERUSER_ID and
                        executor_company._get_violated_lock_dates(candidate_date, False, journal) and
                        not service_company._get_violated_lock_dates(candidate_date, False, journal),
                        "real_executor_period_closed_while_uid1_exception_opens_service_period")
            _, checks = self.observe(CASE_IDS[3], scope, registration, scope.command["action"],
                                     facts=self.facts(period=False))
            return dict(checks, native_executor_uid_period_closed=True,
                        uid1_only_exception_does_not_authorize_executor=True, no_clock_override=True)
        finally:
            # Administrative fixture restoration is outside the observer and
            # only after its unchanged-after-parent-commit gate has completed.
            with self.registry.cursor() as cr:
                self.base.cursor_gate(cr)
                env = self.base.env(cr)
                env["res.company"].browse(scope.workflow.company_id).write({"fiscalyear_lock_date": False})
                if exception_id is not None:
                    env["account.lock_exception"].browse(exception_id).write({"active": False})
                cr.commit()

    def post_origin(self):
        scope, registration = self.fixture(created=True)
        _, checks = self.observe(CASE_IDS[4], scope, registration, self.post_action(scope), facts=self.facts())
        return dict(checks, actual_audited_create_origin_excluded_from_duplicate=True,
                    target_derived_from_actual_original_receipt=True, no_post_or_approval_performed=True)

    def post_reference_duplicate(self):
        scope, registration = self.fixture(created=True)
        self.prepare_native_reference_duplicate(scope, reference=scope.command["action"]["document_ref"])
        _, checks = self.observe(CASE_IDS[5], scope, registration, self.post_action(scope),
                                 facts=self.facts(reference=True))
        return dict(checks, only_original_create_receipt_and_move_excluded=True,
                    additional_native_reference_duplicate_detected=True, no_post_or_approval_performed=True)

    def audit_unavailable(self):
        scope, registration = self.fixture()
        with self.registry.cursor() as cr:
            self.base.cursor_gate(cr)
            self.base.env(cr)["ir.config_parameter"].set_param("ir_attachment.location", "file")
            cr.commit()
        try:
            _, checks = self.observe(CASE_IDS[6], scope, registration, scope.command["action"],
                                     facts=self.facts(), audit="UNAVAILABLE")
            return dict(checks, real_attachment_storage_preflight_unavailable=True,
                        no_test_insert_or_healthcheck_artifact=True, audit_unavailability_explicit=True)
        finally:
            with self.registry.cursor() as cr:
                self.base.cursor_gate(cr)
                self.base.env(cr)["ir.config_parameter"].set_param("ir_attachment.location", "db")
                cr.commit()

    def candidate_change(self):
        scope, registration = self.fixture()
        original = copy.deepcopy(scope.command["action"])
        changed = dict(copy.deepcopy(original), document_ref="TCC-NEW-CANDIDATE-SEM-VALOR-FISCAL",
                       invoice_date="2026-09-29")
        first, checks = self.observe(CASE_IDS[7], scope, registration, original, facts=self.facts())
        second, second_checks = self.observe(CASE_IDS[7], scope, registration, changed, facts=self.facts())
        require(first["scope"]["action_sha256"] != second["scope"]["action_sha256"] and
                first["scope"]["document_ref"] != second["scope"]["document_ref"] and
                first["scope"]["invoice_date"] != second["scope"]["invoice_date"] and
                first["registration"] == second["registration"] and
                first["provenance"] == second["provenance"] and
                first["observation_sha256"] != second["observation_sha256"],
                "changed_reference_and_date_bind_distinct_observation_of_same_registration")
        require(checks["projection_sha256"] == second_checks["projection_sha256"],
                "both_candidate_observations_leave_same_company_projection")
        return dict(checks, both_candidate_actions_independently_hash_verified=True,
                    changed_reference_and_date_change_action_hash=True,
                    same_registration_provenance_and_unchanged_state=True)

    def run(self):
        operations = (self.create_clean, self.ledger_duplicate, self.reference_duplicate, self.closed_period,
                      self.post_origin, self.post_reference_duplicate, self.audit_unavailable, self.candidate_change)
        for name, operation in zip(CASE_IDS, operations, strict=True):
            try:
                checks = operation()
                self.cases.append({"case": name, "case_id": name, "status": "PASS", "checks": checks})
            except BaseException as error:
                category = str(error) if isinstance(error, ProbeFailure) else "unexpected_runtime_failure"
                require(re.fullmatch(r"[a-z0-9_]+", category), "safe_failure_category")
                self.cases.append({"case": name, "case_id": name, "status": "FAIL", "category": category,
                                   "failure_diagnostic": failure_diagnostic(error)})
                raise ProbeFailure(category) from None

    def evidence(self, *, status):
        return {
            "schema_version": "operational-observation-transactions-evidence/v1", "status": status,
            "scope": "private-registered-operational-observation-readonly-only",
            "git_base": self.git_base, "source_bundle_sha256": self.source_bundle_sha256,
            "configuration_sha256": self.configuration_sha256,
            "cases": self.cases, "case_count": len(self.cases), "test_count": len(self.cases),
            "passed_case_count": sum(case["status"] == "PASS" for case in self.cases),
            "observation_records": self.observation_records, "record_count": len(self.observation_records),
            "normal_registry": True, "test_cursor_used": False, "registry_test_mode": False,
            "mocked_sql_commit": False, "mocked_financial_method": False, "mocked_clock": False,
            "approval_material_emitted": False, "real_api_used": False, "real_provider_calls_executed": 0,
            "public_executor_enabled": False,
            "public_financial_effects_enabled": False, "scientific_run": False, "human_review_complete": False,
            "limitations": [
                "Private administrative read-only module API; no public RPC, complete gateway or supervision.",
                "Preflight is advisory and cannot establish future audit append availability or eliminate TOCTOU.",
                "Declared hashes identify sources and configuration, not authenticated administrative authority.",
                "Company projection is a development no-effect check, not the scientific oracle or reset.",
                "No real API, final dataset, pilot, freeze or independent human acceptance.",
            ],
        }


def startup_evidence(args, error):
    return {
        "schema_version": "operational-observation-transactions-evidence/v1", "status": "FAIL",
        "scope": "private-registered-operational-observation-readonly-only",
        "git_base": args.git_base, "source_bundle_sha256": args.source_bundle_sha256,
        "configuration_sha256": args.configuration_sha256,
        "cases": [], "case_count": 0, "test_count": 0, "passed_case_count": 0,
        "observation_records": [], "record_count": 0,
        "normal_registry": False, "test_cursor_used": False, "registry_test_mode": False,
        "mocked_sql_commit": False, "mocked_financial_method": False, "mocked_clock": False,
        "approval_material_emitted": False, "real_api_used": False, "real_provider_calls_executed": 0,
        "public_executor_enabled": False,
        "public_financial_effects_enabled": False, "scientific_run": False, "human_review_complete": False,
        "startup_failed": True, "startup_diagnostic": failure_diagnostic(error),
        "limitations": ["Initialization failed; normal registry and native case gates not established."],
    }


def main():
    parser = argparse.ArgumentParser(description="Disposable read-only registered operational observations")
    for name in ("config", "database", "evidence", "git-base", "source-bundle-sha256", "configuration-sha256"):
        parser.add_argument("--" + name, required=True)
    args = parser.parse_args()
    require(args.config == "/etc/odoo/c104.conf", "trusted_config_path")
    require(re.fullmatch(r"tcc_observation_[0-9a-f]{12}", args.database), "disposable_database_namespace")
    require(args.evidence == "/mnt/c1-evidence/operational-observation-transactions.json", "trusted_evidence_path")
    require(re.fullmatch(r"[0-9a-f]{40}", args.git_base), "declared_git_base_shape")
    require(re.fullmatch(r"[0-9a-f]{64}", args.source_bundle_sha256), "declared_source_bundle_shape")
    require(re.fullmatch(r"[0-9a-f]{64}", args.configuration_sha256), "declared_configuration_shape")
    logging.disable(logging.CRITICAL)
    probe = None
    startup_failure = None
    status = "FAIL"
    try:
        odoo.tools.config.parse_config(["-c", args.config, "-d", args.database, "--no-http"], setup_logging=False)
        probe = OperationalObservationProbe(
            Registry(args.database), git_base=args.git_base, source_bundle_sha256=args.source_bundle_sha256,
            configuration_sha256=args.configuration_sha256,
        )
        probe.run()
        require(tuple(case["case_id"] for case in probe.cases) == CASE_IDS and
                all(case["status"] == "PASS" for case in probe.cases) and
                len(probe.observation_records) == 9, "all_eight_cases_and_nine_real_observations_executed")
        status = "PASS"
    except BaseException as error:
        if probe is None:
            startup_failure = startup_evidence(args, error)
    result = startup_failure if probe is None else probe.evidence(status=status)
    Path(args.evidence).write_bytes(canonical(result) + b"\n")
    print("Operational observation " + status + " " + str(result["passed_case_count"]) + "/8 cases")
    return 0 if status == "PASS" else 1


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (ProbeFailure, Exception):
        print("Operational observation FAIL safe-runtime-category")
        raise SystemExit(1) from None
