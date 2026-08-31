"""Smoke test script for verifying JSON-2 client against local Odoo instance."""

from __future__ import annotations

import os
import sys

# Ensure gateway package is importable
sys.path.insert(0, "gateway/src")

os.environ["ODOO_BASE_URL"] = "http://127.0.0.1:8069"
os.environ["ODOO_DATABASE"] = "tcc_ap_lab"
os.environ["ODOO_API_TOKEN_FILE"] = ".runtime/secrets/odoo_api_key"

from tcc_gateway import OdooConfig, OdooJson2Client


def main() -> None:
    config = OdooConfig.from_env()
    with OdooJson2Client(config) as client:
        # 1. Search read
        partners = client.call(
            "res.partner",
            "search_read",
            arguments={"domain": [], "fields": ["id", "name"], "limit": 2},
        )
        assert len(partners) > 0, "search_read returned empty"
        print(f"  JSON-2 search_read: PASS ({len(partners)} partners found)")

        # 2. Create synthetic vendor
        new_ids = client.call(
            "res.partner",
            "create",
            arguments={
                "vals_list": [
                    {
                        "name": "Fornecedor Sintetico TCC Smoke Test",
                        "is_company": True,
                        "supplier_rank": 1,
                    }
                ]
            },
        )
        new_id = new_ids[0] if isinstance(new_ids, list) else new_ids
        assert new_id > 0, "create returned invalid ID"
        print(f"  JSON-2 create vendor: PASS (id={new_id})")

        # 3. Read back created vendor
        created = client.call(
            "res.partner",
            "search_read",
            arguments={
                "domain": [["id", "=", new_id]],
                "fields": ["name", "supplier_rank", "is_company"],
            },
        )
        assert len(created) == 1, "read back failed"
        assert created[0]["name"] == "Fornecedor Sintetico TCC Smoke Test"
        assert created[0]["supplier_rank"] == 1
        print(f"  JSON-2 verify read-back: PASS (name='{created[0]['name']}')")


if __name__ == "__main__":
    main()
