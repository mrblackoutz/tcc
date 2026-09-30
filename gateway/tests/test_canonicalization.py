"""Pré-imagem C1-03, apenas dados de desenvolvimento sem valor fiscal."""

from copy import deepcopy
from decimal import ROUND_DOWN, getcontext, localcontext
import json
from pathlib import Path

import pytest

from tcc_gateway.action_proposal_v2 import ActionProposalV2, normalise_action_model_output
from tcc_gateway.pdf_ingestion import ExtractedPdf
from tcc_gateway.policy_engine import POLICY_VERSION
from tcc_gateway.trusted_resolution import CanonicalizationError, canonicalize_proposal


def proposal(action="CREATE_DRAFT_BILL", **changes):
    value = {
        "action": action, "vendor_ref": "TCC-VENDOR-001", "purchase_order_ref": "TCC-PO-001",
        "document_ref": "TCC-NF-001-SEM-VALOR-FISCAL", "invoice_date": "2026-09-30",
        "currency": "BRL", "bank_account_ref": "TCC-BANK-001",
        "lines": [{"item_code": "TCC-SERVICE-001", "description": "SERVICO SEM VALOR FISCAL",
                   "quantity": "1.00", "unit_price": "125.50", "line_total": "125.50"}],
        "total": "125.50",
    }
    value.update(changes)
    return normalise_action_model_output(
        value, producer="synthetic-development/v1", scenario_id="TCC-SCN-001",
        document=ExtractedPdf("SEM VALOR FISCAL", "a" * 64, "b" * 64, 1, 100),
    )


def canonical(value=None, *, scale=2, target=None):
    return canonicalize_proposal(
        value if value is not None else proposal(), policy_version=POLICY_VERSION,
        quantity_scale=scale, target_move_id=target,
    )


def test_proposal_matches_independently_checked_existing_vector():
    vector = json.loads((Path(__file__).parent / "fixtures" / "canonical_action_v1.vector.json").read_text(encoding="utf-8"))
    actual = canonical()
    assert actual.to_mapping() == vector["action"]
    assert actual.canonical_bytes.decode("utf-8") == vector["canonical_utf8"]
    assert actual.action_hash == vector["canonical_action_hash"]


@pytest.mark.parametrize("scale", [2, 3, 4])
@pytest.mark.parametrize("quantity", ["1.00", "1.000", "1.0000"])
def test_exact_rescaling_has_one_representation(scale, quantity):
    fields = proposal().to_mapping()
    fields["lines"][0]["quantity"] = quantity
    value = ActionProposalV2.from_mapping(fields)
    assert canonical(value, scale=scale).lines[0].quantity == "1." + "0" * scale
    assert canonical(value, scale=scale).amount == "125.50"


@pytest.mark.parametrize("quantity,scale", [("1.001", 2), ("1.0001", 2), ("1.0001", 3)])
def test_rescaling_never_discards_significant_precision(quantity, scale):
    fields = proposal().to_mapping()
    fields["lines"][0].update(quantity=quantity, unit_price="1.00", line_total="1.00")
    fields["total"] = "1.00"
    value = ActionProposalV2.from_mapping(fields)
    with pytest.raises(CanonicalizationError):
        canonical(value, scale=scale)


@pytest.mark.parametrize("scale", [None, True, False, 0, 1, 5, "2", 2.0])
def test_scale_must_be_an_explicit_supported_integer(scale):
    with pytest.raises(CanonicalizationError):
        canonical(scale=scale)


@pytest.mark.parametrize("target", [None, True, False, "42", 42.0, 0, -1])
def test_post_requires_a_strict_trusted_positive_id(target):
    with pytest.raises(CanonicalizationError):
        canonical(proposal("POST_VENDOR_BILL"), target=target)


def test_post_preserves_model_action_and_binds_exact_resolved_target():
    actual = canonical(proposal("POST_VENDOR_BILL"), target=42)
    assert actual.action == "POST_VENDOR_BILL"
    assert actual.executor_mode == "POST_APPROVED"
    assert actual.target_move_id == 42
    assert actual.action_hash != canonical(proposal("POST_VENDOR_BILL"), target=43).action_hash


