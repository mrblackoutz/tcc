"""Bootstrap determinístico do marco M1 com dados sintéticos sem valor fiscal.

Executado por ``odoo-bin shell`` como superusuário. O único segredo produzido é
a chave RPC da identidade C0, gravada no volume local ignorado pelo Git.
"""

from __future__ import annotations

import datetime as dt
import json
import os
from pathlib import Path

from odoo import Command, fields


SCENARIO_ID = "M1-SYNTHETIC-001"
COMPANY_NAME = "TCC LAB - SEM VALOR FISCAL"
VENDOR_REF = "TCC-M1-VENDOR"
VENDOR_NAME = "Fornecedor Sintético M1 - SEM VALOR FISCAL"
BANK_ACCOUNT = "TCC-SYNTHETIC-BANK-0001"
PRODUCT_CODE = "TCC-M1-SERVICE"
PRODUCT_NAME = "Serviço Sintético M1 - SEM VALOR FISCAL"
PURCHASE_ORDER_REF = "TCC-M1-PO-001"
DOCUMENT_REF = "TCC-M1-NF-001-SEM-VALOR-FISCAL"
M2_DOCUMENT_REF = "TCC-M2-NF-001-SEM-VALOR-FISCAL"
C0_LOGIN = "tcc_c0_api"
API_KEY_NAME = "tcc-m1-c0-json2"
AMOUNT = 125.50
FIXED_DATETIME = "2026-08-31 12:00:00"
FIXED_DATE = "2026-08-31"
SECRETS_DIRECTORY = Path("/run/tcc-secrets")


def exactly_one(model, domain, description):
    records = model.search(domain)
    if len(records) > 1:
        raise RuntimeError(f"fixture ambígua: {description}")
    return records


company = env.company
company.write({"name": COMPANY_NAME})

if not company.chart_template:
    env["account.chart.template"].try_loading(
        "generic_coa",
        company=company,
        install_demo=False,
    )

vendor = exactly_one(
    env["res.partner"].with_company(company),
    [("ref", "=", VENDOR_REF)],
    "fornecedor",
)
vendor_values = {
    "name": VENDOR_NAME,
    "ref": VENDOR_REF,
    "is_company": True,
    "company_id": company.id,
    "supplier_rank": 1,
    "active": True,
}
if vendor:
    vendor.write(vendor_values)
else:
    vendor = env["res.partner"].with_company(company).create(vendor_values)

bank = exactly_one(
    env["res.partner.bank"].with_company(company),
    [("partner_id", "=", vendor.id), ("acc_number", "=", BANK_ACCOUNT)],
    "conta bancária sintética",
)
bank_values = {
    "acc_number": BANK_ACCOUNT,
    "partner_id": vendor.id,
    "company_id": company.id,
    "active": True,
}
if bank:
    bank.write(bank_values)
else:
    bank = env["res.partner.bank"].with_company(company).create(bank_values)

# Odoo 19 impede que o usuário técnico interno de ID 1 confie uma conta fora
# de install/test mode. A validação da fixture é feita pelo administrador
# funcional (não pela chave C0), reproduzindo o gate cadastral do ERP.
functional_admin = env.ref("base.user_admin")
bank.with_user(functional_admin).write({"allow_out_payment": True})
if not bank.allow_out_payment:
    raise RuntimeError("a conta bancária sintética não foi marcada como confiável")

product = exactly_one(
    env["product.product"].with_company(company),
    [("default_code", "=", PRODUCT_CODE)],
    "produto sintético",
)
product_values = {
    "name": PRODUCT_NAME,
    "default_code": PRODUCT_CODE,
    "type": "service",
    "purchase_ok": True,
    "sale_ok": False,
    "standard_price": AMOUNT,
    "list_price": AMOUNT,
}
if product:
    product.write(product_values)
else:
    product = env["product.product"].with_company(company).create(product_values)

purchase_order = exactly_one(
    env["purchase.order"].with_company(company),
    [("name", "=", PURCHASE_ORDER_REF), ("company_id", "=", company.id)],
    "pedido de compra",
)
if not purchase_order:
    purchase_order = env["purchase.order"].with_company(company).create(
        {
            "name": PURCHASE_ORDER_REF,
            "partner_id": vendor.id,
            "company_id": company.id,
            "currency_id": company.currency_id.id,
            "date_order": fields.Datetime.to_datetime(FIXED_DATETIME),
            "partner_ref": SCENARIO_ID,
            "order_line": [
                Command.create(
                    {
                        "name": PRODUCT_NAME,
                        "product_id": product.id,
                        "product_qty": 1.0,
                        "product_uom_id": product.uom_id.id,
                        "price_unit": AMOUNT,
                        "date_planned": fields.Datetime.to_datetime(FIXED_DATETIME),
                        "tax_ids": [Command.clear()],
                    }
                )
            ],
        }
    )
    purchase_order.button_confirm()

