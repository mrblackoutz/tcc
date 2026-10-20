"""DEC-066 synthetic gate tests; no native Odoo or scientific evidence here."""

from copy import deepcopy
from dataclasses import asdict, replace
from functools import lru_cache
import hashlib
import importlib.util
import json
from pathlib import Path
import sys

import pytest


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "gateway" / "tests"))
SPEC = importlib.util.spec_from_file_location(
    "dataset_fixture_evidence_validator_test", ROOT / "scripts" / "validate_dataset_fixture_evidence.py",
)
validator = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(validator)

from tcc_gateway.pdf_ingestion import extract_pdf_bytes
from tcc_gateway.state import canonical_json_bytes
from tcc_gateway.synthetic_pdf import build_text_layer_pdf
from tcc_gateway.trusted_resolution import canonicalize_proposal
from runner_dataset_fixture_gateway import LedgerCaller, evaluate_case
from test_operational_observation import _binding, _observation, _rehash
from test_trusted_resolution import FakeOdoo, _proposal, _workflow


def _json(value):
    return json.loads(canonical_json_bytes(value))


def _projection(binding, post):
    value = {model: [] for model in validator.PROJECTION_FIELDS}

    def row(model, identity, **changes):
        result = {field: False for field in validator.PROJECTION_FIELDS[model].split()}
        result.update(id=identity, **changes)
        value[model].append(result)

    relation = lambda identity: [identity, "SINTETICO SEM VALOR FISCAL"]
    action = canonicalize_proposal(_proposal(post=post), policy_version="policy-v1.0.0",
                                  quantity_scale=2, target_move_id=42 if post else None)
    row("res.partner", binding.vendor_id, ref=action.vendor_ref, active=True, supplier_rank=1)
    row("res.partner.bank", binding.allowed_bank_ids[0], active=True, allow_out_payment=True,
        acc_number=action.recipient_bank_ref, partner_id=relation(binding.vendor_id))
    row("purchase.order", binding.purchase_order_id, state="purchase", amount_total=125.5,
        partner_id=relation(binding.vendor_id))
    row("purchase.order.line", binding.purchase_line_ids[0], price_unit=125.5, product_qty=1.0,
        qty_to_invoice=0.0 if post else 1.0, order_id=relation(binding.purchase_order_id),
        discount=0.0, tax_ids=[])
    row("ap.security.workflow.registration", binding.registration_id)
    row("company_locks", binding.company_id)
    if post:
        row("account.move", 42, state="draft", move_type="in_invoice", amount_total=125.5,
            ref=action.document_ref, invoice_date=action.invoice_date, invoice_origin=action.purchase_order_ref,
            partner_id=relation(binding.vendor_id), partner_bank_id=relation(binding.allowed_bank_ids[0]),
            journal_id=relation(binding.journal_id))
        row("account.move.line", 51, move_id=relation(42), purchase_line_id=relation(binding.purchase_line_ids[0]),
            account_id=relation(90), quantity=1.0, price_unit=125.5, debit=125.5, credit=0.0,
            discount=0.0, tax_ids=[])
        row("account.move.line", 52, move_id=relation(42), purchase_line_id=False,
            account_id=relation(91), quantity=0.0, price_unit=0.0, debit=0.0, credit=125.5,
            discount=0.0, tax_ids=[])
    value.update(auxiliary_counts={name: 0 for name in validator.AUXILIARY_MODELS}, attachment_storage="db")
    return value


