"""DEC-087 read retries: native/HTTP/capture doubles, never API or effects."""

from copy import deepcopy
from dataclasses import replace
import inspect
import json

import pytest

from tcc_gateway.observation_retry import (
    FinalStateObservation, ObservationAttempt, ObservationContractError,
    ReadonlyObservationFailure, build_observation_evidence, classify_observation,
    observe_final_state,
)
from tcc_gateway.odoo_json2 import OdooJson2Error
from tcc_gateway.company_capture import parse_company_capture
from test_company_capture import BINDING, fixture


class Clock:
    def __init__(self):
        self.value = 100
        self.waits = []

    def now(self):
        return self.value

    def sleep(self, seconds):
        self.waits.append(seconds)
        self.value += seconds * 1_000_000_000


class Reader:
    """Only a read adapter is exposed; not an arbitrary Odoo RPC caller."""
    def __init__(self, clock, *values):
        self.clock, self.values, self.calls = clock, list(values), 0

    def read_capture(self):
        self.calls += 1
        self.clock.value += 20
        value = self.values.pop(0)
        if isinstance(value, Exception):
            raise value
        return deepcopy(value)


def run(*values, sleep=None):
    clock = Clock()
    reader = Reader(clock, *values)
    result = observe_final_state(reader, binding=BINDING, sleep=sleep or clock.sleep, clock_ns=clock.now)
    return result, reader, clock


def flags(**changes):
    return dict(document_hash_verified=True, initial_state_verified=True, pipeline_started=True,
        side_effect_quiesced=True, reset_verified=True, infrastructure_failure_independent=False) | changes


def transient(status=503):
    return OdooJson2Error(f"Odoo JSON-2 request failed with HTTP status {status}")


def test_first_capture_is_observed_and_private_payload_is_not_in_metadata_or_repr():
    raw = fixture()
    result, reader, clock = run(raw)
    assert result.status == "OBSERVED" and reader.calls == 1 and clock.waits == []
    assert result.capture.to_mapping() == raw
    assert result.to_mapping()["capture_sha256"] == raw["capture_sha256"]
    assert "records" not in result.to_mapping() and "filestore" not in repr(result)
    assert classify_observation(result, **flags()).disposition == "EVALUABLE"
    raw["records"].clear()
    assert result.capture.to_mapping()["records"]


@pytest.mark.parametrize("failures", [1, 2])
def test_transient_failure_then_valid_capture_records_real_attempts_and_completed_backoff(failures):
    result, reader, clock = run(*([transient()] * failures), fixture())
    assert result.status == "OBSERVED" and reader.calls == failures + 1
    assert clock.waits == [1, 2][:failures]
    assert [a.category for a in result.attempts] == ["HTTP_ERROR"] * failures + ["OBSERVED"]
    assert all(a.to_mapping()["elapsed_ns"] == 20 for a in result.attempts)
    assert build_observation_evidence(result, **flags()).observation_retries_exhausted is False
    assert classify_observation(result, **flags()).disposition == "EVALUABLE"


@pytest.mark.parametrize("kind", ["http408", "http429", "http500", "http599", "transport", "native"])
def test_exactly_three_eligible_failures_exhaust_and_never_call_a_fourth_time(kind):
    error = {"http408": transient(408), "http429": transient(429), "http500": transient(500),
        "http599": transient(599), "transport": OdooJson2Error("Odoo JSON-2 request failed before a response"),
        "native": ReadonlyObservationFailure("TRANSPORT")}[kind]
    result, reader, clock = run(error, error, error, fixture())
    assert result.status == "EXHAUSTED" and result.capture is None
    assert reader.calls == 3 and len(reader.values) == 1 and clock.waits == [1, 2]
    assert build_observation_evidence(result, **flags()).observation_retries_exhausted is True
    assert classify_observation(result, **flags()).disposition == "HOLD_UNCERTAIN"
    independent = flags()
    independent["infrastructure_failure_independent"] = True
    assert classify_observation(result, **independent).disposition == "MISSING"
    independent["side_effect_quiesced"] = False
    assert classify_observation(result, **independent).disposition == "HOLD_UNCERTAIN"


@pytest.mark.parametrize("status", [301, 400, 401, 403, 404, 409, 422])
def test_authorization_and_permanent_http_failure_stop_without_retry_or_missing(status):
    result, reader, clock = run(transient(status), fixture())
    assert result.status == "UNCONFIRMED" and reader.calls == 1 and clock.waits == []
    evidence = flags()
    evidence["infrastructure_failure_independent"] = True
    assert classify_observation(result, **evidence).disposition == "HOLD_UNCERTAIN"
    assert result.attempts[0].category == ("AUTHORIZATION" if status in {401, 403} else "HTTP_ERROR")


@pytest.mark.parametrize("category", ["AUTHORIZATION", "CONTRACT", "PERMANENT", "UNKNOWN"])
def test_typed_native_permanent_categories_are_finite_and_do_not_retry(category):
    result, reader, clock = run(ReadonlyObservationFailure(category), fixture())
    assert result.status == "UNCONFIRMED" and reader.calls == 1 and clock.waits == []


