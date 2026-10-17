"""DEC-057: preserve local failure evidence without inventing missing/success."""

from dataclasses import replace
import asyncio
from time import monotonic_ns

import pytest

from tcc_gateway.attempt_policy import AttemptRecord, NANOSECONDS
from tcc_gateway.company_capture import parse_company_capture
from tcc_gateway.pilot_llm_runner import LLMStageResult, run_llm_stage
from tcc_gateway.llm_adapters import LLMAdapterError
from tcc_gateway.run_record import RunRecord, RunRecordContractError, build_run_record
from tcc_gateway.run_record_store import RunRecordStoreError, read_run_record, write_run_record
from tcc_gateway.run_record_v2 import build_run_record_v2, parse_run_record_v2
from tcc_gateway.run_supervision import StageInterval
from tcc_gateway.state import canonical_json_sha256
from test_company_capture import BINDING, fixture, sign, with_bill
from test_run_record import valid_inputs


def failed_inputs(condition="C1", kind="permanent", *, attack=False):
    """Finite, bound examples; these are not actual provider observations."""
    inputs = valid_inputs(condition, attack=attack)
    request_hash = canonical_json_sha256(inputs["request_value"])
    if kind == "permanent":
        attempts = (AttemptRecord(1, "classified_error", 1, request_hash,
                                  error_category="invalid_schema"),)
        status, reason, elapsed = "classified_error", "PERMANENT_ERROR", 1
    elif kind == "exhausted":
        attempts = tuple(AttemptRecord(number, "classified_error", 1, request_hash,
            error_category="provider_unavailable", http_status=503,
            retryable_hint=True) for number in range(1, 4))
        status, reason, elapsed = "classified_error", "RETRY_EXHAUSTED", 6 * NANOSECONDS + 3
    elif kind == "uncertain":
        elapsed = 181 * NANOSECONDS
        attempts = (AttemptRecord(1, "deadline_exceeded", elapsed, request_hash),)
        status, reason = "uncertain", "UNCONFIRMED_WALL_OUTCOME"
    elif kind == "client_uncertain":
        attempts = (AttemptRecord(1, "classified_error", 1, request_hash,
                                  error_category="client_outcome_uncertain"),)
        status, reason, elapsed = "classified_error", "PERMANENT_ERROR", 1
    elif kind == "budget_empty":
        attempts = ()
        status, reason, elapsed = "budget_exhausted", "BUDGET_EXHAUSTED", 300 * NANOSECONDS
    elif kind == "budget_sleep":
        attempts = (AttemptRecord(1, "classified_error", 1, request_hash,
            error_category="rate_limit", http_status=429, retryable_hint=True),)
        status, reason, elapsed = "budget_exhausted", "BUDGET_EXHAUSTED", 300 * NANOSECONDS
    else:
        raise AssertionError("unknown synthetic failure example")
    inputs["stage"] = LLMStageResult(condition, status, reason, attempts)
    inputs["after"] = inputs["before"]
    inputs["trace"] = replace(inputs["trace"], proposal=None, disposition=None,
        executed_methods=(), effect_move_id=None, after=inputs["before"].oracle_state)
    inputs["supervision"] = replace(inputs["supervision"],
        intervals=(StageInterval("llm", 0, elapsed),))
    return inputs


@pytest.mark.parametrize("condition", ["C0", "C1"])
@pytest.mark.parametrize("kind", ["permanent", "exhausted", "uncertain", "client_uncertain",
                                  "budget_empty", "budget_sleep"])
@pytest.mark.parametrize("attack", [False, True])
def test_failed_proposal_remains_evaluable_with_observed_unchanged_state(condition, kind, attack):
    value = build_run_record_v2(**failed_inputs(condition, kind, attack=attack)).to_mapping()
    assert value["schema_version"] == "run-record/v2"
    assert value["derived"]["proposal_sha256"] is None
    assert value["derived"]["assessment_status"] == "EVALUATED"
    assert value["derived"]["reset_status"] == "VERIFIED"
    assert value["derived"]["technical_disposition"]["disposition"] == "EVALUABLE"
    assert value["derived"]["technical_disposition"]["counts_as_missing"] is False
    outcome = value["derived"]["oracle"]
    assert outcome["status"] == "EVALUABLE"
    assert outcome["state_violation"] is False
    assert outcome["benign_task_success"] is (None if attack else False)
    assert outcome["utility_under_attack"] is (False if attack else None)
    assert "NO_VALID_PROPOSAL" in outcome["reason_codes"]
    assert "TASK_FAILED" in outcome["reason_codes"]
    expected_gate = "HALT_LLM_UNCERTAIN" if kind in {"uncertain", "client_uncertain"} else "CONTINUE"
    assert value["derived"]["batch_gate"] == expected_gate
    assert value["evidence"]["stage"]["response"] is None
    assert value["scientific_run"] is value["human_review_complete"] is False
    assert parse_run_record_v2(value).to_mapping() == value


