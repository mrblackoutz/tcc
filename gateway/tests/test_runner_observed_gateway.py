"""DEC-054 offline proof plumbing: synthetic fakes, no network or Odoo effects.

These fixtures exercise the actual client-stage/parser/policy path. They do not
constitute a native round-trip, supervisor, human review or scientific result.
"""

from copy import deepcopy
from dataclasses import asdict, replace
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

import httpx
import pytest

from tcc_gateway.attempt_policy import AttemptRecord
from tcc_gateway.llm_client_service import LLMClientServiceConfig, parse_client_request_v2, process_client_request
from tcc_gateway.llm_config import DEEPSEEK_MODEL, DeepSeekConfig
from tcc_gateway.operational_observation import OperationalObservationError
from tcc_gateway.pdf_ingestion import extract_pdf_text
from tcc_gateway.pilot_llm_runner import LLMStageResult
from tcc_gateway.policy_contracts import DependencyStatus
from tcc_gateway.policy_engine import POLICY_VERSION
from tcc_gateway.runner_contract_v2 import proposal_from_llm_stage_v2
from tcc_gateway.state import canonical_json_sha256
from tcc_gateway.synthetic_pdf import build_text_layer_pdf
from tcc_gateway.trusted_resolution import TrustedStateResolutionError, canonicalize_proposal

from test_operational_observation import _binding, _observation, _rehash
from test_runner_contract_v2 import _model_output, _request
from test_trusted_resolution import COMPANY_NAME, FakeOdoo, _workflow


ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "observed_gateway_test_module", ROOT / "odoo" / "probes" / "runner_observed_gateway.py",
)
probe = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(probe)
AVAILABLE = DependencyStatus("AVAILABLE", "AVAILABLE", "AVAILABLE")
EXPECTED_STATUSES = ("ALLOW", "DENY", "DENY", "DENY", "DENY", "DENY", "REJECTED", "REVIEW", "ALLOW")


def _sync_stage(request, output):
    def provider_mock(_request):
        return httpx.Response(200, json={
            "id": "synthetic-observed-offline", "model": DEEPSEEK_MODEL,
            "choices": [{"finish_reason": "stop", "message": {"content": json.dumps(output)}}],
        })

    status, response = process_client_request(request, LLMClientServiceConfig(
        mode="deepseek-smoke", deepseek_config=DeepSeekConfig(api_key="synthetic-test-placeholder"),
    ), transport=httpx.MockTransport(provider_mock), expected_request_version="llm-client-request/v2")
    assert status == 200
    return LLMStageResult("C1", "success", "SUCCESS", (AttemptRecord(
        1, "success", 0, canonical_json_sha256(request), canonical_json_sha256(response),
    ),), response)


def _offline_artifacts():
    """Independent synthetic fixture bindings for the nine declared cases."""
    cases, candidates, observations, documents = [], [], [], {}
    for index, name in enumerate(probe.CASES):
        post = name == "observed_post_without_approval"
        workflow = replace(_workflow(post=post), scenario_id=f"SCN-OBS-{index:03d}")
        request = _request()
        request["scenario_id"] = workflow.scenario_id
        document = parse_client_request_v2(request)[1].document
        output = _model_output(post=post)
        if name == "observed_amount_deviation":
            output["total"] = "250.00"
            output["lines"][0].update(unit_price="250.00", line_total="250.00")
        if name == "observed_bank_deviation":
            output["bank_account_ref"] = "TCC-UNREGISTERED-REDIRECT-BANK"
        stage = _sync_stage(request, output)
        proposal = proposal_from_llm_stage_v2(request, stage)
        action = canonicalize_proposal(proposal, policy_version=POLICY_VERSION,
            quantity_scale=workflow.quantity_scale, target_move_id=42 if post else None)
        binding = _binding(registration_id=60 + index)
        workflow_map = asdict(workflow)
        workflow_map["allowed_bank_refs"] = list(workflow.allowed_bank_refs)
        case = {"name": name, "scenario_id": workflow.scenario_id,
            "document_sha256": document.document_sha256, "model_output": output,
            "workflow": workflow_map, "binding": binding.to_mapping(),
            "policy_version": POLICY_VERSION, "target_move_id": 42 if post else None}
        saved = {"name": name, "request": request, "stage": probe.stage_to_mapping(stage),
            "canonical_action": action.to_mapping(), "request_sha256": canonical_json_sha256(request),
            "proposal_sha256": canonical_json_sha256(proposal.to_mapping()), "action_sha256": action.action_hash}
        observation = _observation(post=post)
        observation["registration"].update(registration_id=binding.registration_id)
        observation["scope"].update(scenario_id=workflow.scenario_id, action_sha256=action.action_hash,
            document_ref=action.document_ref, invoice_date=action.invoice_date)
        if name == "observed_reference_duplicate":
            observation["facts"].update(reference_duplicate=True, duplicate_detected=True)
        if name == "observed_closed_period":
            observation["facts"]["accounting_period_open"] = False
        if name == "observed_audit_unavailable":
            observation["preflight"]["audit"] = "UNAVAILABLE"
        if name == "observed_candidate_drift":
            changed = replace(action, document_ref="TCC-DRIFT-SEM-VALOR-FISCAL", invoice_date="2026-09-29")
            observation["scope"].update(document_ref=changed.document_ref, invoice_date=changed.invoice_date,
                action_sha256=changed.action_hash)
        observation = _rehash(observation)
        checks = {check: not (check == "candidate_hash_bound" and name == "observed_candidate_drift")
                  for check in probe.OBSERVATION_CHECKS}
        cases.append(case)
        candidates.append(saved)
        observations.append({"name": name, "observation": observation, "checks": checks})
        documents[name] = document
    manifest = {"schema_version": "runner-observed-fixture/v1", "database": "tcc_runner_0123456789ab",
        "git_base": "e" * 40, "source_bundle_sha256": "f" * 64, "configuration_sha256": "1" * 64,
        "synthetic_data": True, "fiscal_value": False, "company_id": 1, "company_name": COMPANY_NAME,
        "reader_user_id": 90, "reader_readonly_acl_verified": True, "cases": cases}
    declarations = {name: manifest[name] for name in probe.PROVENANCE_KEYS}
    candidate_top = {"schema_version": "runner-observed-candidates/v1", "status": "PASS", **declarations,
        "provider_mocked": True, "external_provider_called": False, "cases": candidates}
    observation_top = {"schema_version": "runner-observed-observations/v1", "status": "PASS", **declarations,
        "cases": observations}
    return manifest, candidate_top, observation_top, documents


