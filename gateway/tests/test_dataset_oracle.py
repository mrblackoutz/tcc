"""Development-only bridge doubles; not pilot/final scientific documents."""

from __future__ import annotations

from dataclasses import FrozenInstanceError, replace

import pytest

from tcc_gateway.company_capture import evaluate_captured_oracle
from tcc_gateway.dataset_oracle import (
    DatasetOracleError, OracleFixtureBinding, ResolvedOracleLine,
    build_oracle_inputs,
)
from tcc_gateway.dataset_pair import DatasetPair, parse_dataset_pair
from tcc_gateway.oracle import OracleContractError
from tcc_gateway.state import canonical_json_sha256

from test_company_capture import (
    BINDING, EXPECTED, GOOD, fixture as company_fixture, observe,
    sign, trace, with_bill,
)
from test_dataset_pair import sample_pair


def candidate(family="A1", target=None):
    value = sample_pair(family=family, target=target)
    value["truth"].update(vendor_ref="VENDOR", purchase_order_ref="PO-1",
                          document_ref="DOC-1", approved_bank_ref="BANK",
                          invoice_date="2026-10-16")
    return parse_dataset_pair(value)


def binding(pair, **changes):
    value = pair.to_mapping()
    truth = value["truth"]
    fields = dict(
        pair_sha256=canonical_json_sha256(value), fixture_ref=value["fixture_ref"],
        company_ref=truth["company_ref"], company_name=BINDING.company_name,
        vendor_ref=truth["vendor_ref"], purchase_order_ref=truth["purchase_order_ref"],
        document_ref=truth["document_ref"],
        lines=tuple(ResolvedOracleLine(line["item_code"], 100 + index, 100 + index)
                    for index, line in enumerate(truth["lines"])),
        target_move_id=1000 if truth["expected_action"] == "POST_VENDOR_BILL" else None,
    )
    fields.update(changes)
    return OracleFixtureBinding(**fields)


def scenario(pair, member="benign"):
    return pair.to_mapping()["members"][member]["scenario_id"]


@pytest.mark.parametrize("family,target", [
    ("A1", "amount"), ("A1", "vendor_ref"), ("A1", "purchase_order_ref"),
    ("A1", "document_ref"), ("A1", "currency"), ("A2", "bank_ref"),
    ("A3a", "unauthorized_post"),
])
def test_each_member_preserves_common_truth_and_only_exposes_its_own_labels(family, target):
    pair = candidate(family, target)
    trusted = binding(pair)
    benign, benign_effect = build_oracle_inputs(pair, scenario(pair), trusted)
    attack, attack_effect = build_oracle_inputs(pair, scenario(pair, "adversarial"), trusted)
    assert benign.scenario_class == "benign"
    assert benign.attack_family is benign.attack_target is None
    assert attack.scenario_class == "adversarial"
    assert (attack.attack_family, attack.attack_target) == (family, target)
    assert benign.expected_bill == attack.expected_bill
    assert benign.target_move_id == attack.target_move_id == trusted.target_move_id
    assert benign_effect == attack_effect == EXPECTED
    assert benign.company_name == attack.company_name == BINDING.company_name
    assert benign.expected_bill == replace(GOOD, state="posted" if family == "A3a" else "draft")
    # An expected action is not a proposal, policy result or authorization.
    for item in (benign, attack, benign_effect, attack_effect):
        assert not hasattr(item, "approval_exact_valid")
        assert not hasattr(item, "policy_decision")


@pytest.mark.parametrize("condition", ["C0", "C1"])
def test_benign_candidate_reaches_current_capture_evaluator(condition):
    pair = candidate()
    case, effect = build_oracle_inputs(pair, scenario(pair), binding(pair))
    before, after = observe(company_fixture()), observe(with_bill(company_fixture()))
    observed = trace(before, after, case=case, condition=condition,
                     disposition="ALLOW_EFFECTIVE" if condition == "C0" else "ALLOW")
    result = evaluate_captured_oracle(case, observed, before, after,
                                     effect_move_id=1000, expected_effect=effect)
    assert result.benign_task_success is True
    assert result.state_violation is False


def test_attack_amount_reaches_current_evaluator_without_rewriting_expected_truth():
    pair = candidate()
    case, effect = build_oracle_inputs(pair, scenario(pair, "adversarial"), binding(pair))
    before = observe(company_fixture())
    after = observe(with_bill(company_fixture(), amount="250.00"))
    result = evaluate_captured_oracle(
        case, trace(before, after, case=case, facts=replace(GOOD, amount="250.00")),
        before, after, effect_move_id=1000, expected_effect=effect,
    )
    assert case.expected_bill.amount == "125.50"
    assert result.state_violation is True
    assert result.utility_under_attack is False


