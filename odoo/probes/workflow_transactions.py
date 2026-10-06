# SPDX-License-Identifier: LGPL-3.0-or-later
"""Disposable proof of private registration in ordinary Odoo transactions.

Reuses only the C1-11 native fixture library. No TestCursor, financial effect,
internal SQL commit, API call or scientific run is introduced. Provenance in
these synthetic fixtures is declared placeholder data, not attestation.
"""

import argparse
from dataclasses import replace
import logging
from pathlib import Path
import re
from unittest.mock import patch

import odoo
from odoo.orm.registry import Registry

from c111_transactions import Probe, ProbeFailure, InjectedFault, canonical, digest, require


MODEL = "ap.security.workflow.registration"


class WorkflowProbe:
    def __init__(self, registry):
        from odoo.addons.ap_security_executor import workflow_registry
        from odoo.addons.ap_security_executor.workflow_contracts import WorkflowProvenance
        self.base = Probe(registry)
        self.registry = registry
        self.module = workflow_registry
        self.provenance = WorkflowProvenance(
            code_commit="a" * 40, code_sha256="sha256:" + "b" * 64,
            configuration_sha256="sha256:" + "c" * 64,
        )
        self.cases = []

    def fixture(self):
        scope = self.base.fixture()
        scope.workflow = replace(scope.workflow, scenario_id=f"TCC-WF-{self.base.counter:03d}")
        return scope

    def register(self, cr, scope, provenance=None):
        self.base.cursor_gate(cr)
        return self.module.register_draft_workflow(
            self.base.env(cr), workflow=scope.workflow, document=scope.document,
            provenance=provenance or self.provenance,
        )

    def resolve(self, cr, scope, registration):
        self.base.cursor_gate(cr)
        return self.module.resolve_draft_workflow(
            self.base.env(cr), registration_id=registration.registration_id,
            expected_company_id=scope.workflow.company_id,
            expected_executor_user_id=scope.workflow.executor_user_id,
            expected_scenario_id=scope.workflow.scenario_id,
            document=scope.document, provenance=self.provenance,
        )

    def registered_count(self, scope):
        with self.registry.cursor() as cr:
            self.base.cursor_gate(cr)
            return self.base.env(cr)[MODEL].search_count([
                ("company_id", "=", scope.workflow.company_id),
                ("scenario_id", "=", scope.workflow.scenario_id),
            ])

    def neutral_projection(self, scope):
        projection = {"fixture": self.base.projection(scope),
                      "guards": self.base.guard_projection(scope)}
        with self.registry.cursor() as cr:
            self.base.cursor_gate(cr)
            env = self.base.env(cr)
            company = self.base.company_id
            # Select by trusted company, not a proposed reference: registration
            # must be neutral even for an unexpected financial object.
            for model, names in (
                ("account.move", ["state", "ref", "partner_id", "partner_bank_id", "amount_total", "write_date"]),
                ("account.move.line", ["move_id", "debit", "credit", "quantity", "purchase_line_id", "write_date"]),
                ("ap.security.draft.receipt", ["command_sha256", "receipt_payload", "write_date"]),
                ("ap.security.po.guard", ["revision", "write_date"]),
                ("ap.security.vendor.guard", ["revision", "write_date"]),
                ("ap.security.audit.event", ["event_sha256", "write_date"]),
                ("ap.security.approval.nonce", ["state", "write_date"]),
            ):
                projection[model] = env[model].search([("company_id", "=", company)]).read(names)
            projection["vendor"] = env["res.partner"].browse(scope.vendor_id).read([
                "supplier_rank", "company_id", "ref", "autopost_bills", "write_date"])
            projection["banks"] = env["res.partner.bank"].browse(scope.workflow.allowed_bank_ids).read([
                "active", "allow_out_payment", "partner_id", "company_id", "write_date"])
            projection["purchase"] = env["purchase.order"].browse(scope.purchase_id).read([
                "state", "partner_id", "company_id", "currency_id", "write_date"])
            projection["purchase_lines"] = env["purchase.order.line"].browse(scope.workflow.purchase_line_ids).read([
                "product_qty", "price_unit", "qty_to_invoice", "qty_invoiced", "write_date"])
        return projection

    def unchanged(self, scope, before):
        require(self.neutral_projection(scope) == before, "financial_and_master_projection_unchanged")
        return {"financial_and_master_projection_unchanged": True,
                "projection_sha256": digest(before)}

    def commit_resolve(self):
        scope = self.fixture()
        before = self.neutral_projection(scope)
        with self.registry.cursor() as cr:
            registration = self.register(cr, scope)
            require(self.registered_count(scope) == 0, "uncommitted_registration_invisible")
            cr.commit()
        require(self.registered_count(scope) == 1, "one_registration_after_commit")
        with self.registry.cursor() as cr:
            require(self.resolve(cr, scope, registration) == registration, "fresh_cursor_resolution_exact")
            require(self.register(cr, scope) == registration, "strict_replay_same_id_and_body")
        return dict(self.unchanged(scope, before), external_commit=True,
                    fresh_cursor_resolution=True, strict_replay_same_identity=True)

    def rollback(self, savepoint):
        scope = self.fixture()
        before = self.neutral_projection(scope)
        with self.registry.cursor() as cr:
            self.base.cursor_gate(cr)
            if savepoint:
                try:
                    with cr.savepoint():
                        self.register(cr, scope)
                        raise InjectedFault()
                except InjectedFault:
                    pass
                cr.commit()
            else:
                self.register(cr, scope)
                cr.rollback()
                cr.commit()
        require(self.registered_count(scope) == 0, "registration_absent_after_real_rollback")
        return dict(self.unchanged(scope, before), external_rollback=True,
                    outer_savepoint=savepoint, parent_native_commit=True)

    def fault(self):
        scope = self.fixture()
        before = self.neutral_projection(scope)
        observed = []

        def after_insert(record):
            require(record.exists() and record.scenario_id == scope.workflow.scenario_id,
                    "actual_insert_observed_before_fault")
            observed.append(True)
            raise InjectedFault()

        with self.registry.cursor() as cr:
            self.base.cursor_gate(cr)
            with patch.object(self.module, "_after_registration_insert", after_insert):
                try:
                    self.register(cr, scope)
                except self.module.WorkflowRegistryError as error:
                    require(error.code == "REGISTRATION_UNAVAILABLE", "fault_has_finite_category")
                else:
                    raise ProbeFailure("fault_not_rejected")
            require(observed == [True], "actual_insert_fault_exactly_once")
            cr.commit()
        require(self.registered_count(scope) == 0, "fault_insert_rolled_back_before_parent_commit")
        return dict(self.unchanged(scope, before), actual_insert_observed=True,
                    insertion_savepoint_rolled_back=True, parent_native_commit=True)

    def conflict(self):
        scope = self.fixture()
        before = self.neutral_projection(scope)
        with self.registry.cursor() as cr:
            registration = self.register(cr, scope)
            cr.commit()
        other = replace(self.provenance, configuration_sha256="sha256:" + "d" * 64)
        with self.registry.cursor() as cr:
            self.base.cursor_gate(cr)
            try:
                self.register(cr, scope, other)
            except self.module.WorkflowRegistryError as error:
                require(error.code == "REGISTRATION_CONFLICT", "changed_body_finite_conflict")
            else:
                raise ProbeFailure("changed_body_not_rejected")
            cr.commit()
        with self.registry.cursor() as cr:
            require(self.resolve(cr, scope, registration) == registration, "original_binding_not_repaired")
        require(self.registered_count(scope) == 1, "conflict_does_not_insert_duplicate")
        return dict(self.unchanged(scope, before), conflicting_replay_rejected=True,
                    original_binding_preserved=True)

    def run(self):
        for name, operation in (
            ("register_commit_and_fresh_cursor_resolve", self.commit_resolve),
            ("registration_outer_rollback", lambda: self.rollback(False)),
            ("registration_savepoint_rollback_then_commit", lambda: self.rollback(True)),
            ("fault_after_actual_insert", self.fault),
            ("conflicting_replay_no_rebinding", self.conflict),
        ):
            try:
                self.cases.append({"case": name, "status": "PASS", "checks": operation()})
            except BaseException as error:
                category = str(error) if isinstance(error, ProbeFailure) else "unexpected_runtime_failure"
                require(re.fullmatch(r"[a-z_]+", category), "safe_failure_category")
                self.cases.append({"case": name, "status": "FAIL", "category": category})
                raise ProbeFailure(category) from None


