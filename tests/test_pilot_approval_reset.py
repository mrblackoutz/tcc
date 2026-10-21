"""DEC-074 approval opt-in contracts; no Docker, provider or real dataset."""

from copy import deepcopy
import hashlib
from pathlib import Path

import pytest

from test_pilot_materialization_reset import bare, candidate_inputs, simulated_run
import pilot_materialization_reset as reset
from tcc_gateway.pilot_a3a_origin_contract import PilotA3aOriginInput
from tcc_gateway.pilot_seed_contract import PilotAlternativeCatalog, PilotBusinessSeed


def construct(tmp_path, monkeypatch, **options):
    seed, catalog, origins = candidate_inputs()
    queue = iter(origins)

    def read(path, cls, _limit):
        return {PilotBusinessSeed: lambda: seed, PilotAlternativeCatalog: lambda: catalog,
                PilotA3aOriginInput: lambda: next(queue)}[cls]()

    def allocate(instance, **_kwargs):
        instance.run_id = "a" * 32
        instance.artifacts = tmp_path / "artifacts"
        instance.artifacts.mkdir()

    monkeypatch.setattr(reset, "_read_private", read)
    monkeypatch.setattr(reset, "verify_extraction", lambda _package: None)
    monkeypatch.setattr(reset.StateHarness, "__init__", allocate)
    return reset.PilotResetHarness(seed_file=Path("seed"), alternatives_file=Path("alternatives"),
        origin_files=(Path("member0"), Path("member1")), **options)


def test_approval_is_disabled_by_default_and_does_not_change_input_contract(tmp_path, monkeypatch):
    value = construct(tmp_path, monkeypatch)
    assert value.with_approval_binding is False
    seed, catalog, origins = candidate_inputs()
    assert value.proof_inputs == reset.validate_inputs(seed, catalog, origins)


@pytest.mark.parametrize("enabled", [False, True])
def test_approval_option_requires_explicit_exact_boolean(tmp_path, monkeypatch, enabled):
    value = construct(tmp_path, monkeypatch, with_approval_binding=enabled)
    assert value.with_approval_binding is enabled


@pytest.mark.parametrize("enabled", [0, 1, None, "true", "false", [], {}],
                         ids=["zero", "one", "none", "text-true", "text-false", "list", "dict"])
def test_invalid_approval_option_rejected_before_input_reads_or_runtime_allocation(monkeypatch, enabled):
    def unexpected(*_args, **_kwargs):
        pytest.fail("Invalid authority selector must fail before input reads or runtime allocation")
    monkeypatch.setattr(reset, "_read_private", unexpected)
    monkeypatch.setattr(reset.StateHarness, "__init__", unexpected)
    with pytest.raises(ValueError):
        reset.PilotResetHarness(seed_file=Path("seed"), alternatives_file=Path("alternatives"),
            origin_files=(Path("member0"), Path("member1")), with_approval_binding=enabled)


@pytest.mark.parametrize("mode", ["prepare", "capture", "materialize"])
@pytest.mark.parametrize("enabled", [False, True])
def test_native_approval_flag_reaches_only_optin_materialization(tmp_path, enabled, mode):
    value = bare(tmp_path)
    value.with_approval_binding = enabled
    value.git_base, value.bundle_hash = "a" * 40, "b" * 64
    value.odoo_image = "sha256:" + "c" * 64
    value.containers = set()
    value.odoo_arguments = lambda *_args: ["run", *value.mount(value.artifacts, "/mnt/runner-artifacts")]
    calls = []
    value.docker = lambda arguments, **_kwargs: calls.append(arguments)
    value.remove_container = lambda name: value.containers.remove(name)
    value.native(mode, value.database(1), "structural-data", value.artifacts / "clone",
                 fixture_ref="FIX-00" if mode == "materialize" else None)
    assert len(calls) == 1
    assert ("--with-approval-binding" in calls[0]) is (enabled and mode == "materialize")


def test_legacy_matrix_preserves_no_approval_evidence(tmp_path, monkeypatch):
    value, _events, writes = simulated_run(tmp_path, monkeypatch)
    value.with_approval_binding = False
    value.run_cases()
    assert value.result["schema_version"] == "pilot-materialization-reset-evidence/v1"
    assert value.result["decision"] == "DEC-073"
    assert value.result["approval_generated"] is False
    assert "approval_binding_count" not in value.result
    assert writes == [deepcopy(value.result)]


