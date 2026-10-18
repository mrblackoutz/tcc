"""DEC-060/DEC-063: v3 records carry the ratified rules; v2 keeps its own."""

from dataclasses import replace

import pytest

from tcc_gateway import run_record_store as records
from tcc_gateway import run_reset_journal as journal
from tcc_gateway.attempt_policy import AttemptRecord, NANOSECONDS
from tcc_gateway.company_capture import parse_company_capture
from tcc_gateway.oracle import oracle_proposal_for_case
from tcc_gateway.run_record import RunRecordContractError, build_run_record, parse_run_record
from tcc_gateway.run_record_v2 import build_run_record_v2
from tcc_gateway.run_record_v3 import build_run_record_v3 as _build_run_record_v3, parse_run_record_v3
from tcc_gateway.run_reset_checkpoint import derive_next_slot_gate
from tcc_gateway.runner_contract_v2 import proposal_from_llm_stage_v2
from tcc_gateway.run_supervision import StageInterval
from test_company_capture import BINDING, sign
from test_run_record import valid_inputs
from test_run_record_v2 import failed_inputs
from test_run_reset_checkpoint import checkpoint, record_inputs


def build_run_record_v3(**inputs):
    """Test shim: C1 denial fixtures declare their class explicitly.

    The shared fixtures model business-rule denials (A1 amount), so they
    declare POLICY_RULE. Production callers pass the class from the decision,
    the executor receipt or the pre-policy classifier; the contract tests
    below call ``_build_run_record_v3`` directly.
    """
    trace, confirmed = inputs["trace"], inputs["supervision"].effect_quiescence == "CONFIRMED"
    if "deny_class" not in inputs and trace.condition == "C1" and (trace.disposition == "DENY"
            or trace.disposition == "ALLOW" and trace.effect_move_id is None and confirmed):
        inputs = {**inputs, "deny_class": "POLICY_RULE"}
    return _build_run_record_v3(**inputs)


def uncertain_then_success(inputs, category="timeout"):
    success = inputs["stage"].attempts[0]
    inputs["stage"] = replace(inputs["stage"], attempts=(AttemptRecord(1, "classified_error", 1,
        success.request_sha256, error_category=category, retryable_hint=True), replace(success, number=2)))
    inputs["supervision"] = replace(inputs["supervision"],
        intervals=(StageInterval("llm", 0, 2 * NANOSECONDS + 2),))
    return inputs


def near_miss_inputs(condition):
    inputs = valid_inputs(condition)
    near_miss = inputs["after"].to_mapping()
    near_miss["records"]["account.move.line"][0].update(quantity="2.00", price_unit="62.75")
    inputs["after"] = parse_company_capture(sign(near_miss), BINDING)
    inputs["trace"] = replace(inputs["trace"], after=inputs["after"].oracle_state)
    return inputs


@pytest.mark.parametrize("condition", ["C0", "C1"])
@pytest.mark.parametrize("category", ["timeout", "transport"])
def test_v2_keeps_its_gate_while_v3_flags_uncertainty_followed_by_success(condition, category):
    old = build_run_record_v2(**uncertain_then_success(valid_inputs(condition), category)).to_mapping()
    new = build_run_record_v3(**uncertain_then_success(valid_inputs(condition), category)).to_mapping()
    assert (old["schema_version"], new["schema_version"]) == ("run-record/v2", "run-record/v3")
    assert old["derived"]["batch_gate"] == "HALT_LLM_UNCERTAIN"
    assert "llm_attempt_uncertain" not in old["derived"] and "deny_class" not in old["evidence"]["trace"]
    assert new["derived"]["batch_gate"] == "CONTINUE"
    assert new["derived"]["llm_attempt_uncertain"] is True
    assert new["derived"]["oracle"] == old["derived"]["oracle"]
    assert parse_run_record(old).to_mapping() == old
    assert parse_run_record(new).to_mapping() == new


@pytest.mark.parametrize("condition", ["C0", "C1"])
@pytest.mark.parametrize("kind", ["permanent", "uncertain", "client_uncertain"])
def test_v3_still_halts_when_uncertainty_leaves_no_valid_proposal(condition, kind):
    value = build_run_record_v3(**failed_inputs(condition, kind)).to_mapping()
    uncertain = kind != "permanent"
    assert value["derived"]["assessment_status"] == "EVALUATED"
    assert value["derived"]["batch_gate"] == ("HALT_LLM_UNCERTAIN" if uncertain else "CONTINUE")
    assert value["derived"]["llm_attempt_uncertain"] is uncertain
    assert "NO_VALID_PROPOSAL" in value["derived"]["oracle"]["reason_codes"]


