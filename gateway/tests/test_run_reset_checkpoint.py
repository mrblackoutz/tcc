"""DEC-059: reset recovery never rewrites a run or manufactures a score."""

from dataclasses import FrozenInstanceError, replace

import pytest

from tcc_gateway.attempt_policy import AttemptRecord, NANOSECONDS
from tcc_gateway.company_capture import CapturedCompanyState, parse_company_capture
from tcc_gateway.run_record import build_run_record
from tcc_gateway.run_record_v2 import build_run_record_v2
from tcc_gateway.run_reset_checkpoint import (
    VERSION, RunResetCheckpoint, RunResetCheckpointContractError,
    build_run_reset_checkpoint, derive_next_slot_gate, parse_run_reset_checkpoint,
)
from tcc_gateway.run_supervision import StageInterval
from tcc_gateway.state import canonical_json_bytes, canonical_json_sha256
from test_company_capture import BINDING, sign
from test_run_record import valid_inputs
from test_run_record_v2 import failed_inputs


def divergent_capture(baseline):
    value = baseline.to_mapping()
    value["records"]["postgres.sequence"][0]["last_value"] += 1
    return parse_company_capture(sign(value), BINDING)


def record_inputs(condition="C1", *, reset="divergent", attack=True, failed=None):
    value = failed_inputs(condition, failed, attack=attack) if failed else valid_inputs(condition, attack)
    if reset == "absent":
        value["restored"] = None
    elif reset == "divergent":
        value["restored"] = divergent_capture(value["baseline"])
    return value


def supervision_for(record, previous=None, **changes):
    from tcc_gateway.run_supervision import RunSupervision

    original = RunSupervision.from_mapping(record.to_mapping()["supervision"])
    end = previous.to_mapping()["supervision"]["intervals"][-1]["ended_ns"] if previous else original.intervals[-1].ended_ns
    return replace(original, intervals=(StageInterval("capture", end, end + 1),), **changes)


def checkpoint(record, restored, previous=None, **supervision_changes):
    return build_run_reset_checkpoint(record=record, previous=previous, restored=restored,
        supervision=supervision_for(record, previous, **supervision_changes))


@pytest.mark.parametrize("condition", ["C0", "C1"])
@pytest.mark.parametrize("reset", ["absent", "divergent", "verified"])
@pytest.mark.parametrize("later", ["absent", "divergent", "verified"])
@pytest.mark.parametrize("attack", [False, True])
def test_bound_later_reset_preserves_original_outcome_and_gate(condition, reset, later, attack):
    inputs = record_inputs(condition, reset=reset, attack=attack)
    record = build_run_record_v2(**inputs)
    original = canonical_json_bytes(record.to_mapping())
    restored = None if later == "absent" else divergent_capture(inputs["baseline"]) if later == "divergent" else inputs["baseline"]
    event = checkpoint(record, restored)
    value = event.to_mapping()
    assert value["schema_version"] == VERSION
    assert value["identity"] == record.to_mapping()["identity"]
    assert value["record_sha256"] == canonical_json_sha256(record.to_mapping())
    assert value["sequence"] == event.sequence == 1
    assert value["previous_checkpoint_sha256"] is None
    assert value["derived"] == {
        "reset_status": {"absent": "UNOBSERVED", "divergent": "DIVERGED", "verified": "VERIFIED"}[later],
        "batch_gate": "CONTINUE" if later == "verified" else "HALT_RESET",
    }
    assert derive_next_slot_gate(record, (event,)) == value["derived"]["batch_gate"]
    assert parse_run_reset_checkpoint(value, record=record, previous=None).to_mapping() == value
    assert event.run_id == record.run_id
    assert value["scientific_run"] is value["human_review_complete"] is False
    assert canonical_json_bytes(record.to_mapping()) == original
    assert "oracle" not in value and "after" not in value and "stage" not in value
    assert record.to_mapping()["derived"]["oracle"]["state_violation"] is (attack and condition == "C0")


@pytest.mark.parametrize("condition", ["C0", "C1"])
def test_recovery_chain_preserves_failures_and_latest_degradation(condition):
    inputs = record_inputs(condition)
    record = build_run_record_v2(**inputs)
    first = checkpoint(record, None)
    second = checkpoint(record, divergent_capture(inputs["baseline"]), first)
    third = checkpoint(record, inputs["baseline"], second)
    fourth = checkpoint(record, None, third)
    events = (first, second, third, fourth)
    assert [event.sequence for event in events] == [1, 2, 3, 4]
    assert [derive_next_slot_gate(record, events[:count]) for count in range(1, 5)] == [
        "HALT_RESET", "HALT_RESET", "CONTINUE", "HALT_RESET",
    ]
    for previous, current in zip(events, events[1:]):
        assert current.to_mapping()["previous_checkpoint_sha256"] == canonical_json_sha256(previous.to_mapping())
    assert record.to_mapping()["derived"]["reset_status"] == "DIVERGED"


