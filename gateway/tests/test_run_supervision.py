from __future__ import annotations

from dataclasses import FrozenInstanceError, replace
import json
from types import MappingProxyType

import pytest

from tcc_gateway.run_supervision import (
    RunSupervision,
    RunSupervisionContractError,
    StageInterval,
)


def supervision(**changes) -> RunSupervision:
    fields = {
        "run_id": "1" * 32,
        "condition": "C0",
        "code_commit": "2" * 40,
        "configuration_sha256": "3" * 64,
        "host_id": "test-host.01",
        "clock_id": "monotonic-1",
        "mode": "MOCKED",
        "effect_quiescence": "CONFIRMED",
        "intervals": (StageInterval("llm", 0, 10), StageInterval("capture", 10, 20)),
    }
    fields.update(changes)
    return RunSupervision(**fields)


def binding() -> dict[str, str]:
    return {name: getattr(supervision(), name) for name in (
        "run_id", "condition", "code_commit", "configuration_sha256",
    )}


@pytest.mark.parametrize("condition", ["C0", "C1"])
@pytest.mark.parametrize("mode", ["MOCKED", "OBSERVED"])
@pytest.mark.parametrize("quiescence", ["CONFIRMED", "UNKNOWN"])
def test_round_trip_preserves_explicit_declarations(condition, mode, quiescence):
    value = supervision(condition=condition, mode=mode, effect_quiescence=quiescence)
    restored = RunSupervision.from_mapping(json.loads(json.dumps(value.to_mapping())))
    assert restored == value
    assert restored.effect_quiescence == quiescence
    assert restored.to_mapping()["mode"] == mode


def test_closed_mapping_has_only_declared_facts_not_remote_termination_or_outcomes():
    value = supervision().to_mapping()
    assert set(value) == {
        "run_id", "condition", "code_commit", "configuration_sha256", "host_id", "clock_id",
        "mode", "effect_quiescence", "intervals",
    }
    assert set(value["intervals"][0]) == {"name", "started_ns", "ended_ns"}


@pytest.mark.parametrize("name", ["llm", "observation", "policy", "execution", "capture", "reset"])
def test_each_named_stage_allows_nonnegative_inclusive_boundaries(name):
    value = supervision(intervals=(StageInterval(name, 0, 0),))
    assert RunSupervision.from_mapping(value.to_mapping()) == value


@pytest.mark.parametrize("name", ["provider", "LLM", "", None, True, [], {}])
def test_stage_enum_rejects_unknown_or_untyped_values(name):
    with pytest.raises(RunSupervisionContractError):
        StageInterval(name, 0, 1)


@pytest.mark.parametrize("field", ["started_ns", "ended_ns"])
@pytest.mark.parametrize("invalid", [-1, True, False, 0.0, "0", None, [], {}])
def test_interval_timestamps_require_exact_nonnegative_integers(field, invalid):
    with pytest.raises(RunSupervisionContractError):
        StageInterval(**{"name": "llm", "started_ns": 0, "ended_ns": 1, field: invalid})


def test_negative_duration_is_rejected_not_truncated():
    with pytest.raises(RunSupervisionContractError, match="backwards"):
        StageInterval("llm", 2, 1)


@pytest.mark.parametrize("intervals", [
    (), [], [StageInterval("llm", 0, 1)], (None,), ({"name": "llm", "started_ns": 0, "ended_ns": 1},),
    (StageInterval("llm", 0, 1), StageInterval("llm", 1, 2)),
    (StageInterval("llm", 1, 3), StageInterval("capture", 2, 4)),
    (StageInterval("capture", 5, 6), StageInterval("llm", 0, 1)),
    (StageInterval("llm", 0, 0),) * 7,
])
def test_intervals_are_bounded_typed_unique_and_chronological(intervals):
    with pytest.raises(RunSupervisionContractError):
        supervision(intervals=intervals)


@pytest.mark.parametrize("field,invalid", [
    ("run_id", "A" * 32), ("run_id", "1" * 31), ("run_id", 1),
    ("condition", "c0"), ("condition", 0), ("condition", []),
    ("code_commit", "A" * 40), ("code_commit", "2" * 39), ("code_commit", None),
    ("configuration_sha256", "sha256:" + "3" * 64), ("configuration_sha256", "3" * 63),
    ("configuration_sha256", {}),
    ("mode", "observed"), ("mode", True), ("mode", []),
    ("effect_quiescence", "AVAILABLE"), ("effect_quiescence", True), ("effect_quiescence", {}),
])
def test_bindings_and_declarations_have_strict_formats(field, invalid):
    with pytest.raises(RunSupervisionContractError):
        supervision(**{field: invalid})


