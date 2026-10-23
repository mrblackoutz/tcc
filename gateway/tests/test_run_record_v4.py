"""DEC-076 closed v4 records and reset continuity without legacy rewrites."""

from dataclasses import replace

import pytest

from tcc_gateway import run_record_store as records
from tcc_gateway import run_reset_journal as journal
from tcc_gateway.company_capture import parse_company_capture
from tcc_gateway.run_record import RunRecordContractError, parse_run_record
from tcc_gateway.run_record_v4 import build_run_record_v4 as _build, parse_run_record_v4
from tcc_gateway.policy_contracts import CanonicalAction
from tcc_gateway.run_reset_checkpoint import derive_next_slot_gate
from tcc_gateway.state import canonical_json_bytes
from test_run_record import valid_inputs
from test_run_record_v2 import failed_inputs
from test_run_record_v3 import build_run_record_v3, near_miss_inputs, uncertain_then_success
from test_run_reset_checkpoint import checkpoint, divergent_capture, record_inputs
from test_company_capture import BINDING, sign
from test_approval_attribution import approved_inputs


def build_run_record_v4(**inputs):
    """Shared fixture denials explicitly declare their existing business class."""
    trace = inputs["trace"]
    confirmed = inputs["supervision"].effect_quiescence == "CONFIRMED"
    if "deny_class" not in inputs and trace.condition == "C1" and (
            trace.disposition == "DENY" or trace.disposition == "ALLOW"
            and trace.effect_move_id is None and confirmed):
        inputs = {**inputs, "deny_class": "POLICY_RULE"}
    return _build(**inputs)


@pytest.mark.parametrize("condition", ["C0", "C1"])
@pytest.mark.parametrize("attack", [False, True])
def test_v4_null_noncritical_observation_preserves_every_v3_measurement(condition, attack):
    inputs = valid_inputs(condition, attack)
    old = build_run_record_v3(**inputs).to_mapping()
    value = build_run_record_v4(**inputs).to_mapping()
    assert value["schema_version"] == "run-record/v4"
    assert value["evidence"]["approval_observation"] is None
    assert value["evidence"]["trace"]["approval_exact_valid"] is False
    assert value["derived"]["approval"]["status"] == "NOT_APPLICABLE"
    assert {key: item for key, item in value["derived"].items() if key != "approval"} == old["derived"]
    assert value["pending"] == old["pending"]
    assert value["scientific_run"] is value["human_review_complete"] is False
    assert parse_run_record(value).to_mapping() == value


@pytest.mark.parametrize("condition", ["C0", "C1"])
@pytest.mark.parametrize("near_miss", [False, True])
def test_v4_preserves_coherent_effect_mismatch_and_success_uncertainty_rules(condition, near_miss):
    inputs = near_miss_inputs(condition) if near_miss else valid_inputs(condition)
    uncertain_then_success(inputs)
    old = build_run_record_v3(**inputs).to_mapping()
    new = build_run_record_v4(**inputs).to_mapping()
    assert new["derived"]["batch_gate"] == "CONTINUE"
    assert new["derived"]["llm_attempt_uncertain"] is True
    assert new["derived"]["oracle"] == old["derived"]["oracle"]


@pytest.mark.parametrize("condition", ["C0", "C1"])
@pytest.mark.parametrize("kind", ["permanent", "uncertain", "client_uncertain"])
def test_v4_failed_noncritical_stage_keeps_v3_outcome_and_gate(condition, kind):
    inputs = failed_inputs(condition, kind)
    old = build_run_record_v3(**inputs).to_mapping()
    new = build_run_record_v4(**inputs).to_mapping()
    assert {key: item for key, item in new["derived"].items() if key != "approval"} == old["derived"]


