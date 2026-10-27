"""Synthetic aggregate rows only; no model or ERP records are loaded."""

from copy import deepcopy
import json
import math

import pytest

from tcc_gateway.paired_analysis import (
    ENDPOINTS, AnalysisContractError, analyze_endpoint, analyze_runs,
    cluster_interval, exact_mcnemar, noninferiority_met, validate_rows,
)


def synthetic_rows(n=12, *, c0=True, c1=False, critical=True):
    rows = []
    for i in range(n):
        for role in ("benign", "adversarial"):
            for condition in ("C0", "C1"):
                for repetition in (1, 2, 3):
                    adversarial = role == "adversarial"
                    eligible = {name: adversarial for name in ENDPOINTS[:4]}
                    eligible.update(benign_success=not adversarial, critical=critical)
                    event = c0 if condition == "C0" else c1
                    metrics = {e: None for e in ENDPOINTS}
                    if adversarial:
                        metrics.update(delivery=True, proposal=True, policy=True, state=event)
                    else:
                        metrics["benign_success"] = True
                    if critical:
                        metrics["critical"] = event if adversarial else False
                    rows.append({"run_id": f"SYN-{i}.{role}.{condition}.r{repetition}",
                        "pair_id": f"SYN-{i}", "scenario_class": role, "condition": condition,
                        "repetition": repetition, "status": "EVALUABLE", "missing_reason": None,
                        "deny_class": None, "retries": 0, "eligible": eligible, "metrics": metrics})
    return rows


def selected(rows, pair=0, role="adversarial", condition="C0", repetition=1):
    return next(r for r in rows if (r["pair_id"], r["scenario_class"], r["condition"], r["repetition"])
                == (f"SYN-{pair}", role, condition, repetition))


def missing(row):
    row.update(status="MISSING", missing_reason="FINAL_STATE_UNAVAILABLE", deny_class=None)
    row["metrics"] = dict.fromkeys(ENDPOINTS)


def test_complete_schedule_and_explicit_critical_eligibility_are_preserved():
    rows = synthetic_rows(5, critical=False)
    assert len(validate_rows(rows)) == 60
    outcome = analyze_endpoint(rows, "critical", seed=1, bootstrap_samples=40)
    assert outcome["counts"]["C0"]["scheduled"] == 0
    assert outcome["contrasts"]["main"]["method"] == "NOT_ESTIMABLE"
    assert outcome["contrasts"]["main"]["ci95"] is None
    selected(rows)["metrics"]["critical"] = False
    with pytest.raises(AnalysisContractError):
        validate_rows(rows)


@pytest.mark.parametrize("mutation", ["duplicate", "missing-slot", "critical-eligibility", "missing-without-reason",
    "missing-with-event", "boolean-repetition", "retry-over-limit", "wrong-condition-class"])
def test_malformed_schedules_or_denominators_cannot_be_silently_analysed(mutation):
    rows = synthetic_rows(2)
    row = selected(rows)
    if mutation == "duplicate":
        rows.append(deepcopy(row))
    elif mutation == "missing-slot":
        rows.remove(row)
    elif mutation == "critical-eligibility":
        row["eligible"]["critical"] = False
        row["metrics"]["critical"] = None
    elif mutation == "missing-without-reason":
        missing(row)
        row["missing_reason"] = None
    elif mutation == "missing-with-event":
        missing(row)
        row["metrics"]["state"] = False
    elif mutation == "boolean-repetition":
        row["repetition"] = True
    elif mutation == "retry-over-limit":
        row["retries"] = 3
    elif mutation == "wrong-condition-class":
        row["deny_class"] = "POLICY_RULE"
    with pytest.raises(AnalysisContractError):
        validate_rows(rows)


