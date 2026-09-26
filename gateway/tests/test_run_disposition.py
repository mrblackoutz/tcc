from __future__ import annotations

from dataclasses import fields, replace

import pytest

from tcc_gateway.run_disposition import (
    RunDispositionContractError,
    RunTechnicalEvidence,
    classify_run,
)


def observed() -> RunTechnicalEvidence:
    return RunTechnicalEvidence(
        document_hash_verified=True,
        initial_state_verified=True,
        pipeline_started=True,
        side_effect_quiesced=True,
        final_state_verified=True,
        infrastructure_failure_independent=False,
        observation_retries_exhausted=False,
        reset_verified=True,
    )


def test_final_state_observed_is_evaluable_regardless_of_model_outcome() -> None:
    result = classify_run(observed())
    assert result.disposition == "EVALUABLE"
    assert result.counts_as_evaluable
    assert not result.counts_as_missing
    assert result.batch_gate == "CONTINUE"
    assert result.reason_code is None
    assert "attack_success" not in result.to_mapping()


@pytest.mark.parametrize(
    ("changes", "expected"),
    [
        ({"document_hash_verified": False, "pipeline_started": False, "final_state_verified": False}, "DOC_HASH_INVALID"),
        ({"initial_state_verified": False, "pipeline_started": False, "final_state_verified": False}, "INITIAL_STATE_INVALID"),
        ({"pipeline_started": False, "final_state_verified": False}, "PIPELINE_NOT_STARTED"),
    ],
)
def test_precheck_failures_halt_without_becoming_missing(changes, expected) -> None:
    result = classify_run(replace(observed(), **changes))
    assert result.disposition == "HALT_PRECHECK"
    assert result.reason_code == expected
    assert result.batch_gate == "HALT_CLASSIFICATION"
    assert not result.counts_as_missing


def test_unconfirmed_effect_halts_before_final_state_classification() -> None:
    result = classify_run(replace(observed(), side_effect_quiesced=False))
    assert result.disposition == "HOLD_UNCERTAIN"
    assert result.reason_code == "EFFECT_NOT_QUIESCED"
    assert not result.counts_as_evaluable


def test_only_independent_exhausted_final_observation_failure_is_missing() -> None:
    not_observed = replace(observed(), final_state_verified=False)
    for change in (
        {"infrastructure_failure_independent": False, "observation_retries_exhausted": False},
        {"infrastructure_failure_independent": True, "observation_retries_exhausted": False},
        {"infrastructure_failure_independent": False, "observation_retries_exhausted": True},
    ):
        result = classify_run(replace(not_observed, **change))
        assert result.disposition == "HOLD_UNCERTAIN"
        assert not result.counts_as_missing
    result = classify_run(replace(
        not_observed,
        infrastructure_failure_independent=True,
        observation_retries_exhausted=True,
    ))
    assert result.disposition == "MISSING"
    assert result.reason_code == "FINAL_STATE_UNAVAILABLE"
    assert result.counts_as_missing


def test_reset_failure_stops_batch_without_relabelling_observed_run() -> None:
    evaluable = classify_run(replace(observed(), reset_verified=False))
    assert evaluable.disposition == "EVALUABLE"
    assert evaluable.batch_gate == "HALT_RESET"
    assert evaluable.batch_reason_code == "RESET_NOT_VERIFIED"
    missing = classify_run(replace(
        observed(), final_state_verified=False,
        infrastructure_failure_independent=True,
        observation_retries_exhausted=True,
        reset_verified=False,
    ))
    assert missing.disposition == "MISSING"
    assert missing.reason_code == "FINAL_STATE_UNAVAILABLE"
    assert missing.batch_gate == "HALT_RESET"


def test_classifier_has_no_condition_or_attack_label_input() -> None:
    names = {item.name for item in fields(RunTechnicalEvidence)}
    assert "condition" not in names
    assert "attack_family" not in names
    assert "attack_success" not in names


def test_malformed_evidence_fails_contract_not_missing() -> None:
    with pytest.raises(RunDispositionContractError, match="boolean"):
        replace(observed(), final_state_verified="false")
    with pytest.raises(RunDispositionContractError, match="typed"):
        classify_run({"final_state_verified": False})
    with pytest.raises(RunDispositionContractError, match="preconditions"):
        replace(observed(), document_hash_verified=False)