@pytest.mark.parametrize("value", [{}, None, "not JSON", b'{}'])
def test_invalid_capture_never_becomes_missing_or_triggers_a_read_retry(value):
    result, reader, clock = run(value, fixture())
    assert result.status == "UNCONFIRMED" and result.attempts[0].category == "CAPTURE_INVALID"
    assert reader.calls == 1 and clock.waits == []


def test_foreign_capture_binding_is_rejected_without_retry():
    raw = fixture()
    foreign = replace(BINDING, configuration_sha256="e" * 64)
    reader_clock = Clock()
    reader = Reader(reader_clock, raw)
    result = observe_final_state(reader, binding=foreign, sleep=reader_clock.sleep, clock_ns=reader_clock.now)
    assert result.status == "UNCONFIRMED" and reader.calls == 1


@pytest.mark.parametrize("error", [
    RuntimeError("SYNTHETIC-SECRET-MUST-NOT-ESCAPE"),
    OdooJson2Error("SYNTHETIC-SECRET-MUST-NOT-ESCAPE"),
    OdooJson2Error("Odoo JSON-2 request failed with HTTP status 503 SYNTHETIC-SECRET-MUST-NOT-ESCAPE"),
])
def test_unknown_error_is_not_parsed_by_substring_or_exposed(error):
    result, reader, clock = run(error, fixture())
    assert result.status == "UNCONFIRMED" and result.attempts[0].category == "UNKNOWN_ERROR"
    assert "SYNTHETIC-SECRET" not in json.dumps(result.to_mapping()) + repr(result)
    assert reader.calls == 1 and clock.waits == []


@pytest.mark.parametrize("message", ["Odoo JSON-2 arguments are not JSON serializable",
    "Odoo JSON-2 returned an invalid JSON response"])
def test_transport_contract_failures_are_not_retry_eligible(message):
    result, reader, clock = run(OdooJson2Error(message), fixture())
    assert result.attempts[0].category == "CONTRACT_INVALID" and result.status == "UNCONFIRMED"
    assert reader.calls == 1 and not clock.waits


def test_wait_failure_does_not_claim_exhaustion_or_repeat_a_read():
    def bad_wait(_seconds):
        raise RuntimeError("SYNTHETIC-SECRET-MUST-NOT-ESCAPE")
    result, reader, _clock = run(transient(), fixture(), sleep=bad_wait)
    assert result.status == "UNCONFIRMED" and result.reason == "WAIT_UNCONFIRMED"
    assert reader.calls == 1 and not build_observation_evidence(result, **flags()).observation_retries_exhausted


def test_permanent_failure_after_transient_reads_is_not_exhaustion_of_eligible_reads():
    result, reader, clock = run(transient(), transient(), OdooJson2Error(
        "Odoo JSON-2 returned an invalid JSON response"), fixture())
    assert result.status == "UNCONFIRMED" and reader.calls == 3 and clock.waits == [1, 2]
    assert not build_observation_evidence(result, **flags()).observation_retries_exhausted
    assert classify_observation(result, **flags(infrastructure_failure_independent=True)).disposition == "HOLD_UNCERTAIN"


def test_reset_failure_halts_without_relabelling_observed_or_missing_outcomes():
    observed, _, _ = run(fixture())
    exhausted, _, _ = run(transient(), transient(), transient())
    upstream = flags()
    upstream["reset_verified"] = False
    assert classify_observation(observed, **upstream).disposition == "EVALUABLE"
    upstream["infrastructure_failure_independent"] = True
    value = classify_observation(exhausted, **upstream)
    assert value.disposition == "MISSING" and value.batch_gate == "HALT_RESET"


def test_financial_function_or_generic_odoo_caller_is_never_accepted_as_a_reader():
    calls = []
    def financial():
        calls.append("POST")
    class GenericCaller:
        def call(self, *_args, **_kwargs):
            calls.append("CREATE")
    for reader in (financial, GenericCaller()):
        with pytest.raises(ObservationContractError):
            observe_final_state(reader, binding=BINDING)
    assert calls == []
    assert not {"condition", "attack_family", "label", "model", "method"} & set(inspect.signature(observe_final_state).parameters)


@pytest.mark.parametrize("bad", [True, -1, 1.5, None])
def test_invalid_clock_does_not_fabricate_a_missing_record(bad):
    reader = Reader(Clock(), fixture())
    with pytest.raises(ObservationContractError):
        observe_final_state(reader, binding=BINDING, clock_ns=lambda: bad)
    assert reader.calls == 0


def test_exhaustion_cannot_be_fabricated_from_one_attempt_or_skipped_wait():
    attempt = ObservationAttempt(1, 0, 20, "READ_TRANSPORT")
    with pytest.raises(ObservationContractError):
        FinalStateObservation("EXHAUSTED", (attempt,), BINDING)
    attempts = (attempt, ObservationAttempt(2, 30, 40, "READ_TRANSPORT"),
        ObservationAttempt(3, 50, 60, "READ_TRANSPORT"))
    with pytest.raises(ObservationContractError):
        FinalStateObservation("EXHAUSTED", attempts, BINDING)


def test_valid_typed_capture_is_reparsed_and_observed():
    typed = parse_company_capture(fixture(), BINDING)
    result, reader, _clock = run(typed)
    assert result.status == "OBSERVED" and reader.calls == 1
