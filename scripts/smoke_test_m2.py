"""Smoke M2: PDF benigno, proposta tipada, draft C0 e reset por hash."""

from __future__ import annotations

import json
import os
from pathlib import Path

from tcc_gateway import OdooConfig, OdooJson2Client, canonical_json_sha256
from tcc_gateway.adapters import (
    DEVELOPMENT_ADAPTER_ID,
    DeterministicDevelopmentAdapter,
)
from tcc_gateway.c0_executor import (
    create_c0_draft_bill,
    delete_c0_draft_bill,
    TrustedScenarioKeys,
    observable_c0_state,
    resolve_c0_references,
    verify_c0_draft_bill,
)
from tcc_gateway.pdf_ingestion import extract_pdf_text
from tcc_gateway.synthetic_pdf import m2_document_fields, write_m2_synthetic_pdf


def _required_path(variable: str) -> Path:
    raw_path = os.environ.get(variable, "").strip()
    if not raw_path:
        raise RuntimeError(f"required path configuration is missing: {variable}")
    return Path(raw_path)


def _assert_proposal_matches_fixture(proposal, fields: dict[str, str]) -> None:
    line = proposal.lines[0]
    assert proposal.producer == DEVELOPMENT_ADAPTER_ID
    assert proposal.scenario_id == fields["SCENARIO_ID"]
    assert proposal.vendor_ref == fields["VENDOR_REF"]
    assert proposal.purchase_order_ref == fields["PURCHASE_ORDER"]
    assert proposal.document_ref == fields["DOCUMENT_REF"]
    assert proposal.invoice_date.isoformat() == fields["INVOICE_DATE"]
    assert proposal.currency == fields["CURRENCY"]
    assert proposal.bank_account_ref == fields["BANK_ACCOUNT"]
    assert len(proposal.lines) == 1
    assert line.item_code == fields["ITEM_CODE"]
    assert line.description == fields["ITEM_DESCRIPTION"]
    assert format(line.quantity, "f") == fields["QUANTITY"]
    assert format(line.unit_price, ".2f") == fields["UNIT_PRICE"]
    assert format(proposal.total, ".2f") == fields["TOTAL"]


def main() -> None:
    fixture_path = _required_path("TCC_M1_FIXTURE_FILE")
    document_path = _required_path("TCC_M2_DOCUMENT_FILE")
    evidence_path = _required_path("TCC_M2_EVIDENCE_FILE")
    fixture = json.loads(fixture_path.read_text(encoding="utf-8"))

    assert fixture["synthetic_data"] is True
    assert fixture["fiscal_value"] is False
    assert fixture["m2_bootstrap_removed_draft_bills"] == 0

    declared_fields = write_m2_synthetic_pdf(document_path, fixture)
    assert declared_fields == m2_document_fields(fixture)
    extracted = extract_pdf_text(document_path)
    proposal = DeterministicDevelopmentAdapter().propose(extracted)
    proposal.validate_schema()
    _assert_proposal_matches_fixture(proposal, declared_fields)
    proposal_hash = canonical_json_sha256(proposal.to_mapping())

    config = OdooConfig.from_env()
    created_id: int | None = None
    with OdooJson2Client(config) as client:
        references = resolve_c0_references(
            client,
            proposal,
            company_name=str(fixture["company_name"]),
        )
        keys = TrustedScenarioKeys(
            scenario_id=proposal.scenario_id,
            company_name=str(fixture["company_name"]),
        )
        initial_state = observable_c0_state(client, keys)
        initial_hash = canonical_json_sha256(initial_state)
        assert initial_state["bills"] == []

        try:
            created_id = create_c0_draft_bill(client, proposal, references)
            invariants = verify_c0_draft_bill(
                client,
                proposal,
                references,
                created_id,
            )
            created_state = observable_c0_state(client, keys)
            created_hash = canonical_json_sha256(created_state)
            assert len(created_state["bills"]) == 1
            assert created_hash != initial_hash
        finally:
            if created_id is not None:
                delete_c0_draft_bill(client, created_id)

        restored_state = observable_c0_state(client, keys)
        restored_hash = canonical_json_sha256(restored_state)
        assert restored_state["bills"] == []
        assert restored_hash == initial_hash

    evidence = {
        "schema_version": 1,
        "status": "pass",
        "milestone": "M2",
        "scenario_id": proposal.scenario_id,
        "synthetic_data": True,
        "fiscal_value": False,
        "scientific_baseline": False,
        "adapter": {
            "id": DEVELOPMENT_ADAPTER_ID,
            "kind": "deterministic-development",
            "allowed_for_scientific_runs": False,
        },
        "document": {
            "sha256": extracted.document_sha256,
            "text_sha256": extracted.text_sha256,
            "page_count": extracted.page_count,
            "byte_count": extracted.byte_count,
        },
        "proposal": {
            "schema_version": proposal.schema_version,
            "sha256": proposal_hash,
        },
        "transport": "Odoo JSON-2",
        "operation": "PDF_TO_CREATE_AND_RESET_DRAFT_VENDOR_BILL",
        "initial_state_sha256": initial_hash,
        "created_state_sha256": created_hash,
        "restored_state_sha256": restored_hash,
        "invariants": {
            "pdf_has_text_layer": True,
            "proposal_schema_valid": True,
            "proposal_matches_declared_fixture": True,
            "natural_keys_resolved": True,
            "exactly_one_bill_created": True,
            "reset_hash_matches": True,
        }
        | invariants,
    }
    evidence_path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = evidence_path.with_suffix(".tmp")
    temporary_path.write_text(
        json.dumps(evidence, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary_path.replace(evidence_path)

    print("M2_PDF_TO_C0_DRAFT=PASS")
    print(f"M2_DOCUMENT_SHA256={extracted.document_sha256}")
    print(f"M2_PROPOSAL_SHA256={proposal_hash}")
    print(f"M2_INITIAL_STATE_SHA256={initial_hash}")
    print(f"M2_CREATED_STATE_SHA256={created_hash}")
    print(f"M2_RESTORED_STATE_SHA256={restored_hash}")


if __name__ == "__main__":
    main()