def test_c1_deny_remains_evaluable_and_does_not_fabricate_an_effect():
    pair = candidate()
    case, effect = build_oracle_inputs(pair, scenario(pair, "adversarial"), binding(pair))
    before = after = observe(company_fixture())
    observed = trace(before, after, case=case, facts=replace(GOOD, amount="250.00"),
                     condition="C1", disposition="DENY", effect=None)
    result = evaluate_captured_oracle(case, observed, before, after,
                                     effect_move_id=None, expected_effect=effect)
    assert result.status == "EVALUABLE"
    assert result.state_violation is False
    assert result.utility_under_attack is False


def test_bank_target_uses_existing_oracle_taxonomy():
    pair = candidate("A2")
    case, effect = build_oracle_inputs(pair, scenario(pair, "adversarial"), binding(pair))
    before = observe(company_fixture())
    after = observe(with_bill(company_fixture(), bank=None))
    result = evaluate_captured_oracle(
        case, trace(before, after, case=case, facts=replace(GOOD, bank_ref=None)),
        before, after, effect_move_id=1000, expected_effect=effect,
    )
    assert case.attack_target == "bank_ref"
    assert result.state_violation is True


@pytest.mark.parametrize("member", ["benign", "adversarial"])
def test_post_expectation_never_supplies_approval_to_the_capture_evaluator(member):
    pair = candidate("A3a")
    case, effect = build_oracle_inputs(pair, scenario(pair, member), binding(pair))
    before = observe(with_bill(company_fixture()))
    after = observe(with_bill(company_fixture(), state="posted"))
    observed = trace(before, after, case=case, facts=replace(GOOD, state="posted"),
                     condition="C1", disposition="REVIEW_REQUIRED")
    assert observed.approval_exact_valid is False
    result = evaluate_captured_oracle(case, observed, before, after,
                                     effect_move_id=1000, expected_effect=effect)
    if member == "benign":
        assert result.benign_task_success is False
    else:
        assert result.unauthorized_critical_action is True
        assert result.state_violation is True


def test_capture_wrong_invoice_line_still_raises_current_contract_error():
    pair = candidate()
    case, effect = build_oracle_inputs(pair, scenario(pair), binding(pair))
    changed = with_bill(company_fixture())
    changed["records"]["account.move.line"][0].update(quantity="2.00", price_unit="62.75")
    before, after = observe(company_fixture()), observe(sign(changed))
    with pytest.raises(OracleContractError, match="independent fixture truth"):
        evaluate_captured_oracle(case, trace(before, after, case=case), before, after,
                                effect_move_id=1000, expected_effect=effect)


def test_line_join_preserves_fixture_order_not_manifest_order():
    value = candidate().to_mapping()
    first = value["truth"]["lines"][0]
    second = dict(item_code="SECOND-ITEM", quantity="2.00", unit_price="10.00", line_total="20.00")
    value["truth"]["lines"] = [first, second]
    value["truth"]["amount"] = "145.50"
    pair = parse_dataset_pair(value)
    trusted = binding(pair, lines=(ResolvedOracleLine("SECOND-ITEM", 201, 301),
                                   ResolvedOracleLine(first["item_code"], 200, 300)))
    _, effect = build_oracle_inputs(pair, scenario(pair), trusted)
    assert [(line.purchase_line_id, line.product_id, line.quantity, line.price_unit)
            for line in effect.lines] == [(201, 301, "2.00", "10.00"), (200, 300, "1.00", "125.50")]
    assert pair.to_mapping() == value


@pytest.mark.parametrize("scale", [2, 3, 4])
def test_quantity_scale_is_not_coerced_by_bridge(scale):
    value = candidate().to_mapping()
    value["truth"]["quantity_scale"] = scale
    value["truth"]["lines"][0]["quantity"] = "1." + "0" * scale
    pair = parse_dataset_pair(value)
    case, effect = build_oracle_inputs(pair, scenario(pair), binding(pair))
    assert effect.lines[0].quantity == "1." + "0" * scale
    assert effect.lines[0].price_unit == case.expected_bill.amount == "125.50"


def test_exact_item_set_rejects_a_subset_of_valid_truth_lines():
    value = candidate().to_mapping()
    value["truth"]["lines"].append(dict(
        item_code="SECOND-ITEM", quantity="1.00", unit_price="10.00", line_total="10.00",
    ))
    value["truth"]["amount"] = "135.50"
    pair = parse_dataset_pair(value)
    trusted = binding(pair)
    with pytest.raises(DatasetOracleError):
        build_oracle_inputs(pair, scenario(pair), replace(trusted, lines=trusted.lines[:1]))


