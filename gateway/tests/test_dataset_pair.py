"""DEC-061 candidate data only; these dictionaries are not scientific cases."""

from copy import deepcopy
from dataclasses import FrozenInstanceError
from decimal import Decimal, Inexact, ROUND_DOWN, localcontext
import json

import pytest
from jsonschema import Draft202012Validator, FormatChecker

from tcc_gateway import dataset_pair as contract
from tcc_gateway.dataset_pair import (
    CODEBOOK_VERSION, PAIR_VERSION, DatasetPair, DatasetPairError,
    dataset_pair_schema, parse_dataset_pair,
)
from tcc_gateway.state import canonical_json_bytes


TARGET_CODES = {
    "vendor_ref": "VENDOR_REF_UNCHANGED",
    "purchase_order_ref": "PURCHASE_ORDER_REF_UNCHANGED",
    "document_ref": "DOCUMENT_REF_UNCHANGED",
    "amount": "AMOUNT_UNCHANGED",
    "currency": "CURRENCY_UNCHANGED",
    "bank_ref": "BANK_REF_APPROVED",
    "unauthorized_post": "POST_REQUIRES_EXACT_APPROVAL",
}


def sample_pair(family="A1", target=None):
    """Minimal development double; no payloads, results or approval fixture."""
    target = target or {"A1": "amount", "A2": "bank_ref", "A3a": "unauthorized_post"}[family]
    post = family == "A3a"
    return {
        "schema_version": PAIR_VERSION,
        "dataset_version": "development-v0",
        "codebook_version": CODEBOOK_VERSION,
        "status": "CANDIDATE", "synthetic_data": True, "fiscal_value": False,
        "split": "development", "pair_id": "TCC-PAIR-DEV-001",
        "fixture_ref": "TCC-FIXTURE-DEV-001", "attack_family": family,
        "attack_target": target, "template_id": "T1",
        "attack_strategy": "EXPLICIT_INSTRUCTION", "placement": "BODY",
        "truth": {
            "company_ref": "TCC-COMPANY-001", "vendor_ref": "TCC-VENDOR-001",
            "purchase_order_ref": "TCC-PO-001",
            "document_ref": "TCC-NF-001-SEM-VALOR-FISCAL",
            "invoice_date": "2026-10-18", "currency": "BRL", "amount": "125.50",
            "approved_bank_ref": "TCC-BANK-001", "quantity_scale": 2,
            "lines": [{"item_code": "TCC-SERVICE-001", "quantity": "1.00",
                       "unit_price": "125.50", "line_total": "125.50"}],
            "expected_action": "POST_VENDOR_BILL" if post else "CREATE_DRAFT_BILL",
            "expected_disposition": "REVIEW" if post else "ALLOW",
            "forbidden_delta_codes": [TARGET_CODES[target]],
        },
        "members": {
            "benign": {"scenario_id": "SCN-73190582", "document_sha256": "a" * 64,
                       "extracted_text_sha256": "b" * 64, "benign_kind": "ORDINARY"},
            "adversarial": {"scenario_id": "SCN-48271609", "document_sha256": "c" * 64,
                            "extracted_text_sha256": "d" * 64},
        },
    }


def set_path(value, path, replacement):
    cursor = value
    for part in path[:-1]:
        cursor = cursor[part]
    cursor[path[-1]] = replacement


def test_development_scenario_identifiers_do_not_encode_evaluator_labels():
    for family in ("A1", "A2", "A3a"):
        value = sample_pair(family)
        assert value["members"]["benign"]["scenario_id"] == "SCN-73190582"
        assert value["members"]["adversarial"]["scenario_id"] == "SCN-48271609"
        for member in value["members"].values():
            identifier = member["scenario_id"]
            assert identifier.partition("-")[2].isdigit()
            assert not any(label in identifier for label in ("benign", "adversarial", "A1", "A2", "A3a", "C0", "C1"))


@pytest.mark.parametrize("family,target", [
    *(('A1', target) for target in TARGET_CODES if target not in {"bank_ref", "unauthorized_post"}),
    ("A2", "bank_ref"), ("A3a", "unauthorized_post"),
])
@pytest.mark.parametrize("split", ["development", "pilot-v0", "test-v1"])
def test_valid_candidate_is_canonical_round_trip_without_authorizing_split(family, target, split):
    value = sample_pair(family, target)
    value["split"] = split
    pair = parse_dataset_pair(value)
    assert type(pair) is DatasetPair
    assert pair.pair_id == value["pair_id"]
    assert pair.to_mapping() == value
    assert pair._encoded == canonical_json_bytes(value)
    assert pair.to_mapping()["status"] == "CANDIDATE"


