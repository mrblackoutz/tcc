# SPDX-License-Identifier: LGPL-3.0-or-later
"""Immutable private workflow declarations; only the closed SQL helper writes.

This boundary protects against ORM/RPC mutation, not an administrator with
arbitrary SQL access. It contains no PDF bytes or executable financial authority.
"""

from odoo import api, fields, models
from odoo.exceptions import AccessError


class ApSecurityWorkflowRegistration(models.Model):
    _name = "ap.security.workflow.registration"
    _description = "Internal Documentary Draft Workflow Registration"
    _rec_name = "scenario_id"
    _order = "id"
    _check_company_auto = True

    company_id = fields.Many2one("res.company", required=True, ondelete="restrict", index=True)
    executor_user_id = fields.Many2one("res.users", required=True, ondelete="restrict", index=True)
    registrar_user_id = fields.Many2one("res.users", required=True, ondelete="restrict", index=True)
    po_id = fields.Many2one("purchase.order", required=True, ondelete="restrict", check_company=True)
    vendor_id = fields.Many2one("res.partner", required=True, ondelete="restrict", check_company=True)
    journal_id = fields.Many2one("account.journal", required=True, ondelete="restrict", check_company=True)
    expense_account_id = fields.Many2one("account.account", required=True, ondelete="restrict", check_company=True)
    scenario_id = fields.Char(required=True, index=True)
    document_sha256 = fields.Char(required=True, index=True)
    schema_version = fields.Char(required=True)
    registration_sha256 = fields.Char(required=True)
    registration_payload = fields.Json(required=True)

    _binding_unique = models.Constraint(
        "UNIQUE (company_id, scenario_id)",
        "A private workflow registration already exists for this company and scenario.",
    )

    @api.model_create_multi
    def create(self, vals_list):
        raise AccessError("Workflow registrations cannot be created through the ORM.")

    def write(self, vals):
        raise AccessError("Workflow registrations are immutable.")

    def unlink(self):
        raise AccessError("Workflow registrations are immutable.")