@pytest.mark.parametrize("condition", ["C0", "C1"])
@pytest.mark.parametrize("failure", ["permanent", "exhausted", "budget_empty", "budget_sleep", "uncertain", "client_uncertain"])
def test_model_failure_does_not_disappear_when_reset_is_recovered(condition, failure):
    inputs = record_inputs(condition, failed=failure, attack=False)
    record = build_run_record_v2(**inputs)
    event = checkpoint(record, inputs["baseline"])
    assert event.to_mapping()["derived"]["batch_gate"] == (
        "HALT_LLM_UNCERTAIN" if failure in {"uncertain", "client_uncertain"} else "CONTINUE")
    assert record.to_mapping()["derived"]["oracle"]["benign_task_success"] is False
    assert record.to_mapping()["derived"]["technical_disposition"]["counts_as_missing"] is False


@pytest.mark.parametrize("condition", ["C0", "C1"])
@pytest.mark.parametrize("category", ["timeout", "transport"])
def test_recovered_reset_cannot_hide_earlier_uncertain_attempt_followed_by_success(condition, category):
    inputs = record_inputs(condition, attack=False)
    success = inputs["stage"].attempts[0]
    inputs["stage"] = replace(inputs["stage"], attempts=(AttemptRecord(1, "classified_error", 1,
        success.request_sha256, error_category=category, retryable_hint=True), replace(success, number=2)))
    inputs["supervision"] = replace(inputs["supervision"], intervals=(StageInterval("llm", 0, 2 * NANOSECONDS + 2),))
    record = build_run_record_v2(**inputs)
    assert record.to_mapping()["derived"]["batch_gate"] == "HALT_RESET"
    assert record.to_mapping()["derived"]["oracle"]["benign_task_success"] is True
    event = checkpoint(record, inputs["baseline"])
    assert derive_next_slot_gate(record, (event,)) == "HALT_LLM_UNCERTAIN"


@pytest.mark.parametrize("condition", ["C0", "C1"])
@pytest.mark.parametrize("problem", ["after_absent", "oracle_rejected", "unquiesced"])
def test_reset_capture_is_not_late_execution_state_or_missing_classification(condition, problem):
    inputs = record_inputs(condition)
    if problem == "after_absent":
        inputs["after"] = None
        inputs["trace"] = replace(inputs["trace"], after=None)
    elif problem == "oracle_rejected":
        changed = inputs["after"].to_mapping()
        changed["records"]["res.partner.bank"][0]["allow_out_payment"] = False
        inputs["after"] = parse_company_capture(sign(changed), BINDING)
        inputs["trace"] = replace(inputs["trace"], after=inputs["after"].oracle_state)
    else:
        inputs["supervision"] = replace(inputs["supervision"], effect_quiescence="UNKNOWN")
    record = build_run_record_v2(**inputs)
    event = checkpoint(record, inputs["baseline"])
    assert event.to_mapping()["derived"]["reset_status"] == "VERIFIED"
    assert derive_next_slot_gate(record, (event,)) == "HALT_CLASSIFICATION"
    assert record.to_mapping()["derived"]["oracle"] is None
    assert record.to_mapping()["derived"]["technical_disposition"]["counts_as_missing"] is False


def test_financial_quiescence_cannot_be_promoted_by_reset_only_history():
    inputs = record_inputs()
    record = build_run_record_v2(**inputs)
    first = checkpoint(record, inputs["baseline"], effect_quiescence="UNKNOWN")
    assert derive_next_slot_gate(record, (first,)) == "HALT_CLASSIFICATION"
    with pytest.raises(RunResetCheckpointContractError):
        checkpoint(record, inputs["baseline"], first, effect_quiescence="CONFIRMED")
    inputs["supervision"] = replace(inputs["supervision"], effect_quiescence="UNKNOWN")
    unknown_record = build_run_record_v2(**inputs)
    with pytest.raises(RunResetCheckpointContractError):
        checkpoint(unknown_record, inputs["baseline"], effect_quiescence="CONFIRMED")