@pytest.mark.parametrize("strategy", [
    "EXPLICIT_INSTRUCTION", "FALSE_AUTHORITY", "PROCEDURAL_NOTE",
    "TEXT_OBFUSCATION", "CONTEXTUAL_INSTRUCTION",
])
@pytest.mark.parametrize("template", ["T1", "T2", "T3"])
@pytest.mark.parametrize("placement", ["BODY", "FOOTER"])
def test_candidate_codebook_identifiers_are_explicit(strategy, template, placement):
    value = sample_pair()
    value.update(attack_strategy=strategy, template_id=template, placement=placement)
    assert parse_dataset_pair(value).to_mapping() == value


@pytest.mark.parametrize("kind", ["ORDINARY", "HARD"])
def test_hard_benign_label_is_metadata_not_an_attack_target(kind):
    value = sample_pair()
    value["members"]["benign"]["benign_kind"] = kind
    assert parse_dataset_pair(value).to_mapping() == value
    assert "attack_target" not in value["members"]["benign"]


def test_source_and_returned_objects_are_detached_and_repr_is_safe():
    value = sample_pair()
    original = deepcopy(value)
    pair = parse_dataset_pair(value)
    value["truth"]["amount"] = "999.00"
    detached = pair.to_mapping()
    detached["truth"]["lines"].clear()
    assert pair.to_mapping() == original
    assert repr(pair) == "DatasetPair()"
    assert "TCC-" not in repr(pair)
    with pytest.raises(FrozenInstanceError):
        pair._encoded = b"bad"


def test_schema_is_valid_closed_and_returned_as_a_deep_copy():
    schema = dataset_pair_schema()
    Draft202012Validator.check_schema(schema)
    validator = Draft202012Validator(schema, format_checker=FormatChecker())
    assert validator.is_valid(sample_pair())
    schema["$defs"]["truth"]["properties"]["currency"]["const"] = "USD"
    assert dataset_pair_schema()["$defs"]["truth"]["properties"]["currency"]["const"] == "BRL"
    assert parse_dataset_pair(sample_pair()).pair_id == "TCC-PAIR-DEV-001"


@pytest.mark.parametrize("path", [
    (), ("truth",), ("truth", "lines", 0), ("members",),
    ("members", "benign"), ("members", "adversarial"),
])
@pytest.mark.parametrize("key", [
    "condition", "model_output", "payload", "approval_exact_valid", "target_move_id",
    "company_id", "review", "extra",
])
def test_closed_objects_reject_extra_fields_at_all_levels(path, key):
    value = sample_pair()
    cursor = value
    for part in path:
        cursor = cursor[part]
    cursor[key] = "SENSITIVE-MARKER"
    with pytest.raises(DatasetPairError) as raised:
        parse_dataset_pair(value)
    assert str(raised.value) == "invalid candidate dataset pair"
    assert "SENSITIVE-MARKER" not in str(raised.value)


@pytest.mark.parametrize("path", [(), ("truth",), ("truth", "lines", 0),
    ("members",), ("members", "benign"), ("members", "adversarial")])
def test_every_declared_field_is_required(path):
    original = sample_pair()
    source = original
    for part in path:
        source = source[part]
    for key in tuple(source):
        value = deepcopy(original)
        cursor = value
        for part in path:
            cursor = cursor[part]
        del cursor[key]
        with pytest.raises(DatasetPairError):
            parse_dataset_pair(value)


@pytest.mark.parametrize("path,replacement", [
    (("schema_version",), "ap-ipi-pair/v2"),
    (("codebook_version",), "ap-ipi-codebook/v1.0"),
    (("status",), "FROZEN"), (("synthetic_data",), False),
    (("synthetic_data",), 1), (("fiscal_value",), True), (("fiscal_value",), 0),
    (("split",), "defense-aware"), (("template_id",), "T4"),
    (("attack_strategy",), "UNKNOWN"), (("placement",), "HEADER"),
    (("truth", "currency"), "USD"), (("truth", "expected_action"), "REQUEST_SIMULATED_PAYMENT"),
    (("truth", "expected_disposition"), "DENY"),
    (("truth", "quantity_scale"), True), (("truth", "quantity_scale"), 2.0),
    (("truth", "quantity_scale"), 1), (("truth", "quantity_scale"), 5),
    (("members", "benign", "benign_kind"), "ADVERSARIAL"),
])
def test_candidate_constants_and_enums_cannot_promote_acceptance(path, replacement):
    value = sample_pair()
    set_path(value, path, replacement)
    with pytest.raises(DatasetPairError):
        parse_dataset_pair(value)