@pytest.mark.parametrize("condition", ["C0", "C1"])
@pytest.mark.parametrize("benign", [False, True])
def test_missing_observation_is_not_observed_absence_for_any_post_case(condition, benign):
    inputs = valid_inputs(condition, post=True)
    if benign:
        inputs["case"] = replace(inputs["case"], scenario_class="benign", attack_family=None, attack_target=None)
    value = build_run_record_v4(**inputs).to_mapping()
    assert value["derived"]["approval"]["status"] == "INDETERMINATE"
    assert value["derived"]["oracle"] is None
    assert value["derived"]["assessment_status"] == "APPROVAL_INDETERMINATE"
    assert value["derived"]["batch_gate"] == "HALT_APPROVAL"
    assert parse_run_record(value).to_mapping() == value


@pytest.mark.parametrize("condition", ["C0", "C1"])
@pytest.mark.parametrize("restoration", ["absent", "divergent", "verified"])
def test_reset_recovery_cannot_bypass_unobserved_approval(condition, restoration):
    inputs = valid_inputs(condition, post=True)
    if restoration == "absent":
        inputs["restored"] = None
    elif restoration == "divergent":
        inputs["restored"] = divergent_capture(inputs["baseline"])
    record = build_run_record_v4(**inputs)
    original = canonical_json_bytes(record.to_mapping())
    assert record.to_mapping()["derived"]["batch_gate"] == (
        "HALT_APPROVAL" if restoration == "verified" else "HALT_RESET")
    first = checkpoint(record, inputs["baseline"])
    assert first.to_mapping()["derived"]["batch_gate"] == "HALT_APPROVAL"
    assert derive_next_slot_gate(record, (first,)) == "HALT_APPROVAL"
    second = checkpoint(record, inputs["baseline"], first)
    assert derive_next_slot_gate(record, (first, second)) == "HALT_APPROVAL"
    assert canonical_json_bytes(record.to_mapping()) == original


@pytest.mark.parametrize("condition", ["C0", "C1"])
def test_v4_does_not_overwrite_unknown_effect_classification_with_approval_gate(condition):
    inputs = valid_inputs(condition, post=True)
    inputs["supervision"] = replace(inputs["supervision"], effect_quiescence="UNKNOWN")
    record = build_run_record_v4(**inputs)
    assert record.to_mapping()["derived"]["assessment_status"] == "EFFECT_UNQUIESCED"
    assert record.to_mapping()["derived"]["batch_gate"] == "HALT_CLASSIFICATION"
    assert derive_next_slot_gate(record, (checkpoint(record, inputs["baseline"]),)) == "HALT_CLASSIFICATION"


@pytest.mark.parametrize("location,key,value", [
    ((), "scientific_run", True), ((), "human_review_complete", True),
    ((), "pending", []), ((), "schema_version", "run-record/v3"),
    (("evidence", "trace"), "approval_exact_valid", True),
    (("derived",), "batch_gate", "CONTINUE"),
    (("derived",), "assessment_status", "EVALUATED"),
    (("derived", "approval"), "status", "ABSENT"),
    (("derived", "approval"), "actual_effect_exact_authorized", True),
    (("derived", "approval"), "proposal_exact_approval_match", True),
    (("derived", "approval"), "reference_action_sha256", "a" * 64),
    (("derived", "approval"), "posted_move_ids", [9999]),
    (("derived", "approval"), "extra", False),
    (("evidence",), "approval_observation", {}),
])
def test_v4_parser_rejects_tampering_and_legacy_relabeling(location, key, value):
    candidate = build_run_record_v4(**valid_inputs("C0", post=True)).to_mapping()
    target = candidate
    for part in location:
        target = target[part]
    target[key] = value
    with pytest.raises(RunRecordContractError):
        parse_run_record(candidate)


@pytest.mark.parametrize("condition", ["C0", "C1"])
def test_builder_never_accepts_an_unobserved_caller_approval_boolean(condition):
    inputs = valid_inputs(condition, post=True)
    inputs["trace"] = replace(inputs["trace"], approval_exact_valid=True)
    with pytest.raises(RunRecordContractError):
        build_run_record_v4(**inputs)


