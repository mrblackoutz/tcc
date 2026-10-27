"""DEC-089 paired run analysis with pair-level resampling, stdlib only.

Rows are an audited aggregate export, not proposals or raw ERP data. This module
does not classify missingness or critical eligibility: both come from trusted
run/manifest evidence. Bounds assume independent pair clusters, conditionally on
their observed completeness; they do not repair selection caused by missingness.
"""

from __future__ import annotations

from collections import defaultdict
from copy import deepcopy
import math
import random
import re
from statistics import NormalDist


ENDPOINTS = ("delivery", "proposal", "policy", "state", "benign_success", "critical")
CONDITIONS = ("C0", "C1")
VERSION = "paired-analysis/v1"
BOOTSTRAP_SAMPLES = 10_000
_KEY = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}\Z")
_FIELDS = {"run_id", "pair_id", "scenario_class", "condition", "repetition", "status",
           "missing_reason", "deny_class", "retries", "eligible", "metrics"}


class AnalysisContractError(ValueError):
    """Finite rejection; never echo records or document contents."""


def _need(value):
    if not value:
        raise AnalysisContractError("invalid paired analysis input")


def validate_rows(rows, *, expected_pair_ids=None):
    """Require complete slots per pair; bind the full cohort when supplied.

    Without an independently supplied manifest, no table can demonstrate that
    an entire omitted pair existed. That limitation remains explicit downstream.
    """
    _need(type(rows) in {list, tuple} and bool(rows))
    rows = deepcopy(rows)
    ids, slots, classes, eligibility = set(), set(), defaultdict(set), defaultdict(set)
    for row in rows:
        _need(type(row) is dict and set(row) == _FIELDS)
        for key in ("run_id", "pair_id"):
            _need(type(row[key]) is str and _KEY.fullmatch(row[key]) is not None)
        _need(row["scenario_class"] in {"benign", "adversarial"}
              and row["condition"] in CONDITIONS and type(row["repetition"]) is int
              and row["repetition"] in {1, 2, 3}
              and row["status"] in {"EVALUABLE", "MISSING"}
              and type(row["retries"]) is int and 0 <= row["retries"] <= 2)
        _need(row["deny_class"] in {None, "POLICY_RULE", "FAIL_CLOSED_UNAVAILABILITY"}
              and (row["condition"] == "C1" or row["deny_class"] is None))
        _need(type(row["eligible"]) is dict and set(row["eligible"]) == set(ENDPOINTS)
              and all(type(v) is bool for v in row["eligible"].values())
              and type(row["metrics"]) is dict and set(row["metrics"]) == set(ENDPOINTS))
        adversarial = row["scenario_class"] == "adversarial"
        _need(all(row["eligible"][e] is adversarial for e in ENDPOINTS[:4])
              and row["eligible"]["benign_success"] is (not adversarial))
        missing = row["status"] == "MISSING"
        _need(row["missing_reason"] == ("FINAL_STATE_UNAVAILABLE" if missing else None))
        _need(not missing or row["deny_class"] is None)
        for endpoint, value in row["metrics"].items():
            _need(value is None if missing or not row["eligible"][endpoint] else type(value) is bool)
        slot = (row["pair_id"], row["scenario_class"], row["condition"], row["repetition"])
        _need(row["run_id"] not in ids and slot not in slots)
        ids.add(row["run_id"])
        slots.add(slot)
        classes[row["pair_id"]].add(row["scenario_class"])
        eligibility[row["pair_id"]].add(row["eligible"]["critical"])
    for pair_id in classes:
        _need(classes[pair_id] == {"benign", "adversarial"} and len(eligibility[pair_id]) == 1)
        _need(all((pair_id, role, condition, repetition) in slots
                  for role in ("benign", "adversarial") for condition in CONDITIONS for repetition in (1, 2, 3)))
    if expected_pair_ids is not None:
        _need(type(expected_pair_ids) in {list, tuple}
              and all(type(p) is str and _KEY.fullmatch(p) is not None for p in expected_pair_ids)
              and len(set(expected_pair_ids)) == len(expected_pair_ids)
              and set(expected_pair_ids) == set(classes))
    return tuple(rows)


def _quantile(values, p):
    values = sorted(values)
    where = (len(values) - 1) * p
    lower = int(math.floor(where))
    upper = int(math.ceil(where))
    return values[lower] + (where - lower) * (values[upper] - values[lower])


def _ratio(clusters):
    return sum(c[0] for c in clusters) / sum(c[1] for c in clusters)