@pytest.mark.parametrize("field,value", [
    ("run_id", "2" * 32), ("condition", "C0"), ("code_commit", "0" * 40),
    ("configuration_sha256", "0" * 64), ("host_id", "other-host"),
    ("clock_id", "other-clock"), ("mode", "OBSERVED"),
])
def test_supervision_cannot_change_original_binding_or_clock_domain(field, value):
    inputs = record_inputs()
    record = build_run_record_v2(**inputs)
    with pytest.raises(RunResetCheckpointContractError):
        checkpoint(record, inputs["baseline"], **{field: value})


@pytest.mark.parametrize("intervals", [
    (StageInterval("reset", 1, 2),),
    (StageInterval("capture", 0, 1),),
    (StageInterval("capture", 1, 2), StageInterval("reset", 2, 3)),
])
def test_only_one_later_capture_interval_is_accepted(intervals):
    inputs = record_inputs()
    record = build_run_record_v2(**inputs)
    with pytest.raises(RunResetCheckpointContractError):
        build_run_reset_checkpoint(record=record, previous=None, restored=inputs["baseline"],
            supervision=replace(inputs["supervision"], intervals=intervals))


def test_predecessor_captures_cannot_overlap_even_when_after_original_stage():
    inputs = record_inputs()
    record = build_run_record_v2(**inputs)
    first = checkpoint(record, None)
    with pytest.raises(RunResetCheckpointContractError):
        build_run_reset_checkpoint(record=record, previous=first, restored=inputs["baseline"],
            supervision=supervision_for(record))


@pytest.mark.parametrize("field,value", [
    ("company_id", 99), ("company_name", "OTHER"), ("fixture_manifest_sha256", "0" * 64),
    ("code_commit", "0" * 40), ("code_sha256", "0" * 64), ("configuration_sha256", "0" * 64),
])
def test_later_capture_must_have_original_complete_binding(field, value):
    inputs = record_inputs()
    record = build_run_record_v2(**inputs)
    restored = inputs["baseline"].to_mapping()
    restored["binding"][field] = value
    forged = CapturedCompanyState(replace(BINDING, **{field: value}), canonical_json_bytes(sign(restored)))
    with pytest.raises(RunResetCheckpointContractError):
        checkpoint(record, forged)


@pytest.mark.parametrize("location,field,value", [
    ((), "schema_version", "other/v1"), ((), "record_sha256", "0" * 64),
    ((), "sequence", True), ((), "sequence", 0), ((), "sequence", 2),
    ((), "previous_checkpoint_sha256", "0" * 64), ((), "scientific_run", True),
    ((), "human_review_complete", True), ((), "scientific_run", 0),
    (("identity",), "run_id", "2" * 32), (("identity",), "scenario_id", "OTHER"),
    (("identity",), "pair_id", "OTHER"), (("identity",), "condition", "C0"),
    (("identity",), "repetition", 2), (("identity",), "order", 2),
    (("identity",), "schedule_sha256", "0" * 64), (("identity",), "provider_mode", "OBSERVED"),
    (("derived",), "batch_gate", "CONTINUE"), (("derived",), "reset_status", "VERIFIED"),
    (("derived",), "batch_gate", True), (("derived",), "oracle", {"status": "MISSING"}),
    ((), "after", {}), ((), "oracle", {"status": "EVALUABLE"}), ((), "extra", None),
])
def test_closed_parser_rejects_favourable_edits_and_slot_changes(location, field, value):
    inputs = record_inputs()
    record = build_run_record_v2(**inputs)
    mapping = checkpoint(record, None).to_mapping()
    target = mapping
    for component in location:
        target = target[component]
    target[field] = value
    with pytest.raises(RunResetCheckpointContractError):
        parse_run_reset_checkpoint(mapping, record=record, previous=None)


@pytest.mark.parametrize("bad", [None, {}, 1, [], "private-placeholder"])
def test_boundary_types_and_diagnostics_are_finite(bad):
    inputs = record_inputs()
    record = build_run_record_v2(**inputs)
    with pytest.raises(RunResetCheckpointContractError) as caught:
        parse_run_reset_checkpoint(bad, record=record, previous=None)
    assert str(caught.value) == "invalid private run reset checkpoint"
    assert "private-placeholder" not in repr(caught.value)


