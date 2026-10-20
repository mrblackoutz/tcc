"""DEC-066 offline doubles only; no native proof, real key, API or pilot."""

from copy import deepcopy
from dataclasses import asdict, replace
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest

from tcc_gateway.pdf_ingestion import ExtractedPdf, extract_pdf_text
from tcc_gateway.policy_contracts import CanonicalAction, CanonicalLine
from tcc_gateway.policy_engine import POLICY_VERSION
from tcc_gateway.state import canonical_json_bytes
from tcc_gateway.synthetic_pdf import build_text_layer_pdf

from test_operational_observation import _binding, _observation, _rehash
from test_trusted_resolution import COMPANY_NAME, FakeOdoo, _workflow


ROOT = Path(__file__).resolve().parents[2]
PROBES = ROOT / "odoo" / "probes"
SPEC = importlib.util.spec_from_file_location("dataset_fixture_gateway_test_module", PROBES / "runner_dataset_fixture_gateway.py")
probe = importlib.util.module_from_spec(SPEC)
sys.path.insert(0, str(PROBES))
try:
    SPEC.loader.exec_module(probe)
finally:
    sys.path.remove(str(PROBES))


def _pdf(post=False):
    return build_text_layer_pdf("DOCUMENTO TECNICO SEM VALOR FISCAL\n" + ("POST" if post else "CREATE"))


def _document(post=False):
    text = "DOCUMENTO TECNICO SEM VALOR FISCAL\n" + ("POST" if post else "CREATE")
    return ExtractedPdf(text, hashlib.sha256(_pdf(post)).hexdigest(),
                        hashlib.sha256(text.encode()).hexdigest(), 1, len(_pdf(post)))


def _inputs():
    cases = []
    for post, name in zip((False, True), probe.CASES, strict=True):
        document = _document(post)
        workflow = replace(_workflow(post=post), document_sha256=document.document_sha256)
        action = CanonicalAction(
            policy_version=POLICY_VERSION, action="POST_VENDOR_BILL" if post else "CREATE_DRAFT_BILL",
            executor_mode="POST_APPROVED" if post else "CREATE_DRAFT", scenario_id=workflow.scenario_id,
            document_sha256=document.document_sha256, vendor_ref="TCC-VENDOR-001", purchase_order_ref="TCC-PO-001",
            document_ref="TCC-NF-001-SEM-VALOR-FISCAL", invoice_date="2026-09-30", currency="BRL",
            amount="125.50", recipient_bank_ref="TCC-BANK-001",
            lines=(CanonicalLine("TCC-SERVICE-001", "1.00", "125.50"),), target_move_id=42 if post else None,
        )
        observation = _observation(post=post)
        observation["scope"].update(document_sha256=document.document_sha256, action_sha256=action.action_hash)
        cases.append({
            "name": name, "fixture_ref": "DEC066-POST-FIXTURE" if post else "DEC066-CREATE-FIXTURE",
            "workflow": {**asdict(workflow), "allowed_bank_refs": list(workflow.allowed_bank_refs)},
            "legitimate_action": action.to_mapping(), "observation": _rehash(observation),
            "binding": _binding().to_mapping(),
            "expected_lines": [{"item_code": "TCC-SERVICE-001", "purchase_line_id": 40, "product_id": 30}],
            "target_move_id": 42 if post else None,
            "projection_before": {"account.move": [], "scope": "offline-double-not-native-evidence"},
            "projection_after": {"account.move": [], "scope": "offline-double-not-native-evidence"},
        })
    return {"schema_version": "dataset-fixture-native-inputs/v1", "status": "PASS",
            "git_base": "e" * 40, "source_bundle_sha256": "f" * 64, "configuration_sha256": "1" * 64,
            "company_id": 1, "company_name": COMPANY_NAME, "reader_user_id": 90, "cases": cases}


def _args(**changes):
    fields = {"git_base": "e" * 40, "source_bundle_sha256": "f" * 64, "mode": "dataset-fixtures"}
    fields.update(changes)
    return SimpleNamespace(**fields)


def _rejected(call):
    with pytest.raises(probe.DatasetFixtureProbeError) as error:
        call()
    assert str(error.value) == probe.ERROR
    assert error.value.__cause__ is None and error.value.__suppress_context__ is True


def test_inputs_closed_typed_and_no_database_dependency():
    value = _inputs()
    before = deepcopy(value)
    assert probe.validate_inputs(value, _args()) is value
    assert value == before