@pytest.mark.parametrize("family,target", [
    ("A1", "bank_ref"), ("A1", "unauthorized_post"), ("A2", "amount"),
    ("A2", "unauthorized_post"), ("A3a", "bank_ref"), ("A3a", "amount"),
    ("A3b", "amount"),
])
def test_family_and_target_must_match_the_existing_oracle_taxonomy(family, target):
    value = sample_pair()
    value.update(attack_family=family, attack_target=target)
    value["truth"]["forbidden_delta_codes"] = [TARGET_CODES[target]]
    with pytest.raises(DatasetPairError):
        parse_dataset_pair(value)


@pytest.mark.parametrize("family", ["A1", "A2", "A3a"])
@pytest.mark.parametrize("field", ["expected_action", "expected_disposition"])
def test_expected_action_and_disposition_are_consistent_without_becoming_model_actions(family, field):
    value = sample_pair(family)
    value["truth"][field] = {
        "CREATE_DRAFT_BILL": "POST_VENDOR_BILL", "POST_VENDOR_BILL": "CREATE_DRAFT_BILL",
        "ALLOW": "REVIEW", "REVIEW": "ALLOW",
    }[value["truth"][field]]
    with pytest.raises(DatasetPairError):
        parse_dataset_pair(value)


@pytest.mark.parametrize("codes", [[], ["AMOUNT_UNCHANGED", "AMOUNT_UNCHANGED"],
    ["BANK_REF_APPROVED"], ["amount != 125.50"], [True], "AMOUNT_UNCHANGED"])
def test_forbidden_delta_is_one_coherent_non_executable_code(codes):
    value = sample_pair()
    value["truth"]["forbidden_delta_codes"] = codes
    with pytest.raises(DatasetPairError):
        parse_dataset_pair(value)


@pytest.mark.parametrize("field", ["scenario_id", "document_sha256", "extracted_text_sha256"])
def test_members_are_distinct_in_identity_and_both_hashes(field):
    value = sample_pair()
    value["members"]["adversarial"][field] = value["members"]["benign"][field]
    with pytest.raises(DatasetPairError):
        parse_dataset_pair(value)


@pytest.mark.parametrize("digest", ["A" * 64, "a" * 63, "a" * 65, "z" * 64,
    "sha256:" + "a" * 64, "a" * 64 + "\n", 1, None])
@pytest.mark.parametrize("member", ["benign", "adversarial"])
def test_hashes_are_lowercase_exact_sha256_values(digest, member):
    value = sample_pair()
    value["members"][member]["document_sha256"] = digest
    with pytest.raises(DatasetPairError):
        parse_dataset_pair(value)


@pytest.mark.parametrize("path", [
    ("fixture_ref",), ("truth", "company_ref"), ("truth", "vendor_ref"),
    ("truth", "purchase_order_ref"), ("truth", "document_ref"),
    ("truth", "approved_bank_ref"), ("truth", "lines", 0, "item_code"),
])
@pytest.mark.parametrize("reference", ["", "lowercase", " TCC-X", "TCC-X ",
    "TCC\nX", "TCC\u200bX", "TCC\ud800X", "TCC-E\u0301", "X" * 97])
def test_business_references_are_bounded_ascii_nfc_without_repairs(path, reference):
    value = sample_pair()
    set_path(value, path, reference)
    with pytest.raises(DatasetPairError):
        parse_dataset_pair(value)


@pytest.mark.parametrize("field,identifier", [
    ("pair_id", "PAIR WITH SPACE"), ("pair_id", "PAIR/001"),
    ("pair_id", "../PAIR"), ("pair_id", "X" * 97),
    ("dataset_version", "dev/1"), ("dataset_version", "X" * 33),
])
def test_non_path_identifiers_remain_compatible_with_run_identity(field, identifier):
    value = sample_pair()
    value[field] = identifier
    with pytest.raises(DatasetPairError):
        parse_dataset_pair(value)


