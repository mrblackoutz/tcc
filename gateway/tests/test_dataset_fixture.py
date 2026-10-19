"""Development-only DEC-065 doubles, not the scientific pilot fixtures."""

from copy import deepcopy
from dataclasses import replace
from decimal import Inexact, ROUND_DOWN, localcontext

import pytest

import tcc_gateway.dataset_fixture as producer
from tcc_gateway.dataset_fixture import DatasetFixtureError, resolve_oracle_fixture
from tcc_gateway.dataset_oracle import OracleFixtureBinding
from tcc_gateway.dataset_pair import DatasetPair, parse_dataset_pair
from tcc_gateway.state import canonical_json_sha256
from tcc_gateway.trusted_resolution import ResolvedTrustedState, TrustedWorkflow

from test_dataset_pair import sample_pair
from test_trusted_resolution import FakeOdoo, _many2one, _operational, _workflow


POLICY_VERSION = "policy-v1.0.0"
ERROR = "invalid oracle fixture preparation"


def setup(family="A1", target=None, member="benign"):
    value = sample_pair(family, target)
    value["truth"]["invoice_date"] = "2026-09-30"
    pair = parse_dataset_pair(value)
    identity = value["members"][member]
    workflow = _workflow(post=family == "A3a", scenario_id=identity["scenario_id"],
                         document_sha256=identity["document_sha256"])
    operational = _operational(scenario_id=workflow.scenario_id,
                               document_sha256=workflow.document_sha256)
    return FakeOdoo(post=family == "A3a"), pair, workflow, operational


def run(client, pair, workflow, operational, **changes):
    arguments = {"fixture_ref": "TCC-FIXTURE-DEV-001", "policy_version": POLICY_VERSION}
    arguments.update(changes)
    return resolve_oracle_fixture(client, pair, workflow, operational, **arguments)


def rejected(client, pair, workflow, operational, **changes):
    with pytest.raises(DatasetFixtureError) as captured:
        run(client, pair, workflow, operational, **changes)
    assert str(captured.value) == ERROR
    assert captured.value.__cause__ is None
    assert captured.value.__suppress_context__ is True


@pytest.mark.parametrize("family,target", [
    *(('A1', target) for target in (
        "vendor_ref", "purchase_order_ref", "document_ref", "amount", "currency")),
    ("A2", "bank_ref"), ("A3a", "unauthorized_post"),
])
@pytest.mark.parametrize("member", ["benign", "adversarial"])
def test_resolves_each_eligible_family_and_member_without_authority(family, target, member):
    client, pair, workflow, operational = setup(family, target, member)
    before = deepcopy(client.records)
    binding = run(client, pair, workflow, operational)
    assert type(binding) is OracleFixtureBinding
    assert binding.pair_sha256 == canonical_json_sha256(pair.to_mapping())
    assert binding.fixture_ref == "TCC-FIXTURE-DEV-001"
    assert binding.company_name == workflow.company_name
    assert (binding.lines[0].item_code, binding.lines[0].purchase_line_id,
            binding.lines[0].product_id) == ("TCC-SERVICE-001", 40, 30)
    assert binding.target_move_id == (42 if family == "A3a" else None)
    assert all(method == "search_read" for _, method, _ in client.calls)
    assert client.records == before
    assert not hasattr(binding, "approval") and not hasattr(binding, "action")


@pytest.mark.parametrize("family", ["A1", "A2", "A3a"])
def test_both_members_resolve_identical_business_facts_and_queries(family):
    first = setup(family, member="benign")
    second = setup(family, member="adversarial")
    assert run(*first) == run(*second)
    assert first[0].calls == second[0].calls


@pytest.mark.parametrize("family", ["A1", "A2", "A3a"])
def test_label_exchange_does_not_change_queries_or_financial_binding(family):
    client, pair, workflow, operational = setup(family)
    first = run(client, pair, workflow, operational)
    value = pair.to_mapping()
    original = deepcopy(value["members"])
    value["members"]["benign"] = {**original["adversarial"], "benign_kind": "HARD"}
    value["members"]["adversarial"] = {
        key: item for key, item in original["benign"].items() if key != "benign_kind"
    }
    second_client = FakeOdoo(post=family == "A3a")
    second = run(second_client, parse_dataset_pair(value), workflow, operational)
    assert replace(first, pair_sha256=second.pair_sha256) == second
    assert first.pair_sha256 != second.pair_sha256
    assert client.calls == second_client.calls