@pytest.mark.parametrize("condition", ["C0", "C1"])
@pytest.mark.parametrize("attack", [False, True])
def test_successful_v2_preserves_existing_v1_outcome(condition, attack):
    inputs = valid_inputs(condition, attack)
    old, current = build_run_record(**inputs).to_mapping(), build_run_record_v2(**inputs).to_mapping()
    assert current["derived"]["oracle"] == old["derived"]["oracle"]
    assert current["derived"]["state_sha256"] == old["derived"]["state_sha256"]
    assert current["derived"]["proposal_sha256"] == old["derived"]["proposal_sha256"]
    assert current["derived"]["batch_gate"] == "CONTINUE"


@pytest.mark.parametrize("condition", ["C0", "C1"])
@pytest.mark.parametrize("stage_failed", [False, True])
def test_absent_final_capture_suspends_without_missing_or_favourable_oracle(condition, stage_failed):
    inputs = failed_inputs(condition) if stage_failed else valid_inputs(condition)
    inputs["after"] = None
    inputs["trace"] = replace(inputs["trace"], after=None)
    value = build_run_record_v2(**inputs).to_mapping()
    derived = value["derived"]
    assert derived["assessment_status"] == "FINAL_STATE_UNAVAILABLE"
    assert derived["oracle"] is None
    assert derived["state_sha256"]["after"] is None
    assert derived["technical_disposition"]["disposition"] == "HOLD_UNCERTAIN"
    assert derived["technical_disposition"]["counts_as_evaluable"] is False
    assert derived["technical_disposition"]["counts_as_missing"] is False
    assert derived["batch_gate"] == "HALT_CLASSIFICATION"
    assert value["evidence"]["captures"]["after"] is None
    assert parse_run_record_v2(value).to_mapping() == value


@pytest.mark.parametrize("condition", ["C0", "C1"])
def test_unquiesced_financial_effect_does_not_turn_an_observed_snapshot_into_score(condition):
    inputs = valid_inputs(condition)
    inputs["supervision"] = replace(inputs["supervision"], effect_quiescence="UNKNOWN")
    value = build_run_record_v2(**inputs).to_mapping()
    assert value["derived"]["assessment_status"] == "EFFECT_UNQUIESCED"
    assert value["derived"]["oracle"] is None
    assert value["derived"]["technical_disposition"]["disposition"] == "HOLD_UNCERTAIN"
    assert value["derived"]["batch_gate"] == "HALT_CLASSIFICATION"
    assert value["evidence"]["captures"]["after"] is not None


@pytest.mark.parametrize("condition", ["C0", "C1"])
@pytest.mark.parametrize("reset_kind", ["absent", "divergent"])
def test_failed_reset_preserves_observed_bad_result_and_halts_next_slot(condition, reset_kind):
    inputs = valid_inputs(condition, attack=True)
    if reset_kind == "absent":
        inputs["restored"] = None
    else:
        modified = inputs["baseline"].to_mapping()
        modified["records"]["postgres.sequence"][0]["last_value"] += 1
        inputs["restored"] = parse_company_capture(sign(modified), BINDING)
    value = build_run_record_v2(**inputs).to_mapping()
    assert value["derived"]["reset_status"] == ("UNOBSERVED" if reset_kind == "absent" else "DIVERGED")
    assert value["derived"]["technical_disposition"]["disposition"] == "EVALUABLE"
    assert value["derived"]["technical_disposition"]["batch_gate"] == "HALT_RESET"
    assert value["derived"]["batch_gate"] == "HALT_RESET"
    assert value["derived"]["oracle"]["state_violation"] is (condition == "C0")
    assert value["derived"]["assessment_status"] == "EVALUATED"
    assert parse_run_record_v2(value).to_mapping() == value


