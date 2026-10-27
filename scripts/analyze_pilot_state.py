"""Descriptive analysis of the DEC-095 pilot state run (DEC-094: rates and differences).

Reads the run evidence and every slot envelope. Reports per condition: benign task
success in the ERP state (BTSR), attack success in the state (ASR-state),
unauthorized critical actions on A3a (UACR), compromised proposals, dispositions,
model failures, latency and tokens. Paired differences C1 - C0 use a cluster
bootstrap by pair (10,000 replicates, fixed seed), BCa and percentile sensitivity.
Degenerate distributions use the pre-specified conservative DEC-089 bound for
the same contrast. No hypothesis decisions. Nothing is written or modified.
"""

import argparse
from collections import Counter, defaultdict
import json
from pathlib import Path
import statistics
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "gateway/src"))

from tcc_gateway.paired_analysis import cluster_interval


METRIC_ROLES = {"benign_task_success": "benign", "state_violation": "adversarial",
                "unauthorized_critical_action": "adversarial"}


def load(run_dir):
    evidence = json.loads((run_dir / "evidence.json").read_text(encoding="utf-8"))
    rows = []
    for slot in evidence["slots"]:
        directory = run_dir / "artifacts" / f"slot-{slot['position']:03d}"
        envelope = json.loads((directory / "slot.gateway-run.json").read_text(encoding="utf-8"))
        record = envelope["record"]
        stage = record["evidence"]["stage"]
        usage = stage["response"]["metadata"]["usage"] if stage["response"] else {}
        intervals = {item["name"]: (item["ended_ns"] - item["started_ns"]) / 1e9 for item in record["supervision"]["intervals"]}
        rows.append(dict(slot, pair_id=record["identity"]["pair_id"], usage=usage, intervals=intervals))
    return evidence, rows


def rate(values):
    values = [value for value in values if value is not None]
    return (sum(values), len(values))


def paired_bootstrap(rows, metric, *, replicates=10_000, seed=2026102801):
    """DEC-097: paired C1-C0 in the endpoint universe, clustered by pair."""
    role = METRIC_ROLES[metric]
    cells = defaultdict(dict)
    for row in rows:
        if row["role"] != role or (metric == "unauthorized_critical_action" and row["attack_family"] != "A3a"):
            continue
        value = row["oracle"].get(metric)
        if value is not None:
            cells[(row["pair_id"], row["member_key"], row["repetition"])][row["condition"]] = int(value)
    by_pair = defaultdict(list)
    for (pair, _member, _rep), value in cells.items():
        if {"C0", "C1"} <= value.keys():
            by_pair[pair].append(value["C1"] - value["C0"])
    pairs = sorted(by_pair)
    if not pairs:
        return None
    flat = [d for pair in pairs for d in by_pair[pair]]
    estimate = sum(flat) / len(flat)
    interval = cluster_interval([(sum(by_pair[pair]), len(by_pair[pair])) for pair in pairs],
                                seed=seed, bootstrap_samples=replicates)
    percentile = interval["percentile_sensitivity"]
    return {"estimate": estimate, "ci95": interval["ci95"], "method": interval["method"],
            "reason": interval["reason"], "ci95_percentile": percentile,
            "pairs": len(pairs), "slots": len(flat), "seed": seed, "replicates": replicates,
            "degenerate": percentile is not None and percentile[0] == percentile[1],
            "missing_bias_corrected": False}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", type=Path, required=True)
    args = parser.parse_args(argv)
    evidence, rows = load(args.run_dir)
    print(f"run={args.run_dir.name} status={evidence.get('status')} slots={len(rows)} provider={evidence['provider_mode']}"
          f" cleanup={evidence.get('cleanup_verified')} secret={evidence.get('secret_found_in_logs_or_outputs')}")
    print("stage reasons:", dict(Counter(row["stage_reason"] for row in rows)))
    print("\n== Por condição ==")
    for condition in ("C0", "C1"):
        subset = [row for row in rows if row["condition"] == condition]
        benign = [row for row in subset if row["role"] == "benign"]
        adversarial = [row for row in subset if row["role"] == "adversarial"]
        a3a = [row for row in adversarial if row["attack_family"] == "A3a"]
        btsr, asr = rate(row["oracle"]["benign_task_success"] for row in benign), rate(row["oracle"]["state_violation"] for row in adversarial)
        prop = rate(row["oracle"]["proposal_compromised"] for row in adversarial)
        uacr = rate(row["oracle"]["unauthorized_critical_action"] for row in a3a)
        uua = rate(row["oracle"]["utility_under_attack"] for row in adversarial)
        print(f"{condition}: BTSR {btsr[0]}/{btsr[1]} | ASR-state {asr[0]}/{asr[1]} | proposta comprometida {prop[0]}/{prop[1]}"
              f" | UACR(A3a) {uacr[0]}/{uacr[1]} | utilidade sob ataque {uua[0]}/{uua[1]}")
        print("   disposições:", dict(Counter(str(row["disposition"]) for row in subset)))
    print("\n== Por família (adversariais, C0 / C1) ==")
    for family in ("A1", "A2", "A3a"):
        values = []
        for condition in ("C0", "C1"):
            subset = [row for row in rows if row["role"] == "adversarial" and row["attack_family"] == family
                      and row["condition"] == condition]
            violation = rate(row["oracle"]["state_violation"] for row in subset)
            values.append(f"{violation[0]}/{violation[1]}")
        print(f"{family}: ASR-state C0 {values[0]} | C1 {values[1]}")
    print("\n== Diferenças pareadas C1 - C0 (BCa por par; fronteira conservadora DEC-089) ==")
    for metric in METRIC_ROLES:
        print(metric, json.dumps(paired_bootstrap(rows, metric)))
    print("\n== Latência por etapa (s): mediana / p95 ==")
    for name in ("llm", "observation", "policy", "execution", "capture", "reset"):
        values = sorted(row["intervals"][name] for row in rows if name in row["intervals"])
        if values:
            print(f"{name}: {statistics.median(values):.1f} / {values[int(0.95 * (len(values) - 1))]:.1f} (n={len(values)})")
    for condition in ("C0", "C1"):
        totals = [sum(v for k, v in row["intervals"].items() if k not in {"capture", "reset"})
                  for row in rows if row["condition"] == condition]
        print(f"{condition} ponta a ponta sem captura/reset: mediana {statistics.median(totals):.1f} s")
    tokens = Counter()
    for row in rows:
        tokens.update({key: value for key, value in row["usage"].items() if isinstance(value, int)})
    print("\ntokens:", dict(tokens))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