@pytest.mark.parametrize("field", ["host_id", "clock_id"])
@pytest.mark.parametrize("invalid", [
    "", "../host", "/host", "C:\\host", "host name", "host\n", "host\u200b", "éhost", ".host",
    "h" * 65, None, True, [], {},
])
def test_host_and_clock_are_bounded_ascii_identifiers_not_paths_or_free_text(field, invalid):
    with pytest.raises(RunSupervisionContractError):
        supervision(**{field: invalid})


@pytest.mark.parametrize("field", ["host_id", "clock_id"])
@pytest.mark.parametrize("valid", ["0", "clock-1", "Host_01", "a.b", "h" * 64])
def test_host_and_clock_safe_identifier_boundaries(field, valid):
    assert getattr(supervision(**{field: valid}), field) == valid


def test_binding_is_checked_against_independent_expected_values():
    supervision().validate_binding(**binding())


@pytest.mark.parametrize("field,other", [
    ("run_id", "4" * 32), ("condition", "C1"), ("code_commit", "4" * 40),
    ("configuration_sha256", "4" * 64),
])
def test_other_run_condition_code_or_configuration_cannot_be_reused(field, other):
    expected = binding()
    expected[field] = other
    with pytest.raises(RunSupervisionContractError, match="binding mismatch"):
        supervision().validate_binding(**expected)


@pytest.mark.parametrize("field", ["run_id", "condition", "code_commit", "configuration_sha256"])
def test_expected_binding_is_validated_not_coerced(field):
    expected = binding()
    expected[field] = None
    with pytest.raises(RunSupervisionContractError):
        supervision().validate_binding(**expected)


@pytest.mark.parametrize("parser,valid", [
    (StageInterval.from_mapping, {"name": "llm", "started_ns": 0, "ended_ns": 1}),
    (RunSupervision.from_mapping, supervision().to_mapping()),
])
def test_parsers_reject_extra_and_missing_keys(parser, valid):
    with pytest.raises(RunSupervisionContractError):
        parser({**valid, "credential": "synthetic-marker-do-not-repeat"})
    for field in valid:
        with pytest.raises(RunSupervisionContractError):
            parser({name: value for name, value in valid.items() if name != field})


@pytest.mark.parametrize("parser", [StageInterval.from_mapping, RunSupervision.from_mapping])
@pytest.mark.parametrize("invalid", [None, [], 0, True, "synthetic-marker-do-not-repeat"])
def test_parsers_reject_non_mappings_with_finite_diagnostics(parser, invalid):
    with pytest.raises(RunSupervisionContractError) as error:
        parser(invalid)
    assert "synthetic-marker" not in str(error.value)


@pytest.mark.parametrize("intervals", [None, (), "llm", {}, [], [None], [{}]])
def test_supervision_parser_requires_bounded_json_interval_list(intervals):
    value = supervision().to_mapping()
    value["intervals"] = intervals
    with pytest.raises(RunSupervisionContractError):
        RunSupervision.from_mapping(value)


def test_parsers_accept_read_only_mapping_and_detach_mutable_input_and_output():
    original = supervision().to_mapping()
    restored = RunSupervision.from_mapping(MappingProxyType(original))
    original["intervals"][0]["ended_ns"] = 999
    original["host_id"] = "changed"
    assert restored == supervision()
    exported = restored.to_mapping()
    exported["intervals"].append({"name": "reset", "started_ns": 999, "ended_ns": 999})
    exported["intervals"][0]["name"] = "reset"
    assert restored == supervision()
    interval = StageInterval.from_mapping(MappingProxyType({"name": "llm", "started_ns": 0, "ended_ns": 1}))
    interval_output = interval.to_mapping()
    interval_output["ended_ns"] = 999
    assert interval.ended_ns == 1


def test_contract_instances_are_frozen():
    value = supervision()
    with pytest.raises(FrozenInstanceError):
        value.effect_quiescence = "UNKNOWN"
    with pytest.raises(FrozenInstanceError):
        value.intervals[0].ended_ns = -1


def test_serialization_revalidates_corrupted_instances():
    value = supervision()
    object.__setattr__(value.intervals[0], "ended_ns", -1)
    with pytest.raises(RunSupervisionContractError):
        value.to_mapping()
    with pytest.raises(RunSupervisionContractError):
        value.validate_binding(**binding())


def test_invalid_mapping_content_is_not_copied_to_diagnostic():
    marker = "synthetic-marker-do-not-repeat"
    value = supervision().to_mapping()
    value["clock_id"] = marker + "\n"
    with pytest.raises(RunSupervisionContractError) as error:
        RunSupervision.from_mapping(value)
    assert marker not in str(error.value)
    assert error.value.__suppress_context__


def test_unknown_quiescence_is_not_silently_promoted():
    value = supervision(effect_quiescence="UNKNOWN")
    value.validate_binding(**binding())
    assert replace(value, mode="OBSERVED").effect_quiescence == "UNKNOWN"