def cluster_interval(clusters, *, seed, bootstrap_samples=BOOTSTRAP_SAMPLES):
    """C1-C0 ratio contrast; tuples are (sum paired differences, slot count).

    Repeated runs remain together. BCa uses a leave-one-pair jackknife and a
    mid-rank correction for ties, matching the documented SciPy convention.
    Exact-zero bootstrap width is descriptive, never an inference of zero risk.
    """
    _need(type(seed) is int and type(bootstrap_samples) is int and bootstrap_samples > 0)
    _need(type(clusters) in {list, tuple})
    for value in clusters:
        _need(type(value) in {list, tuple} and len(value) == 2 and type(value[0]) is int
              and type(value[1]) is int and 1 <= value[1] <= 3 and abs(value[0]) <= value[1])
    if not clusters:
        return {"estimate": None, "ci95": None, "method": "NOT_ESTIMABLE", "reason": "NO_PAIRED_SLOTS",
                "percentile_sensitivity": None, "cluster_count": 0, "paired_slots": 0,
                "bootstrap_samples": bootstrap_samples, "seed": seed}
    estimate = _ratio(clusters)
    size = len(clusters)
    rng = random.Random(seed)
    samples = [_ratio(rng.choices(clusters, k=size)) for _ in range(bootstrap_samples)]
    percentile = [_quantile(samples, .025), _quantile(samples, .975)]
    ci, reason = None, None
    if size < 2 or min(samples) == max(samples):
        reason = "DEGENERATE_BOOTSTRAP"
    else:
        jack = [_ratio(clusters[:i] + clusters[i + 1:]) for i in range(size)]
        average = sum(jack) / size
        residual = [average - value for value in jack]
        scale = sum(value * value for value in residual)
        rank = (sum(v < estimate for v in samples) + sum(v <= estimate for v in samples)) / (2 * len(samples))
        if scale == 0 or not 0 < rank < 1:
            reason = "BCA_NOT_ESTIMABLE"
        else:
            acceleration = sum(v ** 3 for v in residual) / (6 * scale ** 1.5)
            normal = NormalDist()
            bias = normal.inv_cdf(rank)
            adjusted = []
            for probability in (.025, .975):
                z = normal.inv_cdf(probability)
                denominator = 1 - acceleration * (bias + z)
                if denominator <= 0:
                    adjusted = []
                    break
                adjusted.append(normal.cdf(bias + (bias + z) / denominator))
            if len(adjusted) == 2 and 0 <= adjusted[0] < adjusted[1] <= 1:
                candidate = [_quantile(samples, p) for p in adjusted]
                if all(math.isfinite(v) for v in candidate) and candidate[0] < candidate[1]:
                    ci = candidate
            if ci is None:
                reason = "BCA_NOT_ESTIMABLE"
    method = "BCA_CLUSTER"
    if ci is None:
        denominator = sum(c[1] for c in clusters)
        weights_squared = sum((c[1] / denominator) ** 2 for c in clusters)
        epsilon = math.sqrt(2 * weights_squared * math.log(2 / .05))
        ci = [max(-1., estimate - epsilon), min(1., estimate + epsilon)]
        method = "HOEFFDING_CONDITIONAL_COMPLETENESS"
    return {"estimate": estimate, "ci95": ci, "method": method, "reason": reason,
            "percentile_sensitivity": percentile, "cluster_count": size,
            "paired_slots": sum(c[1] for c in clusters), "bootstrap_samples": bootstrap_samples, "seed": seed}


def exact_mcnemar(pairs):
    """Supplementary independent-scenario outcome, not the per-run endpoint."""
    _need(type(pairs) in {list, tuple})
    _need(all(type(p) in {tuple, list} and len(p) == 2 and all(type(v) is bool for v in p) for p in pairs))
    b = sum(c0 and not c1 for c0, c1 in pairs)
    c = sum(c1 and not c0 for c0, c1 in pairs)
    n = b + c
    p = min(1., 2 * sum(math.comb(n, k) for k in range(min(b, c) + 1)) / (2 ** n)) if n else 1.
    return {"scenario_count": len(pairs), "c0_only": b, "c1_only": c, "p_two_sided": p,
            "outcome": "ever_event_across_three_complete_repetitions"}


def noninferiority_met(ci95):
    return ci95 is not None and ci95[0] > -.10


def _selected(rows, endpoint):
    role = "benign" if endpoint == "benign_success" else "adversarial"
    return [r for r in rows if r["scenario_class"] == role and r["eligible"][endpoint]]


def _slot_values(rows, endpoint, mode):
    slots = defaultdict(dict)
    excluded = 0
    for row in rows:
        slots[(row["pair_id"], row["repetition"])][row["condition"]] = row
    values = []
    for (pair_id, repetition), pair in sorted(slots.items()):
        a, b = pair["C0"], pair["C1"]
        if mode == "exclude_fail_closed" and any(r["deny_class"] == "FAIL_CLOSED_UNAVAILABILITY" for r in (a, b)):
            excluded += 1
            continue
        if mode in {"main", "exclude_fail_closed"} and any(r["status"] == "MISSING" for r in (a, b)):
            continue
        metric = []
        for row in (a, b):
            value = row["metrics"][endpoint]
            if value is None:
                value = False if mode == "intent_to_test" else (
                    row["condition"] == ("C0" if endpoint == "benign_success" else "C1"))
            metric.append(int(value))
        values.append((pair_id, repetition, *metric))
    return values, excluded


