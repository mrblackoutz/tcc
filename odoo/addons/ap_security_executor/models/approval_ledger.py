# SPDX-License-Identifier: LGPL-3.0-or-later
"""Private approval nonce storage, not an executable approval capability.

The API identity has no direct rights on this model. The administrative
transaction helper stores only hashes and technical bindings, reserves once,
and consumes after the enclosing operation succeeds without committing.
"""

from odoo import fields, models


class ApSecurityApprovalNonce(models.Model):
    _name = "ap.security.approval.nonce"
    _description = "Internal Accounts Payable Approval Nonce"
    _rec_name = "fixture_id"
    _order = "id"
    _check_company_auto = True

    company_id = fields.Many2one(
        "res.company", required=True, ondelete="restrict", index=True,
    )
    executor_user_id = fields.Many2one(
        "res.users", required=True, ondelete="restrict", index=True,
    )
    key_id = fields.Char(required=True)
    fixture_id = fields.Char(required=True)
    scenario_id = fields.Char(required=True)
    approver_ref = fields.Char(required=True)
    nonce_sha256 = fields.Char(required=True, index=True)
    action_sha256 = fields.Char(required=True)
    approval_sha256 = fields.Char(required=True)
    command_sha256 = fields.Char(required=True)
    state = fields.Selection(
        [("reserved", "Reserved"), ("consumed", "Consumed")],
        required=True,
    )
    verified_at = fields.Datetime(required=True)
    expires_at = fields.Datetime(required=True)
    consumed_at = fields.Datetime()

    _nonce_unique = models.Constraint(
        "UNIQUE (nonce_sha256)",
        "An approval nonce has already been reserved.",
    )
    _consumption_state = models.Constraint(
        "CHECK ((state = 'reserved' AND consumed_at IS NULL) "
        "OR (state = 'consumed' AND consumed_at IS NOT NULL))",
        "Approval nonce consumption metadata is inconsistent.",
    )
