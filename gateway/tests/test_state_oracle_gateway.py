"""DEC-055 proof plumbing, with explicit offline doubles (not native evidence)."""

from copy import deepcopy
import importlib.util
import json
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest

from tcc_gateway.llm_client_service import parse_client_request_v2
from tcc_gateway.runner_contract_v2 import proposal_from_llm_stage_v2
from tcc_gateway.state import canonical_json_sha256
from tcc_gateway.synthetic_pdf import build_text_layer_pdf
from test_runner_observed_gateway import _offline_artifacts


PROBES = Path(__file__).resolve().parents[2] / "odoo" / "probes"


@pytest.fixture
def probe(monkeypatch):
    monkeypatch.syspath_prepend(str(PROBES))
    spec = importlib.util.spec_from_file_location("state_oracle_gateway_test", PROBES / "state_oracle_gateway.py")
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


def setup_case(tmp_path, case_name="benign", condition="C1"):
    manifest, candidates, observations, documents = _offline_artifacts()
    source_index = {"benign": 0, "amount": 1, "bank": 2, "post": 7}[case_name]
    case = deepcopy(manifest["cases"][source_index])
    case["name"] = case_name
    raw = build_text_layer_pdf("TCC SYNTHETIC WITHOUT FISCAL VALUE")
    path = tmp_path / (case_name + ".pdf")
    path.write_bytes(raw)
    # A fresh document changes the model custody binding, not business groundtruth.
    from tcc_gateway.pdf_ingestion import extract_pdf_text
    doc = extract_pdf_text(path)
    case["document_sha256"] = case["workflow"]["document_sha256"] = doc.document_sha256
    manifest = {"git_base": "e" * 40, "source_bundle_sha256": "f" * 64,
                "configuration_sha256": "1" * 64, "cases": [case]}
    binding = {"fixture_manifest_sha256": canonical_json_sha256(manifest), "code_commit": "e" * 40,
               "code_sha256": "f" * 64, "configuration_sha256": "1" * 64}
    (tmp_path / "state-fixture.json").write_text(json.dumps(manifest), encoding="utf-8")
    (tmp_path / "capture-binding.json").write_text(json.dumps(binding), encoding="utf-8")
    return SimpleNamespace(artifacts=str(tmp_path), database="tcc_state_0123456789ab_001",
        case=case_name, condition=condition, git_base="e" * 40, source_bundle_sha256="f" * 64), case


@pytest.mark.parametrize("condition", ["C0", "C1"])
@pytest.mark.parametrize("case_name", ["benign", "amount", "bank", "post"])
def test_real_mocked_client_pipeline_preserves_condition_and_model_values(probe, tmp_path, condition, case_name):
    args, case = setup_case(tmp_path, case_name, condition)
    probe.candidate(args)
    stem = tmp_path / (args.database + "-" + case_name + "-" + condition)
    saved = probe.read_artifact(stem.with_suffix(".candidate.json"))
    stage = probe.saved_stage(saved, condition)
    proposal = proposal_from_llm_stage_v2(saved["request"], stage)
    value = proposal.to_mapping()
    assert stage.condition == condition
    assert value["total"] == case["model_output"]["total"]
    assert value["bank_account_ref"] == case["model_output"]["bank_account_ref"]
    assert value["action"] == case["model_output"]["action"]
    assert saved["action_sha256"] == "sha256:" + canonical_json_sha256(saved["canonical_action"])
    assert condition not in parse_client_request_v2(saved["request"])[1].document.text


def test_common_request_is_identical_across_conditions(probe, tmp_path):
    requests = []
    for condition in ("C0", "C1"):
        args, _ = setup_case(tmp_path, condition=condition)
        probe.candidate(args)
        requests.append(probe.read_artifact((tmp_path / (args.database + "-benign-" + condition)).with_suffix(".candidate.json"))["request"])
    assert requests[0] == requests[1]


@pytest.mark.parametrize("name", ["git_base", "source_bundle_sha256"])
def test_changed_provenance_blocks_before_any_pipeline(probe, tmp_path, name):
    args, _ = setup_case(tmp_path)
    setattr(args, name, "0" * (40 if name == "git_base" else 64))
    with pytest.raises(ValueError):
        probe.candidate(args)
    assert not list(tmp_path.glob("*.candidate.json"))


def test_changed_fixture_blocks_before_pipeline(probe, tmp_path):
    args, _ = setup_case(tmp_path)
    path = tmp_path / "state-fixture.json"
    value = json.loads(path.read_text(encoding="utf-8"))
    value["cases"][0]["model_output"]["total"] = "999.00"
    path.write_text(json.dumps(value), encoding="utf-8")
    with pytest.raises(ValueError):
        probe.candidate(args)


@pytest.mark.parametrize("mode", ["execute", "capture", "prepare", "bad"])
def test_gateway_dispatcher_refuses_native_or_unknown_modes(probe, mode):
    with pytest.raises(ValueError):
        probe.run(SimpleNamespace(mode=mode))


@pytest.mark.parametrize("mode,condition", [("dispatch", "C1"), ("policy", "C0")])
def test_wrong_condition_fails_before_read_or_write(probe, mode, condition):
    with pytest.raises(ValueError):
        getattr(probe, mode)(SimpleNamespace(condition=condition))


def test_c0_saved_stage_tampering_is_not_promoted_to_proposal(probe, tmp_path):
    args, _ = setup_case(tmp_path, condition="C0")
    probe.candidate(args)
    saved = probe.read_artifact((tmp_path / (args.database + "-benign-C0")).with_suffix(".candidate.json"))
    saved["proposal_sha256"] = "0" * 64
    with pytest.raises(ValueError):
        probe.saved_stage(saved, "C0")