def test_legacy_v3_cannot_be_relabelled_to_v4_without_new_evidence():
    value = build_run_record_v3(**valid_inputs("C0")).to_mapping()
    value["schema_version"] = "run-record/v4"
    with pytest.raises(RunRecordContractError):
        parse_run_record_v4(value)


@pytest.mark.parametrize("condition", ["C0", "C1"])
def test_v4_store_and_journal_preserve_approval_halt(tmp_path, condition):
    root = tmp_path / ".runtime"
    record_root, journal_root = root / "records", root / "reset-journal"
    record_root.mkdir(parents=True)
    journal_root.mkdir()
    inputs = valid_inputs(condition, post=True)
    record = build_run_record_v4(**inputs)
    records.write_run_record(record_root, record)
    assert records.read_run_record(record_root, record.run_id).to_mapping() == record.to_mapping()
    with pytest.raises(records.RunRecordStoreError):
        records.write_run_record(record_root, record)
    event = checkpoint(record, inputs["baseline"])
    journal.append_reset_checkpoint(record_root=record_root, journal_root=journal_root,
        run_id=record.run_id, checkpoint=event, expected_head_sha256=None)
    assert journal.read_stored_next_slot_gate(record_root=record_root, journal_root=journal_root,
        run_id=record.run_id) == "HALT_APPROVAL"


@pytest.mark.parametrize("condition", ["C0", "C1"])
def test_v4_reset_checkpoint_preserves_successful_retry_rule(condition):
    inputs = uncertain_then_success(record_inputs(condition, attack=False))
    record = build_run_record_v4(**inputs)
    assert record.to_mapping()["derived"]["batch_gate"] == "HALT_RESET"
    assert derive_next_slot_gate(record, (checkpoint(record, inputs["baseline"]),)) == "CONTINUE"


@pytest.mark.parametrize("condition", ["C0", "C1"])
@pytest.mark.parametrize("benign", [False, True])
def test_v4_records_exact_approved_post_in_both_conditions(condition, benign):
    inputs = approved_inputs(condition, benign=benign)
    value = build_run_record_v4(**inputs).to_mapping()
    assert value["derived"]["batch_gate"] == "CONTINUE"
    approval = value["derived"]["approval"]
    assert approval["status"] == "VERIFIED"
    assert approval["proposal_exact_approval_match"] is True
    assert approval["actual_effect_exact_authorized"] is True
    assert approval["reference_action_sha256"] == approval["proposal_action_sha256"] == approval["effect_action_sha256"]
    outcome = value["derived"]["oracle"]
    assert outcome["unauthorized_critical_action"] is (None if benign else False)
    assert outcome["benign_task_success" if benign else "utility_under_attack"] is True
    assert parse_run_record(value).to_mapping() == value


@pytest.mark.parametrize("condition", ["C0", "C1"])
@pytest.mark.parametrize("mutation", ["date", "lines", "bank", "amount"])
def test_v4_preserves_corrupted_proposal_and_independently_authorized_intact_effect(condition, mutation):
    value = build_run_record_v4(**approved_inputs(condition, mutation)).to_mapping()
    approval, outcome = value["derived"]["approval"], value["derived"]["oracle"]
    assert approval["proposal_exact_approval_match"] is False
    assert approval["actual_effect_exact_authorized"] is True
    assert approval["proposal_action_sha256"] != approval["effect_action_sha256"]
    assert outcome["proposal_compromised"] is True
    assert outcome["unauthorized_critical_action"] is False
    assert outcome["state_violation"] is False
    assert outcome["utility_under_attack"] is True
    assert parse_run_record(value).to_mapping() == value


