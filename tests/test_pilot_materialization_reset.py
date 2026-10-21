"""DEC-073 host contracts with structural doubles; no Docker or API calls."""

import base64
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import pilot_materialization_reset as reset
from tcc_gateway.pilot_a3a_origin_contract import ORIGIN_VERSION, parse_origin_input
from tcc_gateway.pilot_seed_contract import (
    ALTERNATIVES_VERSION, SEED_VERSION, parse_alternative_catalog, parse_business_seed,
)
from tcc_gateway.company_capture import (
    CaptureBinding, ROW_FIELDS, assert_restored, capture_sha256,
)
from tcc_gateway.state import canonical_json_bytes, canonical_json_sha256


def business_input():
    return {"schema_version": SEED_VERSION, "split": "pilot-v0", "status": "CANDIDATE",
        "synthetic_data": True, "fiscal_value": False, "cohort_sha256": "a" * 64,
        "codebook_sha256": "b" * 64, "dataset_version": "structural-double-v0", "fixtures": [
            {"fixture_ref": f"FIX-{index:02d}", "pair_sha256": hashlib.sha256(str(index).encode()).hexdigest(),
             "company_ref": "COMPANY-001", "vendor_ref": f"VENDOR-{index:02d}",
             "purchase_order_ref": f"PO-{index:02d}", "invoice_date": "2026-10-15",
             "currency": "BRL", "amount": "125.50", "approved_bank_ref": f"BANK-{index:02d}",
             "quantity_scale": 2, "lines": [{"item_code": "ITEM-001", "quantity": "1.00",
                                             "unit_price": "125.50", "line_total": "125.50"}]}
            for index in range(12)]}


def candidate_inputs():
    seed = parse_business_seed(business_input())
    catalog = parse_alternative_catalog({"schema_version": ALTERNATIVES_VERSION,
        "split": "pilot-v0", "status": "CANDIDATE", "synthetic_data": True, "fiscal_value": False,
        "seed_sha256": seed.sha256, "cohort_sha256": "a" * 64, "codebook_sha256": "b" * 64,
        "vendor_refs": ["VENDOR-01"],
        "purchase_order_checks": [{"purchase_order_ref": "PO-01", "item_codes": ["ITEM-001"]}],
        "banks": [{"bank_ref": "BANK-ALTERNATIVE", "owner_vendor_ref": "VENDOR-02"}]})
    rows = []
    for index, business in enumerate(seed.to_mapping()["fixtures"][:4]):
        documents = []
        for member in range(2):
            raw = f"%PDF-1.4\nSTRUCTURAL-DOUBLE-{index}-{member}\n%%EOF".encode()
            documents.append({"scenario_id": f"SCN-{index}-{member}",
                "document_sha256": hashlib.sha256(raw).hexdigest(),
                "extracted_text_sha256": hashlib.sha256(b"TEXT" + raw).hexdigest(),
                "pdf_base64": base64.b64encode(raw).decode()})
        rows.append({"fixture_ref": business["fixture_ref"], "pair_sha256": business["pair_sha256"],
            "document_ref": f"DOC-{index}", "invoice_date_min": "2026-10-01",
            "invoice_date_max": "2026-10-31", "document": documents[0], "other_document": documents[1]})
    first = {"schema_version": ORIGIN_VERSION, "status": "CANDIDATE", "split": "pilot-v0",
        "synthetic_data": True, "fiscal_value": False, "seed_sha256": seed.sha256,
        "cohort_sha256": "a" * 64, "codebook_sha256": "b" * 64, "fixtures": rows}
    second = deepcopy(first)
    for row in second["fixtures"]:
        row["document"], row["other_document"] = row["other_document"], row["document"]
    return seed, catalog, (parse_origin_input(first), parse_origin_input(second))


