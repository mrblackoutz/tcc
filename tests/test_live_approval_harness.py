"""DEC-077 host gates with explicit doubles; no native/Docker/provider calls."""

from copy import deepcopy
from dataclasses import replace
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "gateway/tests"))
import live_approval_harness as live
from test_approval_attribution import approved_inputs
from test_company_capture import BINDING, row, sign
from tcc_gateway.company_capture import parse_company_capture


def native_double(condition="C0", grant="valid"):
    """Administrative boundary double, not proof of a native financial effect."""
    posted = condition == "C0" or grant == "valid"
    inputs = approved_inputs(condition, effect=posted)
    before, after = (inputs[key].to_mapping() for key in ("before", "after"))
    for capture in (before, after):
        capture["records"]["res.users"].append(row("res.users", ordinal=2, company_id=1, company_ids=[1]))
        capture["identity_map"]["res.users"].append(101)
    proof = "a" * 32
    slot = live.slot_id(proof, condition, grant)
    principal = 100 if condition == "C0" else 101
    observation = deepcopy(inputs["approval_observation"])
    observation["binding"].update(run_id=slot, executor_user_id=principal)
    if grant == "invalid-mac":
        observation["verification"] = {"status": "REJECTED", "reason_code": "SIGNATURE_INVALID", "metadata": None}
    if condition == "C1" and grant == "valid":
        meta = observation["verification"]["metadata"]
        after["records"]["ap.security.approval.nonce"] = [row("ap.security.approval.nonce",
            company_id=1, executor_user_id=2, state="consumed", nonce_sha256=meta["nonce_sha256"],
            action_sha256=meta["action_hash"], approval_sha256=meta["approval_sha256"],
            command_sha256=meta["command_sha256"], **{key: meta[key] for key in
                ("key_id", "fixture_id", "scenario_id", "approver_ref")})]
        after["identity_map"]["ap.security.approval.nonce"] = [3000]
    before, after = (parse_company_capture(sign(capture), BINDING) for capture in (before, after))
    observation["binding"]["before_capture_sha256"] = before.to_mapping()["capture_sha256"]
    service = principal if condition == "C0" else 1
    supervision = replace(inputs["supervision"], run_id=slot,
        mode="OBSERVED", intervals=(inputs["supervision"].intervals[-1],))
    value = {"schema_version": "live-approval-native/v1", "status": "PASS", "proof_run_id": proof,
        "slot_run_id": slot, "database": "tcc_state_aaaaaaaaaaaa_001", "condition": condition, "grant_mode": grant,
        "git_base": BINDING.code_commit, "source_bundle_sha256": BINDING.code_sha256,
        "before_capture_sha256": before.to_mapping()["capture_sha256"], "after_capture_sha256": after.to_mapping()["capture_sha256"],
        "observation": observation, "supervision": supervision.to_mapping(), "effect_move_id": 1000 if posted else None,
        "identity": {"approval_principal_id": principal, "administrative_caller_id": service,
            "financial_service_uid": service, "execution_env_uid": service, "execution_env_su": condition == "C1"},
        "read_only_invariant_verified": True, "nonce_available_before": True,
        "nonce_consumed_after": condition == "C1" and grant == "valid", "effect_posted": posted,
        **{key: False for key in live.DISABLED}}
    manifest = {"c0_user_id": 100, "cases": [{"name": "post", "scenario_id": "SCN-001", "target_move_id": 1000,
        "document_sha256": observation["binding"]["document_sha256"]}],
        "native_cases": [{"name": "post", "workflow": {"executor_user_id": 101},
            "command": {"action": observation["reference_action"]}}]}
    arguments = dict(proof_run_id=proof, database=value["database"], condition=condition, grant_mode=grant,
                     binding=BINDING, manifest=manifest, before=before, after=after)
    return value, arguments


@pytest.mark.parametrize("condition,grant", live.MATRIX)
def test_four_symmetric_identity_and_effect_paths_are_rederived(condition, grant):
    value, arguments = native_double(condition, grant)
    outcome = live.validate_live_result(value, **arguments)
    assert outcome["proposal_exact_approval_match"] is False
    assert outcome["actual_effect_exact_authorized"] is (grant == "valid" if value["effect_posted"] else None)


@pytest.mark.parametrize("key,bad", [
    ("schema_version", "other/v1"), ("status", "FAIL"), ("proof_run_id", "b" * 32),
    ("slot_run_id", "b" * 32), ("database", "other"), ("condition", "C1"), ("grant_mode", "invalid-mac"),
    ("git_base", "0" * 40), ("source_bundle_sha256", "0" * 64),
    ("before_capture_sha256", "0" * 64), ("after_capture_sha256", "0" * 64),
    ("read_only_invariant_verified", False), ("nonce_available_before", False),
    ("effect_posted", False), ("nonce_consumed_after", True), ("effect_move_id", None),
])
def test_hash_bindings_and_claims_cannot_be_transplanted(key, bad):
    value, arguments = native_double()
    value[key] = bad
    with pytest.raises(ValueError):
        live.validate_live_result(value, **arguments)


