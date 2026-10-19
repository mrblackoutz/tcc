"""DEC-065 read-only fixture preparation using the existing trusted resolver.

This is an evaluator handoff, not execution authority. Workflows, operational
observations and the logical fixture reference must come from an independent
trusted configuration. Their types and hashes do not authenticate that source.
No proposal, payload, condition or approval is accepted or produced here.
"""

from __future__ import annotations

from decimal import Context, Decimal, localcontext

from .dataset_oracle import OracleFixtureBinding, ResolvedOracleLine
from .dataset_pair import DatasetPair, parse_dataset_pair
from .policy_contracts import DependencyStatus, TrustedPolicyState
from .state import canonical_json_sha256
from .trusted_resolution import (
    ReadOnlyOdooCaller, ResolvedPurchaseLine, ResolvedTrustedState,
    TrustedOperationalStatus, TrustedWorkflow, read_trusted_state,
)


class DatasetFixtureError(ValueError):
    """Finite preparation failure without fixture records or transport details."""


def _require(condition: bool) -> None:
    if not condition:
        raise DatasetFixtureError("invalid oracle fixture preparation")


def _identity(value: object) -> None:
    _require(type(value) is int and value > 0)


def resolve_oracle_fixture(
    client: ReadOnlyOdooCaller, pair: DatasetPair, workflow: TrustedWorkflow,
    operational: TrustedOperationalStatus, *, fixture_ref: str, policy_version: str,
) -> OracleFixtureBinding:
    """Compare independent pair truth with fresh read-only ERP resolution.

    A member is located only by trusted scenario/document provenance. Its label
    never selects queries, facts or authority. Both members therefore resolve
    the same business fixture, while remaining distinct workflow identities.
    This does not verify adversarial alternative fixtures, CREATE-origin audit
    evidence, authorization, custody, human review or scientific readiness.
    """
    try:
        _require(type(pair) is DatasetPair and type(workflow) is TrustedWorkflow
                 and type(operational) is TrustedOperationalStatus)
        value = parse_dataset_pair(pair.to_mapping()).to_mapping()
        truth = value["truth"]
        _require(type(fixture_ref) is str and fixture_ref == value["fixture_ref"])
        _require(type(policy_version) is str)
        workflow = TrustedWorkflow(**{
            name: getattr(workflow, name) for name in workflow.__dataclass_fields__
        })
        _require(type(operational.dependencies) is DependencyStatus)
        _require(all(type(status) is str and status == "AVAILABLE"
                     for status in operational.dependencies.to_mapping().values()))
        _require(operational.duplicate_detected is False
                 and operational.accounting_period_open is True)
        members = [member for member in value["members"].values() if (
            member["scenario_id"], member["document_sha256"]
        ) == (workflow.scenario_id, workflow.document_sha256)]
        _require(len(members) == 1)
        is_post = truth["expected_action"] == "POST_VENDOR_BILL"
        _require(workflow.phase == ("POST_REVIEW" if is_post else "DRAFT_INTAKE"))
        _require(workflow.company_ref == truth["company_ref"]
                 and workflow.purchase_order_ref == truth["purchase_order_ref"]
                 and workflow.quantity_scale == truth["quantity_scale"])
        _require(workflow.invoice_date_min <= truth["invoice_date"] <= workflow.invoice_date_max)
        _require(workflow.target_document_ref == (truth["document_ref"] if is_post else None))
        _require(truth["approved_bank_ref"] in workflow.allowed_bank_refs)

        resolved = read_trusted_state(client, workflow, operational, policy_version=policy_version)
        _require(type(resolved) is ResolvedTrustedState and type(resolved.state) is TrustedPolicyState)
        state = TrustedPolicyState.from_mapping(resolved.state.to_mapping())
        for identity in (resolved.company_id, resolved.vendor_id, resolved.purchase_order_id):
            _identity(identity)
        _require((state.company_ref, state.scenario_id, state.document_sha256,
                  state.phase, state.quantity_scale) == (
            workflow.company_ref, workflow.scenario_id, workflow.document_sha256,
            workflow.phase, workflow.quantity_scale,
        ))
        _require(state.duplicate_detected is False and state.accounting_period_open is True)
        _require(state.dependencies == operational.dependencies)
        _require((state.invoice_date_min, state.invoice_date_max, state.monetary_tolerance) == (
            workflow.invoice_date_min, workflow.invoice_date_max, workflow.monetary_tolerance,
        ))
        po = state.purchase_order
        _require(po.confirmed is True)
        _require((po.purchase_order_ref, po.vendor_ref, po.currency, po.amount) == (
            truth["purchase_order_ref"], truth["vendor_ref"], truth["currency"], truth["amount"],
        ))
        expected = {line["item_code"]: line for line in truth["lines"]}
        actual = {line.item_code: line for line in po.lines}
        _require(set(actual) == set(expected))
        _require(type(resolved.lines) is tuple and len(resolved.lines) == len(expected))
        _require(all(type(line) is ResolvedPurchaseLine for line in resolved.lines))
        _require(tuple(line.item_code for line in resolved.lines)
                 == tuple(line.item_code for line in po.lines))
        for line in resolved.lines:
            for identity in (line.purchase_line_id, line.product_id, line.uom_id):
                _identity(identity)
        with localcontext(Context(prec=64)):
            for code, expected_line in expected.items():
                observed_line = actual[code]
                _require((observed_line.quantity, observed_line.unit_price) == (
                    expected_line["quantity"], expected_line["unit_price"],
                ))
                if not is_post:
                    _require(Decimal(observed_line.quantity_to_invoice)
                             >= Decimal(expected_line["quantity"]))

        _require(type(resolved.bank_ids) is tuple)
        bank_refs, bank_ids = [], []
        for entry in resolved.bank_ids:
            _require(type(entry) is tuple and len(entry) == 2)
            ref, identity = entry
            _require(type(ref) is str and ref in workflow.allowed_bank_refs)
            _identity(identity)
            bank_refs.append(ref)
            bank_ids.append(identity)
        _require(tuple(bank_refs) == tuple(sorted(set(bank_refs)))
                 and len(set(bank_ids)) == len(bank_ids))
        _require(tuple(bank_refs) == state.allowed_bank_refs
                 and truth["approved_bank_ref"] in bank_refs)

        target = state.target_bill
        if is_post:
            _require(target is not None and target.state == "draft")
            action = target.action
            _require((action.policy_version, action.action, action.executor_mode,
                      action.scenario_id, action.document_sha256) == (
                policy_version, "POST_VENDOR_BILL", "POST_APPROVED",
                workflow.scenario_id, workflow.document_sha256,
            ))
            _require((action.vendor_ref, action.purchase_order_ref, action.document_ref,
                      action.invoice_date, action.currency, action.amount, action.recipient_bank_ref) == (
                truth["vendor_ref"], truth["purchase_order_ref"], truth["document_ref"],
                truth["invoice_date"], truth["currency"], truth["amount"], truth["approved_bank_ref"],
            ))
            target_lines = {line.item_code: line for line in action.lines}
            _require(set(target_lines) == set(expected))
            for code, expected_line in expected.items():
                _require((target_lines[code].quantity, target_lines[code].unit_price) == (
                    expected_line["quantity"], expected_line["unit_price"],
                ))
        else:
            _require(target is None)
        return OracleFixtureBinding(
            pair_sha256=canonical_json_sha256(value), fixture_ref=fixture_ref,
            company_ref=truth["company_ref"], company_name=workflow.company_name,
            vendor_ref=po.vendor_ref, purchase_order_ref=po.purchase_order_ref,
            document_ref=truth["document_ref"],
            lines=tuple(ResolvedOracleLine(
                line.item_code, line.purchase_line_id, line.product_id,
            ) for line in resolved.lines),
            target_move_id=target.move_id if target is not None else None,
        )
    except Exception:
        # Resolver/transport callers can carry raw records or endpoint details.
        # No partial binding or favorable fallback is returned on any failure.
        raise DatasetFixtureError("invalid oracle fixture preparation") from None
