"""Smoke M1: conta de fornecedor sintética via JSON-2 e reset por hash."""

from __future__ import annotations

import json
import os
from decimal import Decimal
from pathlib import Path
from typing import Any

from tcc_gateway import OdooConfig, OdooJson2Client, canonical_json_sha256


def _required_path(variable: str) -> Path:
    raw_path = os.environ.get(variable, "").strip()
    if not raw_path:
        raise RuntimeError(f"required path configuration is missing: {variable}")
    return Path(raw_path)


def _many2one_id(value: Any) -> int | None:
    if not value:
        return None
    if not isinstance(value, list) or len(value) != 2:
        raise AssertionError("unexpected many2one representation")
    return int(value[0])


def _one(records: list[dict[str, Any]], description: str) -> dict[str, Any]:
    assert len(records) == 1, f"expected exactly one {description}, got {len(records)}"
    return records[0]


def _observable_state(
    client: OdooJson2Client, fixture: dict[str, Any]
) -> dict[str, Any]:
    vendor = _one(
        client.call(
            "res.partner",
            "search_read",
            arguments={
                "domain": [["ref", "=", fixture["vendor_ref"]]],
                "fields": ["name", "ref", "active", "supplier_rank"],
                "limit": 2,
            },
        ),
        "synthetic vendor",
    )
    bank = _one(
        client.call(
            "res.partner.bank",
            "search_read",
            arguments={
                "domain": [
                    ["partner_id", "=", fixture["vendor_id"]],
                    ["acc_number", "=", fixture["bank_account"]],
                ],
                "fields": ["acc_number", "active", "allow_out_payment"],
                "limit": 2,
            },
        ),
        "synthetic bank account",
    )
    purchase_order = _one(
        client.call(
            "purchase.order",
            "search_read",
            arguments={
                "domain": [
                    ["name", "=", fixture["purchase_order_ref"]],
                    ["company_id", "=", fixture["company_id"]],
                ],
                "fields": [
                    "name",
                    "state",
                    "partner_id",
                    "currency_id",
                    "amount_total",
                ],
                "limit": 2,
            },
        ),
        "synthetic purchase order",
    )
    bills = client.call(
        "account.move",
        "search_read",
        arguments={
            "domain": [
                ["move_type", "=", "in_invoice"],
                ["ref", "=", fixture["document_ref"]],
                ["company_id", "=", fixture["company_id"]],
            ],
            "fields": [
                "move_type",
                "state",
                "auto_post",
                "ref",
                "invoice_origin",
                "amount_total",
            ],
            "order": "id",
        },
    )

    return {
        "schema_version": 1,
        "scenario_id": fixture["scenario_id"],
        "synthetic_data": True,
        "vendor": {
            "name": vendor["name"],
            "ref": vendor["ref"],
            "active": vendor["active"],
            "supplier_rank": vendor["supplier_rank"],
        },
        "bank": {
            "account": bank["acc_number"],
            "active": bank["active"],
            "allow_out_payment": bank["allow_out_payment"],
        },
        "purchase_order": {
            "name": purchase_order["name"],
            "state": purchase_order["state"],
            "vendor_matches": _many2one_id(purchase_order["partner_id"])
            == fixture["vendor_id"],
            "currency_matches": _many2one_id(purchase_order["currency_id"])
            == fixture["currency_id"],
            "amount": f"{Decimal(str(purchase_order['amount_total'])):.2f}",
        },
        "bills": [
            {
                "move_type": bill["move_type"],
                "state": bill["state"],
                "auto_post": bill["auto_post"],
                "ref": bill["ref"],
                "invoice_origin": bill["invoice_origin"],
                "amount": f"{Decimal(str(bill['amount_total'])):.2f}",
            }
            for bill in bills
        ],
    }


