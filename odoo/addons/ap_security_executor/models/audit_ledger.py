# SPDX-License-Identifier: LGPL-3.0-or-later
"""Operational audit storage with no ORM mutation capability.

Only the private, closed SQL writer can append an event. This is not protection
against a trusted database administrator or arbitrary SQL access. There is no
public API method, mutable status or authority contained in these records.
"""

from odoo import api, fields, models
from odoo.exceptions import AccessError


class ApSecurityAuditEvent(models.Model):
    _name = "ap.security.audit.event"
    _description = "Internal Accounts Payable Operational Audit Event"
    _rec_name = "run_id"
    _order = "id"
    _check_company_auto = True

    company_id = fields.Many2one(
        "res.company", required=True, ondelete="restrict", index=True,
    )
    executor_user_id = fields.Many2one(
        "res.users", required=True, ondelete="restrict", index=True,
    )
    run_id = fields.Char(required=True, index=True)
    attempt_id = fields.Char(required=True, index=True)
    executor_mode = fields.Selection(
        [("CREATE_DRAFT", "Create draft"), ("POST_APPROVED", "Post approved")],
        required=True, index=True,
    )
    status = fields.Selection(
        [("CREATED", "Created"), ("POSTED", "Posted"),
         ("REPLAY", "Replay"), ("DENIED", "Denied")],
        required=True, index=True,
    )
    receipt_id = fields.Many2one(
        "ap.security.draft.receipt", ondelete="restrict", check_company=True, index=True,
    )
    success_receipt_id = fields.Many2one(
        "ap.security.draft.receipt", ondelete="restrict", check_company=True, index=True,
    )
    original_event_id = fields.Many2one(
        "ap.security.audit.event", ondelete="restrict", check_company=True, index=True,
    )
    event_sha256 = fields.Char(required=True)
    event_payload = fields.Json(required=True)

    _success_receipt_unique = models.Constraint(
        "UNIQUE (success_receipt_id)",
        "An audit event already exists for this successful receipt.",
    )
    _operation_state = models.Constraint(
        "CHECK ((status = 'CREATED' AND executor_mode = 'CREATE_DRAFT') "
        "OR (status = 'POSTED' AND executor_mode = 'POST_APPROVED') "
        "OR (status IN ('REPLAY', 'DENIED') "
        "AND executor_mode IN ('CREATE_DRAFT', 'POST_APPROVED')))",
        "Audit operation and state are inconsistent.",
    )
    _receipt_links = models.Constraint(
        "CHECK ((status IN ('CREATED', 'POSTED') AND receipt_id IS NOT NULL "
        "AND success_receipt_id IS NOT NULL AND success_receipt_id = receipt_id "
        "AND original_event_id IS NULL) "
        "OR (status = 'REPLAY' AND receipt_id IS NOT NULL "
        "AND success_receipt_id IS NULL AND original_event_id IS NOT NULL) "
        "OR (status = 'DENIED' AND receipt_id IS NULL "
        "AND success_receipt_id IS NULL AND original_event_id IS NULL))",
        "Audit receipt and original event links are inconsistent.",
    )

    @api.model_create_multi
    def create(self, vals_list):
        raise AccessError("Audit events cannot be created through the ORM.")

    def write(self, vals):
        raise AccessError("Audit events are immutable.")

    def unlink(self):
        raise AccessError("Audit events are immutable.")
