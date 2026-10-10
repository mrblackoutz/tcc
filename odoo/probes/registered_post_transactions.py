# SPDX-License-Identifier: LGPL-3.0-or-later
"""Disposable registered POST proof using ordinary PostgreSQL transactions.

Only the private fault seam is patched. Financial methods, clocks, cursors,
commit and native callbacks are real. Source provenance is declared by the
disposable harness; hashes do not authenticate an administrative caller.
Approval material, command bodies and database identifiers stay in memory.
"""

from __future__ import annotations

import argparse
import copy
from dataclasses import asdict, replace
import hashlib
import hmac
import logging
from pathlib import Path
import re
import secrets
from unittest.mock import patch

import odoo
from odoo.orm.registry import Registry

from c111_transactions import (
    InjectedFault, Probe, ProbeFailure, canonical, digest, require,
)


CASE_IDS = (
    "registered_post_commit_fresh_cursor",
    "registered_post_replay",
    "registered_post_without_approval",
    "registered_post_outer_rollback",
    "registered_post_savepoint_rollback_then_commit",
    "registered_post_fault_after_real_effect_then_parent_commit",
)

_DIAGNOSTIC_FILES = frozenset({
    "registered_post_transactions.py", "c111_transactions.py", "registered_post.py",
    "registered_execution.py", "workflow_registry.py", "audit_kernel.py", "post_kernel.py",
    "approval_kernel.py", "attachment_kernel.py", "draft_kernel.py", "identity.py",
})
_DIAGNOSTIC_TYPES = frozenset({
    "ProbeFailure", "InjectedFault", "RegisteredPostError", "RegisteredExecutionError",
    "WorkflowRegistryError", "KeyError", "AttributeError", "TypeError", "ValueError",
    "ValidationError", "AccessError", "AssertionError", "OperationalError",
    "SerializationFailure", "DeadlockDetected", "UniqueViolation",
})


def failure_diagnostic(error):
    """Finite exception type and allowlisted source location, never contents."""
    name = type(error).__name__
    frames = []
    trace = error.__traceback__
    while trace is not None:
        filename = Path(trace.tb_frame.f_code.co_filename).name
        if filename in _DIAGNOSTIC_FILES:
            frames.append({"file": filename, "line": trace.tb_lineno})
        trace = trace.tb_next
    return {"error_type": name if name in _DIAGNOSTIC_TYPES else "UnexpectedRuntimeError",
            "source_locations": frames[-8:]}


