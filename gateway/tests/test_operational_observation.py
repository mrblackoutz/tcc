"""DEC-053 offline: fakes sintéticos, sem valor fiscal, rede ou efeitos Odoo."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import FrozenInstanceError, replace
import hashlib
import inspect
import json

import httpx
import pytest

from tcc_gateway.attempt_policy import AttemptRecord
from tcc_gateway.llm_client_service import LLMClientServiceConfig, process_client_request
from tcc_gateway.llm_config import DEEPSEEK_MODEL, DeepSeekConfig
from tcc_gateway.operational_observation import (
    ObservationBinding, ObservedTrustedState, OperationalObservationError,
    RegisteredOperationalObservation, parse_registered_observation,
    prepare_observed_policy_input, read_observed_trusted_state,
)
from tcc_gateway.pilot_llm_runner import LLMStageResult
from tcc_gateway.policy_contracts import DependencyStatus, ReasonCode
from tcc_gateway.policy_engine import POLICY_VERSION, evaluate_policy
from tcc_gateway.runner_contract_v2 import (
    C1PrePolicyRejection, RunnerContractError, classify_c1_prepolicy_error,
    prepare_c1_observed_draft_command_v2, proposal_from_llm_stage_v2,
)
from tcc_gateway.state import canonical_json_bytes, canonical_json_sha256
from tcc_gateway.trusted_resolution import (
    CanonicalizationError, TrustedStateResolutionError, canonicalize_proposal, read_trusted_state,
)

from test_runner_contract_v2 import _model_output, _request
from test_trusted_resolution import FakeOdoo, _operational, _proposal, _workflow


AVAILABLE = DependencyStatus("AVAILABLE", "AVAILABLE", "AVAILABLE")
EVALUATED = "2026-10-13T12:00:00Z"
EXPIRES = "2026-10-13T12:01:00Z"


def _binding(**changes):
    value = dict(
        registration_id=60, registration_sha256="sha256:" + "d" * 64,
        company_id=1, executor_user_id=70, vendor_id=10, purchase_order_id=20,
        journal_id=80, code_commit="e" * 40, code_sha256="sha256:" + "f" * 64,
        configuration_sha256="sha256:" + "1" * 64,
        purchase_line_ids=(40,), allowed_bank_ids=(11,),
    )
    value.update(changes)
    return ObservationBinding(**value)


def _rehash(value):
    value["observation_sha256"] = "sha256:" + hashlib.sha256(
        b"tcc-operational-observation/v1\0" + canonical_json_bytes({
            name: item for name, item in value.items() if name != "observation_sha256"
        }),
    ).hexdigest()
    return value


def _observation(proposal=None, *, post=False):
    proposal = proposal or _proposal(post=post)
    action = canonicalize_proposal(
        proposal, policy_version=POLICY_VERSION, quantity_scale=2,
        target_move_id=42 if post else None,
    )
    workflow = _workflow(post=post)
    binding = _binding()
    return _rehash({
        "schema_version": "registered-operational-observation/v1",
        "registration": {"registration_id": binding.registration_id, "registration_sha256": binding.registration_sha256},
        "provenance": {name: getattr(binding, name) for name in ("code_commit", "code_sha256", "configuration_sha256")},
        "scope": {
            **{name: getattr(binding, name) for name in ("company_id", "executor_user_id", "vendor_id", "purchase_order_id", "journal_id")},
            "purchase_line_ids": [40], "allowed_bank_ids": [11],
            **{name: getattr(workflow, name) for name in ("scenario_id", "document_sha256", "invoice_date_min", "invoice_date_max", "monetary_tolerance", "quantity_scale")},
            "policy_version": POLICY_VERSION, "executor_mode": action.executor_mode,
            "action_sha256": action.action_hash, "document_ref": action.document_ref,
            "invoice_date": action.invoice_date, "target_move_id": action.target_move_id,
        },
        "facts": {"document_duplicate": False, "reference_duplicate": False,
                  "duplicate_detected": False, "accounting_period_open": True},
        "preflight": {"state": "AVAILABLE", "audit": "AVAILABLE"},
        "observed_at": "2026-10-13T11:59:59Z",
    })


def _read(value=None, *, post=False, workflow=None, client=None, dependencies=AVAILABLE):
    return read_observed_trusted_state(
        client or FakeOdoo(post=post), workflow or _workflow(post=post),
        value or _observation(post=post), _binding(),
        dependencies=dependencies, policy_version=POLICY_VERSION,
    )


def _prepare(proposal=None, observed=None, *, post=False):
    return prepare_observed_policy_input(
        proposal or _proposal(post=post), observed or _read(post=post),
        policy_version=POLICY_VERSION, evaluated_at=EVALUATED, expires_at=EXPIRES,
    )


def _stage(*, post=False, condition="C1", **changes):
    """Transporte HTTP puramente síncrono em memória, sem async socketpair."""
    request = _request()
    output = _model_output(post=post, **changes)

    def handler(_request):
        return httpx.Response(200, json={
            "id": "synthetic-observed-stage", "model": DEEPSEEK_MODEL,
            "choices": [{"index": 0, "message": {"role": "assistant", "content": json.dumps(output)},
                         "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
        })

    status, response = process_client_request(
        request, LLMClientServiceConfig(mode="deepseek-smoke", deepseek_config=DeepSeekConfig(api_key="synthetic-test-key")),
        transport=httpx.MockTransport(handler), expected_request_version="llm-client-request/v2",
    )
    assert status == 200
    return request, LLMStageResult(condition, "success", "SUCCESS", (
        AttemptRecord(1, "success", 0, canonical_json_sha256(request), canonical_json_sha256(response)),
    ), response)


def _run(request, stage, observed):
    return prepare_c1_observed_draft_command_v2(
        request, stage, observed=observed, policy_version=POLICY_VERSION,
        evaluated_at=EVALUATED, expires_at=EXPIRES,
    )


def test_closed_observation_is_detached_and_rechecked_without_mutating_source():
    original = _observation()
    before = deepcopy(original)
    parsed = parse_registered_observation(original, _binding())
    assert original == before and parsed.to_mapping() == before
    original["facts"]["accounting_period_open"] = False
    detached = parsed.to_mapping()
    detached["scope"]["allowed_bank_ids"].append(99)
    assert parsed.to_mapping() == before
    with pytest.raises(FrozenInstanceError):
        parsed.canonical_bytes = b"{}"
    reparsed = parse_registered_observation(parsed.to_mapping(), _binding())
    assert reparsed == parsed


@pytest.mark.parametrize("path", [(), ("registration",), ("provenance",), ("scope",), ("facts",), ("preflight",)])
def test_all_objects_reject_unknown_fields_even_with_recomputed_hash(path):
    value = _observation()
    member = value
    for name in path:
        member = member[name]
    member["approval"] = "UNTRUSTED-MARKER"
    with pytest.raises(OperationalObservationError) as captured:
        parse_registered_observation(_rehash(value), _binding())
    assert "UNTRUSTED-MARKER" not in str(captured.value)


@pytest.mark.parametrize("section,field", [
    ("registration", "registration_id"), ("scope", "executor_user_id"),
    ("scope", "company_id"), ("scope", "vendor_id"), ("scope", "purchase_order_id"),
    ("scope", "journal_id"), ("scope", "quantity_scale"),
])
@pytest.mark.parametrize("invalid", [True, False, 1.0, "1", 0, -1])
def test_ids_and_scale_reject_boolean_numeric_coercion(section, field, invalid):
    value = _observation()
    value[section][field] = invalid
    with pytest.raises(OperationalObservationError):
        parse_registered_observation(_rehash(value), _binding())


@pytest.mark.parametrize("field", ["purchase_line_ids", "allowed_bank_ids"])
@pytest.mark.parametrize("invalid", [[True], [1.0], [1, 1], [40, 11], [], ["11"]])
def test_id_lists_are_strict_sorted_unique(field, invalid):
    value = _observation()
    value["scope"][field] = invalid
    with pytest.raises(OperationalObservationError):
        parse_registered_observation(_rehash(value), _binding())


@pytest.mark.parametrize("field", ["document_duplicate", "reference_duplicate", "duplicate_detected", "accounting_period_open"])
@pytest.mark.parametrize("invalid", [0, 1, "false", None])
def test_facts_are_real_booleans(field, invalid):
    value = _observation()
    value["facts"][field] = invalid
    with pytest.raises(OperationalObservationError):
        parse_registered_observation(_rehash(value), _binding())


@pytest.mark.parametrize("document,reference,aggregate", [(False, False, True), (True, False, False), (False, True, False), (True, True, False)])
def test_duplicate_or_invariant_is_mandatory(document, reference, aggregate):
    value = _observation()
    value["facts"].update(document_duplicate=document, reference_duplicate=reference, duplicate_detected=aggregate)
    with pytest.raises(OperationalObservationError):
        parse_registered_observation(_rehash(value), _binding())


@pytest.mark.parametrize("field,invalid", [
    ("registration_id", 61), ("registration_sha256", "sha256:" + "2" * 64),
    ("company_id", 2), ("executor_user_id", 71), ("vendor_id", 12),
    ("purchase_order_id", 21), ("journal_id", 81), ("code_commit", "2" * 40),
    ("code_sha256", "sha256:" + "2" * 64), ("configuration_sha256", "sha256:" + "2" * 64),
])
def test_rehashed_observation_cannot_change_independent_binding(field, invalid):
    value = _observation()
    section = "registration" if field.startswith("registration_") else (
        "provenance" if field in {"code_commit", "code_sha256", "configuration_sha256"} else "scope"
    )
    value[section][field] = invalid
    with pytest.raises(OperationalObservationError):
        parse_registered_observation(_rehash(value), _binding())


@pytest.mark.parametrize("field,invalid", [
    ("observed_at", "2026-10-13T11:59:59+00:00"),
    ("observed_at", "2026-10-13T11:59:59-03:00"),
    ("observed_at", "2026-10-32T11:59:59Z"), ("schema_version", "other/v1"),
    ("observation_sha256", "0" * 64),
])
def test_invalid_closed_metadata(field, invalid):
    value = _observation()
    value[field] = invalid
    if field != "observation_sha256":
        _rehash(value)
    with pytest.raises(OperationalObservationError):
        parse_registered_observation(value, _binding())


def test_plain_undomained_hash_does_not_validate_observation():
    value = _observation()
    value["observation_sha256"] = "sha256:" + canonical_json_sha256({
        name: item for name, item in value.items() if name != "observation_sha256"
    })
    with pytest.raises(OperationalObservationError):
        parse_registered_observation(value, _binding())


def test_tampered_fact_without_rehash_is_rejected():
    value = _observation()
    value["facts"]["accounting_period_open"] = False
    with pytest.raises(OperationalObservationError):
        parse_registered_observation(value, _binding())


@pytest.mark.parametrize("post,target", [(False, 42), (False, True), (True, None), (True, True), (True, 42.0)])
def test_mode_target_binding_has_no_repair(post, target):
    value = _observation(post=post)
    value["scope"]["target_move_id"] = target
    before = deepcopy(_rehash(value))
    with pytest.raises(OperationalObservationError):
        parse_registered_observation(value, _binding())
    assert value == before


@pytest.mark.parametrize("field,invalid", [
    ("scenario_id", "SCN-OTHER"), ("document_sha256", "2" * 64),
    ("purchase_line_ids", [41]), ("allowed_bank_ids", [13]),
    ("invoice_date_min", "2026-09-02"), ("invoice_date_max", "2026-10-30"),
    ("monetary_tolerance", "0.01"), ("quantity_scale", 3),
    ("policy_version", "policy-other"),
])
def test_rehashed_scope_must_match_read_ids_and_workflow_limits(field, invalid):
    value = _observation()
    value["scope"][field] = invalid
    with pytest.raises(OperationalObservationError):
        _read(_rehash(value))


def test_post_origin_must_match_real_resolved_target_id():
    value = _observation(post=True)
    value["scope"]["target_move_id"] = 99
    with pytest.raises(OperationalObservationError):
        _read(_rehash(value), post=True)


@pytest.mark.parametrize("field", ["company_id", "vendor_id", "purchase_order_id"])
def test_snapshot_id_drift_is_rejected_on_prepare(field):
    observed = _read()
    object.__setattr__(observed.resolved, field, True)
    with pytest.raises(OperationalObservationError):
        _prepare(observed=observed)


@pytest.mark.parametrize("field,invalid", [
    ("phase", "POST_REVIEW"), ("monetary_tolerance", "1.00"),
    ("duplicate_detected", True), ("accounting_period_open", False),
    ("invoice_date_min", "2026-09-02"),
])
def test_frozen_state_constructor_bypass_is_rechecked(field, invalid):
    observed = _read()
    object.__setattr__(observed.resolved.state, field, invalid)
    with pytest.raises(OperationalObservationError):
        _prepare(observed=observed)


def test_constructor_bypass_of_po_amount_changes_snapshot_digest():
    observed = _read()
    object.__setattr__(observed.resolved.state.purchase_order, "amount", "126.50")
    with pytest.raises(OperationalObservationError):
        _prepare(observed=observed)


def test_constructor_bypass_of_workflow_binding_and_observation_is_rechecked():
    for target, field, value in [
        ("workflow", "allowed_bank_refs", ("TCC-BANK-OTHER",)),
        ("binding", "code_commit", "2" * 40),
        ("dependencies", "audit", "UNAVAILABLE"),
        ("observation", "canonical_bytes", b"{}"),
    ]:
        observed = _read()
        object.__setattr__(getattr(observed, target), field, value)
        with pytest.raises(OperationalObservationError):
            _prepare(observed=observed)


@pytest.mark.parametrize("changes", [
    {"document_ref": "TCC-NF-OTHER"}, {"invoice_date": "2026-10-01"},
    {"bank_account_ref": "TCC-BANK-002"}, {"vendor_ref": "TCC-VENDOR-002"},
    {"purchase_order_ref": "TCC-PO-OTHER"}, {"currency": "USD"},
    {"total": "999.00", "lines": [{"item_code": "TCC-SERVICE-001", "description": "SINTETICO SEM VALOR FISCAL",
                                   "quantity": "1.00", "unit_price": "999.00", "line_total": "999.00"}]},
])
def test_all_candidate_fields_are_bound_to_full_action_hash(changes):
    observed = _read()
    proposal = _proposal(**changes)
    before = proposal.to_mapping()
    with pytest.raises(OperationalObservationError):
        _prepare(proposal, observed)
    assert proposal.to_mapping() == before


@pytest.mark.parametrize("field,invalid", [("document_ref", "TCC-NF-OTHER"), ("invoice_date", "2026-10-01"), ("action_sha256", "sha256:" + "2" * 64)])
def test_rehashed_internally_mismatched_action_fields_fail_at_policy_binding(field, invalid):
    value = _observation()
    value["scope"][field] = invalid
    observed = _read(_rehash(value))
    with pytest.raises(OperationalObservationError):
        _prepare(observed=observed)


def test_changed_candidate_mode_cannot_use_create_observation():
    """DEC-063: a POST proposed in the draft phase is a policy denial, not an observation fault."""
    with pytest.raises(CanonicalizationError) as captured:
        _prepare(_proposal(post=True), _read())
    assert type(captured.value) is CanonicalizationError
    rejection = classify_c1_prepolicy_error(captured.value, proposal_action="POST_VENDOR_BILL",
                                            trusted_phase="DRAFT_INTAKE")
    assert rejection == C1PrePolicyRejection(ReasonCode.PHASE_MISMATCH, "POLICY_RULE")


@pytest.mark.parametrize("changed_field,invalid", [("policy_version", "policy-other"), ("evaluated_at", "2026-10-13T11:59:58Z"), ("expires_at", EVALUATED)])
def test_policy_version_timestamp_and_lifetime_are_rechecked(changed_field, invalid):
    args = dict(policy_version=POLICY_VERSION, evaluated_at=EVALUATED, expires_at=EXPIRES)
    args[changed_field] = invalid
    with pytest.raises(OperationalObservationError):
        prepare_observed_policy_input(_proposal(), _read(), **args)


@pytest.mark.parametrize("source", ["supervisor", "native"])
def test_state_unavailability_never_becomes_favorable_default(source):
    value = _observation()
    dependencies = AVAILABLE
    if source == "native":
        value["preflight"]["state"] = "UNAVAILABLE"
    else:
        dependencies = replace(AVAILABLE, state="UNAVAILABLE")
    client = FakeOdoo()
    with pytest.raises(TrustedStateResolutionError) as captured:
        _read(_rehash(value), dependencies=dependencies, client=client)
    assert captured.value.category == "DEPENDENCY_UNAVAILABLE" and client.calls == []


@pytest.mark.parametrize("source", ["supervisor", "native"])
def test_audit_unavailability_is_preserved_and_denies_policy(source):
    value = _observation()
    dependencies = AVAILABLE
    if source == "native":
        value["preflight"]["audit"] = "UNAVAILABLE"
    else:
        dependencies = replace(AVAILABLE, audit="UNAVAILABLE")
    observed = _read(_rehash(value), dependencies=dependencies)
    assert observed.resolved.state.dependencies.audit == "UNAVAILABLE"
    decision = evaluate_policy(_prepare(observed=observed))
    assert decision.decision == "DENY" and ReasonCode.AUDIT_UNAVAILABLE in decision.reason_codes


def test_supervisor_policy_unavailable_is_not_inferred_from_native_read_success():
    observed = _read(dependencies=replace(AVAILABLE, policy="UNAVAILABLE"))
    assert observed.resolved.state.dependencies.policy == "UNAVAILABLE"
    decision = evaluate_policy(_prepare(observed=observed))
    assert decision.decision == "DENY" and ReasonCode.POLICY_UNAVAILABLE in decision.reason_codes


def test_supervisor_is_required_with_no_default_and_no_untyped_context():
    parameter = inspect.signature(read_observed_trusted_state).parameters["dependencies"]
    assert parameter.default is inspect.Parameter.empty
    with pytest.raises(TypeError):
        read_observed_trusted_state(FakeOdoo(), _workflow(), _observation(), _binding(), policy_version=POLICY_VERSION)
    with pytest.raises(OperationalObservationError):
        _read(dependencies={"state": "AVAILABLE", "audit": "AVAILABLE", "policy": "AVAILABLE"})


def test_revoked_bank_is_not_repaired_or_observed_as_authorized():
    client = FakeOdoo()
    client.records["res.partner.bank"][0]["allow_out_payment"] = False
    observed = _read(client=client)
    assert observed.resolved.bank_ids == ()
    decision = evaluate_policy(_prepare(observed=observed))
    assert decision.decision == "DENY" and ReasonCode.BANK_NOT_ALLOWED in decision.reason_codes


@pytest.mark.parametrize("post", [False, True])
def test_observed_runner_allow_create_and_review_post_without_financial_effect(post):
    request, stage = _stage(post=post)
    proposal = proposal_from_llm_stage_v2(request, stage)
    client = FakeOdoo(post=post)
    before = deepcopy(client.records)
    observed = _read(_observation(proposal, post=post), post=post, client=client)
    result = _run(request, stage, observed)
    assert result.decision.decision == ("REVIEW" if post else "ALLOW")
    assert (result.command is None) is post
    assert client.records == before and all(method == "search_read" for _, method, _ in client.calls)
    assert result.policy_input.action.action_hash == observed.observation.to_mapping()["scope"]["action_sha256"]
    if not post:
        result.command.validate_binding(result.policy_input)
        assert result.command.approval is None


@pytest.mark.parametrize("field,code", [("document_duplicate", ReasonCode.DUPLICATE_DOCUMENT), ("reference_duplicate", ReasonCode.DUPLICATE_DOCUMENT), ("accounting_period_open", ReasonCode.ACCOUNTING_PERIOD_CLOSED)])
def test_observed_runner_duplicate_and_closed_period_deny(field, code):
    request, stage = _stage()
    proposal = proposal_from_llm_stage_v2(request, stage)
    value = _observation(proposal)
    value["facts"][field] = False if field == "accounting_period_open" else True
    value["facts"]["duplicate_detected"] = value["facts"]["document_duplicate"] or value["facts"]["reference_duplicate"]
    result = _run(request, stage, _read(_rehash(value)))
    assert result.decision.decision == "DENY" and code in result.decision.reason_codes and result.command is None


def test_observed_runner_preserves_adversarial_candidate_for_business_deny():
    request, stage = _stage(bank_account_ref="TCC-BANK-002")
    proposal = proposal_from_llm_stage_v2(request, stage)
    result = _run(request, stage, _read(_observation(proposal)))
    assert result.policy_input.action.recipient_bank_ref == "TCC-BANK-002"
    assert result.decision.decision == "DENY" and ReasonCode.BANK_NOT_ALLOWED in result.decision.reason_codes


def test_observation_never_selects_phase_from_candidate_create_in_trusted_post_phase():
    request, stage = _stage()
    proposal = proposal_from_llm_stage_v2(request, stage)
    observed = _read(_observation(proposal), workflow=_workflow(post=True), client=FakeOdoo(post=True))
    result = _run(request, stage, observed)
    assert result.policy_input.trusted_state.phase == "POST_REVIEW"
    assert result.policy_input.action.executor_mode == "CREATE_DRAFT"
    assert result.decision.decision == "DENY" and ReasonCode.PHASE_MISMATCH in result.decision.reason_codes


def test_observed_runner_rejects_legacy_unbound_snapshot_and_wrong_condition():
    request, stage = _stage()
    legacy = read_trusted_state(FakeOdoo(), _workflow(), _operational(), policy_version=POLICY_VERSION)
    with pytest.raises(RunnerContractError):
        _run(request, stage, legacy)
    with pytest.raises(RunnerContractError):
        _run(request, replace(stage, condition="C0"), _read())


def test_parsed_representation_cannot_bypass_validation_at_next_boundary():
    value = _observation()
    value["scope"]["extra"] = "untrusted"
    forged = RegisteredOperationalObservation(canonical_json_bytes(_rehash(value)))
    with pytest.raises(OperationalObservationError):
        _read(forged)


def test_observed_context_constructor_rejects_unbound_members():
    observed = _read()
    with pytest.raises(OperationalObservationError):
        ObservedTrustedState(observed.workflow, observed.resolved, _observation(), _binding(), AVAILABLE, POLICY_VERSION)


def test_read_failure_does_not_leak_transport_cause_or_return_favorable_snapshot():
    client = FakeOdoo()
    client.fail_model = "purchase.order"
    with pytest.raises(TrustedStateResolutionError) as captured:
        _read(client=client)
    assert "RAW-TRANSPORT-MARKER" not in str(captured.value)
    assert captured.value.category == "DEPENDENCY_UNAVAILABLE"


@pytest.mark.parametrize("field,invalid", [("purchase_line_id", True), ("product_id", 30.0), ("uom_id", "31")])
def test_resolved_line_constructor_bypass_rejected(field, invalid):
    observed = _read()
    object.__setattr__(observed.resolved.lines[0], field, invalid)
    with pytest.raises(OperationalObservationError):
        _prepare(observed=observed)


def test_future_timestamp_does_not_create_policy_input():
    value = _observation()
    value["observed_at"] = "2026-10-13T12:00:01Z"
    observed = _read(_rehash(value))
    with pytest.raises(OperationalObservationError):
        _prepare(observed=observed)


def test_independent_binding_json_round_trip_is_closed_and_detached():
    binding = _binding()
    value = binding.to_mapping()
    assert type(value["purchase_line_ids"]) is list and type(value["allowed_bank_ids"]) is list
    rebuilt = ObservationBinding.from_mapping(value)
    assert rebuilt == binding and type(rebuilt.purchase_line_ids) is tuple
    value["allowed_bank_ids"].append(99)
    assert rebuilt.allowed_bank_ids == (11,)
    with pytest.raises(OperationalObservationError):
        ObservationBinding.from_mapping({**binding.to_mapping(), "extra": "UNTRUSTED-MARKER"})
    with pytest.raises(OperationalObservationError):
        ObservationBinding.from_mapping({name: item for name, item in binding.to_mapping().items() if name != "allowed_bank_ids"})


@pytest.mark.parametrize("field", ["purchase_line_ids", "allowed_bank_ids"])
@pytest.mark.parametrize("invalid", [[], [True], [1.0], [1, 1], [40, 11], ["11"], (11,), None])
def test_independent_binding_json_requires_strict_sorted_unique_lists(field, invalid):
    value = _binding().to_mapping()
    value[field] = invalid
    with pytest.raises(OperationalObservationError):
        ObservationBinding.from_mapping(value)


@pytest.mark.parametrize("field", ["purchase_line_ids", "allowed_bank_ids"])
def test_unread_extra_identity_is_rejected_even_with_recomputed_observation_hash(field):
    value = _observation()
    value["scope"][field].append(99)
    with pytest.raises(OperationalObservationError):
        parse_registered_observation(_rehash(value), _binding())


@pytest.mark.parametrize("field", ["purchase_line_ids", "allowed_bank_ids"])
@pytest.mark.parametrize("invalid", [(True,), [11]])
def test_binding_identity_list_tamper_is_revalidated_at_consumption(field, invalid):
    observed = _read()
    object.__setattr__(observed.binding, field, invalid)
    with pytest.raises(OperationalObservationError):
        _prepare(observed=observed)


@pytest.mark.parametrize("shape", ["dict", "list", "depth", "nodes", "bytes", "aggregate_bytes"])
def test_untrusted_mapping_cycles_and_traversal_limits_raise_finite_errors(shape):
    value = _observation()
    if shape == "dict":
        value["loop"] = value
    elif shape == "list":
        loop = []
        loop.append(loop)
        value["loop"] = loop
    elif shape == "depth":
        nested = []
        for _ in range(10):
            nested = [nested]
        value["extra"] = nested
    elif shape == "nodes":
        value["extra"] = [None] * 4097
    elif shape == "bytes":
        value["extra"] = "X" * 65537
    else:
        value["extra"] = ["X" * 32768, "Y" * 32768]
    with pytest.raises(OperationalObservationError) as captured:
        parse_registered_observation(value, _binding())
    assert str(captured.value) == "invalid registered operational observation"


@pytest.mark.parametrize("raw", [b"[" * 1200 + b"0" + b"]" * 1200, b" " * 65537], ids=["deep-bytes", "oversized-bytes"])
def test_forged_byte_representation_respects_limits_at_next_boundary(raw):
    with pytest.raises(OperationalObservationError):
        RegisteredOperationalObservation(raw).to_mapping()