@lru_cache(maxsize=1)
def _template():
    inputs, cases, documents, pdfs, confirmations = {}, [], {}, {}, []
    for index, name in enumerate(validator.CASE_IDS):
        post = index == 1
        raw = build_text_layer_pdf("DOCUMENTO SINTETICO SEM VALOR FISCAL " + name)
        document = extract_pdf_bytes(raw)
        workflow = replace(_workflow(post=post), scenario_id=f"DEC066-TEST-{index}",
                           document_sha256=document.document_sha256)
        action = replace(canonicalize_proposal(_proposal(post=post), policy_version="policy-v1.0.0",
            quantity_scale=2, target_move_id=42 if post else None),
            scenario_id=workflow.scenario_id, document_sha256=document.document_sha256)
        binding = _binding(registration_id=60 + index)
        observed = _observation(post=post)
        observed["registration"]["registration_id"] = binding.registration_id
        observed["scope"].update(scenario_id=workflow.scenario_id,
            document_sha256=document.document_sha256, action_sha256=action.action_hash)
        observed = _rehash(observed)
        projection = _projection(binding, post)
        case = {"name": name, "fixture_ref": f"DEC066-FIXTURE-{index}", "workflow": _json(asdict(workflow)),
            "legitimate_action": action.to_mapping(), "observation": observed, "binding": binding.to_mapping(),
            "expected_lines": [{"item_code": "TCC-SERVICE-001", "purchase_line_id": 40, "product_id": 30}],
            "target_move_id": 42 if post else None,
            "projection_before": deepcopy(projection), "projection_after": deepcopy(projection)}
        cases.append(case)
        documents[name], pdfs[name] = document, raw
        confirmations.append({"name": name, "projection": deepcopy(projection)})
    inputs.update(schema_version="dataset-fixture-native-inputs/v1", status="PASS", git_base="e" * 40,
        source_bundle_sha256="f" * 64, configuration_sha256="1" * 64,
        company_id=1, company_name=cases[0]["workflow"]["company_name"], reader_user_id=71, cases=cases)
    declaration = {name: inputs[name] for name in validator.DECLARATION_KEYS}
    results = []
    for index, case in enumerate(cases):
        caller = LedgerCaller(FakeOdoo(post=index == 1))
        result = evaluate_case(case, documents[case["name"]], caller)
        results.append({"name": case["name"], "result": result, "calls": caller.calls})
    raw_input = canonical_json_bytes(inputs) + b"\n"
    input_sha256 = hashlib.sha256(raw_input).hexdigest()
    resolution = {"schema_version": "dataset-fixture-resolution/v1", "status": "PASS", **declaration,
                  "input_sha256": input_sha256, "cases": results,
                  **{name: False for name in validator.FALSE_FLAGS}}
    confirmation = {"schema_version": "dataset-fixture-native-confirmation/v1", "status": "PASS",
                    **declaration, "reader_readonly_acl_verified": True, "cases": confirmations}
    return dict(zip(validator.FILENAMES, (inputs, resolution, confirmation), strict=True)), documents, pdfs, input_sha256


def _proof():
    return deepcopy(_template())


def _accept(records, documents, input_sha256):
    inputs = records[validator.FILENAMES[0]]
    return validator.validate_bundle(records, documents, git_base=inputs["git_base"],
        source_bundle_sha256=inputs["source_bundle_sha256"], input_sha256=input_sha256)


def test_synthetic_read_ledger_replays_both_actions_without_mutating_artifacts():
    records, documents, _pdfs, digest = _proof()
    before = deepcopy(records)
    result = _accept(records, documents, digest)
    assert result["case_count"] == 2 and result["native_json2_request_count"] > 0
    assert records == before
    rows = records[validator.FILENAMES[1]]["cases"]
    assert [row["result"]["oracle_case"]["expected_action"] for row in rows] == [
        "CREATE_DRAFT_BILL", "POST_VENDOR_BILL"]
    assert all(row["result"]["pair"]["split"] == "development" for row in rows)


@pytest.mark.parametrize("filename", validator.FILENAMES)
@pytest.mark.parametrize("mutation", ["extra", "missing", "numeric-status"])
def test_every_top_level_envelope_is_closed(filename, mutation):
    records, documents, _pdfs, digest = _proof()
    value = records[filename]
    if mutation == "extra":
        value["untrusted"] = "PRIVATE-MARKER"
    elif mutation == "missing":
        value.pop("status")
    else:
        value["status"] = 1
    with pytest.raises(ValueError):
        _accept(records, documents, digest)


@pytest.mark.parametrize("filename", validator.FILENAMES[1:])
@pytest.mark.parametrize("field", sorted(validator.DECLARATION_KEYS))
def test_cross_artifact_source_and_configuration_are_bound(filename, field):
    records, documents, _pdfs, digest = _proof()
    records[filename][field] = "a" * (40 if field == "git_base" else 64)
    with pytest.raises(ValueError):
        _accept(records, documents, digest)


@pytest.mark.parametrize("filename", validator.FILENAMES)
@pytest.mark.parametrize("mutation", ["missing", "extra", "duplicate", "reordered"])
def test_exact_two_named_cases_are_required_in_every_artifact(filename, mutation):
    records, documents, _pdfs, digest = _proof()
    rows = records[filename]["cases"]
    if mutation == "missing":
        rows.pop()
    elif mutation == "extra":
        rows.append(deepcopy(rows[0]))
    elif mutation == "duplicate":
        rows[1] = deepcopy(rows[0])
    else:
        rows.reverse()
    with pytest.raises(ValueError):
        _accept(records, documents, digest)