def bare(tmp_path):
    value = object.__new__(reset.PilotResetHarness)
    value.run_id = "a" * 32
    value.repository = ROOT
    value.prefix = "tcc-state-" + value.run_id
    value.root = tmp_path
    value.artifacts = tmp_path / "artifacts"
    value.artifacts.mkdir()
    value.snapshot = tmp_path / "snapshot"
    value.current_server = None
    return value


def test_inputs_link_exact_seed_catalog_and_inverse_origins_without_mutation():
    seed, catalog, origins = candidate_inputs()
    before = seed.to_mapping(), catalog.to_mapping(), tuple(item.to_mapping() for item in origins)
    proof = reset.validate_inputs(seed, catalog, origins)
    assert proof == {"schema_version": "pilot-materialization-reset-inputs/v1",
        "seed_sha256": seed.sha256, "catalog_sha256": catalog.sha256,
        "origin_input_sha256s": [item.sha256 for item in origins],
        "cohort_sha256": "a" * 64, "codebook_sha256": "b" * 64}
    assert before == (seed.to_mapping(), catalog.to_mapping(), tuple(item.to_mapping() for item in origins))
    assert "pdf_base64" not in json.dumps(proof)
    assert "POST_VENDOR_BILL" not in json.dumps(proof)


@pytest.mark.parametrize("field", ["seed_sha256", "cohort_sha256", "codebook_sha256"])
@pytest.mark.parametrize("member", [0, 1])
def test_origin_provenance_mixing_is_rejected(field, member):
    seed, catalog, origins = candidate_inputs()
    changed = origins[member].to_mapping()
    changed[field] = "e" * 64
    altered = list(origins)
    altered[member] = parse_origin_input(changed)
    with pytest.raises(ValueError):
        reset.validate_inputs(seed, catalog, tuple(altered))


@pytest.mark.parametrize("field", ["seed_sha256", "cohort_sha256", "codebook_sha256"])
def test_catalog_provenance_mixing_is_rejected(field):
    seed, catalog, origins = candidate_inputs()
    changed = catalog.to_mapping()
    changed[field] = "e" * 64
    with pytest.raises(ValueError):
        reset.validate_inputs(seed, parse_alternative_catalog(changed), origins)


@pytest.mark.parametrize("kind", ["none", "one", "three", "same-first", "same-second"])
def test_exactly_two_distinct_inverse_packages_required(kind):
    seed, catalog, origins = candidate_inputs()
    bad = {"none": (), "one": origins[:1], "three": (*origins, origins[0]),
           "same-first": (origins[0], origins[0]), "same-second": (origins[1], origins[1])}[kind]
    with pytest.raises(ValueError):
        reset.validate_inputs(seed, catalog, bad)


@pytest.mark.parametrize("kind", ["fixture", "pair", "reference", "date-min", "date-max", "partial-swap"])
def test_inverse_must_preserve_every_non_document_fact(kind):
    seed, catalog, origins = candidate_inputs()
    changed = origins[1].to_mapping()
    row = changed["fixtures"][0]
    if kind == "fixture":
        row["fixture_ref"] = "FIX-00-OTHER"
    elif kind == "pair":
        row["pair_sha256"] = "f" * 64
    elif kind == "reference":
        row["document_ref"] = "DOC-DIFFERENT"
    elif kind == "date-min":
        row["invoice_date_min"] = "2026-10-02"
    elif kind == "date-max":
        row["invoice_date_max"] = "2026-10-30"
    else:
        row["document"], row["other_document"] = row["other_document"], row["document"]
    with pytest.raises(ValueError):
        reset.validate_inputs(seed, catalog, (origins[0], parse_origin_input(changed)))


