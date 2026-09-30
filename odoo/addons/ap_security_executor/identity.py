# SPDX-License-Identifier: LGPL-3.0-or-later
"""Administrative C1 identity gate; no model method or credential generation.

The inventory describes model rights, not authorization of every public method.
Odoo still permits personal preferences, attachments and safe self-user writes.
"""

import hashlib
import json
import re

from odoo import SUPERUSER_ID, Command, api
from odoo.exceptions import AccessError, ValidationError


EXPLICIT_GROUPS = (
    "ap_security_executor.group_executor", "base.group_user",
)
EFFECTIVE_GROUPS = tuple(sorted((*EXPLICIT_GROUPS,
    "base.group_no_one", "purchase.group_send_reminder")))
OPERATIONS = ("read", "write", "create", "unlink")
NO_DIRECT_READ = frozenset({
    "account.move", "account.move.line", "account.payment",
    "account.payment.register", "purchase.order", "purchase.order.line",
})
NO_MASTER_MUTATION = frozenset({
    "res.partner", "res.partner.bank", "res.bank", "res.company",
    "res.users", "res.groups", "ir.config_parameter",
})
ERROR = "Executor identity configuration rejected."
LOGIN = re.compile(r"[a-z][a-z0-9_.-]{2,63}\Z")


def _admin_environment(env):
    if not (env.su or env.user.has_group("base.group_system")):
        raise AccessError("Administrative identity bootstrap required.")
    return api.Environment(env.cr, env.uid, {}, su=True)


def _xmlids(records):
    return records.get_external_id()


def _named(record, identifiers):
    return identifiers.get(record.id) or "<unmapped>"


def _validated_identity(env, user, company):
    if (getattr(user, "_name", None) != "res.users"
            or getattr(company, "_name", None) != "res.company"
            or user.env.cr is not env.cr or company.env.cr is not env.cr
            or len(user) != 1 or len(company) != 1):
        raise ValidationError(ERROR)
    user, company = env["res.users"].browse(user.id), env["res.company"].browse(company.id)
    if (not user.exists() or not company.exists() or not company.active
            or user.id == SUPERUSER_ID or not user.active or user.share
            or user.company_id != company or user.company_ids != company):
        raise ValidationError(ERROR)
    groups = env["res.groups"]
    explicit = groups.browse([env.ref(xmlid).id for xmlid in EXPLICIT_GROUPS])
    effective = groups.browse([env.ref(xmlid).id for xmlid in EFFECTIVE_GROUPS])
    if set(user.group_ids.ids) != set(explicit.ids) or set(user.all_group_ids.ids) != set(effective.ids):
        raise ValidationError(ERROR)
    partner = user.partner_id
    if (not partner or not partner.active or partner.parent_id
            or partner.commercial_partner_id != partner or partner.supplier_rank
            or partner.with_context(active_test=False).bank_ids
            or env["res.partner"].with_context(active_test=False).search_count([
                ("parent_id", "=", partner.id)], limit=1)
            or env["res.users"].with_context(active_test=False).search_count([
                ("partner_id", "=", partner.id)]) != 1
            or env["res.company"].with_context(active_test=False).search_count([
                ("partner_id", "=", partner.id)])
            or any(env[model_name].with_context(active_test=False).search_count([
                ("partner_id.commercial_partner_id", "=", partner.id)], limit=1)
                for model_name in ("account.move", "purchase.order"))):
        raise ValidationError(ERROR)
    return user, company