def _evaluated_cases(manifest, candidates, observations, documents):
    parsed = probe.parse_observations(observations, manifest)
    result = []
    for case, saved, observation in zip(manifest["cases"], candidates["cases"], parsed, strict=True):
        preflight = observation.to_mapping()["preflight"]
        result.append(probe.evaluate_case(case, saved, observation, documents[case["name"]],
            FakeOdoo(post=case["name"] == "observed_post_without_approval"),
            dependencies=DependencyStatus(preflight["state"], "AVAILABLE", preflight["audit"])))
    return result


@pytest.fixture(scope="module")
def artifacts():
    return _offline_artifacts()


def test_all_nine_closed_manifests_candidates_and_observations_validate(artifacts):
    manifest, candidates, observations, documents = deepcopy(artifacts)
    args = SimpleNamespace(**{name: manifest[name] for name in ("database", "git_base", "source_bundle_sha256")})
    assert probe.parse_manifest(manifest, args) is manifest
    assert probe.parse_candidates(candidates, manifest) is candidates["cases"]
    assert len(probe.parse_observations(observations, manifest)) == 9
    for case, saved in zip(manifest["cases"], candidates["cases"], strict=True):
        assert probe.parse_candidate(saved, case, documents[case["name"]]).status == "success"


@pytest.mark.parametrize("raw", [
    b'{"same":1,"same":2}', b'{"nested":{"same":1,"same":2}}',
    b'{"a":NaN}', b'{"a":Infinity}', b'{"a":-Infinity}',
    b'{"a":1e1000}', b'[]', b'null', b'"SENSITIVE-MARKER"', b'{"a":', b'\xff', b'',
], ids=["duplicate", "nested-duplicate", "nan", "infinity", "negative-infinity",
        "overflow", "array-root", "null-root", "string-root", "incomplete", "invalid-utf8", "empty"])
def test_artifact_parser_rejects_nonfinite_float_duplicate_and_invalid_json(tmp_path, raw):
    path = tmp_path / "synthetic.json"
    path.write_bytes(raw)
    with pytest.raises(probe.ObservedRunnerError) as captured:
        probe.read_artifact(path)
    assert str(captured.value) == "observed runner artifact rejected"


@pytest.mark.parametrize("raw", [b'{"s":"' + b'x' * 2_097_152 + b'"}',
    b'{"a":' + b'[' * 33 + b'0' + b']' * 33 + b'}',
    b'{"a":[' + b'0,' * 65_535 + b'0]}'], ids=["oversize", "depth", "nodes"])
def test_artifact_parser_bounds_bytes_depth_and_nodes(tmp_path, raw):
    path = tmp_path / "synthetic.json"
    path.write_bytes(raw)
    with pytest.raises(probe.ObservedRunnerError):
        probe.read_artifact(path)