@pytest.mark.parametrize("field", sorted(validator.FALSE_FLAGS))
@pytest.mark.parametrize("invalid", [True, 0, "false", None])
def test_limits_are_exact_false_booleans(field, invalid):
    records, documents, _pdfs, digest = _proof()
    records[validator.FILENAMES[1]][field] = invalid
    with pytest.raises(ValueError):
        _accept(records, documents, digest)


@pytest.mark.parametrize("mutation", ["empty", "missing", "extra", "order", "method", "model", "headers",
    "context", "limit-bool", "domain", "result", "call-extra", "call-missing"])
def test_read_ledger_is_recomputed_consumed_and_rejects_effects_or_hidden_calls(mutation):
    records, documents, _pdfs, digest = _proof()
    calls = records[validator.FILENAMES[1]]["cases"][0]["calls"]
    if mutation == "empty":
        calls.clear()
    elif mutation == "missing":
        calls.pop()
    elif mutation == "extra":
        calls.append(deepcopy(calls[-1]))
    elif mutation == "order":
        calls.reverse()
    elif mutation in {"method", "model"}:
        calls[0][mutation] = "create" if mutation == "method" else "res.users"
    elif mutation == "headers":
        calls[0]["headers"] = {"untrusted": "PRIVATE-MARKER"}
    elif mutation == "context":
        calls[0]["arguments"]["context"] = {"allowed_company_ids": [1]}
    elif mutation == "limit-bool":
        calls[0]["arguments"]["limit"] = True
    elif mutation == "domain":
        calls[0]["arguments"]["domain"] = []
    elif mutation == "result":
        calls[0]["result"] = []
    elif mutation == "call-extra":
        calls[0]["extra"] = 1
    else:
        calls[0].pop("result")
    with pytest.raises(ValueError):
        _accept(records, documents, digest)


@pytest.mark.parametrize("field", ["pair", "binding", "oracle_case", "expected_effect", "name"])
def test_resolution_and_evaluator_handoff_cannot_be_fabricated(field):
    records, documents, _pdfs, digest = _proof()
    result = records[validator.FILENAMES[1]]["cases"][0]["result"]
    result[field] = "PRIVATE-MARKER"
    with pytest.raises(ValueError):
        _accept(records, documents, digest)


@pytest.mark.parametrize("location", ["projection_before", "projection_after", "fresh"])
@pytest.mark.parametrize("mutation", ["empty", "field-missing", "id-bool", "row-duplicate", "negative-count", "count-bool"])
def test_projection_is_complete_typed_and_has_unique_native_identities(location, mutation):
    records, documents, _pdfs, digest = _proof()
    case = records[validator.FILENAMES[0]]["cases"][0]
    projection = (records[validator.FILENAMES[2]]["cases"][0]["projection"]
                  if location == "fresh" else case[location])
    if mutation == "empty":
        projection.clear()
    elif mutation == "field-missing":
        projection["res.partner"][0].pop("supplier_rank")
    elif mutation == "id-bool":
        projection["res.partner"][0]["id"] = True
    elif mutation == "row-duplicate":
        projection["res.partner"].append(deepcopy(projection["res.partner"][0]))
    else:
        projection["auxiliary_counts"]["mail.message"] = -1 if mutation == "negative-count" else False
    with pytest.raises(ValueError):
        _accept(records, documents, digest)


@pytest.mark.parametrize("mutation", ["financial-value", "audit-value", "payment", "approval", "storage", "target"])
def test_projection_changes_or_effects_cannot_be_hidden_by_pass_status(mutation):
    records, documents, _pdfs, digest = _proof()
    confirmed = records[validator.FILENAMES[2]]["cases"][1]["projection"]
    if mutation == "financial-value":
        confirmed["account.move"][0]["amount_total"] = 900.0
    elif mutation == "audit-value":
        confirmed["ap.security.audit.event"].append({"id": 1})
    elif mutation == "payment":
        confirmed["auxiliary_counts"]["account.payment"] = 1
    elif mutation == "approval":
        confirmed["ap.security.approval.nonce"].append({"id": 1})
    elif mutation == "storage":
        confirmed["attachment_storage"] = "file"
    else:
        confirmed["account.move"][0]["state"] = "posted"
    with pytest.raises(ValueError):
        _accept(records, documents, digest)


def test_matching_but_empty_or_field_truncated_projections_do_not_pass():
    records, documents, _pdfs, digest = _proof()
    value = {key: [] for key in validator.PROJECTION_MODELS}
    value.update(attachments=[], auxiliary_counts={name: 0 for name in validator.AUXILIARY_MODELS},
                 company_locks=[], attachment_storage="db")
    case = records[validator.FILENAMES[0]]["cases"][0]
    case["projection_before"] = deepcopy(value)
    case["projection_after"] = deepcopy(value)
    records[validator.FILENAMES[2]]["cases"][0]["projection"] = deepcopy(value)
    with pytest.raises(ValueError):
        _accept(records, documents, digest)