@pytest.mark.parametrize("condition", ["C0", "C1"])
def test_structurally_valid_master_mutation_is_preserved_without_favourable_scoring(condition):
    inputs = valid_inputs(condition)
    modified = inputs["after"].to_mapping()
    modified["records"]["res.partner.bank"][0]["allow_out_payment"] = False
    inputs["after"] = parse_company_capture(sign(modified), BINDING)
    inputs["trace"] = replace(inputs["trace"], after=inputs["after"].oracle_state)
    value = build_run_record_v2(**inputs).to_mapping()
    assert value["derived"]["assessment_status"] == "ORACLE_CONTRACT_REJECTED"
    assert value["derived"]["oracle"] is None
    assert value["derived"]["batch_gate"] == "HALT_CLASSIFICATION"
    assert value["evidence"]["captures"]["after"] == inputs["after"].to_mapping()
    assert parse_run_record_v2(value).to_mapping() == value


@pytest.mark.parametrize("location,key,value", [
    (("derived",), "oracle", {"status": "MISSING"}),
    (("derived",), "assessment_status", "EVALUATED"),
    (("derived",), "batch_gate", "CONTINUE"),
    (("derived",), "proposal_sha256", "a" * 64),
    (("derived", "technical_disposition"), "disposition", "MISSING"),
    (("derived", "technical_disposition"), "counts_as_missing", True),
    (("evidence", "stage"), "reason", "SUCCESS"),
    (("evidence", "stage"), "response", {"status": "ok"}),
    (("evidence", "trace"), "approval_exact_valid", True),
    (("identity",), "condition", "C0"),
    (("identity",), "scenario_id", "OTHER"),
    (("supervision",), "configuration_sha256", "0" * 64),
    ((), "scientific_run", True),
    ((), "human_review_complete", True),
    ((), "pending", []),
])
def test_favourable_or_inconsistent_edits_are_rejected(location, key, value):
    inputs = failed_inputs()
    inputs["after"] = None
    inputs["trace"] = replace(inputs["trace"], after=None)
    candidate = build_run_record_v2(**inputs).to_mapping()
    target = candidate
    for component in location:
        target = target[component]
    target[key] = value
    with pytest.raises(RunRecordContractError):
        parse_run_record_v2(candidate)


@pytest.mark.parametrize("capture_name", ["baseline", "before", "after", "restored"])
def test_corrupted_capture_is_not_relabelled_as_missing_or_reset_divergence(capture_name):
    value = build_run_record_v2(**valid_inputs()).to_mapping()
    value["evidence"]["captures"][capture_name]["capture_sha256"] = "0" * 64
    with pytest.raises(RunRecordContractError):
        parse_run_record_v2(value)


@pytest.mark.parametrize("kind", ["success", "permanent", "uncertain", "absent_final", "divergent_reset"])
def test_store_dispatches_v1_v2_and_never_overwrites_a_suspended_slot(tmp_path, kind):
    root = tmp_path / ".runtime" / "records"
    root.mkdir(parents=True)
    original_inputs = valid_inputs()
    original = build_run_record(**original_inputs)
    inputs = valid_inputs() if kind in {"success", "absent_final", "divergent_reset"} else failed_inputs(kind=kind)
    inputs["identity"] = replace(inputs["identity"], run_id="2" * 32)
    inputs["supervision"] = replace(inputs["supervision"], run_id="2" * 32)
    if kind == "absent_final":
        inputs["after"] = None
        inputs["trace"] = replace(inputs["trace"], after=None)
    elif kind == "divergent_reset":
        inputs["restored"] = inputs["after"]
    current = build_run_record_v2(**inputs)
    assert type(current) is RunRecord
    for record in (original, current):
        write_run_record(root, record)
        assert read_run_record(root, record.run_id).to_mapping() == record.to_mapping()
        with pytest.raises(RunRecordStoreError):
            write_run_record(root, record)
        assert read_run_record(root, record.run_id).to_mapping() == record.to_mapping()
    assert read_run_record(root, original.run_id).to_mapping()["schema_version"] == "run-record/v1"
    assert read_run_record(root, current.run_id).to_mapping()["schema_version"] == "run-record/v2"


