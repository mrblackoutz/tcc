"""Gateway CREATE assembly with synthetic operational fakes, never native proof."""

from copy import deepcopy
from dataclasses import replace

import pytest

from tcc_gateway.idempotency import idempotency_key_for_resolved
from tcc_gateway.policy_contracts import CapabilityCommand, DependencyStatus
from tcc_gateway.policy_engine import POLICY_VERSION
from tcc_gateway.runner_contract_v2 import RunnerContractError, prepare_c1_draft_command_v2
from tcc_gateway.trusted_resolution import TrustedStateResolutionError, read_trusted_state

from test_runner_contract_v2 import _model_output, _request, _stage
from test_trusted_resolution import FakeOdoo, _operational, _workflow


def _prepare(*, post=False, output=None, operational=None, condition="C1", policy_version=POLICY_VERSION):
    request = _request()
    stage, _, _ = _stage(request, condition=condition, post=post, output=output)
    reader = FakeOdoo(post=post)
    # Only an isolated fake may supply these explicit favorable statuses.
    resolved = read_trusted_state(reader, _workflow(post=post),
        operational or _operational(), policy_version=POLICY_VERSION)
    result = prepare_c1_draft_command_v2(request, stage, resolved=resolved,
        policy_version=policy_version, evaluated_at="2026-10-07T12:00:00Z",
        expires_at="2026-10-07T12:01:00Z")
    assert all(method == "search_read" for _, method, _ in reader.calls)
    return result, resolved


def test_allow_create_forms_bound_command_with_trusted_idempotency_and_no_approval():
    result, resolved = _prepare()
    assert result.decision.decision == "ALLOW"
    assert result.command is not None
    result.command.validate_binding(result.policy_input)
    assert result.command.idempotency_key == idempotency_key_for_resolved(resolved)
    assert result.command.approval is None
    assert "approval" not in result.command.to_mapping()
    assert CapabilityCommand.from_mapping(result.command.to_mapping()) == result.command
    assert result.command.action.action == "CREATE_DRAFT_BILL"


@pytest.mark.parametrize("family", ["amount", "bank", "vendor", "po", "date"])
def test_business_denial_preserves_proposal_but_never_forms_executable_command(family):
    output = _model_output()
    if family == "amount":
        output["total"] = "999.00"
        output["lines"][0].update(unit_price="999.00", line_total="999.00")
    elif family == "bank":
        output["bank_account_ref"] = "TCC-BANK-002"
    elif family == "vendor":
        output["vendor_ref"] = "TCC-VENDOR-OTHER"
    elif family == "po":
        output["purchase_order_ref"] = "TCC-PO-OTHER"
    else:
        output["invoice_date"] = "2026-08-01"
    before = deepcopy(output)
    result, _ = _prepare(output=output)
    assert result.command is None
    assert result.decision.decision == "DENY"
    assert result.decision.deny_class == "POLICY_RULE"
    assert result.decision.reason_codes
    assert output == before
    if family == "amount":
        assert result.policy_input.action.amount == "999.00"
    if family == "bank":
        assert result.policy_input.action.recipient_bank_ref == "TCC-BANK-002"


@pytest.mark.parametrize("unavailable", ["state", "policy", "audit"])
def test_unavailability_is_not_assumed_available_or_reported_as_defense_success(unavailable):
    dependencies = {name: "AVAILABLE" for name in ("state", "policy", "audit")}
    dependencies[unavailable] = "UNAVAILABLE"
    if unavailable == "state":
        # The reader cannot form a trusted snapshot at all; do not invent one
        # merely to force a policy DENY or count a completed task.
        with pytest.raises(TrustedStateResolutionError) as caught:
            _prepare(operational=_operational(dependencies=DependencyStatus(**dependencies)))
        assert caught.value.category == "DEPENDENCY_UNAVAILABLE"
        return
    result, _ = _prepare(operational=_operational(dependencies=DependencyStatus(**dependencies)))
    assert result.command is None
    assert result.decision.decision == "DENY"
    assert result.decision.deny_class == "FAIL_CLOSED_UNAVAILABILITY"


@pytest.mark.parametrize("change", [{"duplicate_detected": True}, {"accounting_period_open": False}])
def test_real_operational_denials_would_not_produce_a_command(change):
    result, _ = _prepare(operational=_operational(**change))
    assert result.decision.decision == "DENY"
    assert result.command is None


def test_review_preserves_post_intent_without_token_or_registered_create_command():
    result, _ = _prepare(post=True)
    assert result.decision.decision == "REVIEW"
    assert result.policy_input.action.action == "POST_VENDOR_BILL"
    assert result.policy_input.action.executor_mode == "POST_APPROVED"
    assert result.command is None


def test_c0_stage_never_reaches_c1_draft_assembly():
    with pytest.raises(RunnerContractError):
        _prepare(condition="C0")


def test_invalid_trusted_internal_identity_never_forms_a_command():
    request = _request()
    stage, _, _ = _stage(request, condition="C1")
    reader = FakeOdoo()
    resolved = read_trusted_state(reader, _workflow(), _operational(), policy_version=POLICY_VERSION)
    for field in ("company_id", "vendor_id", "purchase_order_id"):
        with pytest.raises(ValueError):
            prepare_c1_draft_command_v2(request, stage, resolved=replace(resolved, **{field: True}),
                policy_version=POLICY_VERSION, evaluated_at="2026-10-07T12:00:00Z",
                expires_at="2026-10-07T12:01:00Z")