def test_dataclass_is_frozen_repr_safe_and_mapping_detached():
    inputs = record_inputs()
    record = build_run_record_v2(**inputs)
    event = checkpoint(record, inputs["baseline"])
    assert repr(event) == "RunResetCheckpoint(private_candidate=True)"
    assert event.run_id not in repr(event)
    changed = event.to_mapping()
    changed["restored_capture"]["binding"]["company_name"] = "not shared"
    assert event.to_mapping()["restored_capture"]["binding"]["company_name"] == BINDING.company_name
    with pytest.raises(FrozenInstanceError):
        event._encoded = b"{}"


@pytest.mark.parametrize("bad_encoded", [b"", b"{} ", b"{\"sequence\":1,\"sequence\":2}", b"[]", b"\xff", "not-bytes", 1])
def test_raw_checkpoint_object_does_not_bypass_canonical_byte_boundary(bad_encoded):
    inputs = record_inputs()
    record = build_run_record_v2(**inputs)
    with pytest.raises(RunResetCheckpointContractError):
        derive_next_slot_gate(record, (RunResetCheckpoint(bad_encoded),))


def test_base_and_predecessor_are_revalidated_even_after_frozen_bypass():
    inputs = record_inputs()
    record = build_run_record_v2(**inputs)
    first = checkpoint(record, None)
    damaged = first.to_mapping()
    damaged["derived"]["batch_gate"] = "CONTINUE"
    object.__setattr__(first, "_encoded", canonical_json_bytes(damaged))
    with pytest.raises(RunResetCheckpointContractError):
        checkpoint(record, inputs["baseline"], first)
    base = record.to_mapping()
    base["derived"]["oracle"]["state_violation"] = not base["derived"]["oracle"]["state_violation"]
    object.__setattr__(record, "_encoded", canonical_json_bytes(base))
    with pytest.raises(RunResetCheckpointContractError):
        derive_next_slot_gate(record, ())


@pytest.mark.parametrize("alteration", ["missing_first", "duplicate", "reverse", "wrong_previous_hash", "jump"])
def test_reducer_requires_complete_contiguous_chain(alteration):
    inputs = record_inputs()
    record = build_run_record_v2(**inputs)
    first = checkpoint(record, None)
    second = checkpoint(record, inputs["baseline"], first)
    if alteration == "missing_first":
        events = (second,)
    elif alteration == "duplicate":
        events = (first, first)
    elif alteration == "reverse":
        events = (second, first)
    else:
        changed = second.to_mapping()
        changed["previous_checkpoint_sha256" if alteration == "wrong_previous_hash" else "sequence"] = "0" * 64 if alteration == "wrong_previous_hash" else 3
        events = (first, RunResetCheckpoint(canonical_json_bytes(changed)))
    with pytest.raises(RunResetCheckpointContractError):
        derive_next_slot_gate(record, events)


def test_predecessor_from_another_base_and_v1_are_not_accepted():
    inputs = record_inputs()
    record = build_run_record_v2(**inputs)
    first = checkpoint(record, None)
    other_inputs = record_inputs()
    other_inputs["policy_sha256"] = "0" * 64
    other = build_run_record_v2(**other_inputs)
    with pytest.raises(RunResetCheckpointContractError):
        checkpoint(other, other_inputs["baseline"], first)
    v1 = build_run_record(**valid_inputs())
    with pytest.raises(RunResetCheckpointContractError):
        derive_next_slot_gate(v1, ())


def test_no_history_preserves_original_gate_and_requires_typed_tuple():
    inputs = record_inputs()
    record = build_run_record_v2(**inputs)
    assert derive_next_slot_gate(record, ()) == record.to_mapping()["derived"]["batch_gate"]
    for events in ([], None, (None,), ({},)):
        with pytest.raises(RunResetCheckpointContractError):
            derive_next_slot_gate(record, events)


def test_limit_and_non_json_container_guards(monkeypatch):
    from tcc_gateway import run_reset_checkpoint as module

    inputs = record_inputs()
    record = build_run_record_v2(**inputs)
    first = checkpoint(record, None)
    mapping = first.to_mapping()
    mapping["identity"] = tuple(mapping["identity"].items())
    with pytest.raises(RunResetCheckpointContractError):
        parse_run_reset_checkpoint(mapping, record=record, previous=None)
    cyclic = first.to_mapping()
    cyclic["cycle"] = cyclic
    with pytest.raises(RunResetCheckpointContractError):
        parse_run_reset_checkpoint(cyclic, record=record, previous=None)
    monkeypatch.setattr(module, "MAX_CHECKPOINT_BYTES", len(first._encoded) - 1)
    with pytest.raises(RunResetCheckpointContractError):
        parse_run_reset_checkpoint(first.to_mapping(), record=record, previous=None)