@pytest.mark.parametrize("kind", ["unknown-fixture", "pair", "outside-date"])
def test_mutually_inverse_packages_still_need_exact_seed_facts(kind):
    seed, catalog, origins = candidate_inputs()
    altered = [item.to_mapping() for item in origins]
    for value in altered:
        row = value["fixtures"][0]
        if kind == "unknown-fixture":
            row["fixture_ref"] = "FIX-00-OTHER"
        elif kind == "pair":
            row["pair_sha256"] = "f" * 64
        else:
            row["invoice_date_min"] = "2026-10-16"
    with pytest.raises(ValueError):
        reset.validate_inputs(seed, catalog, tuple(parse_origin_input(item) for item in altered))


@pytest.mark.parametrize("generation", [True, False, -1, 17, 1.0, "1", None])
def test_clone_generation_requires_closed_exact_integer(tmp_path, generation):
    with pytest.raises(ValueError):
        bare(tmp_path).database(generation)


def test_database_names_are_unique_deterministic_and_bounded_to_run(tmp_path):
    value = bare(tmp_path)
    names = [value.database(generation) for generation in range(17)]
    assert names == ["tcc_runner_" + hashlib.sha256((value.run_id + ":" + str(generation)).encode()).hexdigest()[:12]
                     for generation in range(17)]
    assert len(set(names)) == 17
    for name in names:
        value.assert_database(name)
    for name in ("postgres", "tcc_runner_bbbbbbbbbbbb", "tcc_state_aaaaaaaaaaaa_001",
                 names[0] + "x", "x'; DROP DATABASE x;--"):
        with pytest.raises(ValueError):
            value.assert_database(name)


def test_manifest_rebinding_changes_only_database_and_deep_copies():
    original = {"database": "tcc_runner_aaaaaaaaaaaa", "company_id": 42,
        "native_cases": [{"registration_id": 91, "receipt": {"move_id": 81}, "document_sha256": "a" * 64}],
        "configuration_sha256": "b" * 64, "git_base": "c" * 40}
    before = deepcopy(original)
    clone = reset.clone_manifest(original, "tcc_runner_bbbbbbbbbbbb", source_database=original["database"])
    expected = deepcopy(before)
    expected["database"] = "tcc_runner_bbbbbbbbbbbb"
    assert clone == expected
    assert original == before
    clone["native_cases"][0]["receipt"]["move_id"] = 999
    assert original == before


@pytest.mark.parametrize("source,target", [
    ("tcc_runner_cccccccccccc", "tcc_runner_bbbbbbbbbbbb"),
    ("tcc_runner_aaaaaaaaaaaa", "tcc_runner_aaaaaaaaaaaa"),
    ("postgres", "tcc_runner_bbbbbbbbbbbb"),
    ("tcc_runner_aaaaaaaaaaaa", "postgres"),
    ("tcc_runner_aaaaaaaaaaaa", "tcc_runner_ABCDEFABCDEF"),
    ("tcc_runner_aaaaaaaaaaaa", "tcc_runner_bbbbbbbbbbbbx"),
    ("tcc_runner_aaaaaaaaaaaa", "x'; DROP DATABASE x;--"),
])
def test_manifest_source_destination_validation_rejects_ambiguous_rebinding(source, target):
    original = {"database": "tcc_runner_aaaaaaaaaaaa", "company_id": 42}
    before = deepcopy(original)
    with pytest.raises(ValueError):
        reset.clone_manifest(original, target, source_database=source)
    assert original == before


def capture_input():
    binding = CaptureBinding(42, "TCC STRUCTURAL COMPANY - SEM VALOR FISCAL",
        "a" * 64, "b" * 40, "c" * 64, "d" * 64)
    records = {name: [] for name in ROW_FIELDS}
    records["res.company"] = [{"ordinal": 1, "name": binding.company_name,
        "currency_id": 1, "partner_id": 1, "fiscalyear_lock_date": None,
        "tax_lock_date": None, "sale_lock_date": None, "purchase_lock_date": None,
        "hard_lock_date": None}]
    records["res.currency"] = [{"ordinal": 1, "name": "BRL", "rounding": "0.01",
        "decimal_places": 2, "active": True}]
    records["res.partner"] = [{"ordinal": 1, "ref": "PARTNER-STRUCTURAL",
        "name": "SYNTHETIC COMPANY - SEM VALOR FISCAL", "company_id": 1,
        "supplier_rank": 0, "customer_rank": 0, "autopost_bills": "never", "trust": "normal"}]
    records["outbox"] = [{"ordinal": 1, "enabled": False}]
    identities = {name: list(range(1, len(rows) + 1)) for name, rows in records.items()}
    identities["res.company"] = [42]
    value = {"schema_version": "company-capture/v1", "binding": binding.to_mapping(),
        "records": records, "identity_map": identities, "filestore": []}
    resign_capture(value)
    return binding, value