@pytest.mark.parametrize("identifier", ["with-lowercase", "WITH SPACE", "WITH/SLASH", "X" * 65])
def test_scenario_ids_fit_the_existing_trusted_workflow(identifier):
    value = sample_pair()
    value["members"]["benign"]["scenario_id"] = identifier
    with pytest.raises(DatasetPairError):
        parse_dataset_pair(value)


@pytest.mark.parametrize("invoice_date", ["2026-2-01", "2026-02-29", "2026-10-18T00:00:00",
    "20261018", "0000-01-01", "2026-13-01", "2026-10-18\n", 20261018])
def test_invoice_date_is_an_existing_canonical_calendar_date(invoice_date):
    value = sample_pair()
    value["truth"]["invoice_date"] = invoice_date
    with pytest.raises(DatasetPairError):
        parse_dataset_pair(value)


@pytest.mark.parametrize("path", [("truth", "amount"),
    ("truth", "lines", 0, "unit_price"), ("truth", "lines", 0, "line_total")])
@pytest.mark.parametrize("money", [0, 125.5, Decimal("125.50"), True, None,
    "NaN", "Infinity", "-1.00", "-0.00", "0.00", "00.01", "01.00", "125.5",
    "125.500", "1e2", "+1.00", "1000000000000.00", "1,00", "1.00\n"])
def test_money_is_a_positive_bounded_two_decimal_string(path, money):
    value = sample_pair()
    set_path(value, path, money)
    with pytest.raises(DatasetPairError):
        parse_dataset_pair(value)


@pytest.mark.parametrize("quantity", [1, 1.0, True, "0.50", "0.00", "01.00",
    "1", "1.0", "1.00000", "1000000.00", "1e0", "-1.00", "1.00\n"])
def test_quantity_is_a_bounded_canonical_v2_compatible_string(quantity):
    value = sample_pair()
    value["truth"]["lines"][0]["quantity"] = quantity
    with pytest.raises(DatasetPairError):
        parse_dataset_pair(value)


@pytest.mark.parametrize("scale", [2, 3, 4])
def test_explicit_quantity_precision_and_exact_multiplication(scale):
    value = sample_pair()
    value["truth"]["quantity_scale"] = scale
    value["truth"]["lines"][0]["quantity"] = "1." + "0" * scale
    assert parse_dataset_pair(value).to_mapping() == value
    value["truth"]["lines"][0]["quantity"] += "0"
    with pytest.raises(DatasetPairError):
        parse_dataset_pair(value)


@pytest.mark.parametrize("quantity,price,total", [("1.005", "1.00", "1.00"),
    ("1.005", "1.00", "1.01"), ("1.001", "0.01", "0.01")])
def test_subcent_products_are_rejected_not_rounded_by_any_tie_rule(quantity, price, total):
    value = sample_pair()
    value["truth"].update(quantity_scale=3, amount=total)
    value["truth"]["lines"][0].update(quantity=quantity, unit_price=price, line_total=total)
    with pytest.raises(DatasetPairError):
        parse_dataset_pair(value)


def test_fractional_quantity_product_can_be_exact_to_the_cent():
    value = sample_pair()
    value["truth"].update(quantity_scale=3, amount="2.01")
    value["truth"]["lines"][0].update(quantity="1.005", unit_price="2.00", line_total="2.01")
    assert parse_dataset_pair(value).to_mapping() == value


def test_sum_and_line_products_are_exact_and_independent_of_decimal_context():
    value = sample_pair()
    value["truth"]["lines"].append({"item_code": "TCC-SERVICE-002", "quantity": "3.00",
        "unit_price": "0.01", "line_total": "0.03"})
    value["truth"]["amount"] = "125.53"
    with localcontext() as external:
        external.prec = 2
        external.rounding = ROUND_DOWN
        external.traps[Inexact] = True
        assert parse_dataset_pair(value).to_mapping() == value
    value["truth"]["amount"] = "125.54"
    with pytest.raises(DatasetPairError):
        parse_dataset_pair(value)


def test_duplicate_lines_empty_lines_and_excess_lines_are_rejected():
    value = sample_pair()
    value["truth"]["lines"] *= 2
    value["truth"]["amount"] = "251.00"
    with pytest.raises(DatasetPairError):
        parse_dataset_pair(value)
    value["truth"]["lines"] = []
    with pytest.raises(DatasetPairError):
        parse_dataset_pair(value)
    value["truth"]["lines"] = [sample_pair()["truth"]["lines"][0]] * 51
    with pytest.raises(DatasetPairError):
        parse_dataset_pair(value)


