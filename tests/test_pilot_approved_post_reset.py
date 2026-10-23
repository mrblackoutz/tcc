"""DEC-075 private POST host gates; no Docker, provider or scientific run."""

from copy import deepcopy
import hashlib
from pathlib import Path
from types import SimpleNamespace

import pytest

from test_pilot_approval_reset import construct, approved_simulation, approval_result
from test_pilot_materialization_reset import bare
import pilot_materialization_reset as reset


def test_approved_post_is_disabled_by_default(tmp_path, monkeypatch):
    value = construct(tmp_path, monkeypatch)
    assert value.with_approved_post is False
    assert value.with_approval_binding is False


@pytest.mark.parametrize("enabled", [False, True])
def test_explicit_post_boolean_is_independent_of_default_approval(tmp_path, monkeypatch, enabled):
    value = construct(tmp_path, monkeypatch, with_approval_binding=True, with_approved_post=enabled)
    assert value.with_approved_post is enabled
    assert value.with_approval_binding is True


@pytest.mark.parametrize("enabled", [0, 1, None, "true", "false", [], {}],
                         ids=["zero", "one", "none", "text-true", "text-false", "list", "dict"])
def test_post_optin_rejects_non_booleans_before_reading_inputs(monkeypatch, enabled):
    def unexpected(*_args, **_kwargs):
        pytest.fail("Invalid authority selector must fail before input reads or runtime allocation")
    monkeypatch.setattr(reset, "_read_private", unexpected)
    monkeypatch.setattr(reset.StateHarness, "__init__", unexpected)
    with pytest.raises(ValueError):
        reset.PilotResetHarness(seed_file=Path("seed"), alternatives_file=Path("alternatives"),
            origin_files=(Path("member0"), Path("member1")),
            with_approval_binding=True, with_approved_post=enabled)


def test_post_requires_approval_binding_before_input_or_runtime_access(monkeypatch):
    def unexpected(*_args, **_kwargs):
        pytest.fail("POST without prior approval binding must fail before allocation")
    monkeypatch.setattr(reset, "_read_private", unexpected)
    monkeypatch.setattr(reset.StateHarness, "__init__", unexpected)
    with pytest.raises(ValueError):
        reset.PilotResetHarness(seed_file=Path("seed"), alternatives_file=Path("alternatives"),
            origin_files=(Path("member0"), Path("member1")), with_approved_post=True)


def test_approval_only_matrix_cannot_claim_post_or_nonce_consumption(tmp_path, monkeypatch):
    value, _events, _writes, _receipts = approved_simulation(tmp_path, monkeypatch)
    value.with_approved_post = False
    value.run_cases()
    assert value.result["schema_version"] == "pilot-materialization-approval-reset-evidence/v1"
    assert value.result["decision"] == "DEC-074"
    assert value.result["post_executed"] is False
    assert value.result["nonce_reserved"] is False
    assert value.result["approval_custody_between_phases"] is False
    assert "posted_count" not in value.result


def test_private_holder_uses_separate_labelled_tmpfs_and_no_shared_data_mount(tmp_path):
    value = bare(tmp_path)
    value.with_approval_binding = value.with_approved_post = True
    value.odoo_image = "sha256:" + "a" * 64
    value.containers, value.volumes = set(), set()
    allocations, calls = [], []
    def create(name, *, size):
        allocations.append((name, size))
        value.volumes.add(name)
    value.create_volume = create
    value.docker = lambda arguments: calls.append(arguments)
    value.provision_approval_custody()
    assert allocations == [(value.private_approval_volume, 1_048_576)]
    assert len(calls) == 1
    command = calls[0]
    assert command[command.index("--network") + 1] == "none"
    assert "--read-only" in command and "ALL" in command and "never" in command
    assert "tcc.state.run=" + value.run_id in command
    mounts = [item for item in command if "target=" in item]
    assert mounts == ["type=volume,source=" + value.private_approval_volume + ",target=/run/pilot-approval-private"]
    assert value.prefix + "-approval-private-holder" in value.containers


@pytest.mark.parametrize("mode", ["prepare", "capture", "materialize", "approved-post"])
def test_private_custody_mount_and_flags_are_limited_to_both_private_phases(tmp_path, mode):
    value = bare(tmp_path)
    value.with_approval_binding = value.with_approved_post = True
    value.git_base, value.bundle_hash = "a" * 40, "b" * 64
    value.odoo_image = "sha256:" + "c" * 64
    value.containers, value.volumes = set(), {value.private_approval_volume}
    value.odoo_arguments = lambda *_args: ["run", *value.mount(value.artifacts, "/mnt/runner-artifacts")]
    calls = []
    value.docker = lambda arguments, **_kwargs: calls.append(arguments)
    value.remove_container = lambda name: value.containers.remove(name)
    value.native(mode, value.database(1), "structural-data", value.artifacts / "clone",
                 fixture_ref="FIX-00" if mode in {"materialize", "approved-post"} else None)
    command = calls[0]
    enabled = mode in {"materialize", "approved-post"}
    assert any("target=/run/pilot-approval-private" in item for item in command) is enabled
    assert ("--with-approved-post" in command) is enabled
    assert ("--with-approval-binding" in command) is enabled