@pytest.mark.parametrize("condition", ["C0", "C1"])
@pytest.mark.parametrize("attack", [False, True])
def test_v3_preserves_existing_outcomes_for_valid_runs(condition, attack):
    inputs = valid_inputs(condition, attack)
    old = build_run_record(**inputs).to_mapping()
    new = build_run_record_v3(**inputs).to_mapping()
    assert new["derived"]["oracle"] == old["derived"]["oracle"]
    assert new["derived"]["proposal_sha256"] == old["derived"]["proposal_sha256"]
    assert new["derived"]["batch_gate"] == "CONTINUE"
    assert new["derived"]["llm_attempt_uncertain"] is False


@pytest.mark.parametrize("deny_class", ["POLICY_RULE", "FAIL_CLOSED_UNAVAILABILITY"])
def test_c1_denial_records_the_declared_class(deny_class):
    value = _build_run_record_v3(**valid_inputs("C1", attack=True), deny_class=deny_class).to_mapping()
    assert value["evidence"]["trace"]["deny_class"] == deny_class
    assert parse_run_record_v3(value).to_mapping() == value


@pytest.mark.parametrize("condition,attack,deny_class", [
    ("C1", True, None), ("C1", True, "UNKNOWN"), ("C1", False, "POLICY_RULE"), ("C0", True, "POLICY_RULE"),
])
def test_denial_class_must_match_the_c1_disposition(condition, attack, deny_class):
    with pytest.raises(RunRecordContractError):
        _build_run_record_v3(**valid_inputs(condition, attack=attack), deny_class=deny_class)


def test_executor_denial_after_policy_allow_requires_a_class():
    inputs = valid_inputs("C1")
    inputs["after"] = inputs["before"]
    inputs["trace"] = replace(inputs["trace"], executed_methods=(), effect_move_id=None,
                              after=inputs["before"].oracle_state)
    with pytest.raises(RunRecordContractError):
        _build_run_record_v3(**inputs)
    value = _build_run_record_v3(**inputs, deny_class="FAIL_CLOSED_UNAVAILABILITY").to_mapping()
    assert value["derived"]["oracle"]["benign_task_success"] is False
    assert value["evidence"]["trace"]["deny_class"] == "FAIL_CLOSED_UNAVAILABILITY"


@pytest.mark.parametrize("deny_class", [None, "FAIL_CLOSED_UNAVAILABILITY"])
def test_unconfirmed_executor_outcome_keeps_the_class_optional(deny_class):
    """An executor timeout is not a denial; a receipt class is optional."""
    inputs = valid_inputs("C1")
    inputs["after"] = inputs["before"]
    inputs["trace"] = replace(inputs["trace"], executed_methods=(), effect_move_id=None,
                              after=inputs["before"].oracle_state)
    inputs["supervision"] = replace(inputs["supervision"], effect_quiescence="UNKNOWN")
    value = _build_run_record_v3(**inputs, deny_class=deny_class).to_mapping()
    assert value["evidence"]["trace"]["deny_class"] == deny_class
    assert value["derived"]["assessment_status"] == "EFFECT_UNQUIESCED"
    assert value["derived"]["batch_gate"] == "HALT_CLASSIFICATION"
    assert parse_run_record_v3(value).to_mapping() == value
    with pytest.raises(RunRecordContractError):
        _build_run_record_v3(**inputs, deny_class="UNKNOWN")


def test_create_proposal_in_post_scenario_is_recorded_only_by_v3():
    """The trusted POST target is bound only to a POST proposal."""
    inputs = valid_inputs("C1", post=True)
    create = valid_inputs("C1")
    proposal = proposal_from_llm_stage_v2(create["request_value"], create["stage"])
    inputs["stage"] = create["stage"]
    inputs["trace"] = replace(inputs["trace"], proposal=oracle_proposal_for_case(proposal, inputs["case"]),
                              disposition="DENY")
    with pytest.raises(RunRecordContractError):
        build_run_record_v2(**inputs)
    value = build_run_record_v3(**inputs).to_mapping()
    assert value["evidence"]["trace"]["deny_class"] == "POLICY_RULE"
    assert value["derived"]["assessment_status"] == "EVALUATED"
    outcome = value["derived"]["oracle"]
    assert outcome["state_violation"] is False
    assert outcome["unauthorized_critical_action"] is False
    assert outcome["utility_under_attack"] is False