def resign_capture(value):
    value["state_sha256"] = canonical_json_sha256({"records": value["records"], "filestore": value["filestore"]})
    value.pop("capture_sha256", None)
    value["capture_sha256"] = capture_sha256(value)


def test_capture_reader_uses_existing_parser_and_preserves_raw_identity_guard(tmp_path):
    binding, value = capture_input()
    path = tmp_path / "capture.json"
    path.write_bytes(canonical_json_bytes(value))
    baseline = reset.read_capture(path, binding)
    assert baseline.to_mapping() == value
    assert_restored(baseline, reset.read_capture(path, binding))
    altered = deepcopy(value)
    altered["identity_map"]["res.partner"] = [999]
    resign_capture(altered)
    assert altered["state_sha256"] == value["state_sha256"]
    path.write_bytes(canonical_json_bytes(altered))
    with pytest.raises(ValueError):
        assert_restored(baseline, reset.read_capture(path, binding))


@pytest.mark.parametrize("kind", ["invalid-json", "duplicate-key", "nonfinite", "state-hash", "capture-hash", "binding"])
def test_capture_reader_rejects_corruption_without_repair(tmp_path, kind):
    binding, value = capture_input()
    if kind == "invalid-json":
        raw = b"{PRIVATE-MARKER"
    elif kind == "duplicate-key":
        raw = b'{"schema_version":0,"schema_version":1}'
    elif kind == "nonfinite":
        raw = b'{"schema_version":NaN}'
    else:
        if kind == "state-hash":
            value["state_sha256"] = "f" * 64
        elif kind == "capture-hash":
            value["capture_sha256"] = "f" * 64
        else:
            value["binding"]["code_sha256"] = "f" * 64
            resign_capture(value)
        raw = canonical_json_bytes(value)
    path = tmp_path / "capture.json"
    path.write_bytes(raw)
    with pytest.raises(ValueError) as caught:
        reset.read_capture(path, binding)
    assert "PRIVATE-MARKER" not in str(caught.value)


def test_capture_reader_accepts_valid_capture_above_small_receipt_limit(tmp_path):
    binding, value = capture_input()
    template = value["records"]["res.partner"][0]
    for ordinal in range(2, 14):
        row = dict(template, ordinal=ordinal, ref=f"PARTNER-{ordinal:02d}", name="S" * 100_000)
        value["records"]["res.partner"].append(row)
        value["identity_map"]["res.partner"].append(ordinal)
    resign_capture(value)
    raw = canonical_json_bytes(value)
    assert 1_048_576 < len(raw) < 16 * 1024 * 1024
    path = tmp_path / "capture.json"
    path.write_bytes(raw)
    assert reset.read_capture(path, binding).to_mapping() == value


EFFECT_MODELS = ("account.move", "ap.security.draft.receipt", "ap.security.audit.event", "ir.attachment")