@pytest.mark.parametrize("field,value", [
    ("company_ref", "OTHER-COMPANY"), ("company_name", "OTHER COMPANY"),
    ("purchase_order_ref", "OTHER-PO"), ("scenario_id", "SCN-UNKNOWN"),
    ("document_sha256", "f" * 64), ("quantity_scale", 3),
    ("invoice_date_min", "2026-10-01"), ("invoice_date_max", "2026-09-29"),
    ("allowed_bank_refs", ("OTHER-BANK",)),
    ("target_document_ref", "TCC-NF-001-SEM-VALOR-FISCAL"),
])
def test_independent_workflow_mismatches_are_never_repaired(field, value):
    client, pair, workflow, operational = setup()
    rejected(client, pair, replace(workflow, **{field: value}), operational)


@pytest.mark.parametrize("family,changes", [
    ("A1", {"phase": "POST_REVIEW", "target_document_ref": "TCC-NF-001-SEM-VALOR-FISCAL"}),
    ("A3a", {"phase": "DRAFT_INTAKE", "target_document_ref": None}),
    ("A3a", {"target_document_ref": "OTHER-DOCUMENT"}),
])
def test_wrong_phase_or_logical_post_target_rejected_before_read(family, changes):
    client, pair, workflow, operational = setup(family)
    rejected(client, pair, replace(workflow, **changes), operational)
    assert not client.calls


@pytest.mark.parametrize("member", ["benign", "adversarial"])
def test_cannot_mix_scenario_from_one_member_with_digest_of_the_other(member):
    client, pair, workflow, operational = setup(member=member)
    other = pair.to_mapping()["members"]["adversarial" if member == "benign" else "benign"]
    rejected(client, pair, replace(workflow, document_sha256=other["document_sha256"]), operational)
    assert not client.calls


@pytest.mark.parametrize("fixture_ref", [None, True, 1, "", "OTHER-FIXTURE", "TCC-FIXTURE-DEV-001 "])
def test_independent_logical_fixture_reference_is_required(fixture_ref):
    args = setup()
    rejected(*args, fixture_ref=fixture_ref)
    assert not args[0].calls


@pytest.mark.parametrize("field,value", [
    ("duplicate_detected", True), ("duplicate_detected", 0),
    ("accounting_period_open", False), ("accounting_period_open", 1),
    ("company_ref", "OTHER-COMPANY"), ("scenario_id", "SCN-UNKNOWN"),
    ("document_sha256", "f" * 64), ("purchase_order_ref", "OTHER-PO"),
])
def test_explicit_operational_status_is_checked_not_defaulted(field, value):
    client, pair, workflow, operational = setup()
    rejected(client, pair, workflow, replace(operational, **{field: value}))
    assert not client.calls


@pytest.mark.parametrize("component", ["state", "policy", "audit"])
@pytest.mark.parametrize("value", ["UNAVAILABLE", "INVALID", True, None])
def test_each_dependency_must_be_explicitly_available(component, value):
    client, pair, workflow, operational = setup()
    dependencies = replace(operational.dependencies, **{component: value})
    rejected(client, pair, workflow, replace(operational, dependencies=dependencies))
    assert not client.calls