def test_post_phase_without_optin_never_reaches_docker(tmp_path):
    value = bare(tmp_path)
    value.with_approval_binding = True
    value.with_approved_post = False
    value.odoo_arguments = lambda *_args: pytest.fail("POST disabled before building Docker arguments")
    with pytest.raises(ValueError):
        value.native("approved-post", value.database(1), "data", value.artifacts / "clone", fixture_ref="FIX-00")


def post_result(approval, database):
    output = {name: approval[name] for name in ("fixture_ref", "scenario_id", "document_sha256",
        "origin_input_sha256", "seed_sha256", "cohort_sha256", "codebook_sha256", "git_base",
        "source_bundle_sha256", "action_sha256", "approval_sha256", "nonce_sha256", "profile")}
    output.update(schema_version="pilot-a3a-approved-post-native/v1", status="PASS", database=database,
        command_sha256="sha256:" + hashlib.sha256((database + ":command").encode()).hexdigest(),
        origin_sha256="sha256:" + hashlib.sha256((database + ":origin").encode()).hexdigest(),
        posted_count=1, replay_count=1, invalid_mac_rejections=1,
        fresh_cursor_receipt_nonce_pdf_verified=True, executor_identity_unchanged=True,
        custody_between_phases=True, nonce_consumed=True, external_provider_called=False,
        scientific_run=False, human_review_complete=False, public_executor_enabled=False,
        policy_engine_used=False, llm_stage_used=False, gateway_handoff_performed=False)
    return output


def test_post_receipt_is_closed_copied_and_bound_to_preissued_approval(tmp_path, monkeypatch):
    value, _events, _writes, _receipts = approved_simulation(tmp_path, monkeypatch)
    approval = approval_result(value)
    result = post_result(approval, value.database(1))
    checked = reset.validate_post_result(result, approval=approval, database=value.database(1))
    assert checked == result and checked is not result
    assert not {"key", "key_material", "nonce", "signature", "authority", "approval", "command"} & set(checked)


@pytest.mark.parametrize("field,changed", [
    ("schema_version", "pilot-a3a-approval-native/v1"), ("status", "FAIL"),
    ("fixture_ref", "FIX-OTHER"), ("scenario_id", "SCN-OTHER"), ("database", "tcc_runner_bbbbbbbbbbbb"),
    *[(field, "0" * 64) for field in ("document_sha256", "origin_input_sha256", "seed_sha256",
                                    "cohort_sha256", "codebook_sha256", "source_bundle_sha256")],
    ("git_base", "0" * 40), ("profile", "unratified-profile"),
    *[(field, "sha256:" + "0" * 64) for field in ("action_sha256", "approval_sha256", "nonce_sha256")],
    ("command_sha256", "0" * 64), ("origin_sha256", "sha256:" + "A" * 64),
    *[(field, True) for field in ("posted_count", "replay_count", "invalid_mac_rejections")],
    *[(field, 2) for field in ("posted_count", "replay_count", "invalid_mac_rejections")],
    *[(field, False) for field in ("fresh_cursor_receipt_nonce_pdf_verified", "executor_identity_unchanged",
                                  "custody_between_phases", "nonce_consumed")],
    *[(field, True) for field in ("external_provider_called", "scientific_run", "human_review_complete",
        "public_executor_enabled", "policy_engine_used", "llm_stage_used", "gateway_handoff_performed")],
])
def test_post_result_mismatch_never_claims_an_authorized_effect(tmp_path, monkeypatch, field, changed):
    value, _events, _writes, _receipts = approved_simulation(tmp_path, monkeypatch)
    approval = approval_result(value)
    result = post_result(approval, value.database(1))
    result[field] = changed
    with pytest.raises(ValueError):
        reset.validate_post_result(result, approval=approval, database=value.database(1))


def test_reusable_authority_cannot_be_embedded_in_post_evidence(tmp_path, monkeypatch):
    value, _events, _writes, _receipts = approved_simulation(tmp_path, monkeypatch)
    approval = approval_result(value)
    result = post_result(approval, value.database(1))
    result["command"] = "PRIVATE-MARKER"
    with pytest.raises(ValueError) as caught:
        reset.validate_post_result(result, approval=approval, database=value.database(1))
    assert "PRIVATE-MARKER" not in str(caught.value)