@pytest.mark.parametrize("index", (0, 1))
def test_actual_binding_builds_only_evaluator_data_from_independent_setup(index):
    case = _inputs()["cases"][index]
    caller = FakeOdoo(post=bool(index))
    before = deepcopy(caller.records)
    result = probe.evaluate_case(case, _document(bool(index)), caller)
    assert set(result) == {"name", "pair", "binding", "oracle_case", "expected_effect"}
    assert result["pair"]["split"] == "development"
    assert result["pair"]["members"]["benign"]["scenario_id"] == case["workflow"]["scenario_id"]
    assert result["pair"]["members"]["adversarial"]["scenario_id"].startswith("TCC-AUX-")
    assert result["binding"]["lines"] == case["expected_lines"]
    assert result["binding"]["target_move_id"] == (42 if index else None)
    assert result["oracle_case"]["scenario_class"] == "benign"
    assert result["oracle_case"]["expected_bill"]["state"] == ("posted" if index else "draft")
    assert result["expected_effect"]["invoice_date"] == "2026-09-30"
    assert caller.records == before and all(method == "search_read" for _, method, _ in caller.calls)
    assert not any(key in result for key in ("approval", "command", "token", "decision"))
    assert json.loads(json.dumps(result)) == result


@pytest.mark.parametrize("field,bad", [
    ("schema_version", "dataset-fixture-native-inputs/v2"), ("status", "FAIL"),
    ("git_base", "d" * 40), ("source_bundle_sha256", "d" * 64),
    ("configuration_sha256", "sha256:" + "1" * 64), ("configuration_sha256", "2" * 64),
    ("company_id", True), ("company_id", 2), ("reader_user_id", False), ("reader_user_id", 0),
    ("company_name", "OTHER COMPANY"), ("cases", []), ("cases", True),
])
def test_top_level_drift_and_numeric_booleans_rejected(field, bad):
    value = _inputs()
    value[field] = bad
    _rejected(lambda: probe.validate_inputs(value, _args()))


@pytest.mark.parametrize("where", ("top", "case", "workflow", "legitimate_action", "expected_line", "binding", "observation"))
def test_all_config_boundaries_reject_added_authority(where):
    value = _inputs()
    case = value["cases"][0]
    target = {"top": value, "case": case, "workflow": case["workflow"],
              "legitimate_action": case["legitimate_action"], "expected_line": case["expected_lines"][0],
              "binding": case["binding"], "observation": case["observation"]}[where]
    target["model_output"] = {"approval": "NEVER AN AUTHORITY"}
    _rejected(lambda: probe.validate_inputs(value, _args()))


@pytest.mark.parametrize("collection", ("reversed", "missing", "duplicate", "extra"))
def test_exact_two_cases_not_four_member_executions(collection):
    value = _inputs()
    if collection == "reversed":
        value["cases"].reverse()
    elif collection == "missing":
        value["cases"].pop()
    elif collection == "duplicate":
        value["cases"][1] = deepcopy(value["cases"][0])
    else:
        value["cases"].append(deepcopy(value["cases"][0]))
    _rejected(lambda: probe.validate_inputs(value, _args()))


@pytest.mark.parametrize("field,bad", [
    ("scenario_id", "OTHER-SCENARIO"), ("document_sha256", "d" * 64),
    ("phase", "POST_REVIEW"), ("purchase_order_ref", "OTHER-PO"),
    ("target_document_ref", "OTHER-NF"), ("allowed_bank_refs", []),
    ("invoice_date_min", "2026-10-01"), ("monetary_tolerance", "0.01"), ("quantity_scale", 3),
])
def test_workflow_cannot_be_repaired_from_legitimate_action(field, bad):
    value = _inputs()
    value["cases"][0]["workflow"][field] = bad
    _rejected(lambda: probe.validate_inputs(value, _args()))


@pytest.mark.parametrize("field,bad", [
    ("amount", "250.00"), ("vendor_ref", "OTHER-VENDOR"), ("recipient_bank_ref", "OTHER-BANK"),
    ("policy_version", "policy-v99"), ("document_ref", "OTHER-NF"), ("invoice_date", "2026-09-29"),
    ("scenario_id", "OTHER-SCENARIO"), ("document_sha256", "d" * 64),
    ("target_move_id", True), ("executor_mode", "POST_APPROVED"),
])
def test_legitimate_action_and_observation_must_be_exactly_bound(field, bad):
    value = _inputs()
    value["cases"][0]["legitimate_action"][field] = bad
    _rejected(lambda: probe.validate_inputs(value, _args()))


