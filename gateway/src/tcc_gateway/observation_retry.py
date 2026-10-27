"""DEC-087: bounded final-state reads, never retries of financial effects.

The trusted reader must open a fresh cursor and execute SET TRANSACTION
READ ONLY for each capture. This interface does not prove SQL privileges or
remote termination. It accepts no model, method, condition, payload or label.
Transport timeouts remain the existing Odoo 5 s connection / 30 s read limits;
the monotonic history measures elapsed time, not an enforced wall deadline.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
import re
import time
from typing import Protocol

from .company_capture import (
    CaptureBinding, CapturedCompanyState, CompanyCaptureError, parse_company_capture,
)
from .odoo_json2 import OdooJson2Error
from .run_disposition import RunTechnicalEvidence, RunTechnicalDisposition, classify_run
from .state import canonical_json_sha256


MAX_OBSERVATION_ATTEMPTS = 3
RETRY_DELAYS_SECONDS = (1, 2)
_HTTP_MESSAGE = re.compile(r"Odoo JSON-2 request failed with HTTP status ([0-9]{3})\Z")
_CATEGORIES = frozenset({"OBSERVED", "READ_TRANSPORT", "HTTP_ERROR", "AUTHORIZATION",
    "CONTRACT_INVALID", "CAPTURE_INVALID", "READ_PERMANENT", "UNKNOWN_ERROR"})


class ObservationContractError(ValueError):
    """Finite contract failure; never reinterpret it as missing evidence."""


def _require(value):
    if not value:
        raise ObservationContractError("invalid readonly observation evidence")


class ReadonlyCaptureReader(Protocol):
    def read_capture(self) -> dict:
        """Read a complete capture using a trusted, fresh READ ONLY transaction."""


class ReadonlyObservationFailure(RuntimeError):
    """Finite native-reader failure; never carries a received error message."""

    def __init__(self, category: str, *, http_status: int | None = None):
        _require(type(category) is str and category in {
            "TRANSPORT", "HTTP", "AUTHORIZATION", "CONTRACT", "PERMANENT", "UNKNOWN"})
        if category == "HTTP":
            _require(type(http_status) is int and 100 <= http_status <= 599 and not 200 <= http_status <= 299)
        else:
            _require(http_status is None)
        self.category, self.http_status = category, http_status
        super().__init__("readonly observation failure: " + category)

    def __repr__(self):
        return "ReadonlyObservationFailure(finite_category=True)"


def _http_transient(status):
    return status in {408, 429} or (type(status) is int and 500 <= status <= 599)


@dataclass(frozen=True, slots=True)
class ObservationAttempt:
    number: int
    started_ns: int
    finished_ns: int
    category: str
    http_status: int | None = None

    def __post_init__(self):
        _require(type(self.number) is int and 1 <= self.number <= MAX_OBSERVATION_ATTEMPTS
            and type(self.started_ns) is int and type(self.finished_ns) is int
            and 0 <= self.started_ns <= self.finished_ns
            and type(self.category) is str and self.category in _CATEGORIES)
        if self.category == "HTTP_ERROR":
            _require(type(self.http_status) is int and 100 <= self.http_status <= 599
                and not 200 <= self.http_status <= 299)
        elif self.category == "AUTHORIZATION":
            _require(self.http_status is None or type(self.http_status) is int and self.http_status in {401, 403})
        else:
            _require(self.http_status is None)

    @property
    def retryable(self):
        return self.category == "READ_TRANSPORT" or self.category == "HTTP_ERROR" and _http_transient(self.http_status)

    def to_mapping(self):
        return {"number": self.number, "started_ns": self.started_ns, "finished_ns": self.finished_ns,
            "elapsed_ns": self.finished_ns - self.started_ns, "category": self.category,
            "http_status": self.http_status}


@dataclass(frozen=True, slots=True, repr=False)
class FinalStateObservation:
    status: str
    attempts: tuple[ObservationAttempt, ...]
    binding: CaptureBinding = field(repr=False)
    capture: CapturedCompanyState | None = field(default=None, repr=False)
    reason: str = "READ_FINISHED"

    def __post_init__(self):
        _require(type(self.status) is str and self.status in {"OBSERVED", "EXHAUSTED", "UNCONFIRMED"}
            and type(self.attempts) is tuple and 1 <= len(self.attempts) <= MAX_OBSERVATION_ATTEMPTS
            and type(self.binding) is CaptureBinding and self.reason in {"READ_FINISHED", "WAIT_UNCONFIRMED"})
        CaptureBinding(**self.binding.to_mapping())
        for number, item in enumerate(self.attempts, start=1):
            _require(type(item) is ObservationAttempt and item.number == number)
            ObservationAttempt(item.number, item.started_ns, item.finished_ns, item.category, item.http_status)
            if number > 1:
                previous = self.attempts[number - 2]
                _require(previous.retryable and item.started_ns - previous.finished_ns
                    >= RETRY_DELAYS_SECONDS[number - 2] * 1_000_000_000)
        if self.status == "OBSERVED":
            _require(self.reason == "READ_FINISHED" and self.attempts[-1].category == "OBSERVED"
                and type(self.capture) is CapturedCompanyState and self.capture.binding == self.binding)
        elif self.status == "EXHAUSTED":
            _require(self.reason == "READ_FINISHED" and self.capture is None
                and len(self.attempts) == MAX_OBSERVATION_ATTEMPTS and all(a.retryable for a in self.attempts))
        else:
            _require(self.capture is None and (not self.attempts[-1].retryable
                and self.attempts[-1].category != "OBSERVED" and self.reason == "READ_FINISHED"
                or self.reason == "WAIT_UNCONFIRMED" and self.attempts[-1].retryable
                and len(self.attempts) < MAX_OBSERVATION_ATTEMPTS))

    def __repr__(self):
        return f"FinalStateObservation(status={self.status!r}, attempt_count={len(self.attempts)})"

    def to_mapping(self):
        return {"schema_version": "final-state-observation/v1", "status": self.status, "reason": self.reason,
            "binding_sha256": canonical_json_sha256(self.binding.to_mapping()),
            "capture_sha256": self.capture.to_mapping()["capture_sha256"] if self.capture is not None else None,
            "attempts": [a.to_mapping() for a in self.attempts]}


def _failure(error):
    if type(error) is ReadonlyObservationFailure:
        # Revalidate even a native exception whose public attributes were mutated.
        typed = ReadonlyObservationFailure(error.category, http_status=error.http_status)
        category, status = typed.category, typed.http_status
        if category != "HTTP":
            return {"TRANSPORT": "READ_TRANSPORT", "AUTHORIZATION": "AUTHORIZATION",
                "CONTRACT": "CONTRACT_INVALID", "PERMANENT": "READ_PERMANENT",
                "UNKNOWN": "UNKNOWN_ERROR"}[category], None
    elif type(error) is OdooJson2Error:
        message = str(error)
        if message == "Odoo JSON-2 request failed before a response":
            return "READ_TRANSPORT", None
        if message in {"Odoo JSON-2 arguments are not JSON serializable", "Odoo JSON-2 returned an invalid JSON response"}:
            return "CONTRACT_INVALID", None
        match = _HTTP_MESSAGE.fullmatch(message)
        if match is None:
            return "UNKNOWN_ERROR", None
        status = int(match.group(1))
        if not 100 <= status <= 599 or 200 <= status <= 299:
            return "UNKNOWN_ERROR", None
    elif isinstance(error, CompanyCaptureError):
        return "CAPTURE_INVALID", None
    else:
        return "UNKNOWN_ERROR", None
    return ("AUTHORIZATION" if status in {401, 403} else "HTTP_ERROR"), status


def _now(clock_ns):
    try:
        stamp = clock_ns()
        _require(type(stamp) is int and stamp >= 0)
        return stamp
    except Exception:
        raise ObservationContractError("readonly observation clock unavailable") from None


def observe_final_state(
    reader: ReadonlyCaptureReader, *, binding: CaptureBinding,
    sleep: Callable[[float], None] = time.sleep, clock_ns: Callable[[], int] = time.monotonic_ns,
) -> FinalStateObservation:
    """At most three final-state reads under the common DEC-087 policy.

    ``reader`` is trusted administrative code, not an arbitrary JSON-2 caller
    or function from the document/model. It must itself enforce a fresh READ
    ONLY transaction for each call. No financial method is accepted here.
    """
    _require(type(binding) is CaptureBinding and callable(getattr(reader, "read_capture", None))
        and callable(sleep) and callable(clock_ns))
    binding = CaptureBinding(**binding.to_mapping())
    attempts = []
    for number in range(1, MAX_OBSERVATION_ATTEMPTS + 1):
        started = _now(clock_ns)
        capture = None
        try:
            value = reader.read_capture()
            if type(value) is CapturedCompanyState:
                value = value.to_mapping()
            capture = parse_company_capture(value, binding)
            category, status = "OBSERVED", None
        except Exception as error:
            try:
                category, status = _failure(error)
            except Exception:
                category, status = "UNKNOWN_ERROR", None
        finished = _now(clock_ns)
        attempt = ObservationAttempt(number, started, finished, category, status)
        attempts.append(attempt)
        if capture is not None:
            return FinalStateObservation("OBSERVED", tuple(attempts), binding, capture)
        if not attempt.retryable:
            return FinalStateObservation("UNCONFIRMED", tuple(attempts), binding)
        if number == MAX_OBSERVATION_ATTEMPTS:
            return FinalStateObservation("EXHAUSTED", tuple(attempts), binding)
        try:
            sleep(RETRY_DELAYS_SECONDS[number - 1])
        except Exception:
            return FinalStateObservation("UNCONFIRMED", tuple(attempts), binding, reason="WAIT_UNCONFIRMED")
    raise ObservationContractError("readonly observation did not terminate")


def build_observation_evidence(
    observation: FinalStateObservation, *, document_hash_verified: bool, initial_state_verified: bool,
    pipeline_started: bool, side_effect_quiesced: bool, reset_verified: bool,
    infrastructure_failure_independent: bool,
) -> RunTechnicalEvidence:
    """Derive retries/final-state flags; never infer independence or quiescence."""
    _require(type(observation) is FinalStateObservation)
    FinalStateObservation(observation.status, observation.attempts, observation.binding,
                          observation.capture, observation.reason)
    return RunTechnicalEvidence(document_hash_verified, initial_state_verified, pipeline_started,
        side_effect_quiesced, observation.status == "OBSERVED", infrastructure_failure_independent,
        observation.status == "EXHAUSTED", reset_verified)


def classify_observation(
    observation: FinalStateObservation, *, document_hash_verified: bool, initial_state_verified: bool,
    pipeline_started: bool, side_effect_quiesced: bool, reset_verified: bool,
    infrastructure_failure_independent: bool,
) -> RunTechnicalDisposition:
    """Call the existing classifier, preserving reset and uncertainty gates."""
    return classify_run(build_observation_evidence(observation,
        document_hash_verified=document_hash_verified, initial_state_verified=initial_state_verified,
        pipeline_started=pipeline_started, side_effect_quiesced=side_effect_quiesced,
        reset_verified=reset_verified, infrastructure_failure_independent=infrastructure_failure_independent))
