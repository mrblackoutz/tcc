"""DEC-069 integration of existing observed policy and preissued approval."""

from copy import deepcopy
from dataclasses import replace
from datetime import datetime, timezone
import secrets

import pytest

from tcc_gateway.approval import ApprovalKey, issue_approval_fixture
from tcc_gateway.policy_contracts import ApprovalFixture, CanonicalAction, ReasonCode
from tcc_gateway.runner_contract_v2 import RunnerContractError, prepare_c1_observed_post_command_v2
from tcc_gateway.operational_observation import OperationalObservationError
from tcc_gateway.policy_engine import POLICY_VERSION

from test_operational_observation import EVALUATED, EXPIRES, _stage, _read, _observation
from test_runner_contract_v2 import _model_output, proposal_from_llm_stage_v2


def setup_post(**changes):
    request, stage = _stage(post=True, **changes)
    proposal = proposal_from_llm_stage_v2(request, stage)
    observed = _read(_observation(proposal, post=True), post=True)
    return request, stage, observed


def fixture(action):
    key = ApprovalKey(company_id=1, key_id="observed-post-test/v1", material=secrets.token_bytes(32))
    token = issue_approval_fixture(action, company_id=1, fixture_id="POST-TEST-FIXTURE",
        approver_ref="TEST-APPROVER", nonce=secrets.token_urlsafe(24), issued_at=EVALUATED, expires_at=EXPIRES, key=key)
    return token, key


def prepare(request, stage, observed, approval):
    return prepare_c1_observed_post_command_v2(request, stage, observed=observed, policy_version=POLICY_VERSION,
        evaluated_at=EVALUATED, expires_at=EXPIRES, approval_fixture=approval)


def legitimate():
    request, stage, observed = setup_post()
    pending = prepare(request, stage, observed, None)
    token, key = fixture(pending.policy_input.action)
    return request, stage, observed, token, key


def test_actual_stage_observation_policy_and_preissued_fixture_preserve_review():
    request, stage, observed, token, _ = legitimate()
    before = deepcopy(request)
    result = prepare(request, stage, observed, token)
    assert result.decision.decision == "REVIEW" and result.approval_rejection is None
    assert result.command is not None and result.command.action.action == "POST_VENDOR_BILL"
    assert result.command.action.target_move_id == 42 and result.command.approval is not token
    result.command.validate_binding(result.policy_input)
    assert request == before and "signature" not in repr(result) and "nonce=" not in repr(result)


def test_missing_fixture_never_creates_command_or_downgrades_review_to_allow():
    request, stage, observed = setup_post()
    result = prepare(request, stage, observed, None)
    assert result.decision.decision == "REVIEW" and result.command is None
    assert result.approval_rejection == ReasonCode.APPROVAL_INVALID


@pytest.mark.parametrize("field,value", [("document_ref", "OTHER-DOC"), ("target_move_id", 43),
    ("document_sha256", "e" * 64), ("amount", "90.00"), ("recipient_bank_ref", "OTHER-BANK")],
    ids=["reference", "target", "document", "amount", "bank"])
def test_independently_signed_different_action_is_not_rebound_to_current_proposal(field, value):
    request, stage, observed, _, _ = legitimate()
    action = prepare(request, stage, observed, None).policy_input.action.to_mapping()
    action[field] = value
    if field == "amount":
        action["lines"][0]["unit_price"] = value
    supplied, _ = fixture(CanonicalAction.from_mapping(action))
    result = prepare(request, stage, observed, supplied)
    assert result.command is None and result.approval_rejection == ReasonCode.APPROVAL_HASH_MISMATCH
    assert result.decision.decision == "REVIEW"


def test_other_scenario_precedes_hash_rejection_without_returning_token():
    request, stage, observed, token, _ = legitimate()
    result = prepare(request, stage, observed, replace(token, scenario_id="OTHER-SCENARIO"))
    assert result.command is None and result.approval_rejection == ReasonCode.APPROVAL_SCENARIO_MISMATCH


def test_denied_business_delta_never_becomes_command_even_with_approval_for_that_delta():
    lines = deepcopy(_model_output(post=True)["lines"])
    lines[0].update(unit_price="999.00", line_total="999.00")
    request, stage, observed = setup_post(total="999.00", lines=lines)
    pending = prepare(request, stage, observed, None)
    token, _ = fixture(pending.policy_input.action)
    result = prepare(request, stage, observed, token)
    assert result.decision.decision == "DENY" and result.command is None and result.approval_rejection is None


@pytest.mark.parametrize("value", ["raw-transport", {}, 1])
def test_approval_must_be_a_revalidated_typed_fixture(value):
    request, stage, observed = setup_post()
    with pytest.raises(RunnerContractError, match="invalid preissued approval"):
        prepare(request, stage, observed, value)


def test_forged_frozen_approval_is_rechecked():
    request, stage, observed, token, _ = legitimate()
    object.__setattr__(token, "nonce", "INVALID NONCE")
    with pytest.raises(RunnerContractError):
        prepare(request, stage, observed, token)


def test_create_is_not_silently_converted_to_critical_action():
    request, stage = _stage(post=False)
    with pytest.raises(RunnerContractError, match="requires a POST proposal"):
        prepare(request, stage, _read(), None)


def test_c0_stage_is_not_accepted_by_c1_handoff():
    request, stage = _stage(post=True, condition="C0")
    with pytest.raises(RunnerContractError):
        prepare(request, stage, _read(post=True), None)


def test_changed_proposal_cannot_reuse_original_observation():
    request, stage, observed = setup_post()
    changed_request, changed_stage = _stage(post=True, document_ref="OTHER-DOC")
    with pytest.raises(OperationalObservationError):
        prepare(changed_request, changed_stage, observed, None)


@pytest.mark.parametrize("bad_mac", [False, True])
def test_handoff_still_requires_independent_native_cryptographic_verifier(bad_mac):
    # Existing independent addon loader; no running Odoo or network in this test.
    from test_approval import approval
    request, stage, observed, token, key = legitimate()
    if bad_mac:
        value = token.signature
        token = replace(token, signature=value[:-1] + ("0" if value[-1] != "0" else "1"))
    prepared = prepare(request, stage, observed, token)
    assert prepared.command is not None  # Binding is NOT cryptographic approval.
    command = prepared.command.to_mapping()
    authority = approval.ApprovalAuthority(company_id=1, executor_user_id=9,
        fixture_id=token.fixture_id, scenario_id=token.scenario_id, approver_ref=token.approver_ref,
        nonce=token.nonce, issued_at=token.issued_at, expires_at=token.expires_at, key_id=token.key_id)
    selected = approval.ApprovalKey(company_id=1, key_id=key.key_id, material=key.material)
    args = dict(trusted_action=command["action"], authority=authority, key=selected,
                now=datetime(2026, 10, 13, 12, 0, 30, tzinfo=timezone.utc))
    if bad_mac:
        with pytest.raises(approval.ApprovalVerificationError) as error:
            approval.verify_approval(command, **args)
        assert error.value.code == "SIGNATURE_INVALID"
    else:
        verified = approval.verify_approval(command, **args)
        assert verified.action_hash == prepared.policy_input.action.action_hash