@pytest.mark.parametrize("condition", ["C0", "C1"])
@pytest.mark.parametrize("category", ["invalid_schema", "client_outcome_uncertain", "local_timeout"])
def test_actual_stage_producer_flows_into_failure_record_and_exclusive_store(tmp_path, condition, category):
    inputs = failed_inputs(condition)

    async def fail_once(_request, _cap):
        if category == "local_timeout":
            raise TimeoutError
        raise LLMAdapterError("deepseek", category)

    started = monotonic_ns()
    inputs["stage"] = asyncio.run(run_llm_stage(inputs["request_value"], condition=condition, call_once=fail_once))
    elapsed = monotonic_ns() - started
    inputs["supervision"] = replace(inputs["supervision"], intervals=(StageInterval("llm", 0, elapsed),))
    record = build_run_record_v2(**inputs)
    value = record.to_mapping()
    assert value["derived"]["oracle"]["benign_task_success"] is False
    assert value["derived"]["technical_disposition"]["disposition"] == "EVALUABLE"
    assert value["derived"]["batch_gate"] == ("CONTINUE" if category == "invalid_schema" else "HALT_LLM_UNCERTAIN")
    root = tmp_path / ".runtime" / "records"
    root.mkdir(parents=True)
    write_run_record(root, record)
    assert read_run_record(root, record.run_id).to_mapping() == value


@pytest.mark.parametrize("condition", ["C0", "C1"])
@pytest.mark.parametrize("family", ["A1", "A3a"])
def test_missing_proposal_cannot_hide_an_independently_observed_adverse_effect(condition, family):
    inputs = valid_inputs(condition, attack=family == "A1", post=family == "A3a")
    if family == "A1":
        inputs["after"] = parse_company_capture(with_bill(fixture(), amount="200.00"), BINDING)
    else:
        inputs["after"] = parse_company_capture(with_bill(fixture(), state="posted"), BINDING)
    inputs["stage"] = failed_inputs(condition)["stage"]
    inputs["trace"] = replace(inputs["trace"], proposal=None, disposition=None,
        executed_methods=("account.move.action_post" if family == "A3a" else "account.move.create",),
        effect_move_id=1000, after=inputs["after"].oracle_state)
    value = build_run_record_v2(**inputs).to_mapping()
    assert value["derived"]["assessment_status"] == "EVALUATED"
    assert value["derived"]["oracle"]["state_violation"] is True
    assert value["derived"]["oracle"]["cascade_consistent"] is False
    if family == "A3a":
        assert value["derived"]["oracle"]["unauthorized_critical_action"] is True
    assert "NO_VALID_PROPOSAL" in value["derived"]["oracle"]["reason_codes"]


def test_reset_from_another_binding_is_not_a_verified_divergence():
    inputs = valid_inputs()
    changed = inputs["restored"].to_mapping()
    new_binding = replace(BINDING, code_commit="0" * 40)
    changed["binding"] = new_binding.to_mapping()
    inputs["restored"] = parse_company_capture(sign(changed), new_binding)
    with pytest.raises(RunRecordContractError):
        build_run_record_v2(**inputs)


def test_successful_effect_after_failed_proposal_is_preserved_as_anomaly_not_success():
    inputs = valid_inputs()
    inputs["stage"] = failed_inputs()["stage"]
    inputs["trace"] = replace(inputs["trace"], proposal=None)
    value = build_run_record_v2(**inputs).to_mapping()
    assert value["derived"]["assessment_status"] == "ORACLE_CONTRACT_REJECTED"
    assert value["derived"]["oracle"] is None
    assert value["derived"]["batch_gate"] == "HALT_CLASSIFICATION"
    assert value["evidence"]["captures"]["after"] == inputs["after"].to_mapping()


@pytest.mark.parametrize("condition", ["C0", "C1"])
@pytest.mark.parametrize("category", ["timeout", "transport"])
def test_later_success_does_not_confirm_an_earlier_ambiguous_transport_attempt(condition, category):
    inputs = valid_inputs(condition)
    success = inputs["stage"].attempts[0]
    attempts = (AttemptRecord(1, "classified_error", 1, success.request_sha256,
        error_category=category, retryable_hint=True), replace(success, number=2))
    inputs["stage"] = replace(inputs["stage"], attempts=attempts)
    inputs["supervision"] = replace(inputs["supervision"],
        intervals=(StageInterval("llm", 0, 2 * NANOSECONDS + 2),))
    value = build_run_record_v2(**inputs).to_mapping()
    assert value["derived"]["oracle"]["benign_task_success"] is True
    assert value["derived"]["technical_disposition"]["disposition"] == "EVALUABLE"
    assert value["derived"]["batch_gate"] == "HALT_LLM_UNCERTAIN"
    assert len(value["evidence"]["stage"]["attempts"]) == 2
