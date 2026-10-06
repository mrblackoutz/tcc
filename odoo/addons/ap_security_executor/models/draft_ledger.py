# SPDX-License-Identifier: LGPL-3.0-or-later
"""Internal transactional storage; no capability is granted to the API user.

These records are consumed only by the private draft and approved POST kernels.
Their existence does not enable the public executor or replace later audit gates.
"""

from odoo import fields, models


class ApSecurityDraftReceipt(models.Model):
    _name = "ap.security.draft.receipt"
    _description = "Internal Accounts Payable Idempotency Receipt"
    _rec_name = "idempotency_key"
    _order = "id"
    _check_company_auto = True

    company_id = fields.Many2one("res.company", required=True, ondelete="restrict", index=True)
    executor_mode = fields.Selection(
        [("CREATE_DRAFT", "Create draft"), ("POST_APPROVED", "Post approved")],
        required=True, index=True,
    )
    idempotency_key = fields.Char(required=True, index=True)
    command_sha256 = fields.Char(required=True)
    action_sha256 = fields.Char(required=True)
    document_sha256 = fields.Char(required=True, index=True)
    po_id = fields.Many2one(
        "purchase.order", required=True, ondelete="restrict", check_company=True, index=True,
    )
    vendor_id = fields.Many2one(
        "res.partner", required=True, ondelete="restrict", check_company=True,
    )
    purchase_line_ids = fields.Many2many(
        "purchase.order.line", relation="ap_security_receipt_purchase_line_rel",
        column1="receipt_id", column2="purchase_line_id", required=True, check_company=True,
    )
    move_id = fields.Many2one(
        "account.move", required=True, ondelete="restrict", check_company=True, index=True,
    )
    executor_user_id = fields.Many2one("res.users", required=True, ondelete="restrict", index=True)
    receipt_payload = fields.Json(required=True)

    _operation_unique = models.Constraint(
        "UNIQUE (company_id, executor_mode, idempotency_key)",
        "An idempotency receipt already exists for this operation.",
    )
    _document_unique = models.Constraint(
        "UNIQUE (company_id, executor_mode, document_sha256)",
        "A receipt already exists for this registered document and operation.",
    )


class ApSecurityPoGuard(models.Model):
    _name = "ap.security.po.guard"
    _description = "Internal Purchase Order Serialization Guard"
    _rec_name = "po_id"
    _order = "id"
    _check_company_auto = True

    company_id = fields.Many2one("res.company", required=True, ondelete="restrict", index=True)
    po_id = fields.Many2one(
        "purchase.order", required=True, ondelete="restrict", check_company=True, index=True,
    )
    revision = fields.Integer(required=True, default=0)

    _po_unique = models.Constraint(
        "UNIQUE (company_id, po_id)",
        "A serialization guard already exists for this purchase order.",
    )


class ApSecurityVendorGuard(models.Model):
    _name = "ap.security.vendor.guard"
    _description = "Internal Supplier Document Serialization Guard"
    _rec_name = "vendor_id"
    _order = "id"
    _check_company_auto = True

    company_id = fields.Many2one("res.company", required=True, ondelete="restrict", index=True)
    vendor_id = fields.Many2one(
        "res.partner", required=True, ondelete="restrict", check_company=True, index=True,
    )
    revision = fields.Integer(required=True, default=0)

    _vendor_unique = models.Constraint(
        "UNIQUE (company_id, vendor_id)",
        "A serialization guard already exists for this supplier and company.",
    )