def test_artifact_parser_reads_bounded_even_if_stat_size_is_stale(tmp_path):
    actual = tmp_path / "growing.json"
    actual.write_bytes(b'{"s":"' + b'x' * 2_097_152 + b'"}')
    reads = []

    class GrowingPath:
        def stat(self):
            return SimpleNamespace(st_size=1)

        def open(self, mode):
            stream = actual.open(mode)

            class BoundedRead:
                def __enter__(self):
                    return self

                def read(self, size):
                    reads.append(size)
                    return stream.read(size)

                def __exit__(self, *args):
                    stream.close()

            return BoundedRead()

    with pytest.raises(probe.ObservedRunnerError):
        probe.read_artifact(GrowingPath())
    assert reads == [2_097_153]


def test_artifact_parser_preserves_integer_boolean_null_text_and_missing_file(tmp_path):
    path = tmp_path / "synthetic.json"
    expected = {"int": 1, "float": 0.0, "bool": True, "none": None, "text": "SINTETICO SEM VALOR FISCAL"}
    probe.write_artifact(path, expected)
    assert probe.read_artifact(path) == expected
    with pytest.raises(probe.ObservedRunnerError):
        probe.read_artifact(tmp_path / "missing.json")


def test_actual_candidate_artifact_round_trip_preserves_finite_temperature(artifacts, tmp_path):
    manifest, candidates, _, documents = deepcopy(artifacts)
    path = tmp_path / "synthetic-candidates.json"
    probe.write_artifact(path, candidates)
    loaded = probe.read_artifact(path)
    assert loaded == candidates
    parsed = probe.parse_candidates(loaded, manifest)
    for case, saved in zip(manifest["cases"], parsed, strict=True):
        assert saved["stage"]["response"]["metadata"]["temperature"] == 0.0
        assert type(saved["stage"]["response"]["metadata"]["temperature"]) is float
        assert probe.parse_candidate(saved, case, documents[case["name"]]).status == "success"


@pytest.mark.parametrize("field,bad", [
    ("schema_version", "other/v1"), ("database", "other"), ("git_base", "x" * 40),
    ("source_bundle_sha256", "x" * 64), ("configuration_sha256", "sha256:" + "1" * 64),
    ("synthetic_data", 1), ("fiscal_value", 0), ("reader_readonly_acl_verified", 1),
    ("company_id", True), ("reader_user_id", 0), ("cases", None),
])
def test_manifest_strict_fields_and_provenance(artifacts, field, bad):
    manifest = deepcopy(artifacts[0])
    args = SimpleNamespace(**{name: manifest[name] for name in ("database", "git_base", "source_bundle_sha256")})
    manifest[field] = bad
    with pytest.raises(probe.ObservedRunnerError):
        probe.parse_manifest(manifest, args)


@pytest.mark.parametrize("section,field,bad", [
    ("workflow", "scenario_id", "SCN-OTHER"), ("workflow", "document_sha256", "2" * 64),
    ("workflow", "company_name", "OTHER COMPANY"), ("binding", "company_id", 2),
    ("binding", "code_commit", "2" * 40), ("binding", "code_sha256", "sha256:" + "2" * 64),
    ("binding", "configuration_sha256", "sha256:" + "2" * 64),
    (None, "policy_version", "policy-other"), (None, "target_move_id", True),
])
def test_manifest_independent_workflow_binding_cannot_drift(artifacts, section, field, bad):
    manifest = deepcopy(artifacts[0])
    args = SimpleNamespace(**{name: manifest[name] for name in ("database", "git_base", "source_bundle_sha256")})
    item = manifest["cases"][0] if section is None else manifest["cases"][0][section]
    item[field] = bad
    with pytest.raises(probe.ObservedRunnerError):
        probe.parse_manifest(manifest, args)


@pytest.mark.parametrize("parser_name,artifact_index", [("parse_candidates", 1), ("parse_observations", 2)])
@pytest.mark.parametrize("malformation", ["extra", "missing", "null_case", "nameless", "duplicate", "reordered", "short", "bad_provenance"])
def test_phase_collections_closed_and_malformed_errors_finite(artifacts, parser_name, artifact_index, malformation):
    manifest = deepcopy(artifacts[0])
    value = deepcopy(artifacts[artifact_index])
    if malformation == "extra":
        value["secret"] = "SENSITIVE-MARKER"
    elif malformation == "missing":
        del value["status"]
    elif malformation == "null_case":
        value["cases"][0] = None
    elif malformation == "nameless":
        del value["cases"][0]["name"]
    elif malformation == "duplicate":
        value["cases"][1] = deepcopy(value["cases"][0])
    elif malformation == "reordered":
        value["cases"].reverse()
    elif malformation == "short":
        value["cases"].pop()
    elif malformation == "bad_provenance":
        value["git_base"] = "2" * 40
    with pytest.raises(probe.ObservedRunnerError) as captured:
        getattr(probe, parser_name)(value, manifest)
    assert str(captured.value) == "observed runner artifact rejected"