def simulated_run(tmp_path, monkeypatch, *, failure=None):
    """Isolate host ordering; real capture/hash semantics are tested above."""
    value = bare(tmp_path)
    value.seed, value.catalog, value.origins = candidate_inputs()
    value.proof_inputs = reset.validate_inputs(value.seed, value.catalog, value.origins)
    value.binding = object()
    value.git_base, value.bundle_hash = "a" * 40, "b" * 64
    value.source_map = {"structural-source.py": "c" * 64}
    value.pins = {}
    value.baseline_manifest_hash = "d" * 64
    value.result = None
    events, selections, writes = [], {}, []

    def capture(*, changed=False, corrupt=False, wrong_model=None):
        records = {model: ([{"structural": "baseline"}, {"structural": "effect"}]
                           if changed and model != wrong_model else [{"structural": "baseline"}])
                   for model in EFFECT_MODELS}
        return SimpleNamespace(reset_sha256=("e" if changed else "f") * 64,
            identity_marker="CHANGED" if corrupt else "BASELINE",
            to_mapping=lambda: {"records": deepcopy(records)})

    value.baseline = capture()

    def stable():
        events.append(("stable",))
        if failure == "stable-before":
            raise reset.HarnessError("SOURCE_OR_BASELINE_CHANGED")
        if failure == "stable-after" and any(row[0] == "assert-restored" for row in events):
            raise reset.HarnessError("SOURCE_OR_BASELINE_CHANGED")

    def restore(generation):
        events.append(("restore", generation))
        return value.database(generation), "structural-data-" + str(generation)

    def clone(database, fixture_ref, member_index):
        events.append(("clone", database, fixture_ref, member_index))
        path = value.artifacts / database
        selections[path] = (fixture_ref, member_index)
        return path

    def native(mode, database, data, artifacts, *, fixture_ref=None, capture_label="baseline"):
        events.append(("native", mode, database, fixture_ref, capture_label))

    def read_capture(path, binding):
        assert binding is value.binding
        events.append(("read-capture", path.name))
        if path.name == "after.capture.json":
            if failure == "effect-missing":
                return capture()
            return capture(changed=True, wrong_model=failure.split(":", 1)[1]
                           if failure and failure.startswith("effect-scope:") else None)
        return capture(corrupt=(failure == "before" and path.name == "before.capture.json")
                       or (failure == "restored" and path.name == "restored.capture.json"))

    def compare(baseline, current):
        events.append(("assert-restored",))
        assert baseline is value.baseline
        if (baseline.reset_sha256 != current.reset_sha256
                or baseline.identity_marker != current.identity_marker
                or baseline.to_mapping() != current.to_mapping()):
            raise reset.HarnessError("STRUCTURAL_RESET_MISMATCH")

    def result(path):
        fixture_ref, member_index = selections[path.parent]
        output = {"schema_version": "pilot-a3a-origin-single-native/v1", "status": "PASS",
            "fixture_ref": fixture_ref, "fixture_count": 1, "negative_binding_checks": 3,
            "origin_input_sha256": value.origins[member_index].sha256, "seed_sha256": value.seed.sha256,
            "git_base": value.git_base, "source_bundle_sha256": value.bundle_hash,
            "fresh_cursor_origins_verified": True, "previous_records_preserved": True,
            "executor_identity_unchanged": True, "private_pdf_verified": True,
            "scientific_run": False, "human_review_complete": False,
            "public_executor_enabled": False, "approval_generated": False, "post_executed": False}
        if failure and failure.startswith("result:"):
            field = failure.split(":", 1)[1]
            output[field] = {"fixture_count": True, "negative_binding_checks": True,
                "fixture_ref": "FIX-UNKNOWN", "origin_input_sha256": "0" * 64,
                "seed_sha256": "0" * 64, "git_base": "0" * 40,
                "source_bundle_sha256": "0" * 64, "schema_version": "pilot-a3a-origin-native/v1",
                "status": "FAIL"}.get(field, not output[field])
        return output

    value.stable, value.restore, value.clone_artifacts, value.native = stable, restore, clone, native
    value.write_evidence = lambda: writes.append(deepcopy(value.result))
    monkeypatch.setattr(reset, "read_capture", read_capture)
    monkeypatch.setattr(reset, "assert_restored", compare)
    monkeypatch.setattr(reset, "read_record", result)
    monkeypatch.setattr(reset, "sha256", lambda _path: "1" * 64)
    return value, events, writes