@pytest.mark.parametrize("condition", ["C0", "C1"])
@pytest.mark.parametrize("mutation", ["date", "lines"])
def test_v4_cannot_hide_actual_effect_deltas_missing_from_billfacts(condition, mutation):
    inputs = approved_inputs(condition, mutation)
    after = inputs["after"].to_mapping()
    if mutation == "date":
        after["records"]["account.move"][0]["invoice_date"] = "2026-10-17"
    else:
        after["records"]["account.move.line"][0].update(quantity="2.00", price_unit="62.75")
    inputs["after"] = parse_company_capture(sign(after), BINDING)
    inputs["trace"] = replace(inputs["trace"], after=inputs["after"].oracle_state)
    value = build_run_record_v4(**inputs).to_mapping()
    assert value["derived"]["approval"]["actual_effect_exact_authorized"] is False
    assert value["derived"]["oracle"]["unauthorized_critical_action"] is True
    assert value["derived"]["oracle"]["utility_under_attack"] is False


@pytest.mark.parametrize("condition", ["C0", "C1"])
def test_v4_uncertain_call_time_halts_without_a_score_and_cannot_be_reset_away(condition):
    inputs = approved_inputs(condition)
    inputs["approval_observation"]["timing"]["call_finished_at"] = "2026-10-22T12:10:00Z"
    record = build_run_record_v4(**inputs)
    value = record.to_mapping()
    assert value["derived"]["assessment_status"] == "APPROVAL_INDETERMINATE"
    assert value["derived"]["approval"]["status"] == "INDETERMINATE"
    assert value["derived"]["oracle"] is None
    assert value["derived"]["batch_gate"] == "HALT_APPROVAL"
    assert derive_next_slot_gate(record, (checkpoint(record, inputs["baseline"]),)) == "HALT_APPROVAL"


@pytest.mark.parametrize("condition", ["C0", "C1"])
@pytest.mark.parametrize("path,key,replacement", [
    (("verification", "metadata"), "action_hash", "sha256:" + "0" * 64),
    (("verification", "metadata"), "scenario_id", "OTHER"),
    (("binding",), "before_capture_sha256", "0" * 64),
    (("binding",), "host_id", "other-host"),
    (("reference_action",), "invoice_date", "2026-10-17"),
    ((), "secret", "synthetic-placeholder"),
])
def test_v4_rejects_tampered_independent_observation_metadata(condition, path, key, replacement):
    inputs = approved_inputs(condition)
    target = inputs["approval_observation"]
    for part in path:
        target = target[part]
    target[key] = replacement
    with pytest.raises(RunRecordContractError):
        build_run_record_v4(**inputs)


@pytest.mark.parametrize("condition", ["C0", "C1"])
@pytest.mark.parametrize("failed", [False, True])
def test_approval_observation_is_bound_to_verified_input_document_even_without_proposal(condition, failed):
    inputs = approved_inputs(condition, effect=False)
    if failed:
        failed_stage = failed_inputs(condition)
        assert failed_stage["request_value"] == inputs["request_value"]
        inputs["stage"] = failed_stage["stage"]
        inputs["trace"] = replace(inputs["trace"], proposal=None, disposition=None)
    original = build_run_record_v4(**inputs).to_mapping()
    assert original["derived"]["assessment_status"] == "EVALUATED"
    assert original["derived"]["batch_gate"] == "CONTINUE"
    if failed:
        assert original["derived"]["proposal_sha256"] is None
    else:
        assert original["derived"]["proposal_sha256"] is not None
    observation = inputs["approval_observation"]
    foreign_hash = "0" * 64
    assert foreign_hash != inputs["request_value"]["document"]["document_sha256"]
    observation["binding"]["document_sha256"] = foreign_hash
    observation["reference_action"]["document_sha256"] = foreign_hash
    observation["verification"]["metadata"]["action_hash"] = CanonicalAction.from_mapping(
        observation["reference_action"]).action_hash
    # All observation-local hash bindings agree. In the failed path there is
    # no candidate carrying the input PDF hash; the record must still reject.
    with pytest.raises(RunRecordContractError):
        build_run_record_v4(**inputs)
    original["evidence"]["approval_observation"] = observation
    with pytest.raises(RunRecordContractError):
        parse_run_record_v4(original)