@pytest.mark.parametrize("field,bad", [("provider_mocked", 1), ("external_provider_called", 0), ("external_provider_called", True)])
def test_candidate_provider_flags_cannot_claim_live_or_use_numeric_boolean(artifacts, field, bad):
    value = deepcopy(artifacts[1])
    value[field] = bad
    with pytest.raises(probe.ObservedRunnerError):
        probe.parse_candidates(value, artifacts[0])


@pytest.mark.parametrize("check", sorted(probe.OBSERVATION_CHECKS))
@pytest.mark.parametrize("bad", [False, 1, "true", None])
def test_observation_check_claims_exact_for_ordinary_cases(artifacts, check, bad):
    value = deepcopy(artifacts[2])
    value["cases"][0]["checks"][check] = bad
    with pytest.raises(probe.ObservedRunnerError):
        probe.parse_observations(value, artifacts[0])


def test_declared_drift_requires_false_candidate_check_not_blanket_pass(artifacts):
    value = deepcopy(artifacts[2])
    value["cases"][6]["checks"]["candidate_hash_bound"] = True
    with pytest.raises(probe.ObservedRunnerError):
        probe.parse_observations(value, artifacts[0])


@pytest.mark.parametrize("field", ["registration_id", "registration_sha256", "company_id", "executor_user_id", "vendor_id",
    "purchase_order_id", "journal_id", "code_commit", "code_sha256", "configuration_sha256", "purchase_line_ids", "allowed_bank_ids"])
def test_observation_cannot_rehash_away_any_independent_binding_field(artifacts, field):
    manifest, _, value, _ = deepcopy(artifacts)
    original = manifest["cases"][0]["binding"][field]
    if isinstance(original, list):
        changed = original + [999]
    elif type(original) is int:
        changed = original + 999
    else:
        changed = ("sha256:" if original.startswith("sha256:") else "") + "2" * (40 if field == "code_commit" else 64)
    envelope = value["cases"][0]["observation"]
    section = "registration" if field.startswith("registration_") else (
        "provenance" if field in {"code_commit", "code_sha256", "configuration_sha256"} else "scope")
    envelope[section][field] = changed
    _rehash(envelope)
    with pytest.raises(probe.ObservedRunnerError):
        probe.parse_observations(value, manifest)


@pytest.mark.parametrize("place", ["top", "workflow", "binding", "candidate", "stage", "attempt"])
def test_all_closed_boundaries_reject_extra_authority_fields(artifacts, place):
    manifest, candidates, _, documents = deepcopy(artifacts)
    case, candidate = manifest["cases"][0], candidates["cases"][0]
    if place in {"top", "workflow", "binding"}:
        target = manifest if place == "top" else case[place]
        target["approval"] = "SENSITIVE-MARKER"
        args = SimpleNamespace(**{name: manifest[name] for name in ("database", "git_base", "source_bundle_sha256")})
        call = lambda: probe.parse_manifest(manifest, args)
    else:
        target = candidate if place == "candidate" else candidate["stage"] if place == "stage" else candidate["stage"]["attempts"][0]
        target["approval"] = "SENSITIVE-MARKER"
        call = lambda: probe.parse_candidate(candidate, case, documents[case["name"]])
    with pytest.raises(probe.ObservedRunnerError) as captured:
        call()
    assert "SENSITIVE-MARKER" not in str(captured.value)


@pytest.mark.parametrize("field", ["request_sha256", "proposal_sha256", "action_sha256"])
def test_candidate_hashes_recomputed_from_typed_stage_and_document(artifacts, field):
    manifest, candidates, _, documents = deepcopy(artifacts)
    saved = candidates["cases"][0]
    saved[field] = ("sha256:" if field == "action_sha256" else "") + "2" * 64
    with pytest.raises(probe.ObservedRunnerError):
        probe.parse_candidate(saved, manifest["cases"][0], documents[saved["name"]])


@pytest.mark.parametrize("field,bad", [("condition", "C0"), ("status", "classified_error"), ("reason", "ERROR"),
    ("attempts", []), ("attempts", None), ("response", None)])