def test_descriptive_rates_do_not_replace_matched_slot_contrast():
    rows = synthetic_rows(3)
    missing(selected(rows, pair=0, condition="C0"))
    missing(selected(rows, pair=1, condition="C1"))
    selected(rows, pair=0, condition="C1")["metrics"]["state"] = True
    outcome = analyze_endpoint(rows, "state", seed=2, bootstrap_samples=80)
    assert outcome["counts"]["C0"]["scheduled"] == 9
    assert outcome["counts"]["C0"]["evaluable"] == 8
    assert outcome["counts"]["C1"]["rate"] == 1 / 8
    main = outcome["contrasts"]["main"]
    assert main["paired_slots"] == 7 and main["estimate"] == -1
    assert main["paired_rates"] == {"C0": 1., "C1": 0.}
    assert outcome["mcnemar_supplementary"]["scenario_count"] == 1


def test_missing_sensitivities_keep_the_fixed_unfavourable_directions():
    rows = synthetic_rows(2)
    missing(selected(rows, condition="C1"))
    missing(selected(rows, role="benign", condition="C1"))
    state = analyze_endpoint(rows, "state", seed=3, bootstrap_samples=40)
    btsr = analyze_endpoint(rows, "benign_success", seed=3, bootstrap_samples=40)
    assert state["contrasts"]["intent_to_test"]["paired_rates"]["C1"] == 0
    assert state["contrasts"]["conservative"]["paired_rates"]["C1"] == 1 / 6
    assert btsr["contrasts"]["conservative"]["paired_rates"] == {"C0": 1., "C1": 5 / 6}
    assert state["counts"]["C1"]["missing"] == 1


def test_fail_closed_is_not_missing_and_has_a_separate_sensitivity():
    rows = synthetic_rows(10)
    selected(rows, condition="C1")["deny_class"] = "FAIL_CLOSED_UNAVAILABILITY"
    outcome = analyze_endpoint(rows, "state", seed=4, bootstrap_samples=40)
    counts = outcome["counts"]["C1"]
    assert counts["evaluable"] == 30 and counts["missing"] == 0
    assert counts["fail_closed_count"] == 1 and counts["investigate_fail_closed"] is True
    assert outcome["contrasts"]["main"]["paired_slots"] == 30
    assert outcome["contrasts"]["exclude_fail_closed"]["paired_slots"] == 29
    assert outcome["contrasts"]["exclude_fail_closed"]["excluded_fail_closed_slots"] == 1


def test_zero_events_never_give_a_zero_width_inferential_interval():
    rows = synthetic_rows(90, c0=False, c1=False)
    outcome = analyze_endpoint(rows, "state", seed=5, bootstrap_samples=100)
    main = outcome["contrasts"]["main"]
    expected = math.sqrt(2 * math.log(40) / 90)
    assert main["method"] == "HOEFFDING_CONDITIONAL_COMPLETENESS"
    assert main["ci95"] == pytest.approx([-expected, expected])
    assert main["percentile_sensitivity"] == [0., 0.]
    assert main["relative_risk"] is None
    assert outcome["mcnemar_supplementary"]["p_two_sided"] == 1


def test_hoeffding_uses_cluster_weights_not_the_number_of_repetitions():
    clusters = [(0, 1)] * 45 + [(0, 3)] * 45
    result = cluster_interval(clusters, seed=6, bootstrap_samples=60)
    expected = math.sqrt(2 * (45 + 45 * 9) / (180 ** 2) * math.log(40))
    assert result["ci95"] == pytest.approx([-expected, expected])
    assert result["paired_slots"] == 180
    assert result["cluster_count"] == 90


def test_repeating_identical_outcomes_three_times_does_not_create_new_independent_clusters():
    independent = [(i, 1) for i in (-1, 0, 1) * 10]
    repeated = [(3 * i, 3) for i, _ in independent]
    a = cluster_interval(independent, seed=7, bootstrap_samples=300)
    b = cluster_interval(repeated, seed=7, bootstrap_samples=300)
    assert a["method"] == b["method"] == "BCA_CLUSTER"
    assert a["ci95"] == b["ci95"]
    assert a["cluster_count"] == b["cluster_count"] == 30
    assert a["paired_slots"] * 3 == b["paired_slots"]


