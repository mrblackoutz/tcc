"""DEC-089 statistical dry-run using generated aggregate rows only.

No provider, ERP, pilot or final dataset is read. The JSON is an implementation
validation artifact, not experimental results or a scientific acceptance.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import random
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "gateway/src"))
from tcc_gateway.paired_analysis import ENDPOINTS, analyze_endpoint, validate_rows


def descriptive_report(rows, *, seed, bootstrap_samples=10_000, expected_pair_ids=None):
    """DEC-094/097: estimates and intervals, without hypothesis decisions."""
    rows = validate_rows(rows, expected_pair_ids=expected_pair_ids)
    endpoints = {}
    for name in ENDPOINTS:
        result = analyze_endpoint(rows, name, seed=seed, bootstrap_samples=bootstrap_samples,
                                  expected_pair_ids=expected_pair_ids)
        # The pinned mathematical component retains its former API while a run
        # uses that source bundle. It does not define this descriptive report.
        endpoints[name] = {key: value for key, value in result.items() if key != "mcnemar_supplementary"}
    return {"schema_version": "descriptive-paired-analysis/v1", "analysis_mode": "DESCRIPTIVE",
            "seed": seed, "bootstrap_samples": bootstrap_samples,
            "scheduled_pair_ids_validated": expected_pair_ids is not None,
            "endpoints": endpoints, "utility_reference_percentage_points": 10,
            "interval_target": "paired_run_contrast_conditional_on_observed_completeness",
            "missing_bias_corrected": False, "scientific_run": False}


def synthetic_rows(*, seed, pairs=12):
    rng = random.Random(seed)
    rows = []
    for pair in range(pairs):
        critical = pair % 3 == 0
        for role in ("benign", "adversarial"):
            latent = rng.random()
            for condition in ("C0", "C1"):
                for repetition in (1, 2, 3):
                    adversarial = role == "adversarial"
                    eligible = {e: adversarial for e in ENDPOINTS[:4]}
                    eligible.update(benign_success=not adversarial, critical=critical)
                    metric = dict.fromkeys(ENDPOINTS)
                    if adversarial:
                        event = latent < (.65 if condition == "C0" else .12)
                        metric.update(delivery=True, proposal=True, policy=True, state=event)
                    else:
                        metric["benign_success"] = latent > (.04 if condition == "C0" else .07)
                    if critical:
                        metric["critical"] = metric["state"] if adversarial else False
                    row = {"run_id": f"SYNTHETIC-{pair}.{role}.{condition}.r{repetition}",
                        "pair_id": f"SYNTHETIC-{pair}", "scenario_class": role, "condition": condition,
                        "repetition": repetition, "status": "EVALUABLE", "missing_reason": None,
                        "deny_class": None, "retries": 0, "eligible": eligible, "metrics": metric}
                    if pair % 11 == 0 and condition == "C1" and repetition == 1:
                        row.update(status="MISSING", missing_reason="FINAL_STATE_UNAVAILABLE")
                        row["metrics"] = dict.fromkeys(ENDPOINTS)
                    rows.append(row)
    return rows


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seed", type=int, default=20261026)
    parser.add_argument("--out", type=Path, required=True, help="new JSON path under .runtime")
    parser.add_argument("--bootstrap-samples", type=int, default=10_000)
    args = parser.parse_args(argv)
    target = args.out.resolve()
    if ROOT / ".runtime" not in target.parents or target.exists():
        raise SystemExit("output must be a new file under .runtime")
    rows = synthetic_rows(seed=args.seed)
    expected = [f"SYNTHETIC-{i}" for i in range(12)]
    report = descriptive_report(rows, seed=args.seed, bootstrap_samples=args.bootstrap_samples,
                                expected_pair_ids=expected)
    report.update(synthetic_fixture=True, input_row_count=len(rows),
                  source="generated_independently_no_dataset_read")
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("x", encoding="utf8", newline="\n") as stream:
        json.dump(report, stream, sort_keys=True, indent=2, allow_nan=False)
        stream.write("\n")
    print(json.dumps({"status": "PASS", "synthetic_fixture": True, "input_rows": len(rows),
        "bootstrap_samples": args.bootstrap_samples, "scientific_run": False}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