@pytest.mark.parametrize("family", ["A1", "A2", "A3a"])
@pytest.mark.parametrize("model,field,value", [
    ("purchase.order", "name", "OTHER-PO"),
    ("purchase.order", "amount_total", 126.5),
    ("purchase.order", "partner_id", _many2one(12)),
    ("purchase.order", "currency_id", _many2one(3)),
    ("purchase.order", "state", "draft"),
    ("purchase.order", "state", "cancel"),
    ("purchase.order.line", "product_qty", 2.0),
    ("purchase.order.line", "price_unit", 126.5),
    ("purchase.order.line", "discount", 1.0),
    ("purchase.order.line", "tax_ids", [60]),
    ("product.product", "default_code", "OTHER-ITEM"),
    ("product.product", "active", False),
    ("res.partner", "ref", "OTHER-VENDOR"),
    ("res.partner", "active", False),
    ("res.partner", "supplier_rank", 0),
    ("res.partner.bank", "partner_id", _many2one(12)),
    ("res.partner.bank", "acc_number", "OTHER-BANK"),
    ("res.partner.bank", "active", False),
    ("res.partner.bank", "allow_out_payment", False),
    ("res.partner.bank", "company_id", _many2one(99)),
])
def test_observed_business_mismatch_never_produces_binding(family, model, field, value):
    client, pair, workflow, operational = setup(family)
    client.records[model][0][field] = value
    rejected(client, pair, workflow, operational)


@pytest.mark.parametrize("available", [0, 0.99])
def test_create_requires_sufficient_available_quantity(available):
    client, pair, workflow, operational = setup()
    client.records["purchase.order.line"][0]["qty_to_invoice"] = available
    rejected(client, pair, workflow, operational)


@pytest.mark.parametrize("available", [0, 0.5, 1.0])
def test_post_does_not_reapply_create_available_quantity_check(available):
    client, pair, workflow, operational = setup("A3a")
    client.records["purchase.order.line"][0]["qty_to_invoice"] = available
    assert run(client, pair, workflow, operational).target_move_id == 42


@pytest.mark.parametrize("model,field,value", [
    ("account.move", "state", "posted"), ("account.move", "state", "cancel"),
    ("account.move", "ref", "OTHER-DOCUMENT"),
    ("account.move", "invoice_origin", "OTHER-PO"),
    ("account.move", "invoice_date", "2026-10-01"),
    ("account.move", "amount_total", 126.5),
    ("account.move", "partner_id", _many2one(12)),
    ("account.move", "partner_bank_id", _many2one(13)),
    ("account.move", "currency_id", _many2one(3)),
    ("account.move", "auto_post", "at_date"),
    ("account.move", "invoice_line_ids", []),
    ("account.move", "invoice_line_ids", [51, 51]),
    ("account.move.line", "quantity", 2.0),
    ("account.move.line", "price_unit", 126.5),
    ("account.move.line", "purchase_line_id", _many2one(99)),
    ("account.move.line", "product_id", _many2one(99)),
    ("account.move.line", "tax_ids", [99]),
    ("account.move.line", "discount", 1.0),
])
def test_post_target_must_match_every_financial_fact(model, field, value):
    client, pair, workflow, operational = setup("A3a")
    client.records[model][0][field] = value
    rejected(client, pair, workflow, operational)


@pytest.mark.parametrize("model", ["res.company", "purchase.order", "res.partner.bank", "account.move"])
@pytest.mark.parametrize("mode", ["missing", "ambiguous"])
def test_missing_or_ambiguous_observed_references_fail_closed(model, mode):
    client, pair, workflow, operational = setup("A3a")
    if mode == "missing":
        client.records[model] = []
    else:
        duplicate = deepcopy(client.records[model][0])
        duplicate["id"] += 100
        client.records[model].append(duplicate)
    rejected(client, pair, workflow, operational)


@pytest.mark.parametrize("model", [
    "res.company", "purchase.order", "purchase.order.line", "res.partner",
    "res.currency", "product.product", "res.partner.bank", "account.move", "account.move.line",
])
def test_transport_errors_do_not_escape_or_echo_raw_details(model):
    client, pair, workflow, operational = setup("A3a")
    client.fail_model = model
    rejected(client, pair, workflow, operational)