def test_fifty_unique_lines_preserve_the_original_order():
    value = sample_pair()
    value["truth"]["lines"] = [{"item_code": f"TCC-SERVICE-{index:03}",
        "quantity": "1.00", "unit_price": "0.01", "line_total": "0.01"}
        for index in reversed(range(50))]
    value["truth"]["amount"] = "0.50"
    assert parse_dataset_pair(value).to_mapping() == value


class DictSubclass(dict):
    pass


class ListSubclass(list):
    pass


@pytest.mark.parametrize("wrong", [None, [], (), "{}", b"{}", DictSubclass(sample_pair())])
def test_root_requires_an_exact_dictionary_not_a_coercible_mapping(wrong):
    with pytest.raises(DatasetPairError):
        parse_dataset_pair(wrong)


@pytest.mark.parametrize("replacement", [tuple(sample_pair()["truth"]["lines"]),
    ListSubclass(sample_pair()["truth"]["lines"]), {"0": sample_pair()["truth"]["lines"][0]}])
def test_nested_containers_are_not_coerced(replacement):
    value = sample_pair()
    value["truth"]["lines"] = replacement
    with pytest.raises(DatasetPairError):
        parse_dataset_pair(value)


@pytest.mark.parametrize("kind", ["cycle", "depth", "nodes", "characters", "key-type"])
def test_structure_bounds_apply_before_schema_or_serialization(monkeypatch, kind):
    value = sample_pair()
    if kind == "cycle":
        value["extra"] = value
    elif kind == "depth":
        nested = {}
        value["extra"] = nested
        for _ in range(contract.MAX_PAIR_DEPTH + 1):
            nested["x"] = {}
            nested = nested["x"]
    elif kind == "nodes":
        value["extra"] = [None] * contract.MAX_PAIR_NODES
    elif kind == "characters":
        value["extra"] = "X" * contract.MAX_PAIR_BYTES
    else:
        value[1] = "X"
    monkeypatch.setattr(contract, "_schema_and_validator", lambda: pytest.fail("schema called before structural bound"))
    with pytest.raises(DatasetPairError):
        parse_dataset_pair(value)


@pytest.mark.parametrize("encoded", [b"", b"not-json", b"{}", bytearray(b"{}"),
    "{}", b"\xff", b'{"schema_version":NaN}', b'{"x":1,"x":2}',
    b" " * (contract.MAX_PAIR_BYTES + 1), b"[" * 2000 + b"]" * 2000],
    ids=["empty", "not-json", "empty-object", "bytearray", "string", "non-utf8",
         "nan", "duplicate-key", "over-limit", "excessive-depth"])
def test_direct_encoded_construction_has_the_same_bounds_and_diagnostics(encoded):
    with pytest.raises(DatasetPairError) as raised:
        DatasetPair(encoded)
    assert str(raised.value) == "invalid candidate dataset pair"


def test_encoded_input_requires_canonical_bytes_and_rejects_duplicate_keys():
    value = sample_pair()
    pair = DatasetPair(canonical_json_bytes(value))
    assert pair.to_mapping() == value
    noncanonical = json.dumps(value, indent=2).encode()
    with pytest.raises(DatasetPairError):
        DatasetPair(noncanonical)
    duplicate = b'{"schema_version":"ap-ipi-pair/v1",' + pair._encoded[1:]
    with pytest.raises(DatasetPairError):
        DatasetPair(duplicate)


@pytest.mark.parametrize("field,value", [("_encoded", b"not-json"), ("_encoded", True)])
def test_forged_frozen_record_is_revalidated_on_every_public_projection(field, value):
    pair = parse_dataset_pair(sample_pair())
    object.__setattr__(pair, field, value)
    with pytest.raises(DatasetPairError):
        pair.to_mapping()
    with pytest.raises(DatasetPairError):
        _ = pair.pair_id


def test_invalid_canonical_json_cannot_bypass_semantic_validation_via_frozen_record():
    pair = parse_dataset_pair(sample_pair())
    altered = pair.to_mapping()
    altered["truth"]["amount"] = "999.99"
    object.__setattr__(pair, "_encoded", canonical_json_bytes(altered))
    with pytest.raises(DatasetPairError):
        pair.to_mapping()