def test_stage_handoff_only_accepts_successful_c1(artifacts, field, bad):
    manifest, candidates, _, documents = deepcopy(artifacts)
    saved = candidates["cases"][0]
    saved["stage"][field] = bad
    with pytest.raises(probe.ObservedRunnerError):
        probe.parse_candidate(saved, manifest["cases"][0], documents[saved["name"]])


@pytest.mark.parametrize("field,bad", [("number", True), ("number", 2), ("request_sha256", "2" * 64),
    ("response_sha256", "2" * 64), ("side_effect_started", True), ("elapsed_ns", -1), ("retryable_hint", 1)])
def test_candidate_attempt_contract_cannot_be_mixed_or_coerced(artifacts, field, bad):
    manifest, candidates, _, documents = deepcopy(artifacts)
    saved = candidates["cases"][0]
    saved["stage"]["attempts"][0][field] = bad
    with pytest.raises(probe.ObservedRunnerError):
        probe.parse_candidate(saved, manifest["cases"][0], documents[saved["name"]])


def test_canonical_action_and_raw_output_cannot_be_repaired_or_swapped(artifacts):
    manifest, candidates, _, documents = deepcopy(artifacts)
    case, saved = manifest["cases"][0], candidates["cases"][0]
    saved["canonical_action"]["amount"] = "250.00"
    saved["action_sha256"] = "sha256:" + canonical_json_sha256(saved["canonical_action"])
    with pytest.raises(probe.ObservedRunnerError):
        probe.parse_candidate(saved, case, documents[saved["name"]])
    saved = deepcopy(artifacts[1]["cases"][0])
    case["model_output"]["bank_account_ref"] = "TCC-OTHER-BANK"
    with pytest.raises(probe.ObservedRunnerError):
        probe.parse_candidate(saved, case, documents[saved["name"]])


@pytest.mark.parametrize("field,bad", [("text", "ALTERED DOCUMENT"), ("document_sha256", "2" * 64), ("byte_count", 201)])
def test_document_custody_metadata_is_checked(artifacts, field, bad):
    manifest, candidates, _, documents = deepcopy(artifacts)
    case, saved = manifest["cases"][0], candidates["cases"][0]
    altered = replace(documents[saved["name"]], **{field: bad})
    with pytest.raises(probe.ObservedRunnerError):
        probe.parse_candidate(saved, case, altered)


@pytest.mark.parametrize("model,method,arguments", [
    ("account.move", "create", {"vals_list": []}), ("account.move", "action_post", {"ids": [42]}),
    ("account.move", "write", {"ids": [42], "vals": {}}), ("account.move", "unlink", {"ids": [42]}),
    ("ap.security.executor", "execute", {"command": {}}), ("ir.config_parameter", "search_read", {}),
    ("res.company", "search_read", {"context": {}}), ("res.company", "search_read", None),
])
def test_readonly_facade_rejects_effects_models_and_context_before_client(model, method, arguments):
    client = FakeOdoo()
    reader = probe.ReadonlyCaller(client)
    with pytest.raises(probe.ObservedRunnerError):
        reader.call(model, method, arguments=arguments)
    assert reader.calls == [] and client.calls == []


def test_readonly_facade_forwards_only_unmodified_read_arguments():
    client = FakeOdoo()
    reader = probe.ReadonlyCaller(client)
    arguments = {"domain": [["id", "=", 1]], "fields": ["name"], "limit": 2}
    before = deepcopy(arguments)
    assert reader.call("res.company", "search_read", arguments=arguments)[0]["id"] == 1
    assert reader.calls == [["res.company", "search_read"]]
    assert client.calls[0][2] == arguments == before


def test_actual_policy_dispositions_commands_and_no_fake_financial_effects(artifacts):
    manifest, candidates, observations, documents = deepcopy(artifacts)
    parsed = probe.parse_observations(observations, manifest)
    before = deepcopy(candidates)
    for index, (case, saved, observation) in enumerate(zip(manifest["cases"], candidates["cases"], parsed, strict=True)):
        client = FakeOdoo(post=index == 7)
        records_before = deepcopy(client.records)
        preflight = observation.to_mapping()["preflight"]
        result = probe.evaluate_case(case, saved, observation, documents[case["name"]], client,
            dependencies=DependencyStatus(preflight["state"], "AVAILABLE", preflight["audit"]))
        assert result["status"] == EXPECTED_STATUSES[index]
        assert client.records == records_before
        assert result["native_json2_request_count"] == len(client.calls) > 0
        assert all(model in probe.READ_MODELS and method == "search_read" for model, method, _ in client.calls)
        if index in {0, 8}:
            assert result["command"]["action"] == saved["canonical_action"]
            assert "approval" not in result["command"]
            assert result["command_sha256"] == canonical_json_sha256(result["command"])
        else:
            assert result["command"] is None and result["command_sha256"] is None
        if index == 5:
            assert result["decision"]["deny_class"] == "FAIL_CLOSED_UNAVAILABILITY"
        if index == 6:
            assert result["decision"] is None and result["policy_input"] is None
            assert result["category"] == "CANDIDATE_BINDING_REJECTED"
            assert result["checks"]["actual_policy_evaluated"] is False
        else:
            assert all(value is True for value in result["checks"].values())
    assert candidates == before


