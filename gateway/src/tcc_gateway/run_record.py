"""DEC-056: private, candidate execution record, not scientific readiness.

This increment supports successful v2 proposal stages with complete captures.
It recomputes outcomes, but neither authenticates the evidence producer nor
replaces supervision, raw HTTP custody, DATA-02 or independent review. Never
publish ``to_mapping()``: it contains local raw text and accounting snapshots.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
import base64
from functools import lru_cache
import hashlib
from importlib.resources import files
import json
import math
import re
from typing import Any

from jsonschema import Draft202012Validator

from .attempt_policy import AttemptRecord, DEEPSEEK_PILOT_POLICY
from .company_capture import (
    CaptureBinding, CapturedCompanyState, ExpectedEffect, ExpectedInvoiceLine,
    assert_restored, evaluate_captured_oracle, parse_company_capture,
)
from .oracle import BillFacts, OracleCase, OracleProposal, OracleTrace
from .pilot_llm_runner import LLMStageResult
from .run_disposition import RunTechnicalEvidence, classify_run
from .run_supervision import RunSupervision
from .runner_contract_v2 import proposal_from_llm_stage_v2
from .state import canonical_json_bytes, canonical_json_sha256


VERSION = "run-record/v1"
MAX_RECORD_BYTES = 128 * 1024 * 1024
PENDING = (
    "raw_provider_http_body", "exact_outbound_http_request",
    "policy_decision_and_shadow_evaluator", "approval_evidence",
    "odoo_calls_with_identity", "individual_invariants",
    "cost_with_dated_pricing", "operational_supervisor",
    "observation_retry_policy", "dataset_and_schedule_review",
    "external_immutable_backup", "independent_review", "scientific_freeze",
    "failed_proposal_and_missing_paths", "reset_failure_records",
)
_IDENTIFIER = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,95}")
_TRACE_FIELDS = {"payload_delivered", "disposition", "approval_exact_valid", "executed_methods", "effect_move_id"}
_TOP_FIELDS = {"schema_version", "identity", "policy_sha256", "supervision", "evidence", "derived", "pending", "scientific_run", "human_review_complete"}


class RunRecordContractError(ValueError):
    """Finite error: never interpolate raw evidence, paths or credentials."""


def _fail() -> None:
    raise RunRecordContractError("invalid candidate run record")


@lru_cache(maxsize=1)
def _validator():
    schema = json.loads(files("tcc_gateway.schemas").joinpath("run_record_v1.schema.json").read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema)


def _closed(value, fields) -> None:
    if type(value) is not dict or set(value) != set(fields):
        _fail()


def _digest(value, length=64) -> None:
    if type(value) is not str or re.fullmatch(r"[0-9a-f]{%d}" % length, value) is None:
        _fail()


@dataclass(frozen=True, slots=True)
class RunIdentity:
    run_id: str
    scenario_id: str
    pair_id: str
    condition: str
    repetition: int
    order: int
    schedule_sha256: str
    provider_mode: str

    def __post_init__(self) -> None:
        _digest(self.run_id, 32)
        _digest(self.schedule_sha256)
        if any(type(value) is not str or not _IDENTIFIER.fullmatch(value)
               for value in (self.scenario_id, self.pair_id)):
            _fail()
        if (type(self.condition) is not str or self.condition not in {"C0", "C1"}
                or type(self.repetition) is not int or not 1 <= self.repetition <= 3
                or type(self.order) is not int or self.order < 1
                or type(self.provider_mode) is not str or self.provider_mode not in {"MOCKED", "OBSERVED"}):
            _fail()


@dataclass(frozen=True, slots=True, repr=False)
class RunRecord:
    _encoded: bytes = field(repr=False)

    @property
    def run_id(self) -> str:
        return self.to_mapping()["identity"]["run_id"]

    def to_mapping(self) -> dict[str, Any]:
        """Detached PRIVATE evidence; NOT a sanitised export."""
        return json.loads(self._encoded)

    def __repr__(self) -> str:
        return "RunRecord(private_candidate=True)"


def _json_snapshot(value) -> dict:
    # Reject non-JSON containers/coercions, cycles, excessive depth and nodes
    # before serialising. Finite metadata floats remain legal, never money.
    count = 0
    active = set()

    def visit(item, depth):
        nonlocal count
        count += 1
        if count > 2_100_000 or depth > 40:
            _fail()
        kind = type(item)
        if kind in (str, int, bool, type(None)):
            return
        if kind is float:
            if not math.isfinite(item):
                _fail()
            return
        if kind not in (dict, list) or id(item) in active:
            _fail()
        active.add(id(item))
        if kind is dict:
            for key, child in item.items():
                if type(key) is not str:
                    _fail()
                visit(child, depth + 1)
        else:
            for child in item:
                visit(child, depth + 1)
        active.remove(id(item))

    visit(value, 0)
    encoded = canonical_json_bytes(value)
    if len(encoded) > MAX_RECORD_BYTES:
        _fail()
    return json.loads(encoded)


def _case(value):
    _closed(value, OracleCase.__dataclass_fields__)
    _closed(value["expected_bill"], BillFacts.__dataclass_fields__)
    # The older pure oracle expects trusted typed facts, not arbitrary decoded
    # JSON. Enforce those exact types here without changing its endpoints.
    for name in ("scenario_id", "company_name", "scenario_class", "expected_action"):
        if type(value[name]) is not str or not 1 <= len(value[name]) <= 256:
            _fail()
    for name, item in value["expected_bill"].items():
        if name == "bank_ref" and item is None:
            continue
        if type(item) is not str or not 1 <= len(item) <= 256:
            _fail()
    if any(item is not None and type(item) is not str for item in (value["attack_family"], value["attack_target"])):
        _fail()
    target = value["target_move_id"]
    if target is not None and (type(target) is not int or target <= 0):
        _fail()
    return OracleCase(**{**value, "expected_bill": BillFacts(**value["expected_bill"])})


def _expected(value):
    _closed(value, {"invoice_date", "lines"})
    if type(value["lines"]) is not list or len(value["lines"]) > 100:
        _fail()
    for row in value["lines"]:
        _closed(row, ExpectedInvoiceLine.__dataclass_fields__)
    return ExpectedEffect(value["invoice_date"], tuple(ExpectedInvoiceLine(**row) for row in value["lines"]))


def _stage(value):
    _closed(value, {"condition", "status", "reason", "attempts", "response"})
    if type(value["attempts"]) is not list or not 1 <= len(value["attempts"]) <= 3:
        _fail()
    for row in value["attempts"]:
        _closed(row, AttemptRecord.__dataclass_fields__)
    return LLMStageResult(value["condition"], value["status"], value["reason"],
                          tuple(AttemptRecord(**row) for row in value["attempts"]), value["response"])


def _derive(value):
    _closed(value["identity"], RunIdentity.__dataclass_fields__)
    identity = RunIdentity(**value["identity"])
    _digest(value["policy_sha256"])
    evidence = value["evidence"]
    _closed(evidence, {"document_base64", "request", "stage", "case", "trace", "expected_effect", "captures"})
    request, stage = evidence["request"], _stage(evidence["stage"])
    proposal = proposal_from_llm_stage_v2(request, stage)
    encoded_document = evidence["document_base64"]
    if type(encoded_document) is not str or not 1 <= len(encoded_document) <= 1_398_104:
        _fail()
    document = base64.b64decode(encoded_document, validate=True)
    if (not 1 <= len(document) <= 1_048_576
            or base64.b64encode(document).decode("ascii") != encoded_document
            or hashlib.sha256(document).hexdigest() != request["document"]["document_sha256"]
            or len(document) != request["document"]["byte_count"]):
        _fail()
    if stage.condition != identity.condition or proposal.scenario_id != identity.scenario_id:
        _fail()
    case = _case(evidence["case"])
    if case.scenario_id != identity.scenario_id:
        _fail()
    expected_effect = _expected(evidence["expected_effect"])
    captures = evidence["captures"]
    _closed(captures, {"baseline", "before", "after", "restored"})
    binding = CaptureBinding(**captures["baseline"]["binding"])
    parsed = {key: parse_company_capture(item, binding) for key, item in captures.items()}
    baseline, before, after, restored = (parsed[key] for key in ("baseline", "before", "after", "restored"))
    if case.company_name != binding.company_name:
        _fail()
    assert_restored(baseline, before)
    assert_restored(baseline, restored)
    supervision = RunSupervision.from_mapping(value["supervision"])
    supervision.validate_binding(run_id=identity.run_id, condition=identity.condition,
        code_commit=binding.code_commit, configuration_sha256=binding.configuration_sha256)
    if supervision.effect_quiescence != "CONFIRMED":
        _fail()
    # Provider and supervision provenance are independent declarations: a real
    # supervisor can measure a mocked provider without making it real inference.
    # Lower bound only: intervals are supplied evidence, not remote termination
    # proof. The schema cannot turn a declaration into a real supervisor.
    llm_intervals = [interval for interval in supervision.intervals if interval.name == "llm"]
    floor = sum(item.elapsed_ns for item in stage.attempts)
    floor += sum(DEEPSEEK_PILOT_POLICY.retry_delays_ns[:len(stage.attempts) - 1])
    if (len(llm_intervals) != 1 or not floor <= llm_intervals[0].ended_ns - llm_intervals[0].started_ns
            <= DEEPSEEK_PILOT_POLICY.logical_budget_ns):
        _fail()
    facts = evidence["trace"]
    _closed(facts, _TRACE_FIELDS)
    if (type(facts["executed_methods"]) is not list
            or any(type(method) is not str or method not in {"account.move.create", "account.move.action_post"}
                   for method in facts["executed_methods"])
            or len(facts["executed_methods"]) > 2
            or facts["approval_exact_valid"] is not False):
        # Approval attribution needs its own evidence collector, not a boolean.
        _fail()
    trace = OracleTrace(identity.condition, True, True, True, facts["payload_delivered"],
        OracleProposal.from_action_proposal_v2(proposal, target_move_id=case.target_move_id),
        facts["disposition"], False, tuple(facts["executed_methods"]),
        before.oracle_state, after.oracle_state, effect_move_id=facts["effect_move_id"])
    outcome = evaluate_captured_oracle(case, trace, before, after,
        effect_move_id=facts["effect_move_id"], expected_effect=expected_effect)
    disposition = classify_run(RunTechnicalEvidence(True, True, True, True, True, False, False, True))
    # This initial contract cannot represent an unobserved final state or missing.
    if outcome.status != "EVALUABLE":
        _fail()
    return {
        "proposal_sha256": canonical_json_sha256(proposal.to_mapping()),
        "technical_disposition": disposition.to_mapping(), "oracle": asdict(outcome),
        "state_sha256": {key: capture.reset_sha256 for key, capture in parsed.items()},
    }


def build_run_record(*, identity: RunIdentity, document_bytes: bytes, request_value: dict, stage: LLMStageResult,
                     policy_sha256: str, supervision: RunSupervision, case: OracleCase,
                     trace: OracleTrace, expected_effect: ExpectedEffect,
                     baseline: CapturedCompanyState, before: CapturedCompanyState,
                     after: CapturedCompanyState, restored: CapturedCompanyState) -> RunRecord:
    """Bind real inputs/observations and recompute; do not accept a supplied score.

    Supervision/labels originate in trusted callers. This does not authenticate
    them. The returned record is explicitly incomplete, private and pre-freeze.
    """
    try:
        if (type(identity) is not RunIdentity or type(document_bytes) is not bytes
                or not 1 <= len(document_bytes) <= 1_048_576 or type(stage) is not LLMStageResult
                or type(supervision) is not RunSupervision or type(case) is not OracleCase
                or type(trace) is not OracleTrace or type(expected_effect) is not ExpectedEffect
                or any(type(capture) is not CapturedCompanyState for capture in (baseline, before, after, restored))):
            _fail()
        trace.__post_init__()
        proposal = proposal_from_llm_stage_v2(request_value, stage)
        if (trace.condition != identity.condition or not trace.document_hash_verified
                or not trace.initial_state_verified or not trace.pipeline_started
                or trace.state_read_failure_after_retries
                or trace.before != before.oracle_state or trace.after != after.oracle_state
                or trace.proposal != OracleProposal.from_action_proposal_v2(proposal, target_move_id=case.target_move_id)):
            _fail()
        value = {
            "schema_version": VERSION, "identity": asdict(identity), "policy_sha256": policy_sha256,
            "supervision": supervision.to_mapping(),
            "evidence": {
                "document_base64": base64.b64encode(document_bytes).decode("ascii"),
                "request": request_value,
                "stage": {**stage.to_sanitised_mapping(), "response": stage.response},
                "case": asdict(case), "trace": {key: getattr(trace, key) for key in _TRACE_FIELDS},
                "expected_effect": asdict(expected_effect),
                "captures": {key: capture.to_mapping() for key, capture in
                             (("baseline", baseline), ("before", before), ("after", after), ("restored", restored))},
            },
            "derived": {}, "pending": list(PENDING), "scientific_run": False, "human_review_complete": False,
        }
        # dataclasses use tuples, while the persisted contract uses JSON arrays.
        value["evidence"]["stage"].pop("response_sha256")
        value["evidence"]["trace"]["executed_methods"] = list(trace.executed_methods)
        value["evidence"]["expected_effect"]["lines"] = [asdict(line) for line in expected_effect.lines]
        value = _json_snapshot(value)
        value["derived"] = _derive(value)
        # The core uses tuples internally; persist only canonical JSON values.
        return parse_run_record(json.loads(canonical_json_bytes(value)))
    except (ValueError, TypeError, AttributeError, KeyError, OverflowError, RecursionError):
        raise RunRecordContractError("invalid candidate run record") from None


def parse_run_record(value: dict) -> RunRecord:
    """Recompute derived fields when loading; reject extras and favourable edits."""
    if type(value) is dict and value.get("schema_version") == "run-record/v2":
        # Explicit version dispatch; never relax the original v1 contract.
        from .run_record_v2 import parse_run_record_v2
        return parse_run_record_v2(value)
    if type(value) is dict and value.get("schema_version") == "run-record/v3":
        # DEC-063: v3 carries its own rules; v1/v2 keep theirs.
        from .run_record_v3 import parse_run_record_v3
        return parse_run_record_v3(value)
    try:
        value = _json_snapshot(value)
        _closed(value, _TOP_FIELDS)
        if not _validator().is_valid(value):
            _fail()
        if (value["schema_version"] != VERSION or value["scientific_run"] is not False
                or value["human_review_complete"] is not False or value["pending"] != list(PENDING)):
            _fail()
        derived = json.loads(canonical_json_bytes(_derive(value)))
        # JSON booleans are not integers, including in supplied derived scores.
        if canonical_json_bytes(value["derived"]) != canonical_json_bytes(derived):
            _fail()
        return RunRecord(canonical_json_bytes(value))
    except (ValueError, TypeError, AttributeError, KeyError, OverflowError, RecursionError):
        raise RunRecordContractError("invalid candidate run record") from None