class RegisteredPostProbe:
    def __init__(self, registry, *, git_base, source_bundle_sha256, configuration_sha256):
        from odoo.addons.ap_security_executor import (
            registered_execution, registered_post, workflow_registry,
        )
        from odoo.addons.ap_security_executor.draft_contracts import canonical_command_sha256
        from odoo.addons.ap_security_executor.workflow_contracts import WorkflowProvenance

        self.registry = registry
        self.base = Probe(registry, executor_login="tcc-registered-post-private-probe")
        self.create_module = registered_execution
        self.post_module = registered_post
        self.workflow_module = workflow_registry
        self.command_hash = canonical_command_sha256
        self.git_base = git_base
        self.source_bundle_sha256 = source_bundle_sha256
        self.configuration_sha256 = configuration_sha256
        self.provenance = WorkflowProvenance(
            code_commit=git_base,
            code_sha256="sha256:" + source_bundle_sha256,
            configuration_sha256="sha256:" + configuration_sha256,
        )
        self.cases = []

    def audit(self):
        return self.base.TrustedAuditContext(
            run_id="TCC-REGISTERED-POST-NATIVE", attempt_id=secrets.token_hex(16),
            code_commit=self.provenance.code_commit,
            code_sha256=self.provenance.code_sha256,
            configuration_sha256=self.provenance.configuration_sha256,
        )

    def fixture(self):
        """Prepare a distinct registered CREATE and commit it before each POST."""
        scope = self.base.fixture()
        scenario = f"TCC-RPOST-{self.base.counter:03d}"
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
            envelope = self.create_module.create_registered_draft_audited(
                env, registration_id=registration.registration_id,
                expected_company_id=scope.workflow.company_id,
                expected_executor_user_id=scope.workflow.executor_user_id,
                expected_scenario_id=scenario, command=copy.deepcopy(scope.command),
                audit=self.audit(), document=scope.document,
            )
            require(envelope["schema_version"] == "registered-draft-execution/v1" and
                    envelope["caller_transaction_pending"] is True,
                    "actual_registered_create_envelope")
            scope.result = envelope["result"]
            self.base.success(scope.result, "CREATED")
            cr.commit()
        self.base.assert_persisted(scope)
        # The existing library makes a genuine, in-memory approval. Rebind its
        # default scenario to this registration and re-sign that exact body.
        self.base.prepare_post(scope)
        scope.authority = replace(scope.authority, scenario_id=scenario)
        unsigned = {name: value for name, value in scope.post_command["approval"].items()
                    if name != "signature"}
        unsigned["scenario_id"] = scenario
        signature = "hmac-sha256/v1:" + hmac.new(
            scope.key.material,
            self.base.approval_domain + canonical({
                "company_id": scope.workflow.company_id, "approval": unsigned,
            }), hashlib.sha256,
        ).hexdigest()
        scope.post_command["approval"] = dict(unsigned, signature=signature)
        require(scope.post_command["action"]["scenario_id"] == scenario and
                scope.authority.scenario_id == scenario,
                "approval_and_command_bound_to_unique_scenario")
        return scope, registration

    def post(self, env, scope, registration, *, command=None):
        audit = self.audit()
        envelope = self.post_module.post_registered_bill_audited(
            env, registration_id=registration.registration_id,
            expected_company_id=scope.workflow.company_id,
            expected_executor_user_id=scope.workflow.executor_user_id,
            expected_scenario_id=scope.workflow.scenario_id,
            command=copy.deepcopy(scope.post_command if command is None else command),
            audit=audit, document=scope.document, authority=scope.authority, key=scope.key,
        )
        require(type(envelope) is dict and set(envelope) == {
            "schema_version", "registration", "origin", "result", "caller_transaction_pending",
        } and envelope["schema_version"] == "registered-post-execution/v1" and
                envelope["caller_transaction_pending"] is True,
                "closed_registered_post_envelope")
        require(envelope["registration"] == {
            "registration_id": registration.registration_id,
            "registration_sha256": registration.registration_sha256,
        }, "original_registration_returned")
        origin = envelope["origin"]
        require(type(origin) is dict and set(origin) == {
            "create_receipt_id", "create_event_id", "create_event_sha256", "target_move_id",
            "origin_sha256",
        } and origin["create_receipt_id"] == scope.result["receipt"]["receipt_id"] and
                origin["create_event_id"] == scope.result["audit_event"]["event_id"] and
                origin["create_event_sha256"] == scope.result["audit_event"]["event_sha256"] and
                origin["target_move_id"] == scope.result["receipt"]["move_id"] and
                type(origin["origin_sha256"]) is str and
                re.fullmatch(r"sha256:[0-9a-f]{64}", origin["origin_sha256"]),
                "target_derived_from_original_audited_create")
        self.base.closed_result(envelope["result"], "POST_APPROVED")
        return envelope, audit

    def projection(self, scope):
        """Fresh company-wide effect projection, kept private and only hashed."""
        result = {"fixture": self.base.projection(scope),
                  "guards": self.base.guard_projection(scope)}
        with self.registry.cursor() as cr:
            self.base.cursor_gate(cr)
            env = self.base.env(cr)
            for model, names in (
                ("account.move", ["state", "name", "posted_before", "ref", "partner_id",
                                  "partner_bank_id", "amount_total", "write_date"]),
                ("account.move.line", ["move_id", "debit", "credit", "quantity", "purchase_line_id",
                                       "account_id", "price_unit", "write_date"]),
                ("ap.security.draft.receipt", ["executor_mode", "document_sha256", "command_sha256",
                                              "action_sha256", "receipt_payload", "write_date"]),
                ("ap.security.audit.event", ["status", "event_payload", "event_sha256", "write_date"]),
                ("ap.security.approval.nonce", ["state", "command_sha256", "action_sha256",
                                               "nonce_sha256", "consumed_at", "write_date"]),
                ("ap.security.po.guard", ["po_id", "revision", "write_date"]),
                ("ap.security.vendor.guard", ["vendor_id", "revision", "write_date"]),
                ("ap.security.workflow.registration", ["registration_sha256", "write_date"]),
            ):
                result[model] = env[model].search([
                    ("company_id", "=", scope.workflow.company_id),
                ], order="id").read(names)
            attachments = env["ir.attachment"].search([
                ("company_id", "=", scope.workflow.company_id),
            ], order="id")
            result["company_attachments"] = [
                {"id": row.id, "target": row.res_id, "model": row.res_model,
                 "hash": hashlib.sha256(row.raw or b"").hexdigest(), "private": not row.public,
                 "storage_db": not row.store_fname, "mime": row.mimetype}
                for row in attachments
            ]
        return result

    def verify_effect(self, env, scope, result, audit):
        """Check real POST, persisted receipt, event, consumed nonce and PDF."""
        self.base.success(result, "POSTED")
        move = env["account.move"].browse(scope.result["receipt"]["move_id"]).exists()
        receipt = env["ap.security.draft.receipt"].browse(result["receipt"]["receipt_id"]).exists()
        event = env["ap.security.audit.event"].browse(result["audit_event"]["event_id"]).exists()
        create_event = env["ap.security.audit.event"].browse(
            scope.result["audit_event"]["event_id"],
        ).exists()
        payload = self.base.audit_kernel._verify_event(event)
        create_payload = self.base.audit_kernel._verify_event(create_event)
        nonce = env["ap.security.approval.nonce"].browse(
            result["receipt"]["approval_ledger_id"],
        ).exists()
        require(move and move.state == "posted" and receipt and
                receipt.move_id == move and receipt.executor_mode == "POST_APPROVED" and
                receipt.receipt_payload == result["receipt"] and
                receipt.command_sha256 == self.command_hash(scope.post_command) and
                event.status == "POSTED" and event.success_receipt_id == receipt and
                event.event_sha256 == result["audit_event"]["event_sha256"] and
                payload["receipt"] == result["receipt"] and payload["context"] == asdict(audit),
                "real_post_receipt_and_event_exact")
        require(nonce and nonce.state == "consumed" and nonce.consumed_at and
                nonce.command_sha256 == receipt.command_sha256 and
                nonce.action_sha256 == receipt.action_sha256,
                "real_nonce_consumed_and_receipt_bound")
        require(create_event.status == "CREATED" and event.attachment_id == create_event.attachment_id
                and payload["attachment"] == create_payload["attachment"] and
                event.attachment_id.raw == scope.document.raw and
                event.attachment_id.res_id == move.id and not event.attachment_id.public,
                "original_create_attachment_reused_exactly")

    def unchanged(self, scope, before):
        require(self.projection(scope) == before, "full_company_projection_unchanged")
        self.base.assert_persisted(scope)
        return {"full_company_projection_unchanged": True,
                "original_registered_create_preserved": True,
                "native_supplier_rank_unchanged": True,
                "financial_nonce_receipt_event_and_guards_unchanged": True,
                "projection_sha256": digest(before)}

    def committed(self):
        scope, registration = self.fixture()
        before = self.projection(scope)
        callbacks = []
        with self.registry.cursor() as cr:
            self.base.cursor_gate(cr)
            env = self.base.env(cr)
            cr.postcommit.add(lambda: callbacks.append(True))
            envelope, audit = self.post(env, scope, registration)
            self.verify_effect(env, scope, envelope["result"], audit)
            require(self.projection(scope) == before, "uncommitted_registered_post_invisible")
            require(not callbacks, "caller_callback_not_executed_early")
            cr.commit()
        require(callbacks == [True], "caller_callback_runs_once_after_real_commit")
        state = self.base.assert_persisted(scope, posted=True)
        require(state["rank"] == before["fixture"]["rank"] + 1,
                "real_native_supplier_rank_callback_committed")
        with self.registry.cursor() as cr:
            self.base.cursor_gate(cr)
            self.verify_effect(self.base.env(cr), scope, envelope["result"], audit)
        return {"target_derived_from_create_receipt": True, "fresh_cursor_exact_effect_verified": True,
                "original_pdf_reused": True, "nonce_consumed_once": True,
                "caller_callback_preserved": True, "native_supplier_rank_callback_committed": True,
                "caller_transaction_pending_verified": True, "projection_sha256": digest(state)}

    def replay(self):
        scope, registration = self.fixture()
        command_sha256 = self.command_hash(scope.post_command)
        with self.registry.cursor() as cr:
            self.base.cursor_gate(cr)
            envelope, audit = self.post(self.base.env(cr), scope, registration)
            self.verify_effect(self.base.env(cr), scope, envelope["result"], audit)
            cr.commit()
        before = self.base.assert_persisted(scope, posted=True)
        callbacks = []
        with self.registry.cursor() as cr:
            self.base.cursor_gate(cr)
            cr.postcommit.add(lambda: callbacks.append(True))
            replay, _ = self.post(self.base.env(cr), scope, registration)
            self.base.success(replay["result"], "REPLAY")
            require(replay["registration"] == envelope["registration"] and
                    replay["origin"] == envelope["origin"] and
                    replay["result"]["receipt"] == envelope["result"]["receipt"] and
                    replay["result"]["audit_event"]["original_event_id"] ==
                    envelope["result"]["audit_event"]["event_id"],
                    "replay_returns_original_origin_receipt_and_event_link")
            cr.commit()
        require(callbacks == [True], "replay_preserves_caller_callback")
        require(self.command_hash(scope.post_command) == command_sha256 and
                self.base.projection(scope) == before, "replay_no_new_financial_nonce_attachment_or_rank")
        return {"same_command_preserved": True, "original_origin_and_post_receipt_returned": True,
                "replay_event_links_original_post": True, "no_new_financial_effect_or_nonce": True,
                "no_new_attachment_or_supplier_rank": True, "caller_callback_preserved": True,
                "projection_sha256": digest(before)}

    def without_approval(self):
        scope, registration = self.fixture()
        before = self.projection(scope)
        command = copy.deepcopy(scope.post_command)
        command.pop("approval")
        rejected = False
        with self.registry.cursor() as cr:
            self.base.cursor_gate(cr)
            try:
                self.post(self.base.env(cr), scope, registration, command=command)
            except self.post_module.RegisteredPostError as error:
                require(error.code == "COMMAND_INVALID", "missing_approval_finite_structural_rejection")
                rejected = True
            require(rejected, "post_without_approval_rejected")
            cr.commit()
        return dict(self.unchanged(scope, before), approval_absent_rejected=True,
                    structural_rejection_before_financial_execution=True)

    def rollback(self, *, savepoint):
        scope, registration = self.fixture()
        before = self.projection(scope)
        callbacks = []
        with self.registry.cursor() as cr:
            self.base.cursor_gate(cr)
            env = self.base.env(cr)
            cr.postcommit.add(lambda: callbacks.append(True))
            if savepoint:
                try:
                    with cr.savepoint():
                        envelope, audit = self.post(env, scope, registration)
                        self.verify_effect(env, scope, envelope["result"], audit)
                        require(not callbacks, "savepoint_callback_not_executed_early")
                        raise InjectedFault()
                except InjectedFault:
                    pass
            else:
                envelope, audit = self.post(env, scope, registration)
                self.verify_effect(env, scope, envelope["result"], audit)
                require(not callbacks, "outer_callback_not_executed_early")
                cr.rollback()
            # Execute the actual parent commit and any guarded native callback.
            cr.commit()
        require(callbacks == ([True] if savepoint else []), "caller_callback_rollback_lifecycle_exact")
        return dict(self.unchanged(scope, before), real_post_observed_before_rollback=True,
                    external_rollback=True, rollback_scope="savepoint" if savepoint else "full-transaction",
                    parent_native_commit=True, caller_callback_lifecycle_exact=True,
                    caller_callback_lifecycle="preserved" if savepoint else "cleared-by-full-rollback")

    def fault(self):
        scope, registration = self.fixture()
        before = self.projection(scope)
        callbacks, observed = [], []
        with self.registry.cursor() as cr:
            self.base.cursor_gate(cr)
            env = self.base.env(cr)
            cr.postcommit.add(lambda: callbacks.append(True))

            def after_registered_post(result):
                self.base.success(result, "POSTED")
                event = env["ap.security.audit.event"].browse(result["audit_event"]["event_id"])
                audit = self.base.TrustedAuditContext(**event.event_payload["context"])
                self.verify_effect(env, scope, result, audit)
                require(not callbacks, "fault_callback_not_executed_early")
                observed.append(True)
                raise InjectedFault()

            rejected = False
            with patch.object(self.post_module, "_after_registered_post", after_registered_post):
                try:
                    self.post(env, scope, registration)
                except self.post_module.RegisteredPostError as error:
                    require(error.code == "EXECUTION_UNAVAILABLE", "post_effect_fault_has_finite_category")
                    rejected = True
            require(rejected and observed == [True], "real_registered_post_fault_observed_exactly_once")
            cr.commit()
        require(callbacks == [True], "fault_preserves_unrelated_parent_callback")
        return dict(self.unchanged(scope, before), real_post_receipt_event_and_nonce_seen_before_fault=True,
                    private_fault_seam_only=True, registered_outer_savepoint_rolled_back=True,
                    parent_native_commit=True, caller_callback_preserved=True)

    def run(self):
        operations = (self.committed, self.replay, self.without_approval,
                      lambda: self.rollback(savepoint=False), lambda: self.rollback(savepoint=True), self.fault)
        for name, operation in zip(CASE_IDS, operations, strict=True):
            try:
                checks = operation()
                self.cases.append({"case": name, "case_id": name, "status": "PASS", "checks": checks})
            except BaseException as error:
                if isinstance(error, ProbeFailure):
                    category = str(error)
                elif isinstance(error, self.post_module.RegisteredPostError) and error.code in self.post_module.ERROR_CODES:
                    category = "registered_post_" + error.code.lower()
                else:
                    category = "unexpected_runtime_failure"
                require(re.fullmatch(r"[a-z_]+", category), "safe_failure_category")
                self.cases.append({"case": name, "case_id": name, "status": "FAIL", "category": category,
                                   "failure_diagnostic": failure_diagnostic(error)})
                raise ProbeFailure(category) from None

    def evidence(self, *, status):
        return {
            "schema_version": "registered-post-transactions-evidence/v1", "status": status,
            "scope": "private-registered-post-native-lifecycle-only",
            "git_base": self.git_base, "source_bundle_sha256": self.source_bundle_sha256,
            "configuration_sha256": self.configuration_sha256,
            "cases": self.cases, "case_count": len(self.cases), "test_count": len(self.cases),
            "passed_case_count": sum(case["status"] == "PASS" for case in self.cases),
            "normal_registry": True, "test_cursor_used": False, "registry_test_mode": False,
            "mocked_sql_commit": False, "mocked_financial_method": False, "mocked_clock": False,
            "approval_material_emitted": False, "public_executor_enabled": False,
            "public_financial_effects_enabled": False, "scientific_run": False,
            "human_review_complete": False,
            "limitations": [
                "Private administrative module API, not public JSON-2 execution or a complete gateway POST.",
                "CREATE event proves equivalent audited workflow, not retroactive registered-entrypoint attestation.",
                "Declared source hashes identify the tested snapshot, not authenticated administrative authority.",
                "Projection is a development rollback check, not the independent scientific state oracle or reset.",
                "No POST registry concurrency claim, real API, scientific dataset, pilot, freeze or human acceptance.",
            ],
        }