@pytest.mark.parametrize("condition", ["C0", "C1"])
def test_coherent_near_miss_is_scored_in_v3_and_still_suspended_in_v2(condition):
    """Right total with wrong lines: v3 counts a failure in both conditions."""
    old = build_run_record_v2(**near_miss_inputs(condition)).to_mapping()
    assert old["derived"]["assessment_status"] == "ORACLE_CONTRACT_REJECTED"
    assert old["derived"]["batch_gate"] == "HALT_CLASSIFICATION"
    value = build_run_record_v3(**near_miss_inputs(condition)).to_mapping()
    assert value["derived"]["assessment_status"] == "EVALUATED"
    assert value["derived"]["batch_gate"] == "CONTINUE"
    outcome = value["derived"]["oracle"]
    assert outcome["benign_task_success"] is False
    assert "EXPECTED_EFFECT_MISMATCH" in outcome["reason_codes"]
    assert "TASK_SUCCESS" not in outcome["reason_codes"]
    assert parse_run_record_v3(value).to_mapping() == value


@pytest.mark.parametrize("location,field,value", [
    (("evidence", "trace"), "deny_class", "POLICY_RULE"),
    (("derived",), "llm_attempt_uncertain", True),
    (("derived",), "batch_gate", "HALT_LLM_UNCERTAIN"),
    ((), "schema_version", "run-record/v2"),
])
def test_v3_parser_rejects_tampering_and_relabeling(location, field, value):
    record = build_run_record_v3(**valid_inputs("C0")).to_mapping()
    target = record
    for key in location:
        target = target[key]
    target[field] = value
    with pytest.raises(RunRecordContractError):
        parse_run_record(record)


def test_v2_record_cannot_be_relabeled_as_v3():
    record = build_run_record_v2(**valid_inputs("C0")).to_mapping()
    record["schema_version"] = "run-record/v3"
    with pytest.raises(RunRecordContractError):
        parse_run_record(record)


def test_store_dispatches_v3_and_never_overwrites(tmp_path):
    root = tmp_path / ".runtime" / "records"
    root.mkdir(parents=True)
    record = build_run_record_v3(**valid_inputs("C1", attack=True))
    records.write_run_record(root, record)
    assert records.read_run_record(root, record.run_id).to_mapping() == record.to_mapping()
    with pytest.raises(records.RunRecordStoreError):
        records.write_run_record(root, record)


@pytest.mark.parametrize("condition", ["C0", "C1"])
@pytest.mark.parametrize("category", ["timeout", "transport"])
def test_recovered_reset_continues_for_v3_and_still_halts_for_v2(condition, category):
    for build, expected in ((build_run_record_v2, "HALT_LLM_UNCERTAIN"), (build_run_record_v3, "CONTINUE")):
        inputs = uncertain_then_success(record_inputs(condition, attack=False), category)
        record = build(**inputs)
        assert record.to_mapping()["derived"]["batch_gate"] == "HALT_RESET"
        assert derive_next_slot_gate(record, (checkpoint(record, inputs["baseline"]),)) == expected


@pytest.mark.parametrize("condition", ["C0", "C1"])
def test_v3_checkpoint_still_halts_without_a_valid_proposal(condition):
    inputs = record_inputs(condition, attack=False, failed="uncertain")
    record = build_run_record_v3(**inputs)
    assert derive_next_slot_gate(record, (checkpoint(record, inputs["baseline"]),)) == "HALT_LLM_UNCERTAIN"


def test_reset_journal_accepts_a_v3_base(tmp_path):
    record_root = tmp_path / ".runtime" / "records"
    journal_root = record_root.with_name("reset-journal")
    record_root.mkdir(parents=True)
    journal_root.mkdir()
    inputs = uncertain_then_success(record_inputs("C1", attack=False))
    record = build_run_record_v3(**inputs)
    records.write_run_record(record_root, record)
    event = checkpoint(record, inputs["baseline"])
    journal.append_reset_checkpoint(record_root=record_root, journal_root=journal_root,
        run_id=record.run_id, checkpoint=event, expected_head_sha256=None)
    assert journal.read_stored_next_slot_gate(record_root=record_root, journal_root=journal_root,
                                              run_id=record.run_id) == "CONTINUE"
