"""Revisão adversarial por agente distinto (DEC-081): oráculo da especificação x motor.

Invariante: ALLOW/REVIEW só ocorre se a entrada satisfaz a especificação escrita
de forma independente do motor; e a especificação satisfeita não é negada.
Entrada que não valida o contrato é rejeitada (falha fechada), nunca aceita.
"""

from __future__ import annotations

import random
from copy import deepcopy
from decimal import Decimal

import pytest

from tcc_gateway.policy_contracts import PolicyContractError, PolicyInput
from tcc_gateway.policy_engine import evaluate_policy

from test_policy_engine import input_mapping


def _spec_ok(m: dict) -> bool:
    a, s = m["action"], m["trusted_state"]
    po = s["purchase_order"]
    if any(v != "AVAILABLE" for v in s["dependencies"].values()):
        return False
    pair = (a["action"], a["executor_mode"])
    if pair not in {("CREATE_DRAFT_BILL", "CREATE_DRAFT"), ("POST_VENDOR_BILL", "POST_APPROVED")}:
        return False
    post = pair[0] == "POST_VENDOR_BILL"
    if s["phase"] != ("POST_REVIEW" if post else "DRAFT_INTAKE"):
        return False
    target = s["target_bill"]
    if post:
        if target is None or target["state"] != "draft" or target["move_id"] != a.get("target_move_id") or target["action"] != a:
            return False
    elif target is not None:
        return False
    if not po["confirmed"] or a["vendor_ref"] != po["vendor_ref"]:
        return False
    if a["purchase_order_ref"] != po["purchase_order_ref"] or a["currency"] != po["currency"]:
        return False
    key = lambda line: (line["item_code"], line["quantity"], line["unit_price"])
    if [key(x) for x in a["lines"]] != [key(x) for x in po["lines"]]:
        return False
    if not post and any(
        Decimal(x["quantity"]) > Decimal(p["quantity_to_invoice"]) for x, p in zip(a["lines"], po["lines"])
    ):
        return False
    if abs(Decimal(a["amount"]) - Decimal(po["amount"])) > Decimal(s["monetary_tolerance"]):
        return False
    if a["recipient_bank_ref"] not in s["allowed_bank_refs"] or s["duplicate_detected"]:
        return False
    if not (s["invoice_date_min"] <= a["invoice_date"] <= s["invoice_date_max"]) or not s["accounting_period_open"]:
        return False
    return bool(s["accounting_period_open"])


def _leaves(node, path=()):
    if isinstance(node, dict):
        for k, v in node.items():
            yield from _leaves(v, path + (k,))
    elif isinstance(node, list):
        for i, v in enumerate(node):
            yield from _leaves(v, path + (i,))
    else:
        yield path, node


def _get(root, path):
    for p in path:
        root = root[p]
    return root


def _set(root, path, value):
    _get(root, path[:-1])[path[-1]] = value


def _variants(v):
    if isinstance(v, bool):
        return [not v, None, "true", 1]
    if isinstance(v, int):
        return [v + 1, v - 1, 0, True, str(v), None]
    if isinstance(v, str):
        return [
            "", v + " ", " " + v, v + "​", v.lower(), v.upper(), v[:-1],
            v.replace("-", "‐"), v.replace("0", "O"), "TCC-VENDOR-002", "TCC-BANK-002",
            "TCC-PO-002", "USD", "POST_VENDOR_BILL", "CREATE_DRAFT_BILL", "CREATE_DRAFT",
            "POST_APPROVED", "DRAFT_INTAKE", "POST_REVIEW", "AVAILABLE", "UNAVAILABLE", "draft",
            "posted", "0.00", "0.01", "999999.99", "125.49", "125.51", "2026-08-31", "2026-11-01",
            "2026-09-31", None,
        ]
    return [None]


def _decide(mapping: dict) -> str:
    try:
        policy_input = PolicyInput.from_mapping(mapping)
        decision = evaluate_policy(policy_input)
    except PolicyContractError:
        return "REJECT"
    decision.validate_binding(policy_input)
    return decision.decision


@pytest.mark.parametrize("post", [False, True])
def test_engine_matches_independent_spec_under_hostile_mutations(post: bool) -> None:
    base = input_mapping(post)
    assert _spec_ok(base)
    paths = [p for p, _ in _leaves(base)]
    combos = [((p, v),) for p in paths for v in _variants(_get(base, p))]
    rnd = random.Random(20261026)
    for _ in range(600):
        combos.append(tuple((p, rnd.choice(_variants(_get(base, p)))) for p in rnd.sample(paths, 2)))

    unsafe, false_deny = [], []
    for combo in combos:
        mapping = deepcopy(base)
        for path, value in combo:
            _set(mapping, path, value)
            if post and path[0] == "action":  # alvo confiável acompanha a ação alterada
                try:
                    _set(mapping["trusted_state"]["target_bill"]["action"], path[1:], value)
                except (KeyError, IndexError, TypeError):
                    pass
        outcome = _decide(mapping)
        if outcome in {"ALLOW", "REVIEW"} and not _spec_ok(mapping):
            unsafe.append(combo)
        elif outcome == "DENY" and _spec_ok(mapping):
            false_deny.append(combo)
    assert not unsafe, unsafe[:3]
    assert not false_deny, false_deny[:3]