def test_drift_is_not_silently_accepted_for_ordinary_named_case(artifacts):
    manifest, candidates, observations, documents = deepcopy(artifacts)
    case, saved = manifest["cases"][0], candidates["cases"][0]
    observation = observations["cases"][0]["observation"]
    observation["scope"]["action_sha256"] = "sha256:" + "2" * 64
    parsed = probe.parse_registered_observation(_rehash(observation), probe.ObservationBinding.from_mapping(case["binding"]))
    client = FakeOdoo()
    before = deepcopy(client.records)
    with pytest.raises(probe.ObservedRunnerError):
        probe.evaluate_case(case, saved, parsed, documents[case["name"]], client, dependencies=AVAILABLE)
    assert client.records == before and all(method == "search_read" for _, method, _ in client.calls)


@pytest.mark.parametrize("unavailable", ["policy", "audit"])
def test_dependencies_cannot_be_improved_by_available_native_observation(artifacts, unavailable):
    manifest, candidates, observations, documents = deepcopy(artifacts)
    parsed = probe.parse_observations(observations, manifest)[0]
    case, saved = manifest["cases"][0], candidates["cases"][0]
    dependencies = {"state": "AVAILABLE", "policy": "AVAILABLE", "audit": "AVAILABLE"}
    dependencies[unavailable] = "UNAVAILABLE"
    result = probe.evaluate_case(case, saved, parsed, documents[case["name"]], FakeOdoo(),
        dependencies=DependencyStatus(**dependencies))
    assert result["status"] == "DENY" and result["command"] is None
    assert result["decision"]["deny_class"] == "FAIL_CLOSED_UNAVAILABILITY"
    assert result["policy_input"]["trusted_state"]["dependencies"][unavailable] == "UNAVAILABLE"


def test_unavailable_state_dependency_blocks_before_read_or_effect(artifacts):
    manifest, candidates, observations, documents = deepcopy(artifacts)
    parsed = probe.parse_observations(observations, manifest)[0]
    case, saved = manifest["cases"][0], candidates["cases"][0]
    client = FakeOdoo()
    before = deepcopy(client.records)
    with pytest.raises(TrustedStateResolutionError):
        probe.evaluate_case(case, saved, parsed, documents[case["name"]], client,
            dependencies=DependencyStatus("UNAVAILABLE", "AVAILABLE", "AVAILABLE"))
    assert client.calls == [] and client.records == before


def test_prepare_candidate_uses_actual_pdf_extraction_and_mock_only_provider(tmp_path, monkeypatch):
    path = tmp_path / "synthetic.pdf"
    path.write_bytes(build_text_layer_pdf("DOCUMENTO SINTETICO SEM VALOR FISCAL"))
    document = extract_pdf_text(path)
    case = _offline_artifacts()[0]["cases"][0]
    case["document_sha256"] = document.document_sha256
    case["workflow"]["document_sha256"] = document.document_sha256
    seen = []
    original = probe._synthetic_stage

    def observed_stage(request, output):
        seen.append((deepcopy(request), deepcopy(output)))
        return original(request, output)

    monkeypatch.setattr(probe, "_synthetic_stage", observed_stage)
    result = probe.prepare_candidate(case, document)
    assert len(seen) == 1 and seen[0][0]["document"]["document_sha256"] == document.document_sha256
    assert probe.parse_candidate(result, case, document).status == "success"
    assert result["canonical_action"]["document_sha256"] == document.document_sha256


@pytest.mark.parametrize("mode", ["candidate", "policy"])
def test_real_native_entry_imports_existing_gateway_dispatcher_and_routes_once(mode, monkeypatch, capsys):
    entry_spec = importlib.util.spec_from_file_location(
        "observed_native_entry_under_test", ROOT / "odoo" / "probes" / "runner_observed_native.py",
    )
    entry = importlib.util.module_from_spec(entry_spec)
    entry_spec.loader.exec_module(entry)
    calls = []
    # The imported module and dispatcher are real. Only the two phase bodies
    # are spies here; no sys.modules stub can hide a nonexistent run export.
    monkeypatch.setitem(sys.modules, "runner_observed_gateway", probe)
    monkeypatch.setattr(probe, "candidate", lambda args: calls.append(("candidate", args)))
    monkeypatch.setattr(probe, "policy", lambda args: calls.append(("policy", args)))
    monkeypatch.setattr(sys, "argv", ["runner_observed_native.py", mode,
        "--database", "tcc_runner_0123456789ab", "--git-base", "e" * 40,
        "--source-bundle-sha256", "f" * 64])
    disabled_before = entry.logging.root.manager.disable
    try:
        entry.main()
    finally:
        entry.logging.disable(disabled_before)
    assert len(calls) == 1 and calls[0][0] == calls[0][1].mode == mode
    assert calls[0][1].database == "tcc_runner_0123456789ab"
    assert capsys.readouterr().out == "RUNNER_OBSERVED_PASS_" + mode.upper() + "\n"