@pytest.mark.parametrize("field", sorted(live.DISABLED))
def test_offline_or_native_evidence_never_promotes_scientific_api_or_policy_flags(field):
    value, arguments = native_double()
    value[field] = True
    with pytest.raises(ValueError):
        live.validate_live_result(value, **arguments)


@pytest.mark.parametrize("field,bad", [
    ("approval_principal_id", 101), ("execution_env_uid", 1), ("execution_env_su", True),
    ("financial_service_uid", 1), ("administrative_caller_id", 1), ("execution_env_uid", True),
])
def test_c0_identity_is_not_a_relabelled_c1_or_superuser(field, bad):
    value, arguments = native_double()
    value["identity"][field] = bad
    with pytest.raises(ValueError):
        live.validate_live_result(value, **arguments)


def test_c1_principal_is_distinct_from_privileged_financial_service():
    value, arguments = native_double("C1")
    assert value["identity"]["approval_principal_id"] == 101
    assert value["identity"]["financial_service_uid"] == 1
    value["identity"]["approval_principal_id"] = 1
    with pytest.raises(ValueError):
        live.validate_live_result(value, **arguments)


@pytest.mark.parametrize("change", ["unknown-clock", "expiry", "claimed-valid-signature", "foreign-document", "nonce-hash"])
def test_observation_clock_and_cryptographic_metadata_must_match_live_evidence(change):
    value, arguments = native_double("C1")
    observation = value["observation"]
    if change == "unknown-clock":
        observation["binding"]["clock_id"] = "other-clock"
    elif change == "expiry":
        observation["timing"]["call_finished_at"] = "2026-10-22T12:10:00Z"
    elif change == "claimed-valid-signature":
        observation["verification"] = {"status": "REJECTED", "reason_code": "SIGNATURE_INVALID", "metadata": None}
    elif change == "foreign-document":
        observation["binding"]["document_sha256"] = "0" * 64
    else:
        observation["verification"]["metadata"]["nonce_sha256"] = "sha256:" + "0" * 64
    with pytest.raises(ValueError):
        live.validate_live_result(value, **arguments)


def test_extra_fields_in_native_or_identity_are_rejected():
    for nested in (False, True):
        value, arguments = native_double()
        (value["identity"] if nested else value)["unexpected"] = "SYNTHETIC"
        with pytest.raises(ValueError):
            live.validate_live_result(value, **arguments)


def test_extra_post_cannot_hide_in_the_expected_rejected_approval_cell():
    value, arguments = native_double("C0", "invalid-mac")
    after = arguments["after"].to_mapping()
    move = deepcopy(after["records"]["account.move"][0])
    move.update(ordinal=2, ref="OTHER-DOC", name="BILL/2026/2", line_ids=[2], invoice_line_ids=[2])
    line = deepcopy(after["records"]["account.move.line"][0])
    line.update(ordinal=2, move_id=2, purchase_line_id=None)
    after["records"]["account.move"].append(move)
    after["records"]["account.move.line"].append(line)
    after["identity_map"]["account.move"].append(1001)
    after["identity_map"]["account.move.line"].append(2001)
    arguments["after"] = parse_company_capture(sign(after), BINDING)
    value["after_capture_sha256"] = arguments["after"].to_mapping()["capture_sha256"]
    with pytest.raises(ValueError, match="UNEXPECTED_LIVE_APPROVAL_ATTRIBUTION"):
        live.validate_live_result(value, **arguments)


def test_slots_are_distinct_and_strict_before_any_runtime_action():
    assert len({live.slot_id("a" * 32, condition, grant) for condition, grant in live.MATRIX}) == 4
    for proof, condition, grant in [("wrong", "C0", "valid"), (True, "C0", "valid"),
                                   ("a" * 32, "C2", "valid"), ("a" * 32, "C0", "other")]:
        with pytest.raises(ValueError):
            live.slot_id(proof, condition, grant)


def test_native_dispatch_uses_only_owned_existing_harness_mounts(tmp_path):
    value = object.__new__(live.LiveApprovalHarness)
    value.run_id, value.prefix = "a" * 32, "tcc-state-" + "a" * 32
    value.git_base, value.bundle_hash, value.odoo_image = "b" * 40, "c" * 64, "sha256:" + "d" * 64
    value.containers = set()
    calls = []
    value.odoo_arguments = lambda database, data, name: ["run", "OWNED_MOUNTS", name]
    value.docker = lambda arguments, **kw: calls.append((arguments, kw))
    value.remove_container = lambda name: calls.append((name, "removed"))
    value.live_phase("tcc_state_aaaaaaaaaaaa_001", "OWNED_VOLUME", "C0", "invalid-mac")
    command = calls[0][0]
    assert command[command.index("--condition") + 1] == "C0"
    assert command[command.index("--grant-mode") + 1] == "invalid-mac"
    assert "--slot-run-id" in command and "--proof-run-id" in command
    assert "--privileged" not in command and calls[-1][1] == "removed"
