# SPDX-License-Identifier: LGPL-3.0-or-later
"""C1-05 identity and inventory, using synthetic fixtures only."""

import json

from odoo import Command, api
from odoo.exceptions import AccessError, ValidationError
from odoo.tests import TransactionCase, tagged

from ..identity import (
    EFFECTIVE_GROUPS, ERROR, EXPLICIT_GROUPS, NO_DIRECT_READ,
    assert_executor_identity, provision_executor_identity,
)


@tagged("post_install", "-at_install", "c1_identity")
class TestExecutorIdentity(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env["res.company"].create({
            "name": "TCC C1 identity - no fiscal value",
        })
        cls.other_company = cls.env["res.company"].create({
            "name": "TCC other identity company - no fiscal value",
        })
        cls.user = provision_executor_identity(
            cls.env, login="tcc-c1-identity-test", company=cls.company,
        )

    def _gate(self):
        return assert_executor_identity(self.env, self.user, company=self.company)

    def _reject(self):
        with self.assertRaisesRegex(ValidationError, "^" + ERROR.replace(".", r"\.") + "$"):
            self._gate()

    def test_exact_groups_and_single_company(self):
        identifiers = self.user.all_group_ids.get_external_id()
        self.assertEqual(set(identifiers.values()), set(EFFECTIVE_GROUPS))
        self.assertEqual(set(self.user.group_ids.get_external_id().values()), set(EXPLICIT_GROUPS))
        self.assertEqual(self.user.company_id, self.company)
        self.assertEqual(self.user.company_ids, self.company)
        self.assertTrue(self.user.active)
        self.assertFalse(self.user.share)

    def test_repeat_provision_does_not_write_or_create(self):
        models = ("res.users", "res.partner", "res.users.apikeys", "account.move", "mail.mail")
        before = {name: self.env[name].search_count([]) for name in models}
        write_date = self.user.write_date
        repeated = provision_executor_identity(
            self.env, login="tcc-c1-identity-test", company=self.company,
        )
        self.assertEqual(repeated, self.user)
        self.assertEqual(self.user.write_date, write_date)
        self.assertEqual(before, {name: self.env[name].search_count([]) for name in models})
        self.assertFalse(self.user.api_key_ids)

    def test_sanitized_inventory_and_permissions(self):
        inventory = self._gate()
        self.assertEqual(inventory, self._gate())
        self.assertEqual(inventory["schema_version"], "executor-identity-inventory/v1")
        rights = {row["model"]: row["permissions"] for row in inventory["model_permissions"]}
        self.assertEqual(rights["ap.security.executor"], {
            "read": True, "write": False, "create": False, "unlink": False,
        })
        for name in NO_DIRECT_READ:
            self.assertFalse(any(rights[name].values()), "Critical model access was granted.")
        for name in ("res.partner", "res.partner.bank"):
            self.assertEqual(rights[name], {
                "read": True, "write": False, "create": False, "unlink": False,
            })
        encoded = json.dumps(inventory, sort_keys=True)
        self.assertFalse(self.user.login in encoded, "Inventory contains identity data.")
        self.assertFalse(self.user.name in encoded, "Inventory contains identity data.")
        self.assertTrue(inventory["applicable_acls"])
        self.assertTrue(inventory["applicable_rules"])
        for row in inventory["applicable_rules"]:
            self.assertNotIn("domain_force", row)
            self.assertEqual(len(row["domain_sha256"]), 64)
        self.assertEqual(len(inventory["inventory_sha256"]), 64)

    def test_financial_group_drift_not_repaired(self):
        group = self.env.ref("account.group_account_invoice")
        self.user.write({"group_ids": [Command.link(group.id)]})
        groups = self.user.group_ids
        self._reject()
        with self.assertRaisesRegex(ValidationError, "configuration rejected"):
            provision_executor_identity(self.env, login="tcc-c1-identity-test", company=self.company)
        self.assertEqual(self.user.group_ids, groups)

    def test_missing_executor_group_rejected(self):
        self.user.write({"group_ids": [Command.unlink(self.env.ref("ap_security_executor.group_executor").id)]})
        self._reject()

    def test_inactive_identity_rejected_without_reactivation(self):
        self.user.active = False
        self._reject()
        with self.assertRaisesRegex(ValidationError, "configuration rejected"):
            provision_executor_identity(self.env, login="tcc-c1-identity-test", company=self.company)
        self.assertFalse(self.user.active)

    def test_company_drift_rejected(self):
        self.user.write({
            "company_id": self.other_company.id,
            "company_ids": [Command.set(self.other_company.ids)],
        })
        self._reject()
        self.assertEqual(self.user.company_id, self.other_company)

    def test_multiple_companies_rejected(self):
        self.user.company_ids = [Command.set((self.company | self.other_company).ids)]
        self._reject()

    def test_supplier_partner_rejected(self):
        self.user.partner_id.supplier_rank = 1
        self._reject()
        self.assertEqual(self.user.partner_id.supplier_rank, 1)

    def test_company_partner_rejected(self):
        self.company.partner_id = self.user.partner_id
        self._reject()

    def test_nonexclusive_partner_rejected(self):
        self.env["res.users"].with_context(no_reset_password=True).create({
            "name": "TCC second synthetic identity", "login": "tcc-c1-partner-duplicate",
            "partner_id": self.user.partner_id.id,
            "company_id": self.company.id, "company_ids": [Command.set(self.company.ids)],
            "group_ids": [Command.set(self.user.group_ids.ids)],
        })
        self._reject()

    def test_parented_partner_rejected(self):
        self.user.partner_id.parent_id = self.env["res.partner"].create({
            "name": "TCC unrelated synthetic parent",
        })
        self._reject()

    def test_partner_bank_rejected(self):
        self.env["res.partner.bank"].create({
            "partner_id": self.user.partner_id.id, "acc_number": "TCC-NOT-A-REAL-ACCOUNT",
            "allow_out_payment": False,
        })
        self._reject()

    def test_archived_partner_bank_rejected(self):
        self.env["res.partner.bank"].create({
            "partner_id": self.user.partner_id.id, "acc_number": "TCC-ARCHIVED-NOT-A-REAL-ACCOUNT",
            "allow_out_payment": False, "active": False,
        })
        self._reject()

    def test_archived_duplicate_user_rejected(self):
        archived = self.env["res.users"].with_context(no_reset_password=True).create({
            "name": "TCC archived synthetic identity", "login": "tcc-c1-archived-duplicate",
            "active": False,
            "company_id": self.company.id, "company_ids": [Command.set(self.company.ids)],
            "group_ids": [Command.set(self.user.group_ids.ids)],
        })
        # Creating an archived user on an active shared partner is rejected by
        # core. Assign the partner afterwards to exercise admin-created drift.
        archived.partner_id = self.user.partner_id
        self._reject()

    def test_rank_zero_purchase_partner_rejected(self):
        self.env["purchase.order"].with_context(tracking_disable=True).create({
            "name": "TCC-IDENTITY-PO-NO-FISCAL-VALUE",
            "company_id": self.company.id, "partner_id": self.user.partner_id.id,
        })
        self.user.partner_id.supplier_rank = 0
        self._reject()

    def test_rank_zero_draft_bill_partner_rejected(self):
        journal = self.env["account.journal"].create({
            "name": "TCC identity journal - no fiscal value", "code": "IDTCC",
            "type": "purchase", "company_id": self.company.id,
        })
        self.env["account.move"].with_context(tracking_disable=True).create({
            "move_type": "in_invoice", "journal_id": journal.id,
            "company_id": self.company.id, "partner_id": self.user.partner_id.id,
            "invoice_date": "2026-09-30",
        })
        self.user.partner_id.supplier_rank = 0
        self._reject()

    def test_commercial_partner_of_purchase_contact_rejected(self):
        child = self.env["res.partner"].create({
            "name": "TCC synthetic financial contact", "parent_id": self.user.partner_id.id,
        })
        self.env["purchase.order"].with_context(tracking_disable=True).create({
            "name": "TCC-IDENTITY-CHILD-PO-NO-FISCAL-VALUE",
            "company_id": self.company.id, "partner_id": child.id,
        })
        self.user.partner_id.supplier_rank = 0
        self._reject()

    def test_archived_child_without_business_record_rejected(self):
        self.env["res.partner"].create({
            "name": "TCC archived synthetic personal contact",
            "parent_id": self.user.partner_id.id, "active": False,
        })
        self._reject()

    def test_financial_acl_drift_rejected_without_repair(self):
        acl = self.env["ir.model.access"].create({
            "name": "TCC accidental synthetic finance ACL",
            "model_id": self.env["ir.model"]._get("account.move").id,
            "group_id": self.env.ref("ap_security_executor.group_executor").id,
            "perm_read": True, "perm_write": False, "perm_create": False, "perm_unlink": False,
        })
        self._reject()
        self.assertTrue(acl.perm_read)

    def test_service_acl_drift_rejected_without_repair(self):
        acl = self.env.ref("ap_security_executor.access_executor_read")
        acl.perm_write = True
        self._reject()
        self.assertTrue(acl.perm_write)

    def test_unprivileged_bootstrap_and_inventory_rejected(self):
        neutral = api.Environment(self.env.cr, self.user.id, {}, su=False)
        with self.assertRaisesRegex(AccessError, "Administrative identity bootstrap required"):
            provision_executor_identity(neutral, login="tcc-c1-no-authority", company=self.company)
        with self.assertRaisesRegex(AccessError, "Administrative identity bootstrap required"):
            assert_executor_identity(neutral, self.user, company=self.company)

    def test_invalid_login_and_company_rejected_without_creation(self):
        before = self.env["res.users"].search_count([])
        for login in (None, "", "x", "Contains Space", "tcc@example.invalid", "tcc\nidentity", "a" * 65):
            with self.subTest(case=type(login).__name__):
                with self.assertRaisesRegex(ValidationError, "configuration rejected"):
                    provision_executor_identity(self.env, login=login, company=self.company)
        with self.assertRaisesRegex(ValidationError, "configuration rejected"):
            provision_executor_identity(self.env, login="tcc-c1-invalid-company", company=self.env["res.company"])
        self.assertEqual(before, self.env["res.users"].search_count([]))

    def test_global_financial_acl_drift_rolls_back_new_identity(self):
        self.env["ir.model.access"].create({
            "name": "TCC accidental global bank ACL",
            "model_id": self.env["ir.model"]._get("res.partner.bank").id,
            "perm_read": True, "perm_write": True, "perm_create": False, "perm_unlink": False,
        })
        before = self.env["res.users"].search_count([])
        with self.assertRaisesRegex(ValidationError, "configuration rejected"):
            provision_executor_identity(self.env, login="tcc-c1-reject-created", company=self.company)
        self.assertEqual(before, self.env["res.users"].search_count([]))