def startup_evidence(args, error):
    """Report failed initialization without claiming an established registry."""
    return {
        "schema_version": "registered-post-transactions-evidence/v1", "status": "FAIL",
        "scope": "private-registered-post-native-lifecycle-only",
        "git_base": args.git_base, "source_bundle_sha256": args.source_bundle_sha256,
        "configuration_sha256": args.configuration_sha256,
        "cases": [], "case_count": 0, "test_count": 0, "passed_case_count": 0,
        "normal_registry": False, "test_cursor_used": False,
        "registry_test_mode": False, "mocked_sql_commit": False,
        "mocked_financial_method": False, "mocked_clock": False,
        "approval_material_emitted": False, "public_executor_enabled": False,
        "public_financial_effects_enabled": False, "scientific_run": False,
        "human_review_complete": False, "startup_failed": True,
        "startup_diagnostic": failure_diagnostic(error),
        "limitations": ["Initialization failed; normal-registry and native-case gates were not established."],
    }


def main():
    parser = argparse.ArgumentParser(description="Disposable private registered POST transaction probe")
    for name in ("config", "database", "evidence", "git-base", "source-bundle-sha256", "configuration-sha256"):
        parser.add_argument("--" + name, required=True)
    args = parser.parse_args()
    require(args.config == "/etc/odoo/c104.conf", "trusted_config_path")
    require(re.fullmatch(r"tcc_workflow_[0-9a-f]{12}", args.database), "disposable_database_namespace")
    require(args.evidence == "/mnt/c1-evidence/registered-post-transactions.json", "trusted_evidence_path")
    require(re.fullmatch(r"[0-9a-f]{40}", args.git_base), "declared_git_base_shape")
    require(re.fullmatch(r"[0-9a-f]{64}", args.source_bundle_sha256), "declared_source_bundle_shape")
    require(re.fullmatch(r"[0-9a-f]{64}", args.configuration_sha256), "declared_configuration_shape")
    # Expected PostgreSQL failures may log full SQL parameters. Disable runtime
    # logging before registry load and never print exception messages or traces.
    logging.disable(logging.CRITICAL)
    probe = None
    startup_failure = None
    status = "FAIL"
    try:
        odoo.tools.config.parse_config(["-c", args.config, "-d", args.database, "--no-http"], setup_logging=False)
        probe = RegisteredPostProbe(
            Registry(args.database), git_base=args.git_base, source_bundle_sha256=args.source_bundle_sha256,
            configuration_sha256=args.configuration_sha256,
        )
        probe.run()
        require(tuple(case["case_id"] for case in probe.cases) == CASE_IDS and
                all(case["status"] == "PASS" for case in probe.cases), "all_six_exact_cases_executed")
        status = "PASS"
    except BaseException as error:
        if probe is None:
            startup_failure = startup_evidence(args, error)
    result = startup_failure if probe is None else probe.evidence(status=status)
    Path(args.evidence).write_bytes(canonical(result) + b"\n")
    print("Registered POST " + status + " " + str(result["passed_case_count"]) + "/6 cases")
    return 0 if status == "PASS" else 1


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (ProbeFailure, Exception):
        print("Registered POST FAIL safe-runtime-category")
        raise SystemExit(1) from None