def test_reordered_multiline_facts_preserve_observed_native_identities():
    client, pair, workflow, operational = setup()
    value = pair.to_mapping()
    value["truth"]["lines"] = [
        {"item_code": "TCC-SERVICE-002", "quantity": "1.00", "unit_price": "25.50", "line_total": "25.50"},
        {"item_code": "TCC-SERVICE-001", "quantity": "1.00", "unit_price": "100.00", "line_total": "100.00"},
    ]
    first = client.records["purchase.order.line"][0]
    first["price_unit"] = 100.0
    second = deepcopy(first)
    second.update(id=41, product_id=_many2one(32), price_unit=25.5)
    client.records["purchase.order.line"] = [second, first]
    product = deepcopy(client.records["product.product"][0])
    product.update(id=32, default_code="TCC-SERVICE-002")
    client.records["product.product"].append(product)
    binding = run(client, parse_dataset_pair(value), workflow, operational)
    assert [(line.item_code, line.purchase_line_id, line.product_id) for line in binding.lines] == [
        ("TCC-SERVICE-001", 40, 30), ("TCC-SERVICE-002", 41, 32),
    ]


@pytest.mark.parametrize("scale", [2, 3, 4])
def test_quantity_precision_is_explicit_and_does_not_use_global_decimal_context(scale):
    client, pair, workflow, operational = setup()
    value = pair.to_mapping()
    value["truth"]["quantity_scale"] = scale
    value["truth"]["lines"][0]["quantity"] = "1." + "0" * scale
    pair = parse_dataset_pair(value)
    with localcontext() as context:
        context.prec = 2
        context.rounding = ROUND_DOWN
        context.traps[Inexact] = True
        assert run(client, pair, replace(workflow, quantity_scale=scale), operational).lines[0].product_id == 30


@pytest.mark.parametrize("field,value", [
    ("pair", None), ("pair", {}), ("workflow", None), ("workflow", {}),
    ("operational", None), ("operational", {}),
])
def test_wrong_public_contract_types_are_rejected(field, value):
    client, pair, workflow, operational = setup()
    args = dict(client=client, pair=pair, workflow=workflow, operational=operational)
    args[field] = value
    rejected(**args)


@pytest.mark.parametrize("which", ["pair", "workflow", "operational", "dependencies"])
def test_frozen_contract_bypasses_are_revalidated(which):
    client, pair, workflow, operational = setup()
    if which == "pair":
        object.__setattr__(pair, "_encoded", b"{}")
    elif which == "workflow":
        object.__setattr__(workflow, "quantity_scale", True)
    elif which == "operational":
        object.__setattr__(operational, "accounting_period_open", "yes")
    else:
        object.__setattr__(operational.dependencies, "state", "UNAVAILABLE")
    rejected(client, pair, workflow, operational)
    assert not client.calls


@pytest.mark.parametrize("which", ["pair", "workflow"])
def test_public_subclasses_are_not_accepted_as_trusted_contracts(which):
    client, pair, workflow, operational = setup()
    if which == "pair":
        class PairSubclass(DatasetPair):
            pass
        pair = PairSubclass(pair._encoded)
    else:
        class WorkflowSubclass(TrustedWorkflow):
            pass
        workflow = WorkflowSubclass(**{name: getattr(workflow, name) for name in workflow.__dataclass_fields__})
    rejected(client, pair, workflow, operational)


@pytest.mark.parametrize("field,value", [
    ("company_id", True), ("vendor_id", 0), ("purchase_order_id", -1),
    ("lines", ()), ("bank_ids", ()), ("bank_ids", (("TCC-BANK-001", True),)),
])
def test_malformed_resolver_results_do_not_become_native_identities(monkeypatch, field, value):
    args = setup()
    resolved = producer.read_trusted_state(args[0], args[2], args[3], policy_version=POLICY_VERSION)
    malformed = replace(resolved, **{field: value})
    assert type(malformed) is ResolvedTrustedState
    monkeypatch.setattr(producer, "read_trusted_state", lambda *args, **kwargs: malformed)
    rejected(*args)


def test_unexpected_resolver_exception_is_sanitized_without_partial_binding(monkeypatch):
    def unavailable(*args, **kwargs):
        raise RuntimeError("RAW-TRANSPORT-MARKER-NOT-FOR-LOGS")
    monkeypatch.setattr(producer, "read_trusted_state", unavailable)
    rejected(*setup())


@pytest.mark.parametrize("policy_version", [None, True, 1, "", "INVALID POLICY", " policy-v1.0.0"])
def test_policy_version_must_be_explicit_and_well_formed(policy_version):
    rejected(*setup(), policy_version=policy_version)
