# SPDX-License-Identifier: LGPL-3.0-or-later
"""Private workflow registration with genuine synthetic ORM records.

No inherited test cases, public financial execution or native commit/concurrency
claims. The separate normal-registry probe owns external transaction lifecycle.
"""

import copy
from dataclasses import FrozenInstanceError, asdict, replace
import hashlib
import json
from unittest.mock import patch

from psycopg2.extras import Json

from odoo import Command, SUPERUSER_ID, api
from odoo.exceptions import AccessError
from odoo.tests import TransactionCase, tagged

from .. import audit_kernel, workflow_registry
from ..audit_contracts import TrustedAuditContext
from ..document_contracts import SourceDocument
from ..workflow_contracts import WorkflowProvenance, registration_sha256
from .test_audit_kernel import AuditFixtureMixin, _synthetic_pdf


@tagged("post_install", "-at_install", "c1_workflow")
class TestWorkflowRegistration(AuditFixtureMixin, TransactionCase):
    """Reuse fixture helpers only: AuditFixtureMixin has no test_* methods."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.employee = cls.env["res.users"].with_context(no_reset_password=True).create({
            "name": "TCC REGISTRY EMPLOYEE - SEM VALOR FISCAL", "login": "tcc-workflow-employee",
            "company_id": cls.company.id, "company_ids": [Command.set(cls.company.ids)],
            "group_ids": [Command.set([cls.env.ref("base.group_user").id])],
        })

    def setUp(self):
        super().setUp()
        self.provenance = WorkflowProvenance(code_commit="a" * 40,
            code_sha256="sha256:" + "b" * 64, configuration_sha256="sha256:" + "c" * 64)

    def _register(self, *, env=None, workflow=None, document=None, provenance=None):
        return workflow_registry.register_draft_workflow(
            self.env if env is None else env, workflow=self.draft_workflow if workflow is None else workflow,
            document=self.document if document is None else document,
            provenance=self.provenance if provenance is None else provenance)

    def _resolve(self, registration, *, env=None, **changes):
        arguments = dict(registration_id=registration.registration_id,
            expected_company_id=self.company.id, expected_executor_user_id=self.executor_user.id,
            expected_scenario_id=self.draft_workflow.scenario_id,
            document=self.document, provenance=self.provenance)
        arguments.update(changes)
        return workflow_registry.resolve_draft_workflow(self.env if env is None else env, **arguments)

    def _rows(self):
        return self.env["ap.security.workflow.registration"].sudo().search([
            ("company_id", "=", self.company.id)], order="id")

    def _row(self, registration):
        return self.env["ap.security.workflow.registration"].sudo().browse(registration.registration_id)

    def _financial_projection(self):
        """Hash-only technical projection, explicitly not the freeze oracle."""
        # Native assertRaises/savepoint flushes precommit tracking. Materialize
        # fixture edits before the baseline, retaining all mail/effect checks.
        self.env.flush_all(); self.env.cr.flush(); self.env.invalidate_all()
        result = {}
        for model, fields in {
            "account.move": ["state", "move_type", "partner_id", "partner_bank_id", "amount_total", "ref", "invoice_origin", "auto_post"],
            "account.move.line": ["move_id", "purchase_line_id", "product_id", "quantity", "price_unit", "account_id", "debit", "credit", "tax_ids"],
            "res.partner": ["ref", "active", "supplier_rank", "autopost_bills"],
            "res.partner.bank": ["partner_id", "acc_number", "active", "allow_out_payment"],
            "purchase.order": ["partner_id", "currency_id", "state", "amount_total", "invoice_status"],
            "purchase.order.line": ["order_id", "product_id", "product_qty", "qty_invoiced", "qty_to_invoice", "price_unit", "tax_ids", "discount"],
            "ap.security.po.guard": ["po_id", "revision"],
            "ap.security.vendor.guard": ["vendor_id", "revision"],
            "ap.security.draft.receipt": ["executor_mode", "idempotency_key", "move_id", "receipt_payload"],
            "ap.security.audit.event": ["status", "receipt_id", "attachment_id", "event_sha256", "event_payload"],
            "ap.security.approval.nonce": ["state", "nonce_sha256", "command_sha256"],
        }.items():
            result[model] = self.env[model].sudo().with_context(active_test=False).search([
                ("company_id", "=", self.company.id)], order="id").read(fields)
        result["attachments"] = [{"id": record.id, "target": record.res_id,
            "metadata": record.read(["res_model", "company_id", "name", "mimetype", "file_size", "public", "store_fname"]),
            "raw_sha256": hashlib.sha256(record.raw or b"").hexdigest()}
            for record in self.env["ir.attachment"].sudo().search([
                ("company_id", "=", self.company.id)], order="id")]
        result["auxiliary_counts"] = {model: self.env[model].sudo().search_count([]) for model in (
            "account.payment", "account.partial.reconcile", "account.full.reconcile", "account.analytic.line",
            "mail.mail", "mail.notification", "mail.message", "ir.attachment")}
        result["attachment_storage"] = self.env["ir.config_parameter"].sudo().get_param("ir_attachment.location")
        return hashlib.sha256(json.dumps(result, sort_keys=True, separators=(",", ":"), default=str).encode()).hexdigest()

    def _error(self, operation, *, code=None):
        before = self._financial_projection()
        with self.assertRaises(workflow_registry.WorkflowRegistryError) as caught:
            operation()
        self.assertIn(caught.exception.code, workflow_registry.ERROR_CODES)
        if code:
            self.assertEqual(caught.exception.code, code)
        self.assertNotIn("SENSITIVE", str(caught.exception))
        self.assertEqual(self._financial_projection(), before)
        return caught.exception

    def _corrupt(self, registration, column, value, *, json_value=False):
        # Fixed trusted test column identifiers, bound synthetic values only.
        self.assertIn(column, {"registration_payload", "registration_sha256", "executor_user_id",
            "scenario_id", "document_sha256", "po_id", "vendor_id", "journal_id", "expense_account_id", "registrar_user_id"})
        self.env.flush_all()
        self.env.cr.execute('UPDATE ap_security_workflow_registration SET "' + column + '"=%s WHERE id=%s',
            (Json(value) if json_value else value, registration.registration_id))
        self.env["ap.security.workflow.registration"].invalidate_model()

    def test_register_real_row_without_financial_effects(self):
        before = self._financial_projection()
        registration = self._register()
        self.assertEqual(self._financial_projection(), before)
        self.assertEqual(len(self._rows()), 1)
        row = self._row(registration)
        self.assertEqual(row.registration_sha256, registration.registration_sha256)
        self.assertEqual(registration.workflow, self.draft_workflow)
        self.assertEqual(registration.provenance, self.provenance)
        self.assertEqual(row.registrar_user_id.id, self.env.uid)
        self.assertEqual(row.registration_sha256, registration_sha256(row.registration_payload))
        for field, expected in {
            "company_id": self.company.id, "executor_user_id": self.executor_user.id,
            "po_id": self.purchase.id, "vendor_id": self.vendor.id,
            "journal_id": self.journal.id, "expense_account_id": self.expense.id,
            "create_uid": self.env.uid, "write_uid": self.env.uid,
        }.items():
            self.assertEqual(row[field].id, expected)
        self.assertEqual(row.scenario_id, self.draft_workflow.scenario_id)
        self.assertEqual(row.document_sha256, self.draft_workflow.document_sha256)
        self.assertEqual(row.schema_version, "draft-workflow-registration/v1")

    def test_identical_same_actor_replay_returns_original_registration(self):
        original = self._register(); before = self._financial_projection()
        replay = self._register()
        self.assertEqual(replay, original)
        self.assertEqual(len(self._rows()), 1)
        self.assertEqual(self._financial_projection(), before)

    def test_resolve_reconstructs_typed_original_without_effect(self):
        original = self._register(); before = self._financial_projection()
        self.assertEqual(self._resolve(original), original)
        self.assertEqual(self._financial_projection(), before)

    def test_real_administrator_can_register_without_becoming_c1(self):
        administrator = self.env.ref("base.user_admin")
        registration = self._register(env=self.env(user=administrator.id, su=False))
        self.assertEqual(self._row(registration).registrar_user_id.id, administrator.id)
        self.assertNotEqual(administrator.id, self.executor_user.id)

    def test_other_administrator_can_resolve_but_cannot_replace_registrar(self):
        original = self._register()
        env = self.env(user=self.env.ref("base.user_admin").id, su=False)
        self.assertEqual(self._resolve(original, env=env), original)
        self._error(lambda: self._register(env=env), code="REGISTRATION_CONFLICT")
        self.assertEqual(self._row(original).registrar_user_id.id, self.env.uid)

    def test_restricted_executor_cannot_register_even_with_sudo(self):
        for sudo in (False, True):
            with self.subTest(sudo=sudo), self.assertRaises(AccessError):
                self._register(env=self.env(user=self.executor_user.id, su=sudo))
        self.assertFalse(self._rows())

    def test_employee_cannot_register_even_with_sudo(self):
        for sudo in (False, True):
            with self.subTest(sudo=sudo), self.assertRaises(AccessError):
                self._register(env=self.env(user=self.employee.id, su=sudo))
        self.assertFalse(self._rows())

    def test_executor_with_administrative_group_still_cannot_register(self):
        self.executor_user.write({"group_ids": [Command.link(self.env.ref("base.group_system").id)]})
        before = self._financial_projection()
        for sudo in (False, True):
            with self.subTest(sudo=sudo), self.assertRaises(AccessError):
                self._register(env=self.env(user=self.executor_user.id, su=sudo))
        self.assertFalse(self._rows())
        self.assertEqual(self._financial_projection(), before)

    def test_restricted_executor_cannot_resolve_even_with_sudo(self):
        registration = self._register()
        for sudo in (False, True):
            with self.subTest(sudo=sudo), self.assertRaises(AccessError):
                self._resolve(registration, env=self.env(user=self.executor_user.id, su=sudo))

    def test_employee_cannot_resolve_even_with_sudo(self):
        registration = self._register()
        for sudo in (False, True):
            with self.subTest(sudo=sudo), self.assertRaises(AccessError):
                self._resolve(registration, env=self.env(user=self.employee.id, su=sudo))

    def test_c1_has_no_registration_model_permissions(self):
        model = self.env["ap.security.workflow.registration"].with_user(self.executor_user)
        self.assertFalse(any(model.browse().has_access(operation) for operation in ("read", "create", "write", "unlink")))

    def test_registration_orm_create_write_unlink_are_denied_including_sudo(self):
        registration = self._register(); row = self._row(registration)
        for record in (row, row.sudo()):
            for operation in (lambda record=record: record.create({}),
                              lambda record=record: record.write({"scenario_id": "TCC-SCN-002"}),
                              lambda record=record: record.unlink()):
                with self.assertRaises(AccessError):
                    operation()
        self.assertTrue(row.exists())

    def test_hostile_context_does_not_change_registered_workflow(self):
        env = api.Environment(self.env.cr, SUPERUSER_ID, {
            "allowed_company_ids": [self.other_company.id], "force_company": self.other_company.id,
            "default_company_id": self.other_company.id, "default_vendor_id": self.other_vendor.id,
            "default_scenario_id": "TCC-SCN-ATTACK", "default_registration_sha256": "SENSITIVE-MARKER",
            "lang": "en_US", "tz": "UTC", "active_test": False}, su=True)
        registration = self._register(env=env)
        self.assertEqual(registration.workflow, self.draft_workflow)
        self.assertEqual(self._resolve(registration, env=env), registration)

    def test_document_hash_drift_cannot_rebind_registration(self):
        original = self._register()
        raw = _synthetic_pdf("TCC DIFFERENT DOCUMENT SEM VALOR FISCAL")
        document = SourceDocument(raw=raw, mimetype="application/pdf")
        self._error(lambda: self._resolve(original, document=document), code="DOCUMENT_HASH_MISMATCH")

    def test_document_contract_mime_and_bytes_fail_closed(self):
        for document in (SourceDocument(raw=self.document.raw, mimetype="text/plain"),
                         SourceDocument(raw=b"", mimetype="application/pdf"),
                         SourceDocument(raw=bytearray(self.document.raw), mimetype="application/pdf")):
            with self.subTest(kind=type(document.raw).__name__):
                self._error(lambda document=document: self._register(document=document))
        self.assertFalse(self._rows())

    def test_document_limit_cannot_be_bypassed_by_declared_workflow_hash(self):
        raw = b"%PDF-" + b"x" * 1_048_572
        workflow = replace(self.draft_workflow, document_sha256=hashlib.sha256(raw).hexdigest())
        self._error(lambda: self._register(workflow=workflow,
            document=SourceDocument(raw=raw, mimetype="application/pdf")), code="DOCUMENT_TOO_LARGE")

    def test_new_document_same_binding_is_conflict_not_update(self):
        original = self._register()
        raw = _synthetic_pdf("TCC NEW CONTENT SAME BINDING SEM VALOR FISCAL")
        workflow = replace(self.draft_workflow, document_sha256=hashlib.sha256(raw).hexdigest())
        self._error(lambda: self._register(workflow=workflow,
            document=SourceDocument(raw=raw, mimetype="application/pdf")), code="REGISTRATION_CONFLICT")
        self.assertEqual(self._resolve(original), original)

    def test_changed_configuration_same_binding_is_conflict(self):
        original = self._register()
        self._error(lambda: self._register(workflow=replace(self.draft_workflow,
            monetary_tolerance="0.01")), code="REGISTRATION_CONFLICT")
        self.assertEqual(self._resolve(original), original)

    def test_changed_provenance_same_binding_is_conflict(self):
        original = self._register()
        changed = replace(self.provenance, configuration_sha256="sha256:" + "d" * 64)
        self._error(lambda: self._register(provenance=changed), code="REGISTRATION_CONFLICT")
        self._error(lambda: self._resolve(original, provenance=changed), code="REGISTRATION_PROVENANCE_MISMATCH")

    def test_expected_company_executor_and_scenario_are_mandatory_bindings(self):
        original = self._register()
        for name, value in (("expected_company_id", self.other_company.id),
                            ("expected_executor_user_id", self.employee.id),
                            ("expected_scenario_id", "TCC-SCN-002")):
            with self.subTest(field=name):
                self._error(lambda name=name, value=value: self._resolve(original, **{name: value}),
                            code="REGISTRATION_BINDING_MISMATCH")

    def test_unknown_registration_is_not_adopted(self):
        original = self._register()
        self._error(lambda: self._resolve(original, registration_id=original.registration_id + 100000),
                    code="REGISTRATION_NOT_FOUND")

    def test_registration_identity_requires_exact_integer(self):
        original = self._register()
        for value in (True, 0, -1, "1", 1.0):
            with self.subTest(kind=type(value).__name__):
                self._error(lambda value=value: self._resolve(original, registration_id=value), code="CONTRACT_INVALID")

    def test_expected_scope_types_are_revalidated_without_coercion(self):
        original = self._register()
        for name, values in (
            ("expected_company_id", (True, 0, "1", 1.0)),
            ("expected_executor_user_id", (True, 0, "1", 1.0)),
            ("expected_scenario_id", (None, True, "", "SENSITIVE SCENARIO")),
        ):
            for value in values:
                with self.subTest(field=name, kind=type(value).__name__):
                    self._error(lambda name=name, value=value: self._resolve(original, **{name: value}),
                                code="CONTRACT_INVALID")

    def test_registration_hash_column_corruption_is_rejected(self):
        original = self._register()
        self._corrupt(original, "registration_sha256", "sha256:" + "d" * 64)
        self._error(lambda: self._resolve(original), code="REGISTRATION_INTEGRITY_INVALID")

    def test_registration_unknown_json_fields_and_values_are_rejected(self):
        original = self._register()
        original_body = copy.deepcopy(self._row(original).registration_payload)
        for change in ({"extra": "SENSITIVE-MARKER"}, {"label": "adversarial"}, {"approval": {}}):
            with self.subTest(field=next(iter(change))), self.env.cr.savepoint():
                body = copy.deepcopy(original_body); body.update(change)
                self._corrupt(original, "registration_payload", body, json_value=True)
                self._error(lambda: self._resolve(original), code="REGISTRATION_INTEGRITY_INVALID")
                self._corrupt(original, "registration_payload", original_body, json_value=True)
                self.assertEqual(self._resolve(original), original)

    def test_registration_nonobject_json_is_rejected(self):
        original = self._register()
        self._corrupt(original, "registration_payload", ["SENSITIVE-MARKER"], json_value=True)
        self._error(lambda: self._resolve(original), code="REGISTRATION_INTEGRITY_INVALID")

    def test_denormalized_columns_cannot_disagree_with_payload(self):
        original = self._register()
        original_body = copy.deepcopy(self._row(original).registration_payload)
        for column, value in (("scenario_id", "TCC-SCN-CHANGED"), ("document_sha256", "d" * 64),
                              ("vendor_id", self.other_vendor.id), ("executor_user_id", self.employee.id),
                              ("registrar_user_id", self.employee.id)):
            with self.subTest(column=column):
                self._corrupt(original, column, value)
                self._error(lambda: self._resolve(original), code="REGISTRATION_INTEGRITY_INVALID")
                baseline = {"scenario_id": self.draft_workflow.scenario_id,
                    "document_sha256": self.draft_workflow.document_sha256, "vendor_id": self.vendor.id,
                    "executor_user_id": self.executor_user.id, "registrar_user_id": self.env.uid}
                self._corrupt(original, column, baseline[column])
        self.assertEqual(self._row(original).registration_payload, original_body)

    def test_registration_records_no_raw_pdf_or_proposal_or_approval(self):
        row = self._row(self._register())
        body = row.registration_payload
        self.assertEqual(set(body), {"schema_version", "workflow", "document", "provenance", "registrar_user_id"})
        encoded = json.dumps(body, sort_keys=True)
        self.assertNotIn("%PDF", encoded)
        self.assertNotIn("SEM VALOR FISCAL", encoded)
        self.assertEqual(body["document"]["byte_count"], len(self.document.raw))

    def test_frozen_resolved_configuration_cannot_be_mutated(self):
        resolved = self._register()
        with self.assertRaises(FrozenInstanceError):
            resolved.workflow.vendor_id = self.other_vendor.id
        with self.assertRaises(FrozenInstanceError):
            resolved.registration_id = 0
        with self.assertRaises(FrozenInstanceError):
            resolved.provenance.code_commit = "d" * 40

    def test_frozen_objects_are_reconstructed_not_assumed_valid(self):
        for field, value in (("company_id", True), ("phase", "POST_REVIEW"),
                             ("invoice_date_min", "2026-09-31"), ("quantity_scale", True)):
            forged = replace(self.draft_workflow)
            object.__setattr__(forged, field, value)
            with self.subTest(field=field):
                self._error(lambda forged=forged: self._register(workflow=forged), code="CONTRACT_INVALID")
        forged_provenance = replace(self.provenance)
        object.__setattr__(forged_provenance, "code_commit", "SENSITIVE-MARKER")
        self._error(lambda: self._register(provenance=forged_provenance), code="CONTRACT_INVALID")
        forged_document = replace(self.document)
        object.__setattr__(forged_document, "raw", bytearray(self.document.raw))
        self._error(lambda: self._register(document=forged_document), code="DOCUMENT_INVALID")
        self.assertFalse(self._rows())

    def test_global_defaults_are_not_consumed_or_repaired(self):
        defaults = self.env["ir.default"].sudo()
        defaults.set("ap.security.workflow.registration", "scenario_id", "TCC-SCN-ATTACK", company_id=self.company.id)
        count = defaults.search_count([])
        self._error(self._register, code="REGISTRATION_DEFAULTS_INVALID")
        self.assertEqual(defaults.search_count([]), count)
        self.assertFalse(self._rows())

    def test_service_defaults_are_not_consumed_or_repaired(self):
        original = self._register()
        defaults = self.env["ir.default"].sudo()
        defaults.set("ap.security.workflow.registration", "scenario_id", "TCC-SCN-ATTACK",
                     user_id=SUPERUSER_ID, company_id=self.company.id)
        rows = defaults.search([]).read(["field_id", "user_id", "company_id", "json_value"])
        self._error(self._register, code="REGISTRATION_DEFAULTS_INVALID")
        self._error(lambda: self._resolve(original), code="REGISTRATION_DEFAULTS_INVALID")
        self.assertEqual(defaults.search([]).read(["field_id", "user_id", "company_id", "json_value"]), rows)
        self.assertEqual(len(self._rows()), 1)

    def test_executor_identity_drift_is_not_repaired(self):
        self.executor_user.write({"group_ids": [Command.link(self.env.ref("account.group_account_invoice").id)]})
        self._error(self._register, code="EXECUTOR_IDENTITY_INVALID")
        self.assertFalse(self._rows())

    def test_bank_trust_loss_denies_registration_and_resolution(self):
        original = self._register()
        self.bank.allow_out_payment = False
        self._error(self._register, code="BANK_NOT_ALLOWED")
        self._error(lambda: self._resolve(original), code="BANK_NOT_ALLOWED")

    def test_inactive_vendor_binding_drift_is_rejected(self):
        original = self._register()
        self.vendor.active = False
        self._error(lambda: self._resolve(original), code="WORKFLOW_STATE_INVALID")

    def test_unconfirmed_purchase_binding_drift_is_rejected(self):
        original = self._register()
        self.purchase.write({"state": "draft"})
        self._error(lambda: self._resolve(original), code="WORKFLOW_STATE_INVALID")

    def test_fault_after_real_registration_insert_rolls_back(self):
        before = self._financial_projection(); seen = []
        def fail(record):
            self.assertTrue(record.exists())
            self.assertTrue(record.registration_payload)
            seen.append(True)
            raise RuntimeError("SENSITIVE-FAULT-MARKER")
        with patch.object(workflow_registry, "_after_registration_insert", side_effect=fail):
            self._error(self._register, code="REGISTRATION_UNAVAILABLE")
        self.assertEqual(seen, [True])
        self.assertFalse(self._rows())
        self.assertEqual(self._financial_projection(), before)
        self.assertTrue(self._row(self._register()).exists())

    def test_outer_savepoint_rollback_removes_real_registration(self):
        before = self._financial_projection()
        class DeliberateRollback(Exception):
            pass
        try:
            with self.env.cr.savepoint():
                self.assertTrue(self._row(self._register()).exists())
                raise DeliberateRollback()
        except DeliberateRollback:
            pass
        self.env.invalidate_all()
        self.assertFalse(self._rows())
        self.assertEqual(self._financial_projection(), before)

    def test_public_execute_stays_closed_after_registration(self):
        self._register(); before = self._financial_projection()
        result = self.env["ap.security.executor"].with_user(self.executor_user).execute(self.draft_command)
        self.assertEqual(result["executor_status"], "SCAFFOLD_NOT_READY")
        self.assertIs(result["effect_applied"], False)
        self.assertEqual(self._financial_projection(), before)

    def test_resolved_workflow_is_compatible_with_private_audited_create(self):
        original = self._register(); resolved = self._resolve(original)
        audit = TrustedAuditContext(run_id="TCC-WORKFLOW-COMPAT", attempt_id="d" * 32,
            **asdict(self.provenance))
        result = audit_kernel.create_draft_audited(self.env, command=self.draft_command,
            workflow=resolved.workflow, audit=audit, document=self.document)
        self.assertEqual(result.get("status"), "CREATED")
        self.assertIs(result.get("audit_complete"), True)
        move = self.env["account.move"].browse(result["receipt"]["move_id"])
        self.assertEqual(move.state, "draft")
        self.assertEqual(move.partner_bank_id, self.bank)
        event = self.env["ap.security.audit.event"].browse(result["audit_event"]["event_id"])
        self.assertEqual(event.attachment_id.raw, self.document.raw)
        self.assertEqual(self._resolve(original), original)