@pytest.mark.parametrize("model,field,value", [
    ("res.partner", "ref", "OTHER-VENDOR"),
    ("res.partner.bank", "acc_number", "OTHER-BANK"),
    ("res.partner.bank", "partner_id", [999, "OTHER"]),
    ("res.partner.bank", "allow_out_payment", False),
    ("purchase.order", "amount_total", 900),
    ("purchase.order", "partner_id", [999, "OTHER"]),
    ("purchase.order.line", "product_qty", 2),
    ("purchase.order.line", "price_unit", 900),
    ("purchase.order.line", "order_id", [999, "OTHER"]),
    ("account.move", "ref", "OTHER-REF"),
    ("account.move", "invoice_date", "2026-10-01"),
    ("account.move", "invoice_origin", "OTHER-PO"),
    ("account.move", "partner_bank_id", [999, "OTHER"]),
    ("account.move", "partner_id", [999, "OTHER"]),
    ("account.move", "amount_total", 900),
    ("account.move", "journal_id", [999, "OTHER"]),
])
def test_consistently_forged_native_facts_fail_independent_setup_join(model, field, value):
    records, documents, _pdfs, digest = _proof()
    case = records[validator.FILENAMES[0]]["cases"][1]
    snapshots = [case["projection_before"], case["projection_after"],
                 records[validator.FILENAMES[2]]["cases"][1]["projection"]]
    for projection in snapshots:
        projection[model][0][field] = deepcopy(value)
    with pytest.raises(ValueError):
        _accept(records, documents, digest)


def _post_snapshots(records):
    case = records[validator.FILENAMES[0]]["cases"][1]
    return [case["projection_before"], case["projection_after"],
            records[validator.FILENAMES[2]]["cases"][1]["projection"]]


def test_post_requires_real_linked_invoice_line_and_allows_payable_counterpart():
    records, documents, _pdfs, digest = _proof()
    for projection in _post_snapshots(records):
        lines = projection["account.move.line"]
        assert [line["id"] for line in lines] == [51, 52]
        assert lines[0]["purchase_line_id"][0] == 40 and lines[1]["purchase_line_id"] is False
    assert _accept(records, documents, digest)["case_count"] == 2


@pytest.mark.parametrize("mutation", [
    "empty", "only-counterpart", "move-mismatch", "purchase-absent", "purchase-unknown",
    "purchase-bool", "purchase-duplicate", "purchase-extra", "line-identity", "quantity",
    "unit-price", "discount", "tax", "tax-false", "quantity-bool", "counterpart-linked",
])
def test_identically_corrupted_post_snapshots_cannot_hide_missing_or_changed_lines(mutation):
    records, documents, _pdfs, digest = _proof()
    for projection in _post_snapshots(records):
        lines = projection["account.move.line"]
        if mutation == "empty":
            lines.clear()
        elif mutation == "only-counterpart":
            lines.pop(0)
        elif mutation == "move-mismatch":
            lines[0]["move_id"][0] = 999
        elif mutation == "purchase-absent":
            lines[0]["purchase_line_id"] = False
        elif mutation == "purchase-unknown":
            lines[0]["purchase_line_id"][0] = 999
        elif mutation == "purchase-bool":
            lines[0]["purchase_line_id"][0] = True
        elif mutation in {"purchase-duplicate", "purchase-extra"}:
            extra = deepcopy(lines[0])
            extra["id"] = 53
            if mutation == "purchase-extra":
                extra["purchase_line_id"][0] = 999
            lines.append(extra)
        elif mutation == "line-identity":
            lines[0]["id"] = 50
        elif mutation == "quantity":
            lines[0]["quantity"] = 2.0
        elif mutation == "unit-price":
            lines[0]["price_unit"] = 900.0
        elif mutation == "discount":
            lines[0]["discount"] = 1.0
        elif mutation == "tax":
            lines[0]["tax_ids"] = [9]
        elif mutation == "tax-false":
            lines[0]["tax_ids"] = False
        elif mutation == "quantity-bool":
            lines[0]["quantity"] = True
        else:
            lines[1]["purchase_line_id"] = deepcopy(lines[0]["purchase_line_id"])
    with pytest.raises(ValueError):
        _accept(records, documents, digest)