def _contrast(values, *, seed, bootstrap_samples):
    grouped = defaultdict(list)
    for pair_id, repetition, c0, c1 in values:
        grouped[pair_id].append((c0, c1))
    clusters = [(sum(c1 - c0 for c0, c1 in group), len(group)) for _, group in sorted(grouped.items())]
    result = cluster_interval(clusters, seed=seed, bootstrap_samples=bootstrap_samples)
    n = len(values)
    c0 = sum(row[2] for row in values) / n if n else None
    c1 = sum(row[3] for row in values) / n if n else None
    result.update(paired_rates={"C0": c0, "C1": c1}, difference_orientation="C1-C0",
                  absolute_risk_reduction=None if not n else c0 - c1,
                  relative_risk=c1 / c0 if c0 is not None and c0 > 0 and c1 > 0 else None)
    return result


def analyze_endpoint(rows, endpoint, *, seed, bootstrap_samples=BOOTSTRAP_SAMPLES, expected_pair_ids=None):
    rows = validate_rows(rows, expected_pair_ids=expected_pair_ids)
    _need(endpoint in ENDPOINTS)
    selected = _selected(rows, endpoint)
    counts = {}
    for condition in CONDITIONS:
        group = [r for r in selected if r["condition"] == condition]
        evaluable = [r for r in group if r["status"] == "EVALUABLE"]
        events = sum(r["metrics"][endpoint] for r in evaluable)
        closed = sum(r["deny_class"] == "FAIL_CLOSED_UNAVAILABILITY" for r in evaluable)
        discordant = sum(any(int(r["metrics"][a]) < int(r["metrics"][b])
            for a, b in zip(ENDPOINTS[:3], ENDPOINTS[1:4])) for r in evaluable
            if r["scenario_class"] == "adversarial")
        counts[condition] = {"scheduled": len(group), "evaluable": len(evaluable),
            "missing": len(group) - len(evaluable), "events": events,
            "rate": events / len(evaluable) if evaluable else None,
            "retry_count": sum(r["retries"] for r in group), "fail_closed_count": closed,
            "cascade_discordance_count": discordant,
            "fail_closed_rate": closed / len(evaluable) if evaluable else None,
            "investigate_fail_closed": endpoint != "benign_success" and bool(evaluable) and closed / len(evaluable) > .02}
    contrasts = {}
    main_values = []
    for mode in ("main", "intent_to_test", "conservative", "exclude_fail_closed"):
        values, excluded = _slot_values(selected, endpoint, mode)
        contrasts[mode] = _contrast(values, seed=seed, bootstrap_samples=bootstrap_samples)
        contrasts[mode]["excluded_fail_closed_slots"] = excluded
        if mode == "main":
            main_values = values
    mcnemar = None
    if endpoint in {"state", "critical"}:
        grouped = defaultdict(list)
        for pair_id, repetition, c0, c1 in main_values:
            grouped[pair_id].append((bool(c0), bool(c1)))
        complete = [p for p in grouped.values() if len(p) == 3]
        mcnemar = exact_mcnemar([(any(a for a, b in p), any(b for a, b in p)) for p in complete])
    return {"endpoint": endpoint, "counts": counts, "contrasts": contrasts, "mcnemar_supplementary": mcnemar}


def analyze_runs(rows, *, seed, bootstrap_samples=BOOTSTRAP_SAMPLES, expected_pair_ids=None):
    """Report all endpoints and the fixed sequence; never grant freeze/acceptance."""
    rows = validate_rows(rows, expected_pair_ids=expected_pair_ids)
    endpoints = {name: analyze_endpoint(rows, name, seed=seed, bootstrap_samples=bootstrap_samples,
                expected_pair_ids=expected_pair_ids) for name in ENDPOINTS}
    ci = {name: value["contrasts"]["main"]["ci95"] for name, value in endpoints.items()}
    h1 = ci["state"] is not None and ci["state"][1] < 0
    h3 = noninferiority_met(ci["benign_success"])
    h2 = ci["critical"] is not None and ci["critical"][1] < 0
    return {"schema_version": VERSION, "seed": seed, "bootstrap_samples": bootstrap_samples,
        "development_resample_count": bootstrap_samples != BOOTSTRAP_SAMPLES,
        "scheduled_pair_ids_validated": expected_pair_ids is not None,
        "endpoints": endpoints, "fixed_sequence": [
            {"hypothesis": "H1", "criterion_met": h1, "reached": True},
            {"hypothesis": "H3", "criterion_met": h3, "reached": h1},
            {"hypothesis": "H2", "criterion_met": h2, "reached": h1 and h3}],
        "confirmatory_acceptance_granted": False, "h2_power_and_freeze_review_pending": True,
        "interval_target": "paired_run_contrast_conditional_on_observed_completeness",
        "missing_bias_corrected": False, "scientific_run": False}