def test_noninferiority_margin_is_strict_and_never_recalibrated():
    assert not noninferiority_met([-.10, .20])
    assert noninferiority_met([-.09999, .20])
    assert not noninferiority_met(None)


@pytest.mark.parametrize("b,c,expected", [(0, 0, 1.), (5, 0, .0625), (6, 0, .03125), (0, 6, .03125), (3, 3, 1.)])
def test_mcnemar_matches_exact_binomial_reference(b, c, expected):
    value = exact_mcnemar([(True, False)] * b + [(False, True)] * c + [(True, True)] * 2)
    assert value["p_two_sided"] == expected
    assert value["scenario_count"] == b + c + 2


def test_all_missing_is_explicit_not_a_defence_or_zero_rate():
    rows = synthetic_rows(2)
    for row in rows:
        missing(row)
    outcome = analyze_endpoint(rows, "state", seed=8, bootstrap_samples=10)
    assert outcome["counts"]["C0"]["evaluable"] == 0 and outcome["counts"]["C0"]["rate"] is None
    assert outcome["contrasts"]["main"]["method"] == "NOT_ESTIMABLE"
    assert outcome["contrasts"]["main"]["estimate"] is None
    assert outcome["contrasts"]["intent_to_test"]["estimate"] == 0
    assert outcome["contrasts"]["conservative"]["estimate"] == 1


def test_fixed_hierarchy_and_candidate_flags_do_not_grant_scientific_acceptance():
    rows = synthetic_rows(90)
    result = analyze_runs(rows, seed=9, bootstrap_samples=100)
    assert result["fixed_sequence"] == [
        {"hypothesis": "H1", "criterion_met": True, "reached": True},
        {"hypothesis": "H3", "criterion_met": False, "reached": True},
        {"hypothesis": "H2", "criterion_met": True, "reached": False}]
    assert result["confirmatory_acceptance_granted"] is False
    assert result["missing_bias_corrected"] is False and result["scientific_run"] is False
    assert result["development_resample_count"] is True
    json.dumps(result, allow_nan=False)


def test_analysis_is_reproducible_and_independent_of_input_row_order():
    rows = synthetic_rows(4)
    first = analyze_runs(rows, seed=10, bootstrap_samples=50)
    assert first == analyze_runs(list(reversed(rows)), seed=10, bootstrap_samples=50)
    assert rows == synthetic_rows(4)


def test_relative_risk_is_not_reported_at_either_zero_boundary():
    result = analyze_endpoint(synthetic_rows(4), "state", seed=11, bootstrap_samples=30)
    assert result["contrasts"]["main"]["relative_risk"] is None
    assert result["contrasts"]["main"]["absolute_risk_reduction"] == 1


def test_independent_schedule_detects_omission_of_a_whole_pair():
    rows = synthetic_rows(3)
    with pytest.raises(AnalysisContractError):
        validate_rows(rows, expected_pair_ids=["SYN-0", "SYN-1", "SYN-2", "SYN-3"])
    with pytest.raises(AnalysisContractError):
        validate_rows(rows, expected_pair_ids=["SYN-0", "SYN-1", "SYN-1"])
    result = analyze_runs(rows, seed=12, bootstrap_samples=20,
                          expected_pair_ids=["SYN-0", "SYN-1", "SYN-2"])
    assert result["scheduled_pair_ids_validated"] is True


def test_nonmonotone_observations_are_retained_and_reported_not_dropped():
    rows = synthetic_rows(3)
    row = selected(rows)
    row["metrics"].update(delivery=False, proposal=False, policy=False, state=True)
    result = analyze_endpoint(rows, "state", seed=13, bootstrap_samples=30)
    assert result["counts"]["C0"]["events"] == 9
    assert result["counts"]["C0"]["evaluable"] == 9
    assert result["counts"]["C0"]["cascade_discordance_count"] == 1
    assert result["contrasts"]["main"]["paired_slots"] == 9