@pytest.mark.parametrize("field,value", [("tax_ids", [9]), ("tax_ids", False), ("discount", 1.0), ("discount", False)])
def test_identical_native_po_taxes_or_discount_fail_fixed_scope(field, value):
    records, documents, _pdfs, digest = _proof()
    for projection in _post_snapshots(records):
        projection["purchase.order.line"][0][field] = deepcopy(value)
    with pytest.raises(ValueError):
        _accept(records, documents, digest)


def test_other_move_line_with_no_purchase_link_does_not_invent_target_line():
    records, documents, _pdfs, digest = _proof()
    for projection in _post_snapshots(records):
        line = deepcopy(projection["account.move.line"][1])
        line.update(id=53, move_id=[999, "OTHER SYNTHETIC MOVE"])
        projection["account.move.line"].append(line)
    assert _accept(records, documents, digest)["case_count"] == 2


@pytest.mark.parametrize("identity", [1, True, 70])
def test_reader_identity_is_distinct_from_administrative_or_executor_identity(identity):
    records, documents, _pdfs, digest = _proof()
    records[validator.FILENAMES[0]]["reader_user_id"] = identity
    with pytest.raises(ValueError):
        _accept(records, documents, digest)


@pytest.mark.parametrize("invalid", [False, 1, "true", None])
def test_reader_acl_verification_is_exact_boolean(invalid):
    records, documents, _pdfs, digest = _proof()
    records[validator.FILENAMES[2]]["reader_readonly_acl_verified"] = invalid
    with pytest.raises(ValueError):
        _accept(records, documents, digest)


def test_input_bytes_hash_and_actual_pdf_provenance_are_bound():
    records, documents, _pdfs, digest = _proof()
    with pytest.raises(ValueError):
        _accept(records, documents, "a" * 64)
    documents[validator.CASE_IDS[0]] = documents[validator.CASE_IDS[1]]
    with pytest.raises(ValueError):
        _accept(records, documents, digest)


def _write_bundle(directory, records, pdfs):
    directory.mkdir(parents=True)
    for name, value in records.items():
        (directory / name).write_bytes(canonical_json_bytes(value) + b"\n")
    for name, raw in pdfs.items():
        (directory / (name + ".pdf")).write_bytes(raw)


def _arguments(directory, records, output):
    inputs = records[validator.FILENAMES[0]]
    return ["--artifacts", str(directory), "--git-base", inputs["git_base"],
            "--source-bundle-sha256", inputs["source_bundle_sha256"], "--output", str(output)]


def test_cli_reads_actual_pdf_and_hashes_all_private_artifacts(tmp_path, monkeypatch, capsys):
    records, _documents, pdfs, _digest = _proof()
    monkeypatch.setattr(validator, "ROOT", tmp_path)
    directory = tmp_path / ".runtime" / "runner-native" / "synthetic" / "artifacts"
    _write_bundle(directory, records, pdfs)
    output = directory / "dataset-fixture-validation.json"
    assert validator.main(_arguments(directory, records, output)) == 0
    result = json.loads(capsys.readouterr().out)
    assert result == json.loads(output.read_text(encoding="utf-8"))
    assert result["status"] == "PASS" and set(result["artifact_sha256"]) == set(validator.FILENAMES)
    assert all(result[name] is False for name in ("scientific_run", "human_review_complete", "public_executor_enabled"))


@pytest.mark.parametrize("mutation", ["outside-input", "outside-output", "wrong-output-name", "json", "pdf", "missing"])
def test_cli_failures_remain_finite_and_never_echo_private_artifacts(tmp_path, monkeypatch, capsys, mutation):
    records, _documents, pdfs, _digest = _proof()
    monkeypatch.setattr(validator, "ROOT", tmp_path)
    directory = tmp_path / ".runtime" / "runner-native" / "synthetic" / "artifacts"
    if mutation == "outside-input":
        directory = tmp_path / "outside" / "artifacts"
    _write_bundle(directory, records, pdfs)
    output = directory / "dataset-fixture-validation.json"
    if mutation == "outside-output":
        output = tmp_path / output.name
    elif mutation == "wrong-output-name":
        output = directory / "other.json"
    elif mutation == "json":
        (directory / validator.FILENAMES[0]).write_bytes(b'{"PRIVATE-MARKER":NaN}')
    elif mutation == "pdf":
        (directory / (validator.CASE_IDS[0] + ".pdf")).write_bytes(b"PRIVATE-MARKER")
    elif mutation == "missing":
        (directory / validator.FILENAMES[0]).unlink()
    assert validator.main(_arguments(directory, records, output)) == 1
    text = capsys.readouterr().out
    result = json.loads(text)
    assert result["status"] == "FAIL" and result["case_count"] == 0
    assert "PRIVATE-MARKER" not in text and "Traceback" not in text