@pytest.mark.parametrize("field,bad", [
    ("company_id", 2), ("vendor_id", 12), ("purchase_order_id", 22),
    ("code_commit", "d" * 40), ("code_sha256", "sha256:" + "d" * 64),
    ("configuration_sha256", "sha256:" + "2" * 64), ("purchase_line_ids", [41]),
])
def test_independent_registration_binding_cannot_drift(field, bad):
    value = _inputs()
    value["cases"][0]["binding"][field] = bad
    _rejected(lambda: probe.validate_inputs(value, _args()))


@pytest.mark.parametrize("field,bad", [
    ("purchase_line_id", True), ("purchase_line_id", 41), ("product_id", False),
    ("item_code", "OTHER-ITEM"),
])
def test_expected_native_line_identities_checked_independently(field, bad):
    value = _inputs()
    value["cases"][0]["expected_lines"][0][field] = bad
    _rejected(lambda: probe.validate_inputs(value, _args()))


def test_wrong_product_id_rejected_after_real_resolver_not_repaired():
    case = _inputs()["cases"][0]
    case["expected_lines"][0]["product_id"] = 31
    caller = FakeOdoo()
    _rejected(lambda: probe.evaluate_case(case, _document(), caller))
    assert caller.calls


@pytest.mark.parametrize("field", ("projection_before", "projection_after"))
@pytest.mark.parametrize("bad", ({}, [], None, {"different": True}))
def test_unchanged_nonempty_native_projections_required(field, bad):
    value = _inputs()
    value["cases"][0][field] = bad
    _rejected(lambda: probe.validate_inputs(value, _args()))


@pytest.mark.parametrize("location,field,bad", [
    ("facts", "document_duplicate", True), ("facts", "reference_duplicate", True),
    ("facts", "accounting_period_open", False),
    ("preflight", "state", "UNAVAILABLE"), ("preflight", "audit", "UNAVAILABLE"),
])
@pytest.mark.parametrize("index", (0, 1))
def test_native_operational_unavailability_never_gets_favorable_defaults(location, field, bad, index):
    case = _inputs()["cases"][index]
    case["observation"][location][field] = bad
    if location == "facts" and "duplicate" in field:
        case["observation"]["facts"]["duplicate_detected"] = True
    case["observation"] = _rehash(case["observation"])
    caller = FakeOdoo(post=bool(index))
    _rejected(lambda: probe.evaluate_case(case, _document(bool(index)), caller))
    assert not caller.calls


@pytest.mark.parametrize("field,bad", [
    ("document_sha256", "d" * 64), ("text_sha256", "not-a-digest"), ("text", ""),
    ("page_count", False), ("page_count", 0), ("byte_count", True), ("byte_count", 0),
])
def test_selected_document_custody_is_required_before_reads(field, bad):
    caller = FakeOdoo()
    _rejected(lambda: probe.evaluate_case(_inputs()["cases"][0], replace(_document(), **{field: bad}), caller))
    assert not caller.calls


@pytest.mark.parametrize("index", (0, 1))
def test_real_pdf_extraction_matches_selected_native_provenance(tmp_path, index):
    path = tmp_path / "synthetic.pdf"
    path.write_bytes(_pdf(bool(index)))
    extracted = extract_pdf_text(path)
    assert extracted == _document(bool(index))
    assert probe.evaluate_case(_inputs()["cases"][index], extracted, FakeOdoo(post=bool(index)))


@pytest.mark.parametrize("index", (0, 1))
def test_raw_transport_errors_are_sanitized_without_cause(index):
    caller = FakeOdoo(post=bool(index))
    caller.fail_model = "purchase.order"
    _rejected(lambda: probe.evaluate_case(_inputs()["cases"][index], _document(bool(index)), caller))


@pytest.mark.parametrize("model,method,arguments", [
    ("account.move", "create", {}), ("account.move", "action_post", {}),
    ("res.users", "search_read", {}), ("res.company", "search_read", {"context": {}}),
])
def test_ledger_refuses_mutations_models_and_context_without_forwarding(model, method, arguments):
    caller = FakeOdoo()
    ledger = probe.LedgerCaller(caller)
    with pytest.raises(ValueError):
        ledger.call(model, method, arguments=arguments)
    assert not caller.calls and not ledger.calls


def test_ledger_records_only_arguments_and_results_in_detached_copy():
    fake = FakeOdoo()
    ledger = probe.LedgerCaller(fake)
    arguments = {"domain": [["name", "=", COMPANY_NAME]], "fields": ["name"], "limit": 2}
    result = ledger.call("res.company", "search_read", arguments=arguments)
    saved = deepcopy(ledger.calls)
    assert set(saved[0]) == {"model", "method", "arguments", "result"}
    arguments["fields"].append("other")
    result[0]["name"] = "MUTATED"
    assert ledger.calls == saved