def assert_executor_identity(env, user, *, company):
    """Return only sanitized inventory, or reject drift without repairing it.

    Invoke from trusted administrative bootstrap or the pre-batch gate. Neither
    this helper nor its inventory grants a financial capability.
    """
    admin = _admin_environment(env)
    try:
        user, company = _validated_identity(admin, user, company)
        neutral = api.Environment(admin.cr, user.id, {
            "allowed_company_ids": [company.id], "force_company": company.id,
            "lang": "en_US", "tz": "UTC", "active_test": True,
        }, su=False)
        group_ids = user.all_group_ids.ids
        access = admin["ir.model.access"].search([
            ("active", "=", True), "|", ("group_id", "=", False),
            ("group_id", "in", group_ids),
        ])
        rules = admin["ir.rule"].search([
            ("active", "=", True), "|", ("groups", "=", False),
            ("groups", "in", group_ids),
        ])
        names = sorted(record.model for record in admin["ir.model"].search([])
                       if record.model in neutral)
        rights = []
        for model_name in names:
            flags = {operation: bool(neutral[model_name].browse().has_access(operation))
                     for operation in OPERATIONS}
            if (model_name in NO_MASTER_MUTATION
                    or model_name.startswith(("account.", "purchase."))):
                if any(flags[operation] for operation in OPERATIONS[1:]):
                    raise ValidationError(ERROR)
            if model_name in NO_DIRECT_READ and flags["read"]:
                raise ValidationError(ERROR)
            if model_name == "ap.security.executor" and flags != {
                    "read": True, "write": False, "create": False, "unlink": False}:
                raise ValidationError(ERROR)
            rights.append({"model": model_name, "permissions": flags})
        if not NO_DIRECT_READ.issubset(names) or "ap.security.executor" not in names:
            raise ValidationError(ERROR)

        access_ids, rule_ids = _xmlids(access), _xmlids(rules)
        groups = user.all_group_ids
        group_names = _xmlids(groups)
        acl_rows = [{
            "xml_id": _named(record, access_ids), "model": record.model_id.model,
            "group": _named(record.group_id, group_names) if record.group_id else "<global>",
            "permissions": {op: bool(record["perm_" + op]) for op in OPERATIONS},
        } for record in access]
        rule_rows = [{
            "xml_id": _named(record, rule_ids), "model": record.model_id.model,
            "global": not bool(record.groups),
            "groups": sorted(_named(group, group_names) for group in record.groups & groups),
            "permissions": {op: bool(record["perm_" + op]) for op in OPERATIONS},
            "domain_sha256": hashlib.sha256((record.domain_force or "").encode("utf-8")).hexdigest(),
        } for record in rules]
        stable = lambda row: json.dumps(row, sort_keys=True, separators=(",", ":"))
        inventory = {
            "schema_version": "executor-identity-inventory/v1",
            "explicit_groups": list(EXPLICIT_GROUPS),
            "effective_groups": list(EFFECTIVE_GROUPS),
            "single_company": True, "exclusive_personal_partner": True,
            "model_permissions": rights,
            "applicable_acls": sorted(acl_rows, key=stable),
            "applicable_rules": sorted(rule_rows, key=stable),
            "limits": ["MODEL_RIGHTS_NOT_PUBLIC_METHOD_AUTHORIZATION",
                       "PERSONAL_AND_ATTACHMENT_MUTATIONS_REMAIN",
                       "PERSONAL_DEFAULTS_UNTRUSTED_FOR_FUTURE_EXECUTION"],
        }
        inventory["inventory_sha256"] = hashlib.sha256(
            stable(inventory).encode("utf-8")).hexdigest()
        return inventory
    except (AccessError, KeyError, ValueError, ValidationError):
        raise ValidationError(ERROR) from None


def provision_executor_identity(env, *, login, company):
    """Provision an exact identity once; existing drift is never auto-repaired.

    No password, API key, external message or persistent credential is created.
    Caller supplies the trusted login/company, not a document or LLM proposal.
    """
    admin = _admin_environment(env)
    if type(login) is not str or not LOGIN.fullmatch(login):
        raise ValidationError(ERROR)
    if (getattr(company, "_name", None) != "res.company"
            or company.env.cr is not admin.cr or len(company) != 1
            or not company.exists() or not company.active):
        raise ValidationError(ERROR)
    users = admin["res.users"].with_context(active_test=False)
    existing = users.search([("login", "=", login)])
    if existing:
        assert_executor_identity(admin, existing, company=company)
        return existing
    try:
        with admin.cr.savepoint():
            user = users.with_context(
                no_reset_password=True, tracking_disable=True,
                mail_create_nolog=True, mail_create_nosubscribe=True,
            ).create({
                "name": "TCC restricted executor - synthetic identity",
                "login": login, "active": True,
                "company_id": company.id, "company_ids": [Command.set(company.ids)],
                "group_ids": [Command.set([admin.ref(xmlid).id for xmlid in EXPLICIT_GROUPS])],
                "lang": "en_US", "tz": "UTC",
            })
            assert_executor_identity(admin, user, company=company)
            return user
    except (AccessError, KeyError, ValueError, ValidationError):
        raise ValidationError(ERROR) from None