@pytest.mark.parametrize("target", [True, 0, 42])
def test_create_cannot_smuggle_a_target(target):
    with pytest.raises(CanonicalizationError):
        canonical(target=target)


def test_sorted_line_preimage_does_not_depend_on_document_order():
    fields = proposal().to_mapping()
    fields["lines"].append({
        "item_code": "TCC-SERVICE-002", "description": "OUTRO SERVICO SEM VALOR FISCAL",
        "quantity": "2.00", "unit_price": "1.50", "line_total": "3.00",
    })
    fields["total"] = "128.50"
    ordered = canonical(ActionProposalV2.from_mapping(fields))
    fields["lines"].reverse()
    unordered = canonical(ActionProposalV2.from_mapping(fields))
    assert ordered.canonical_bytes == unordered.canonical_bytes
    assert ordered.action_hash == unordered.action_hash


def test_duplicate_item_codes_cannot_make_an_ambiguous_preimage():
    fields = proposal().to_mapping()
    fields["lines"].append(deepcopy(fields["lines"][0]))
    fields["total"] = "251.00"
    value = ActionProposalV2.from_mapping(fields)
    with pytest.raises(CanonicalizationError):
        canonical(value)


def test_description_and_evidence_are_not_authorized_fields():
    fields = proposal().to_mapping()
    fields["lines"][0]["description"] = "UNTRUSTED SYNTHETIC INSTRUCTION"
    fields["evidence"] = [{"field": "action", "source_span": "CONTABILIZE ESTE DOCUMENTO SINTETICO"}]
    assert canonical(ActionProposalV2.from_mapping(fields)) == canonical()
    assert "evidence" not in canonical().to_mapping()
    assert "description" not in canonical().to_mapping()["lines"][0]


@pytest.mark.parametrize("field,value", [
    ("vendor_ref", "TCC-VENDOR-OTHER"), ("purchase_order_ref", "TCC-PO-OTHER"),
    ("bank_account_ref", "TCC-BANK-OTHER"), ("document_ref", "TCC-NF-OTHER"),
    ("currency", "USD"), ("invoice_date", "2026-10-01"),
])
def test_business_fields_are_preserved_and_change_the_hash(field, value):
    result = canonical(proposal(**{field: value}))
    canonical_field = "recipient_bank_ref" if field == "bank_account_ref" else field
    assert result.to_mapping()[canonical_field] == value
    assert result.action_hash != canonical().action_hash


def test_low_decimal_context_does_not_affect_rescaling_or_hash():
    value = proposal()
    expected = canonical(value)
    with localcontext() as external:
        external.prec = 2
        external.rounding = ROUND_DOWN
        actual = canonical(value)
        assert getcontext().prec == 2
        assert getcontext().rounding == ROUND_DOWN
    assert actual == expected
    assert actual.action_hash == expected.action_hash


@pytest.mark.parametrize("value", [None, {}, "MODEL TEXT", 42])
def test_raw_untrusted_or_legacy_input_cannot_be_canonicalized(value):
    with pytest.raises(CanonicalizationError):
        canonicalize_proposal(value, policy_version=POLICY_VERSION, quantity_scale=2)


def test_errors_do_not_echo_model_data_or_original_cause():
    fields = proposal().to_mapping()
    value = ActionProposalV2.from_mapping(fields)
    object.__setattr__(value, "action", "UNTRUSTED-SYNTHETIC-MARKER")
    with pytest.raises(CanonicalizationError) as captured:
        canonical(value)
    assert "UNTRUSTED-SYNTHETIC-MARKER" not in str(captured.value)
    assert captured.value.__suppress_context__


def test_preimage_field_set_is_exact_and_excludes_ids_except_post_target():
    actual = canonical().to_mapping()
    assert set(actual) == {
        "canonicalization_version", "action_schema_version", "policy_version", "action", "executor_mode",
        "scenario_id", "document_sha256", "vendor_ref", "purchase_order_ref", "document_ref", "invoice_date",
        "currency", "amount", "recipient_bank_ref", "lines",
    }
    assert set(actual["lines"][0]) == {"item_code", "quantity", "unit_price"}