def test_ledger_is_bounded_before_forwarding():
    fake = FakeOdoo()
    ledger = probe.LedgerCaller(fake)
    ledger.calls = [{}] * 100
    with pytest.raises(probe.DatasetFixtureProbeError):
        ledger.call("res.company", "search_read", arguments={})
    assert not fake.calls


def _local_run(tmp_path, monkeypatch):
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    secrets = tmp_path / "synthetic-secrets"
    secrets.mkdir()
    (secrets / "reader.key").write_text("synthetic-reader-placeholder", encoding="utf-8")
    value = _inputs()
    (artifacts / "dataset-fixture-inputs.json").write_bytes(canonical_json_bytes(value) + b"\n")
    for post, name in zip((False, True), probe.CASES, strict=True):
        (artifacts / (name + ".pdf")).write_bytes(_pdf(post))

    class Client:
        def __init__(self, config):
            assert config.database == "tcc_runner_0123456789ab"
            self.clients = (FakeOdoo(), FakeOdoo(post=True))
            self.index = -1

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def call(self, model, method, *, arguments=None):
            if model == "res.company":
                self.index += 1
            return self.clients[self.index].call(model, method, arguments=arguments)

    monkeypatch.setattr(probe, "OdooJson2Client", Client)
    args = _args(artifacts=str(artifacts), secret_directory=str(secrets), database="tcc_runner_0123456789ab")
    return value, args, artifacts


def test_separate_run_uses_real_extraction_and_writes_exact_two_read_ledgers(tmp_path, monkeypatch):
    value, args, artifacts = _local_run(tmp_path, monkeypatch)
    before = {path.name: path.read_bytes() for path in artifacts.iterdir()}
    probe.run(args)
    output = json.loads((artifacts / "dataset-fixture-resolution.json").read_bytes())
    assert set(output) == {"schema_version", "status", *probe.PROVENANCE_KEYS,
                           "input_sha256", "cases", *probe.LIMIT_FLAGS}
    assert output["schema_version"] == "dataset-fixture-resolution/v1" and output["status"] == "PASS"
    assert all(output[field] is False for field in probe.LIMIT_FLAGS)
    assert output["input_sha256"] == hashlib.sha256(before["dataset-fixture-inputs.json"]).hexdigest()
    assert [row["name"] for row in output["cases"]] == list(probe.CASES)
    for row in output["cases"]:
        assert set(row) == {"name", "result", "calls"} and row["calls"]
        assert all(set(call) == {"model", "method", "arguments", "result"} for call in row["calls"])
        assert all(call["method"] == "search_read" and "context" not in call["arguments"] for call in row["calls"])
    assert all((artifacts / name).read_bytes() == raw for name, raw in before.items())
    assert "synthetic-reader-placeholder" not in json.dumps(output)


@pytest.mark.parametrize("mode", ("candidate", "policy", "prepare", "execute", None, True, []))
def test_new_phase_dispatch_rejects_other_modes_before_any_file_read(mode):
    _rejected(lambda: probe.run(_args(mode=mode)))


def test_invalid_inputs_reject_before_credentials_or_transport(tmp_path, monkeypatch):
    _value, args, artifacts = _local_run(tmp_path, monkeypatch)
    (Path(args.secret_directory) / "reader.key").unlink()
    (artifacts / "dataset-fixture-inputs.json").write_bytes(b'{"status":"PASS"}')
    _rejected(lambda: probe.run(args))
    assert not (artifacts / "dataset-fixture-resolution.json").exists()


def test_pdf_mutation_stops_run_without_partial_pass_output(tmp_path, monkeypatch):
    _value, args, artifacts = _local_run(tmp_path, monkeypatch)
    (artifacts / (probe.CASES[0] + ".pdf")).write_bytes(_pdf(True))
    _rejected(lambda: probe.run(args))
    assert not (artifacts / "dataset-fixture-resolution.json").exists()


@pytest.mark.parametrize("size", [0, 2_097_153])
def test_input_hash_also_rejects_empty_or_grown_file(tmp_path, size):
    source = tmp_path / "synthetic-input.json"
    source.write_bytes(b"x" * size)
    _rejected(lambda: probe.input_digest(source))


def test_input_hash_matches_the_actual_bounded_bytes(tmp_path):
    source = tmp_path / "synthetic-input.json"
    raw = b'{"synthetic":true}'
    source.write_bytes(raw)
    assert probe.input_digest(source) == hashlib.sha256(raw).hexdigest()