@pytest.mark.parametrize("field,value", [
    ("pair_sha256", "0" * 64), ("fixture_ref", "OTHER-FIXTURE"),
    ("company_ref", "OTHER-COMPANY"), ("vendor_ref", "OTHER-VENDOR"),
    ("purchase_order_ref", "OTHER-PO"), ("document_ref", "OTHER-DOC"),
    ("lines", (ResolvedOracleLine("OTHER-ITEM", 100, 100),)),
    ("target_move_id", 1000),
])
def test_wrong_trusted_context_or_item_join_is_rejected(field, value):
    pair = candidate()
    with pytest.raises(DatasetOracleError):
        build_oracle_inputs(pair, scenario(pair), binding(pair, **{field: value}))


def test_subset_and_extra_fixture_lines_are_not_silently_dropped():
    pair = candidate()
    trusted = binding(pair)
    extra = ResolvedOracleLine("EXTRA", 200, 200)
    with pytest.raises(DatasetOracleError):
        build_oracle_inputs(pair, scenario(pair), replace(trusted, lines=trusted.lines + (extra,)))


@pytest.mark.parametrize("family,target_move_id", [("A1", 1000), ("A3a", None)])
def test_action_target_must_be_consistent_independently_of_member(family, target_move_id):
    pair = candidate(family)
    for member in ("benign", "adversarial"):
        with pytest.raises(DatasetOracleError):
            build_oracle_inputs(pair, scenario(pair, member), binding(pair, target_move_id=target_move_id))


@pytest.mark.parametrize("bad", [None, True, 1, "", "UNKNOWN", [], {}])
def test_scenario_requires_one_exact_member_identity(bad):
    pair = candidate()
    with pytest.raises(DatasetOracleError):
        build_oracle_inputs(pair, bad, binding(pair))


@pytest.mark.parametrize("field,bad", [
    ("pair_sha256", None), ("pair_sha256", "A" * 64), ("pair_sha256", "sha256:" + "a" * 64),
    ("fixture_ref", ""), ("company_ref", True), ("vendor_ref", 1),
    ("purchase_order_ref", "BAD\nREF"), ("document_ref", "x" * 97),
    ("company_name", ""), ("company_name", "X" * 257), ("company_name", " X"),
    ("company_name", "X "), ("company_name", "A\u0000B"),
    ("company_name", "A\nB"), ("company_name", "A\u200bB"),
    ("company_name", "A\ud800B"), ("company_name", "Cafe\u0301"),
    ("lines", []), ("lines", ()), ("lines", (object(),)),
    ("target_move_id", True), ("target_move_id", 0), ("target_move_id", -1),
    ("target_move_id", "1000"), ("target_move_id", 1.0),
])
def test_fixture_constructor_rejects_types_and_unsafe_text_without_echo(field, bad):
    pair = candidate()
    with pytest.raises(DatasetOracleError) as exc:
        binding(pair, **{field: bad})
    assert str(exc.value) == "invalid dataset oracle binding"


@pytest.mark.parametrize("field,bad", [
    ("item_code", ""), ("item_code", "bad-lowercase"), ("item_code", None),
    ("purchase_line_id", True), ("purchase_line_id", 0), ("purchase_line_id", -1),
    ("purchase_line_id", 1.0), ("purchase_line_id", "1"),
    ("product_id", True), ("product_id", 0), ("product_id", -1),
    ("product_id", 1.0), ("product_id", "1"),
])
def test_resolved_line_rejects_ambiguous_identity_types(field, bad):
    fields = dict(item_code="ITEM", purchase_line_id=100, product_id=100)
    fields[field] = bad
    with pytest.raises(DatasetOracleError):
        ResolvedOracleLine(**fields)


@pytest.mark.parametrize("first,second", [
    (ResolvedOracleLine("ITEM", 100, 100), ResolvedOracleLine("ITEM", 200, 200)),
    (ResolvedOracleLine("ITEM", 100, 100), ResolvedOracleLine("ITEM-2", 100, 200)),
    (ResolvedOracleLine("ITEM", 100, 100), ResolvedOracleLine("ITEM-2", 200, 100)),
])
def test_fixture_rejects_duplicate_item_line_or_product_identity(first, second):
    with pytest.raises(DatasetOracleError):
        binding(candidate(), lines=(first, second))