def test_clean_subprocess_imports_real_gateway_run_without_odoo_runtime():
    result = subprocess.run([sys.executable, "-c",
        "import sys; sys.path.insert(0, 'odoo/probes'); from runner_observed_gateway import run; "
        "assert callable(run); assert 'odoo' not in sys.modules; print('GATEWAY_RUN_IMPORT_PASS')"],
        cwd=ROOT, capture_output=True, text=True, timeout=30, check=False)
    assert result.returncode == 0 and result.stdout == "GATEWAY_RUN_IMPORT_PASS\n" and result.stderr == ""


@pytest.mark.parametrize("mode", ["prepare", "observe", "execute", "confirm", "dispatch", "c1", None, [], True])
def test_gateway_dispatcher_rejects_non_gateway_and_malformed_modes_before_any_phase(mode, monkeypatch):
    calls = []
    monkeypatch.setattr(probe, "candidate", lambda args: calls.append("candidate"))
    monkeypatch.setattr(probe, "policy", lambda args: calls.append("policy"))
    with pytest.raises(probe.ObservedRunnerError) as captured:
        probe.run(SimpleNamespace(mode=mode))
    assert calls == [] and str(captured.value) == "observed runner artifact rejected"


def test_real_gateway_candidate_dispatch_reads_nine_pdfs_and_writes_typed_artifact(artifacts, tmp_path):
    manifest = deepcopy(artifacts[0])
    raw = build_text_layer_pdf("DOCUMENTO SINTETICO SEM VALOR FISCAL")
    documents = {}
    for case in manifest["cases"]:
        path = tmp_path / (case["name"] + ".pdf")
        path.write_bytes(raw)
        document = extract_pdf_text(path)
        documents[case["name"]] = document
        case["document_sha256"] = document.document_sha256
        case["workflow"]["document_sha256"] = document.document_sha256
    probe.write_artifact(tmp_path / "observed-manifest.json", manifest)
    args = SimpleNamespace(mode="candidate", artifacts=str(tmp_path),
        **{name: manifest[name] for name in ("database", "git_base", "source_bundle_sha256")})
    assert probe.run(args) is None
    saved = probe.read_artifact(tmp_path / "observed-candidates.json")
    parsed = probe.parse_candidates(saved, manifest)
    assert len(parsed) == 9 and saved["provider_mocked"] is True and saved["external_provider_called"] is False
    for case, candidate in zip(manifest["cases"], parsed, strict=True):
        assert probe.parse_candidate(candidate, case, documents[case["name"]]).status == "success"


@pytest.mark.parametrize("status", [200, 401, 403, 500, 599, 99, 999])
def test_native_diagnostic_transport_retains_only_valid_last_status(status, monkeypatch):
    requests = []

    def actual_parent_call(_self, request):
        requests.append(request)
        return httpx.Response(status, text="SENSITIVE-RESPONSE-MARKER", headers={"X-Private": "SENSITIVE-HEADER"})

    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", actual_parent_call)
    request = httpx.Request("POST", "http://synthetic.invalid/SENSITIVE-URL", content=b"SENSITIVE-PAYLOAD",
        headers={"Authorization": "Bearer synthetic-test-placeholder"})
    with probe.ReadDiagnosticTransport() as transport:
        assert transport.handle_request(request).status_code == status
        assert requests == [request]
        assert transport.last_http_status == (status if 100 <= status <= 599 else None)


def test_native_diagnostic_transport_resets_prior_status_when_connection_fails(monkeypatch):
    def fail(_self, request):
        raise httpx.ConnectError("SENSITIVE-TRANSPORT-MARKER", request=request)

    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", fail)
    with probe.ReadDiagnosticTransport() as transport:
        transport.last_http_status = 403
        with pytest.raises(httpx.ConnectError):
            transport.handle_request(httpx.Request("GET", "http://synthetic.invalid"))
        assert transport.last_http_status is None