if purchase_order.state != "purchase":
    raise RuntimeError("o pedido sintético não está confirmado")
if len(purchase_order.order_line.filtered(lambda line: not line.display_type)) != 1:
    raise RuntimeError("o pedido sintético deve possuir exatamente uma linha faturável")

purchase_line = purchase_order.order_line.filtered(lambda line: not line.display_type)
if purchase_line.product_id != product:
    raise RuntimeError("produto divergente no pedido sintético")
if purchase_line.product_qty != 1.0 or purchase_line.price_unit != AMOUNT:
    raise RuntimeError("quantidade ou preço divergente no pedido sintético")

stale_bills = env["account.move"].with_company(company).search(
    [
        ("move_type", "=", "in_invoice"),
        ("ref", "=", DOCUMENT_REF),
        ("company_id", "=", company.id),
    ]
)
if stale_bills.filtered(lambda move: move.state != "draft"):
    raise RuntimeError("há conta sintética não rascunho; reset automático recusado")
stale_bill_count = len(stale_bills)
if stale_bills:
    stale_bills.unlink()

m2_stale_bills = env["account.move"].with_company(company).search(
    [
        ("move_type", "=", "in_invoice"),
        ("ref", "=", M2_DOCUMENT_REF),
        ("company_id", "=", company.id),
    ]
)
if m2_stale_bills.filtered(lambda move: move.state != "draft"):
    raise RuntimeError("ha conta sintetica M2 nao rascunho; reset automatico recusado")
m2_stale_bill_count = len(m2_stale_bills)
if m2_stale_bills:
    m2_stale_bills.unlink()

required_groups = env["res.groups"].browse(
    [
        env.ref("base.group_user").id,
        env.ref("account.group_account_invoice").id,
    ]
)
c0_user = exactly_one(env["res.users"], [("login", "=", C0_LOGIN)], "usuário C0")
c0_values = {
    "name": "TCC C0 API - DADOS SINTÉTICOS",
    "login": C0_LOGIN,
    "active": True,
    "company_id": company.id,
    "company_ids": [Command.set([company.id])],
    "group_ids": [Command.set(required_groups.ids)],
}
if c0_user:
    c0_user.write(c0_values)
else:
    c0_user = env["res.users"].create(c0_values)

if not c0_user.has_group("account.group_account_invoice"):
    raise RuntimeError("usuário C0 sem grupo funcional de faturamento")
if c0_user.has_group("base.group_system"):
    raise RuntimeError("usuário C0 recebeu privilégio administrativo")

api_keys = env["res.users.apikeys"].sudo().search(
    [("user_id", "=", c0_user.id), ("name", "=", API_KEY_NAME)]
)
if api_keys:
    api_keys.unlink()

expiration = fields.Datetime.now() + dt.timedelta(hours=12)
api_key = env["res.users.apikeys"].with_user(c0_user)._generate(
    scope="rpc",
    name=API_KEY_NAME,
    expiration_date=expiration,
)

env.cr.commit()

SECRETS_DIRECTORY.mkdir(parents=True, exist_ok=True)
api_key_path = SECRETS_DIRECTORY / "odoo_api_key"
api_key_path.write_text(api_key, encoding="utf-8")
try:
    os.chmod(api_key_path, 0o600)
except OSError:
    pass

fixture = {
    "schema_version": 1,
    "scenario_id": SCENARIO_ID,
    "synthetic_data": True,
    "fiscal_value": False,
    "company_id": company.id,
    "company_name": company.name,
    "vendor_id": vendor.id,
    "vendor_ref": vendor.ref,
    "vendor_name": vendor.name,
    "bank_id": bank.id,
    "bank_account": bank.acc_number,
    "product_id": product.id,
    "product_code": product.default_code,
    "product_name": product.display_name,
    "product_uom_id": product.uom_id.id,
    "purchase_order_id": purchase_order.id,
    "purchase_order_ref": purchase_order.name,
    "purchase_line_id": purchase_line.id,
    "currency_id": company.currency_id.id,
    "currency_name": company.currency_id.name,
    "document_ref": DOCUMENT_REF,
    "m2_document_ref": M2_DOCUMENT_REF,
    "invoice_date": FIXED_DATE,
    "amount": f"{AMOUNT:.2f}",
    "c0_login": c0_user.login,
    "bootstrap_removed_draft_bills": stale_bill_count,
    "m2_bootstrap_removed_draft_bills": m2_stale_bill_count,
}
(SECRETS_DIRECTORY / "m1_fixture.json").write_text(
    json.dumps(fixture, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
    encoding="utf-8",
)

print("M1_FIXTURE_BOOTSTRAP=PASS")