def approval_result(value, fixture_ref="FIX-00", member_index=0):
    package = value.origins[member_index]
    source = next(row for row in package.to_mapping()["fixtures"] if row["fixture_ref"] == fixture_ref)
    return {"schema_version": "pilot-a3a-approval-native/v1", "status": "PASS",
        "fixture_ref": fixture_ref, "scenario_id": source["document"]["scenario_id"],
        "document_sha256": source["document"]["document_sha256"],
        "origin_input_sha256": package.sha256, "seed_sha256": value.seed.sha256,
        "cohort_sha256": value.proof_inputs["cohort_sha256"],
        "codebook_sha256": value.proof_inputs["codebook_sha256"],
        "git_base": value.git_base, "source_bundle_sha256": value.bundle_hash,
        "approval_count": 1, "negative_check_count": 20,
        **{name: "sha256:" + hashlib.sha256((name + ":" + source["document"]["scenario_id"]).encode()).hexdigest()
           for name in ("action_sha256", "approval_sha256", "nonce_sha256")},
        "profile": "c111-development-utc-minus60-plus600/v1",
        "approval_generated": True, "approval_verified": True, "read_only_confirmed": True,
        "executor_identity_unchanged": True, "nonce_reserved": False, "post_executed": False,
        "external_provider_called": False, "scientific_run": False, "human_review_complete": False,
        "public_executor_enabled": False}


def approval_arguments(result):
    return {name: result[name] for name in ("fixture_ref", "scenario_id", "document_sha256",
        "origin_input_sha256", "seed_sha256", "cohort_sha256", "codebook_sha256", "git_base", "source_bundle_sha256")}


def test_approval_result_guard_preserves_closed_sanitized_evidence(tmp_path, monkeypatch):
    value, _events, _writes = simulated_run(tmp_path, monkeypatch)
    result = approval_result(value)
    before = deepcopy(result)
    checked = reset.validate_approval_result(result, **approval_arguments(result))
    assert result == before
    assert checked == result and checked is not result
    for name in ("key", "material", "key_material", "authority", "approval", "signature", "nonce", "command"):
        assert name not in result


@pytest.mark.parametrize("field", ["fixture_ref", "scenario_id", "document_sha256", "origin_input_sha256",
    "seed_sha256", "cohort_sha256", "codebook_sha256", "git_base", "source_bundle_sha256"])
def test_result_provenance_cannot_be_rebound_after_issuance(tmp_path, monkeypatch, field):
    value, _events, _writes = simulated_run(tmp_path, monkeypatch)
    result = approval_result(value)
    arguments = approval_arguments(result)
    arguments[field] = "DIFFERENT" if field in {"fixture_ref", "scenario_id"} else "0" * len(arguments[field])
    with pytest.raises(ValueError):
        reset.validate_approval_result(result, **arguments)


@pytest.mark.parametrize("field,changed", [
    ("schema_version", "pilot-a3a-origin-native/v1"), ("status", "FAIL"),
    ("approval_count", True), ("approval_count", 0), ("approval_count", 4),
    ("negative_check_count", True), ("negative_check_count", 19), ("negative_check_count", 21),
    ("action_sha256", "2" * 64), ("approval_sha256", "sha256:" + "A" * 64),
    ("nonce_sha256", "sha256:invalid"), ("profile", "c111-development-unknown/v1"),
    *[(field, False) for field in ("approval_generated", "approval_verified", "read_only_confirmed",
                                 "executor_identity_unchanged")],
    *[(field, 1) for field in ("approval_generated", "approval_verified", "read_only_confirmed",
                             "executor_identity_unchanged")],
    *[(field, True) for field in ("nonce_reserved", "post_executed", "external_provider_called",
        "scientific_run", "human_review_complete", "public_executor_enabled")],
    *[(field, 0) for field in ("nonce_reserved", "post_executed", "external_provider_called",
        "scientific_run", "human_review_complete", "public_executor_enabled")],
])
def test_approval_result_never_promotes_bad_counts_flags_hash_or_profile(tmp_path, monkeypatch, field, changed):
    value, _events, _writes = simulated_run(tmp_path, monkeypatch)
    result = approval_result(value)
    arguments = approval_arguments(result)
    result[field] = changed
    with pytest.raises(ValueError):
        reset.validate_approval_result(result, **arguments)


@pytest.mark.parametrize("field", ["key", "key_material", "nonce", "signature", "authority", "approval", "command"])
def test_private_material_cannot_be_added_to_approval_receipt(tmp_path, monkeypatch, field):
    value, _events, _writes = simulated_run(tmp_path, monkeypatch)
    result = approval_result(value)
    arguments = approval_arguments(result)
    result[field] = "PRIVATE-MARKER"
    with pytest.raises(ValueError) as caught:
        reset.validate_approval_result(result, **arguments)
    assert "PRIVATE-MARKER" not in str(caught.value)