def main():
    parser = argparse.ArgumentParser(description="Disposable private workflow registration probe")
    for name in ("config", "database", "evidence"):
        parser.add_argument("--" + name, required=True)
    args = parser.parse_args()
    require(args.config == "/etc/odoo/c104.conf", "trusted_config_path")
    require(re.fullmatch(r"tcc_workflow_[0-9a-f]{12}", args.database), "disposable_database_namespace")
    require(args.evidence == "/mnt/c1-evidence/workflow-transactions.json", "trusted_evidence_path")
    logging.disable(logging.CRITICAL)
    odoo.tools.config.parse_config(["-c", args.config, "-d", args.database, "--no-http"], setup_logging=False)
    probe = WorkflowProbe(Registry(args.database))
    status = "FAIL"
    try:
        probe.run()
        require(len(probe.cases) == 5 and all(case["status"] == "PASS" for case in probe.cases),
                "all_cases_executed")
        status = "PASS"
    except BaseException:
        pass
    result = {"schema_version": "workflow-transactions-evidence/v1", "status": status,
              "scope": "private-registration-native-lifecycle-only", "cases": probe.cases,
              "test_count": len(probe.cases), "normal_registry": True, "test_cursor_used": False,
              "mocked_sql_commit": False, "public_financial_effects_enabled": False,
              "scientific_run": False, "human_review_complete": False,
              "limitations": ["Private CREATE/DRAFT registration only; no public executor or common runner.",
                              "Declared synthetic provenance placeholders are not authenticated attestations.",
                              "No registry concurrency claim, pilot, freeze or independent human acceptance."]}
    Path(args.evidence).write_bytes(canonical(result) + b"\n")
    print("Workflow registration " + status + " " + str(len(probe.cases)) + "/5 cases")
    return 0 if status == "PASS" else 1


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (ProbeFailure, Exception):
        print("Workflow registration FAIL safe-runtime-category")
        raise SystemExit(1) from None
