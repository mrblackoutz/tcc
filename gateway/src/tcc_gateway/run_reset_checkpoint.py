"""DEC-059: append-only reset evidence for the same immutable run slot.

This contract changes only the next-slot technical gate. A later restoration
never replaces the execution's final state, proposal, oracle or original reset.
Hashes and declared supervision do not authenticate a producer, end a remote
process, authorise a financial effect or establish scientific readiness.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import json

from .company_capture import (
    CaptureBinding, CapturedCompanyState, CompanyCaptureError, assert_restored,
    parse_company_capture,
)
from .run_record import RunRecord, _closed, _digest, _json_snapshot, parse_run_record
from .run_record_v2 import VERSION as RECORD_VERSION, _stage
from .run_record_v3 import VERSION as RECORD_V3_VERSION
from .run_record_v4 import VERSION as RECORD_V4_VERSION
from .run_supervision import RunSupervision
from .state import canonical_json_bytes, canonical_json_sha256
from .terminal_llm_stage import stage_outcome_uncertain, stage_uncertainty_blocks


VERSION = "run-reset-checkpoint/v1"
MAX_CHECKPOINT_BYTES = 20 * 1024 * 1024
_FIELDS = {
    "schema_version", "identity", "record_sha256", "sequence",
    "previous_checkpoint_sha256", "supervision", "restored_capture", "derived",
    "scientific_run", "human_review_complete",
}
_DERIVED_FIELDS = {"reset_status", "batch_gate"}
_ERROR = "invalid private run reset checkpoint"
_FAILURES = (ValueError, TypeError, AttributeError, KeyError, OverflowError, RecursionError)


class RunResetCheckpointContractError(ValueError):
    """Finite diagnostic: never include paths, identifiers or raw evidence."""


def _fail() -> None:
    raise RunResetCheckpointContractError(_ERROR)


@dataclass(frozen=True, slots=True, repr=False)
class RunResetCheckpoint:
    _encoded: bytes = field(repr=False)

    @property
    def run_id(self) -> str:
        return self.to_mapping()["identity"]["run_id"]

    @property
    def sequence(self) -> int:
        return self.to_mapping()["sequence"]

    def to_mapping(self) -> dict:
        """Detached PRIVATE capture and metadata; never a public export."""
        try:
            if type(self._encoded) is not bytes or not 0 < len(self._encoded) <= MAX_CHECKPOINT_BYTES:
                _fail()
            value = json.loads(self._encoded)
            if type(value) is not dict or canonical_json_bytes(value) != self._encoded:
                _fail()
            return value
        except _FAILURES:
            raise RunResetCheckpointContractError(_ERROR) from None

    def __repr__(self) -> str:
        return "RunResetCheckpoint(private_candidate=True)"


def _base(record: RunRecord) -> dict:
    if type(record) is not RunRecord:
        _fail()
    value = parse_run_record(record.to_mapping()).to_mapping()
    if value["schema_version"] not in {RECORD_VERSION, RECORD_V3_VERSION, RECORD_V4_VERSION}:
        _fail()
    return value


def _llm_blocks(base: dict) -> bool:
    """Each record version keeps its own LLM gate (DEC-063).

    v2 halts on any uncertain attempt; v3/v4 only without a valid proposal.
    """
    stage = _stage(base["evidence"]["stage"])
    if base["schema_version"] in {RECORD_V3_VERSION, RECORD_V4_VERSION}:
        return stage_uncertainty_blocks(stage)
    return stage_outcome_uncertain(stage)


def _snapshot(value: dict) -> dict:
    value = _json_snapshot(value)
    if len(canonical_json_bytes(value)) > MAX_CHECKPOINT_BYTES:
        _fail()
    return value


def _derive(value: dict, base: dict) -> dict:
    """Validate one checkpoint against its base, without claiming ancestry."""
    _closed(value, _FIELDS)
    _closed(value["derived"], _DERIVED_FIELDS)
    if (type(value["schema_version"]) is not str or value["schema_version"] != VERSION
            or value["scientific_run"] is not False or value["human_review_complete"] is not False
            or type(value["sequence"]) is not int or value["sequence"] < 1
            or canonical_json_bytes(value["identity"]) != canonical_json_bytes(base["identity"])):
        _fail()
    _digest(value["record_sha256"])
    if value["record_sha256"] != canonical_json_sha256(base):
        _fail()
    if value["sequence"] == 1:
        if value["previous_checkpoint_sha256"] is not None:
            _fail()
    else:
        _digest(value["previous_checkpoint_sha256"])

    original = RunSupervision.from_mapping(base["supervision"])
    supervision = RunSupervision.from_mapping(value["supervision"])
    if any(getattr(supervision, name) != getattr(original, name) for name in (
        "run_id", "condition", "code_commit", "configuration_sha256", "host_id", "clock_id", "mode",
    )):
        _fail()
    if (len(supervision.intervals) != 1 or supervision.intervals[0].name != "capture"
            or supervision.intervals[0].started_ns < original.intervals[-1].ended_ns
            or original.effect_quiescence == "UNKNOWN" and supervision.effect_quiescence == "CONFIRMED"):
        _fail()

    baseline_value = base["evidence"]["captures"]["baseline"]
    binding = CaptureBinding.from_mapping(baseline_value["binding"])
    baseline = parse_company_capture(baseline_value, binding)
    if value["restored_capture"] is None:
        reset_status = "UNOBSERVED"
    else:
        restored = parse_company_capture(value["restored_capture"], binding)
        try:
            assert_restored(baseline, restored)
        except CompanyCaptureError:
            # A valid, bound but unequal capture is evidence, not corruption.
            reset_status = "DIVERGED"
        else:
            reset_status = "VERIFIED"

    approval_indeterminate = (base["schema_version"] == RECORD_V4_VERSION
                             and base["derived"]["approval"]["status"] == "INDETERMINATE")
    if (base["derived"]["assessment_status"] != "EVALUATED" and not (
            approval_indeterminate and base["derived"]["assessment_status"] == "APPROVAL_INDETERMINATE")
            or (base["derived"]["oracle"] is None and not approval_indeterminate)
            or original.effect_quiescence != "CONFIRMED"
            or supervision.effect_quiescence != "CONFIRMED"):
        gate = "HALT_CLASSIFICATION"
    elif reset_status != "VERIFIED":
        gate = "HALT_RESET"
    elif approval_indeterminate:
        # A later reset never creates the missing approval acquisition facts.
        gate = "HALT_APPROVAL"
    elif _llm_blocks(base):
        # The original HALT_RESET may have hidden a blocking LLM uncertainty.
        gate = "HALT_LLM_UNCERTAIN"
    else:
        gate = "CONTINUE"
    return {"reset_status": reset_status, "batch_gate": gate}


def _checked(value: dict, base: dict) -> dict:
    value = _snapshot(value)
    if canonical_json_bytes(value["derived"]) != canonical_json_bytes(_derive(value, base)):
        _fail()
    return value


def _predecessor(previous: RunResetCheckpoint | None, base: dict) -> dict | None:
    if previous is None:
        return None
    if type(previous) is not RunResetCheckpoint:
        _fail()
    # This checks the predecessor's own contracts. Only the complete-chain
    # reducer/store can prove its ancestry back to sequence one.
    return _checked(previous.to_mapping(), base)


def _linked(value: dict, previous: dict | None) -> None:
    if previous is None:
        if value["sequence"] != 1 or value["previous_checkpoint_sha256"] is not None:
            _fail()
    elif (value["sequence"] != previous["sequence"] + 1
            or value["previous_checkpoint_sha256"] != canonical_json_sha256(previous)
            or value["supervision"]["intervals"][0]["started_ns"]
            < previous["supervision"]["intervals"][0]["ended_ns"]
            or previous["supervision"]["effect_quiescence"] == "UNKNOWN"
            and value["supervision"]["effect_quiescence"] == "CONFIRMED"):
        _fail()


def build_run_reset_checkpoint(
    *, record: RunRecord, previous: RunResetCheckpoint | None,
    restored: CapturedCompanyState | None, supervision: RunSupervision,
) -> RunResetCheckpoint:
    """Record one later observation without executing a reset or replay."""
    try:
        if (type(supervision) is not RunSupervision
                or restored is not None and type(restored) is not CapturedCompanyState):
            _fail()
        base = _base(record)
        prior = _predecessor(previous, base)
        value = {
            "schema_version": VERSION, "identity": base["identity"],
            "record_sha256": canonical_json_sha256(base),
            "sequence": 1 if prior is None else prior["sequence"] + 1,
            "previous_checkpoint_sha256": canonical_json_sha256(prior) if prior is not None else None,
            "supervision": supervision.to_mapping(),
            "restored_capture": restored.to_mapping() if restored is not None else None,
            "derived": {"reset_status": None, "batch_gate": None},
            "scientific_run": False, "human_review_complete": False,
        }
        value = _snapshot(value)
        value["derived"] = _derive(value, base)
        _linked(value, prior)
        return RunResetCheckpoint(canonical_json_bytes(_checked(value, base)))
    except _FAILURES:
        raise RunResetCheckpointContractError(_ERROR) from None


def parse_run_reset_checkpoint(
    value: dict, *, record: RunRecord, previous: RunResetCheckpoint | None,
) -> RunResetCheckpoint:
    """Recompute gates and validate the immediate predecessor and base.

    A standalone predecessor does not establish a complete history. Consumers
    must use ``derive_next_slot_gate`` over the full ordered tuple as the gate.
    """
    try:
        base = _base(record)
        prior = _predecessor(previous, base)
        value = _checked(value, base)
        _linked(value, prior)
        return RunResetCheckpoint(canonical_json_bytes(value))
    except _FAILURES:
        raise RunResetCheckpointContractError(_ERROR) from None


def derive_next_slot_gate(record: RunRecord, checkpoints: tuple[RunResetCheckpoint, ...]) -> str:
    """Revalidate the complete history; never authorise a financial action."""
    try:
        base = _base(record)
        if type(checkpoints) is not tuple:
            _fail()
        previous = None
        gate = base["derived"]["batch_gate"]
        for checkpoint in checkpoints:
            if type(checkpoint) is not RunResetCheckpoint:
                _fail()
            previous = parse_run_reset_checkpoint(checkpoint.to_mapping(), record=record, previous=previous)
            gate = previous.to_mapping()["derived"]["batch_gate"]
        return gate
    except _FAILURES:
        raise RunResetCheckpointContractError(_ERROR) from None