def approved_simulation(tmp_path, monkeypatch, *, corruption=None, reversed_members=False):
    value, events, writes = simulated_run(tmp_path, monkeypatch)
    value.with_approval_binding = True
    if reversed_members:
        value.origins = tuple(reversed(value.origins))
    old_reader = reset.read_record
    old_clone = value.clone_artifacts
    selections, receipts = {}, []

    def clone(database, fixture_ref, member_index):
        path = old_clone(database, fixture_ref, member_index)
        selections[path] = fixture_ref, member_index
        return path

    def read(path):
        if path.name != "pilot-a3a-approval-result.json":
            return old_reader(path)
        fixture_ref, member_index = selections[path.parent]
        result = approval_result(value, fixture_ref, member_index)
        if corruption == "wrong-member":
            result["scenario_id"] = "SCN-OTHER"
        elif corruption == "private-token":
            result["approval"] = "PRIVATE-MARKER"
        elif corruption == "wrong-count":
            result["negative_check_count"] = 19
        elif corruption == "post":
            result["post_executed"] = True
        elif corruption and corruption.startswith("reused:"):
            result[corruption.split(":", 1)[1]] = "sha256:" + "0" * 64
        receipts.append(deepcopy(result))
        return result

    value.clone_artifacts = clone
    monkeypatch.setattr(reset, "read_record", read)
    return value, events, writes, receipts


@pytest.mark.parametrize("reversed_members", [False, True])
def test_optin_preserves_eight_origins_sixteen_resets_and_per_document_authority(
        tmp_path, monkeypatch, reversed_members):
    value, events, writes, receipts = approved_simulation(tmp_path, monkeypatch, reversed_members=reversed_members)
    value.run_cases()
    result = value.result
    assert result["schema_version"] == "pilot-materialization-approval-reset-evidence/v1"
    assert result["decision"] == "DEC-074" and result["approval_generated"] is True
    assert result["status"] == "TESTS_PASSED_CLEANUP_PENDING"
    assert result["approval_binding_count"] == len(receipts) == 8
    assert result["approval_negative_check_count"] == 160
    assert result["case_count"] == result["origin_count"] == 8
    assert result["reset_count"] == result["restored_clone_count"] == 16
    assert [row[1] for row in events if row[0] == "restore"] == list(range(1, 17))
    assert sum(row[:2] == ("native", "materialize") for row in events) == 8
    assert sum(row[:2] == ("native", "capture") for row in events) == 24
    for case, receipt in zip(result["cases"], receipts, strict=True):
        assert case["scenario_id"] == receipt["scenario_id"]
        assert case["document_sha256"] == receipt["document_sha256"]
        assert case["approval"]["action_sha256"] == receipt["action_sha256"]
        assert case["approval"]["approval_sha256"] == receipt["approval_sha256"]
        assert case["approval"]["nonce_sha256"] == receipt["nonce_sha256"]
        assert case["before_sha256"] == case["restored_sha256"] != case["after_sha256"]
    assert len({row["scenario_id"] for row in receipts}) == 8
    assert writes == [deepcopy(result)]
    for field in ("scientific_run", "human_review_complete", "external_provider_called",
                  "public_executor_enabled", "post_executed", "c0_c1_comparison_performed"):
        assert result[field] is False


@pytest.mark.parametrize("corruption", ["wrong-member", "private-token", "wrong-count", "post"])
def test_bad_approval_receipt_stops_before_after_capture_or_next_clone(tmp_path, monkeypatch, corruption):
    value, events, writes, _receipts = approved_simulation(tmp_path, monkeypatch, corruption=corruption)
    with pytest.raises(ValueError):
        value.run_cases()
    assert [row[1] for row in events if row[0] == "restore"] == [1]
    assert sum(row[:2] == ("native", "materialize") for row in events) == 1
    assert sum(row[:2] == ("native", "capture") for row in events) == 1
    assert value.result is None and writes == []


@pytest.mark.parametrize("field", ["action_sha256", "approval_sha256", "nonce_sha256"])
def test_eight_receipts_cannot_reuse_one_action_token_or_nonce_identity(tmp_path, monkeypatch, field):
    value, events, writes, receipts = approved_simulation(tmp_path, monkeypatch, corruption="reused:" + field)
    with pytest.raises(ValueError):
        value.run_cases()
    assert len(receipts) == 8
    assert sum(row[0] == "restore" for row in events) == 16
    assert value.result is None and writes == []