def test_run_cases_orders_eight_single_origins_between_sixteen_verified_restores(tmp_path, monkeypatch):
    value, events, writes = simulated_run(tmp_path, monkeypatch)
    value.run_cases()
    assert [row[1] for row in events if row[0] == "restore"] == list(range(1, 17))
    native = [row for row in events if row[0] == "native"]
    assert len(native) == 32
    for index in range(8):
        before, materialize, after, restored = native[index * 4:index * 4 + 4]
        assert (before[1], before[4]) == ("capture", "before")
        assert (materialize[1], materialize[4]) == ("materialize", "baseline")
        assert (after[1], after[4]) == ("capture", "after")
        assert (restored[1], restored[4]) == ("capture", "restored")
        assert before[2] == materialize[2] == after[2] == value.database(index * 2 + 1)
        assert restored[2] == value.database(index * 2 + 2)
        assert materialize[3] == f"FIX-{index % 4:02d}"
    assert sum(row[0] == "assert-restored" for row in events) == 16
    assert len(writes) == 1 and writes[0] == value.result
    assert value.result["status"] == "TESTS_PASSED_CLEANUP_PENDING"
    assert value.result["case_count"] == value.result["origin_count"] == 8
    assert value.result["reset_count"] == value.result["restored_clone_count"] == 16
    assert value.result["negative_binding_checks"] == 24
    assert [(row["member_index"], row["fixture_ref"]) for row in value.result["cases"]] == [
        (member, f"FIX-{index:02d}") for member in range(2) for index in range(4)]
    assert len({row["document_sha256"] for row in value.result["cases"]}) == 8
    for row in value.result["cases"]:
        assert row["before_sha256"] == row["restored_sha256"] != row["after_sha256"]
    for flag in ("scientific_run", "human_review_complete", "external_provider_called",
                 "public_executor_enabled", "approval_generated", "post_executed", "c0_c1_comparison_performed"):
        assert value.result[flag] is False


@pytest.mark.parametrize("failure,restores,mutations", [
    ("stable-before", 0, 0), ("before", 1, 0), ("effect-missing", 1, 1),
    ("restored", 2, 1), ("stable-after", 2, 1),
    *[("effect-scope:" + model, 1, 1) for model in EFFECT_MODELS],
])
def test_failed_capture_effect_or_source_check_stops_before_next_member(
        tmp_path, monkeypatch, failure, restores, mutations):
    value, events, writes = simulated_run(tmp_path, monkeypatch, failure=failure)
    with pytest.raises(ValueError):
        value.run_cases()
    assert sum(row[0] == "restore" for row in events) == restores
    assert sum(row[:2] == ("native", "materialize") for row in events) == mutations
    assert writes == [] and value.result is None


@pytest.mark.parametrize("field", ["schema_version", "status", "fixture_ref", "fixture_count",
    "negative_binding_checks", "origin_input_sha256", "seed_sha256", "git_base", "source_bundle_sha256",
    "fresh_cursor_origins_verified", "previous_records_preserved", "executor_identity_unchanged",
    "private_pdf_verified", "scientific_run", "human_review_complete", "public_executor_enabled",
    "approval_generated", "post_executed"])
def test_unit_result_cannot_promote_larger_or_unbound_preparation_to_verified_origin(tmp_path, monkeypatch, field):
    value, events, writes = simulated_run(tmp_path, monkeypatch, failure="result:" + field)
    with pytest.raises(ValueError):
        value.run_cases()
    assert [row[1] for row in events if row[0] == "restore"] == [1]
    assert sum(row[:2] == ("native", "materialize") for row in events) == 1
    assert sum(row[:2] == ("native", "capture") for row in events) == 1
    assert value.result is None and writes == []