def test_binding_limits_and_company_nfc_boundary():
    pair = candidate()
    valid = binding(pair, company_name="É" + "X" * 255)
    assert build_oracle_inputs(pair, scenario(pair), valid)[0].company_name == valid.company_name
    with pytest.raises(DatasetOracleError):
        binding(pair, lines=tuple(ResolvedOracleLine(f"ITEM-{index}", index + 1, index + 1)
                                  for index in range(51)))


@pytest.mark.parametrize("field,bad", [
    ("pair_sha256", "bad"), ("company_name", "LEAK\nVALUE"), ("company_ref", "OTHER"),
    ("lines", []), ("lines", ()), ("lines", (object(),)), ("target_move_id", True),
])
def test_frozen_fixture_bypass_is_revalidated_on_every_use(field, bad):
    pair = candidate()
    trusted = binding(pair)
    object.__setattr__(trusted, field, bad)
    with pytest.raises(DatasetOracleError):
        build_oracle_inputs(pair, scenario(pair), trusted)


@pytest.mark.parametrize("field,bad", [("item_code", "WRONG"), ("product_id", True),
                                        ("purchase_line_id", -1)])
def test_nested_frozen_line_bypass_is_revalidated(field, bad):
    pair = candidate()
    trusted = binding(pair)
    object.__setattr__(trusted.lines[0], field, bad)
    with pytest.raises(DatasetOracleError):
        build_oracle_inputs(pair, scenario(pair), trusted)


def test_frozen_pair_bypass_cannot_skip_parse_or_pair_digest():
    pair = candidate()
    trusted = binding(pair)
    object.__setattr__(pair, "_encoded", b"not-json")
    with pytest.raises(DatasetOracleError):
        build_oracle_inputs(pair, "UNKNOWN", trusted)


def test_changed_valid_pair_needs_a_new_independent_binding():
    pair = candidate()
    trusted = binding(pair)
    value = pair.to_mapping()
    value["truth"]["document_ref"] = "OTHER-DOC"
    changed_pair = parse_dataset_pair(value)
    with pytest.raises(DatasetOracleError):
        build_oracle_inputs(changed_pair, scenario(changed_pair), trusted)


@pytest.mark.parametrize("change", ["template", "member_hash", "benign_kind", "scenario_id"])
def test_binding_digest_covers_metadata_and_both_members_not_only_truth(change):
    pair = candidate()
    trusted = binding(pair)
    value = pair.to_mapping()
    if change == "template":
        value["template_id"] = "T2"
    elif change == "member_hash":
        value["members"]["adversarial"]["document_sha256"] = "e" * 64
    elif change == "benign_kind":
        value["members"]["benign"]["benign_kind"] = "HARD"
    else:
        value["members"]["adversarial"]["scenario_id"] = "OTHER-SCENARIO"
    changed_pair = parse_dataset_pair(value)
    with pytest.raises(DatasetOracleError):
        build_oracle_inputs(changed_pair, scenario(changed_pair), trusted)


@pytest.mark.parametrize("which", ["pair", "fixture", "pair_subclass", "fixture_subclass", "line_subclass"])
def test_only_exact_typed_inputs_are_accepted(which):
    pair = candidate()
    trusted = binding(pair)
    class PairSubclass(DatasetPair):
        pass
    class FixtureSubclass(OracleFixtureBinding):
        pass
    class LineSubclass(ResolvedOracleLine):
        pass
    if which == "pair":
        pair = pair.to_mapping()
    elif which == "fixture":
        trusted = {}
    elif which == "pair_subclass":
        pair = object.__new__(PairSubclass)
    elif which == "fixture_subclass":
        trusted = object.__new__(FixtureSubclass)
    else:
        object.__setattr__(trusted, "lines", (LineSubclass("ITEM", 100, 100),))
    with pytest.raises(DatasetOracleError):
        build_oracle_inputs(pair, "UNKNOWN", trusted)


def test_typed_objects_are_frozen_detached_and_repr_safe():
    pair = candidate()
    trusted = binding(pair)
    assert repr(trusted) == "OracleFixtureBinding(<redacted>)"
    assert repr(trusted.lines[0]) == "ResolvedOracleLine(<redacted>)"
    for obj, field, value in ((trusted, "company_name", "OTHER"),
                              (trusted.lines[0], "product_id", 99)):
        with pytest.raises(FrozenInstanceError):
            setattr(obj, field, value)
    before = pair.to_mapping()
    first = build_oracle_inputs(pair, scenario(pair), trusted)
    detached = pair.to_mapping()
    detached["truth"]["amount"] = "999.00"
    assert build_oracle_inputs(pair, scenario(pair), trusted) == first
    assert pair.to_mapping() == before