@pytest.mark.parametrize("category", ["DEPENDENCY_UNAVAILABLE", "STATE_INVALID", "REFERENCE_NOT_FOUND", "REFERENCE_AMBIGUOUS", "OTHER"])
def test_read_diagnostic_whitelists_category_and_never_serializes_exception_payload(tmp_path, category):
    error = TrustedStateResolutionError(category) if category != "OTHER" else RuntimeError("SENSITIVE-EXCEPTION-MARKER")
    reader = probe.ReadonlyCaller(FakeOdoo())
    reader.calls = [["res.company", "search_read"]]
    probe.write_read_diagnostic(tmp_path, 0, reader, SimpleNamespace(last_http_status=403), error)
    diagnostic = probe.read_artifact(tmp_path / "observed-read-diagnostic.json")
    assert diagnostic == {"schema_version": "runner-observed-read-diagnostic/v1", "status": "FAIL", "case_index": 0,
        "last_model": "res.company", "read_call_count": 1, "http_status": 403, "resolution_category": category}
    assert "SENSITIVE" not in json.dumps(diagnostic)


@pytest.mark.parametrize("status", [True, "403", 99, 600, None])
def test_diagnostic_ignores_noninteger_out_of_range_http_codes_and_unknown_models(tmp_path, status):
    reader = probe.ReadonlyCaller(FakeOdoo())
    reader.calls = [["SENSITIVE-MODEL-NOT-ALLOWLISTED", "search_read"]]
    error = TrustedStateResolutionError("STATE_INVALID")
    error.category = "SENSITIVE-CATEGORY-NOT-ALLOWLISTED"
    probe.write_read_diagnostic(tmp_path, 8, reader, SimpleNamespace(last_http_status=status), error)
    diagnostic = probe.read_artifact(tmp_path / "observed-read-diagnostic.json")
    assert diagnostic["last_model"] is None and diagnostic["http_status"] is None
    assert diagnostic["resolution_category"] == "OTHER" and "SENSITIVE" not in json.dumps(diagnostic)


@pytest.mark.parametrize("case_index", [-1, 9, True, "0", None])
def test_diagnostic_rejects_unbounded_case_index_before_writing(tmp_path, case_index):
    with pytest.raises(probe.ObservedRunnerError):
        probe.write_read_diagnostic(tmp_path, case_index, probe.ReadonlyCaller(FakeOdoo()),
            SimpleNamespace(last_http_status=403), RuntimeError("SENSITIVE-MARKER"))
    assert not (tmp_path / "observed-read-diagnostic.json").exists()


@pytest.mark.parametrize("status,payload,category", [
    (403, {"SENSITIVE-RESPONSE-MARKER": True}, "DEPENDENCY_UNAVAILABLE"),
    (200, {"SENSITIVE-RESPONSE-MARKER": True}, "STATE_INVALID"),
    (200, [], "REFERENCE_NOT_FOUND"),
])
def test_actual_policy_failure_writes_only_finite_read_diagnostic_and_remains_failure(
    artifacts, tmp_path, monkeypatch, capsys, status, payload, category,
):
    manifest, candidates, observations, documents = deepcopy(artifacts)
    for filename, value in (("observed-manifest.json", manifest), ("observed-candidates.json", candidates),
        ("observed-observations.json", observations)):
        probe.write_artifact(tmp_path / filename, value)
    secrets = tmp_path / "synthetic-secrets"
    secrets.mkdir()
    (secrets / "reader.key").write_text("synthetic-test-placeholder", encoding="utf-8")
    monkeypatch.setattr(probe, "extract_pdf_text", lambda path: documents[path.stem])
    monkeypatch.setattr(httpx.HTTPTransport, "handle_request",
        lambda _self, _request: httpx.Response(status, json=payload))
    args = SimpleNamespace(mode="policy", artifacts=str(tmp_path), secret_directory=str(secrets),
        **{name: manifest[name] for name in ("database", "git_base", "source_bundle_sha256")})
    with pytest.raises(TrustedStateResolutionError) as captured:
        probe.run(args)
    assert captured.value.category == category
    diagnostic = probe.read_artifact(tmp_path / "observed-read-diagnostic.json")
    assert diagnostic == {"schema_version": "runner-observed-read-diagnostic/v1", "status": "FAIL", "case_index": 0,
        "last_model": "res.company", "read_call_count": 1, "http_status": status, "resolution_category": category}
    assert not (tmp_path / "observed-policy.json").exists()
    assert "SENSITIVE" not in json.dumps(diagnostic) and "synthetic-test-placeholder" not in json.dumps(diagnostic)
    captured_output = capsys.readouterr()
    assert captured_output.out == captured_output.err == ""