def post_simulation(tmp_path, monkeypatch, *, corruption=None, reversed_members=False):
    value, events, writes, receipts = approved_simulation(tmp_path, monkeypatch, reversed_members=reversed_members)
    value.with_approved_post = True
    original_reader, original_capture, original_clone = reset.read_record, reset.read_capture, value.clone_artifacts
    original_baseline = value.baseline
    selections = {}

    def capture_view(capture, *, after=False):
        def mapping():
            result = deepcopy(capture.to_mapping())
            rows = result["records"]
            for row in rows["account.move"]:
                row["state"] = "draft"
            rows["ap.security.approval.nonce"] = []
            if after:
                rows["ap.security.draft.receipt"].append({"structural": "post"})
                rows["ap.security.audit.event"].extend({"structural": "event"} for _ in range(3))
                rows["account.move"][-1]["state"] = "posted"
                rows["ap.security.approval.nonce"] = [{"state": "consumed"}]
                if corruption == "nonce":
                    rows["ap.security.approval.nonce"][0]["state"] = "reserved"
                elif corruption == "posted-state":
                    rows["account.move"][-1]["state"] = "draft"
                elif corruption == "double-receipt":
                    rows["ap.security.draft.receipt"].append({"structural": "undeclared"})
            return result
        return SimpleNamespace(reset_sha256=capture.reset_sha256, identity_marker=capture.identity_marker,
                               to_mapping=mapping)

    value.baseline = capture_view(original_baseline)

    def read_capture(path, binding):
        return capture_view(original_capture(path, binding), after=path.name == "after.capture.json")

    def clone(database, fixture_ref, member_index):
        path = original_clone(database, fixture_ref, member_index)
        selections[path] = fixture_ref, member_index
        return path

    def read(path):
        if path.name != "pilot-a3a-approved-post-result.json":
            return original_reader(path)
        fixture_ref, member_index = selections[path.parent]
        result = post_result(approval_result(value, fixture_ref, member_index), path.parent.name)
        if corruption == "wrong-clone":
            result["database"] = value.database(0)
        elif corruption == "wrong-approval":
            result["approval_sha256"] = "sha256:" + "0" * 64
        return result

    value.clone_artifacts = clone
    monkeypatch.setattr(reset, "read_capture", read_capture)
    monkeypatch.setattr(reset, "read_record", read)
    return value, events, writes, receipts


@pytest.mark.parametrize("reversed_members", [False, True])
def test_eight_private_posts_keep_issued_authority_and_sixteen_resets(tmp_path, monkeypatch, reversed_members):
    value, events, writes, receipts = post_simulation(tmp_path, monkeypatch, reversed_members=reversed_members)
    value.run_cases()
    result = value.result
    assert result["schema_version"] == "pilot-materialization-approved-post-reset-evidence/v1"
    assert result["decision"] == "DEC-075" and result["status"] == "TESTS_PASSED_CLEANUP_PENDING"
    assert result["posted_count"] == result["replay_count"] == result["invalid_mac_rejections"] == 8
    assert result["reset_count"] == result["restored_clone_count"] == 16
    assert result["approval_binding_count"] == len(receipts) == 8
    assert sum(row[:2] == ("native", "approved-post") for row in events) == 8
    assert sum(row[:2] == ("native", "capture") for row in events) == 24
    assert result["nonce_reserved"] is result["approval_custody_between_phases"] is True
    for case in result["cases"]:
        assert case["post"]["database"] == case["database"]
        for field in ("action_sha256", "approval_sha256", "nonce_sha256"):
            assert case["post"][field] == case["approval"][field]
        assert case["before_sha256"] == case["restored_sha256"] != case["after_sha256"]
    for field in ("scientific_run", "human_review_complete", "external_provider_called", "public_executor_enabled",
        "policy_engine_used", "llm_stage_used", "gateway_handoff_performed", "run_record_approval_attribution_performed"):
        assert result[field] is False
    assert writes == [deepcopy(result)]


@pytest.mark.parametrize("corruption", ["wrong-clone", "wrong-approval", "nonce", "posted-state", "double-receipt"])
def test_corrupt_post_result_or_posted_state_halts_before_next_reset_member(tmp_path, monkeypatch, corruption):
    value, events, writes, _receipts = post_simulation(tmp_path, monkeypatch, corruption=corruption)
    with pytest.raises(ValueError):
        value.run_cases()
    assert [row[1] for row in events if row[0] == "restore"] == [1]
    assert sum(row[:2] == ("native", "approved-post") for row in events) == 1
    assert value.result is None and writes == []