def main() -> None:
    fixture_path = _required_path("TCC_M1_FIXTURE_FILE")
    evidence_path = _required_path("TCC_M1_EVIDENCE_FILE")
    fixture = json.loads(fixture_path.read_text(encoding="utf-8"))

    assert fixture["synthetic_data"] is True
    assert fixture["fiscal_value"] is False
    assert fixture["bootstrap_removed_draft_bills"] == 0

    config = OdooConfig.from_env()
    with OdooJson2Client(config) as client:
        initial_state = _observable_state(client, fixture)
        initial_hash = canonical_json_sha256(initial_state)
        assert initial_state["bills"] == [], "initial state contains a residual bill"
        assert initial_state["purchase_order"]["state"] == "purchase"
        assert initial_state["purchase_order"]["amount"] == fixture["amount"]
        assert initial_state["bank"]["allow_out_payment"] is True

        invoice_values = {
            "move_type": "in_invoice",
            "company_id": fixture["company_id"],
            "partner_id": fixture["vendor_id"],
            "currency_id": fixture["currency_id"],
            "invoice_date": fixture["invoice_date"],
            "ref": fixture["document_ref"],
            "invoice_origin": fixture["purchase_order_ref"],
            "partner_bank_id": fixture["bank_id"],
            "auto_post": "no",
            "invoice_line_ids": [
                [
                    0,
                    0,
                    {
                        "name": fixture["product_name"],
                        "product_id": fixture["product_id"],
                        "product_uom_id": fixture["product_uom_id"],
                        "quantity": 1.0,
                        "price_unit": float(Decimal(fixture["amount"])),
                        "purchase_line_id": fixture["purchase_line_id"],
                        "tax_ids": [[6, 0, []]],
                    },
                ]
            ],
        }

        created_id: int | None = None
        try:
            created_ids = client.call(
                "account.move",
                "create",
                arguments={"vals_list": [invoice_values]},
            )
            assert isinstance(created_ids, list) and len(created_ids) == 1
            created_id = int(created_ids[0])

            moves = client.call(
                "account.move",
                "read",
                arguments={
                    "ids": [created_id],
                    "fields": [
                        "move_type",
                        "state",
                        "auto_post",
                        "company_id",
                        "partner_id",
                        "currency_id",
                        "partner_bank_id",
                        "ref",
                        "invoice_origin",
                        "amount_total",
                    ],
                },
            )
            move = _one(moves, "created vendor bill")
            assert move["move_type"] == "in_invoice"
            assert move["state"] == "draft"
            assert move["auto_post"] == "no"
            assert _many2one_id(move["company_id"]) == fixture["company_id"]
            assert _many2one_id(move["partner_id"]) == fixture["vendor_id"]
            assert _many2one_id(move["currency_id"]) == fixture["currency_id"]
            assert _many2one_id(move["partner_bank_id"]) == fixture["bank_id"]
            assert move["ref"] == fixture["document_ref"]
            assert move["invoice_origin"] == fixture["purchase_order_ref"]
            assert f"{Decimal(str(move['amount_total'])):.2f}" == fixture["amount"]

            lines = client.call(
                "account.move.line",
                "search_read",
                arguments={
                    "domain": [
                        ["move_id", "=", created_id],
                        ["display_type", "=", "product"],
                    ],
                    "fields": [
                        "purchase_line_id",
                        "product_id",
                        "quantity",
                        "price_unit",
                    ],
                    "order": "id",
                },
            )
            line = _one(lines, "invoice product line")
            assert _many2one_id(line["purchase_line_id"]) == fixture["purchase_line_id"]
            assert _many2one_id(line["product_id"]) == fixture["product_id"]
            assert Decimal(str(line["quantity"])) == Decimal("1.0")
            assert Decimal(str(line["price_unit"])) == Decimal(fixture["amount"])

            created_state = _observable_state(client, fixture)
            assert len(created_state["bills"]) == 1
            created_hash = canonical_json_sha256(created_state)
        finally:
            if created_id is not None:
                client.call(
                    "account.move",
                    "unlink",
                    arguments={"ids": [created_id]},
                )

        restored_state = _observable_state(client, fixture)
        restored_hash = canonical_json_sha256(restored_state)
        assert restored_state["bills"] == []
        assert restored_hash == initial_hash, "reset did not restore the initial state hash"

    evidence = {
        "schema_version": 1,
        "status": "pass",
        "scenario_id": fixture["scenario_id"],
        "synthetic_data": True,
        "fiscal_value": False,
        "transport": "Odoo JSON-2",
        "operation": "CREATE_AND_RESET_DRAFT_VENDOR_BILL",
        "initial_state_sha256": initial_hash,
        "created_state_sha256": created_hash,
        "restored_state_sha256": restored_hash,
        "invariants": {
            "exactly_one_bill_created": True,
            "move_type_in_invoice": True,
            "state_draft": True,
            "auto_post_no": True,
            "partner_bank_persisted": True,
            "purchase_line_linked": True,
            "amount_matches": True,
            "reset_hash_matches": True,
        },
    }
    evidence_path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = evidence_path.with_suffix(".tmp")
    temporary_path.write_text(
        json.dumps(evidence, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary_path.replace(evidence_path)

    print("M1_JSON2_VENDOR_BILL=PASS")
    print(f"M1_INITIAL_STATE_SHA256={initial_hash}")
    print(f"M1_CREATED_STATE_SHA256={created_hash}")
    print(f"M1_RESTORED_STATE_SHA256={restored_hash}")


if __name__ == "__main__":
    main()
