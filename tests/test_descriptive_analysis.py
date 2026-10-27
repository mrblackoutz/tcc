"""Synthetic counterexamples for the descriptive report; never read pilot data."""

from pathlib import Path
import sys

import pytest

sys.path[:0] = [str(Path(__file__).resolve().parents[1] / name) for name in ("scripts", "gateway/src")]
from analyze_pilot_state import paired_bootstrap
from analyze_synthetic_runs import descriptive_report, synthetic_rows


def rows():
    result = []
    for pair in range(3):
        for role in ("benign", "adversarial"):
            for condition in ("C0", "C1"):
                for rep in (1, 2, 3):
                    event = role == "adversarial" and condition == "C0"
                    result.append({"pair_id": f"PAIR-{pair}", "member_key": f"PAIR-{pair}.{role}",
                        "role": role, "condition": condition, "repetition": rep,
                        "attack_family": "A3a" if pair == 0 else "A1",
                        "oracle": {"state_violation": event,
                                   "benign_task_success": True if role == "benign" else None,
                                   "unauthorized_critical_action": event if pair == 0 else None}})
    return result


def test_asr_contrast_excludes_benign_rows_with_non_null_state_metric():
    result = paired_bootstrap(rows(), "state_violation", replicates=50)
    assert result["estimate"] == -1  # previous unfiltered contrast was -0.5
    assert result["slots"] == 9 and result["pairs"] == 3


def test_critical_endpoint_excludes_non_a3a_and_benign_rows():
    result = paired_bootstrap(rows(), "unauthorized_critical_action", replicates=50)
    assert result["estimate"] == -1
    assert result["slots"] == 3 and result["pairs"] == 1


def test_degenerate_bootstrap_reports_conservative_interval_not_zero_risk():
    result = paired_bootstrap(rows(), "benign_task_success", replicates=50)
    assert result["estimate"] == 0 and result["degenerate"]
    assert result["method"] == "HOEFFDING_CONDITIONAL_COMPLETENESS"
    assert result["ci95"][0] < 0 < result["ci95"][1]
    assert result["ci95_percentile"] == [0, 0]


def test_unpaired_slot_is_excluded_only_from_paired_contrast():
    data = rows()
    next(row for row in data if row["role"] == "adversarial" and row["condition"] == "C1")["oracle"]["state_violation"] = None
    result = paired_bootstrap(data, "state_violation", replicates=50)
    assert result["slots"] == 8 and result["estimate"] == -1
    assert result["missing_bias_corrected"] is False


def test_empty_endpoint_is_not_estimable_and_unknown_metric_is_rejected():
    assert paired_bootstrap([], "state_violation", replicates=50) is None
    with pytest.raises(KeyError):
        paired_bootstrap(rows(), "new_hypothesis", replicates=50)


def test_intervals_are_reproducible_and_invariant_to_input_order():
    first = paired_bootstrap(rows(), "state_violation", replicates=50, seed=3)
    assert first == paired_bootstrap(list(reversed(rows())), "state_violation", replicates=50, seed=3)


def test_current_report_has_only_descriptive_outputs_and_twelve_pair_fixture():
    data = synthetic_rows(seed=13)
    assert len(data) == 144 and len({row["pair_id"] for row in data}) == 12
    report = descriptive_report(data, seed=13, bootstrap_samples=50,
                                expected_pair_ids=[f"SYNTHETIC-{i}" for i in range(12)])
    assert report["analysis_mode"] == "DESCRIPTIVE"
    assert report["utility_reference_percentage_points"] == 10
    assert not {"fixed_sequence", "h2_power_and_freeze_review_pending", "confirmatory_acceptance_granted"} & report.keys()
    assert all("mcnemar_supplementary" not in value for value in report["endpoints"].values())
    assert report["scheduled_pair_ids_validated"] is True
