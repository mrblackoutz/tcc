"""DEC-057: preserve adverse/incomplete observations, never invent missing.

V1 remains readable. V2 adds terminal proposal failures and independently
records evaluation, reset and the next-slot gate. All evidence stays PRIVATE.
This is not a supervisor, scheduler, retry policy or scientific readiness gate.
"""

from __future__ import annotations

import base64
from dataclasses import asdict
from functools import lru_cache
import hashlib
from importlib.resources import files
import json

from jsonschema import Draft202012Validator

from .attempt_policy import AttemptRecord
from .company_capture import (
    CaptureBinding, CapturedCompanyState, CompanyCaptureError, ExpectedEffect,
    assert_restored, evaluate_captured_oracle, parse_company_capture,
)
from .oracle import OracleCase, OracleContractError, OracleProposal, OracleTrace
from .pilot_llm_runner import LLMStageResult
from .run_disposition import RunTechnicalEvidence, classify_run
from .run_record import (
    PENDING as V1_PENDING, RunIdentity, RunRecord, RunRecordContractError,
    _case, _closed, _digest, _expected, _json_snapshot, _TOP_FIELDS,
)
from .run_supervision import RunSupervision
from .state import canonical_json_bytes, canonical_json_sha256
from .terminal_llm_stage import validate_terminal_llm_stage, stage_outcome_uncertain


VERSION = "run-record/v2"
PENDING = tuple(item for item in V1_PENDING if item not in {
    "failed_proposal_and_missing_paths", "reset_failure_records",
}) + ("missing_classification_after_sci03_review", "precheck_and_malformed_evidence_records",
      "append_only_resolution_of_suspended_slot")
_TRACE_FIELDS = {"payload_delivered", "disposition", "approval_exact_valid", "executed_methods", "effect_move_id"}


def _fail():
    raise RunRecordContractError("invalid candidate v2 run record")


@lru_cache(maxsize=1)
def _validator():
    schema = json.loads(files("tcc_gateway.schemas").joinpath("run_record_v2.schema.json").read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema)


def _stage(value):
    _closed(value, {"condition", "status", "reason", "attempts", "response"})
    if type(value["attempts"]) is not list or len(value["attempts"]) > 3:
        _fail()
    for row in value["attempts"]:
        _closed(row, AttemptRecord.__dataclass_fields__)
    return LLMStageResult(value["condition"], value["status"], value["reason"],
                          tuple(AttemptRecord(**row) for row in value["attempts"]), value["response"])


def _reset(baseline, restored):
    if restored is None:
        return "UNOBSERVED"
    try:
        assert_restored(baseline, restored)
    except CompanyCaptureError:
        # Both inputs already passed the closed capture parser and same binding.
        # Preserve this valid but unequal state instead of discarding the run.
        return "DIVERGED"
    return "VERIFIED"


def _derive(value):
    _closed(value["identity"], RunIdentity.__dataclass_fields__)
    identity = RunIdentity(**value["identity"])
    _digest(value["policy_sha256"])
    evidence = value["evidence"]
    _closed(evidence, {"document_base64", "request", "stage", "case", "trace", "expected_effect", "captures"})
    request, stage = evidence["request"], _stage(evidence["stage"])
    if stage.condition != identity.condition:
        _fail()
    encoded = evidence["document_base64"]
    if type(encoded) is not str or not 1 <= len(encoded) <= 1_398_104:
        _fail()
    document = base64.b64decode(encoded, validate=True)
    if (not 1 <= len(document) <= 1_048_576 or base64.b64encode(document).decode("ascii") != encoded
            or hashlib.sha256(document).hexdigest() != request["document"]["document_sha256"]
            or len(document) != request["document"]["byte_count"]
            or request["scenario_id"] != identity.scenario_id):
        _fail()
    captures = evidence["captures"]
    _closed(captures, {"baseline", "before", "after", "restored"})
    binding = CaptureBinding(**captures["baseline"]["binding"])
    parsed = {}
    for key, item in captures.items():
        if item is None:
            if key not in {"after", "restored"}:
                _fail()
            parsed[key] = None
        else:
            parsed[key] = parse_company_capture(item, binding)
    baseline, before, after, restored = (parsed[key] for key in ("baseline", "before", "after", "restored"))
    assert_restored(baseline, before)
    supervision = RunSupervision.from_mapping(value["supervision"])
    supervision.validate_binding(run_id=identity.run_id, condition=identity.condition,
        code_commit=binding.code_commit, configuration_sha256=binding.configuration_sha256)
    llm = [interval for interval in supervision.intervals if interval.name == "llm"]
    if len(llm) != 1:
        _fail()
    proposal = validate_terminal_llm_stage(request, stage, elapsed_ns=llm[0].ended_ns - llm[0].started_ns)
    case, expected_effect = _case(evidence["case"]), _expected(evidence["expected_effect"])
    if case.scenario_id != identity.scenario_id or case.company_name != binding.company_name:
        _fail()
    facts = evidence["trace"]
    _closed(facts, _TRACE_FIELDS)
    if (facts["approval_exact_valid"] is not False or type(facts["executed_methods"]) is not list
            or len(facts["executed_methods"]) > 2
            or any(type(method) is not str or method not in {"account.move.create", "account.move.action_post"}
                   for method in facts["executed_methods"])):
        _fail()
    trace = OracleTrace(identity.condition, True, True, True, facts["payload_delivered"],
        OracleProposal.from_action_proposal_v2(proposal, target_move_id=case.target_move_id) if proposal else None,
        facts["disposition"], False, tuple(facts["executed_methods"]),
        before.oracle_state, after.oracle_state if after is not None else None,
        effect_move_id=facts["effect_move_id"])
    if (identity.condition == "C0" and trace.disposition not in {None, "ALLOW_EFFECTIVE"}
            or identity.condition == "C1" and trace.disposition == "ALLOW_EFFECTIVE"):
        _fail()
    quiescent = supervision.effect_quiescence == "CONFIRMED"
    reset_status = _reset(baseline, restored)
    technical = classify_run(RunTechnicalEvidence(True, True, True, quiescent,
        after is not None, False, False, reset_status == "VERIFIED"))
    outcome = None
    if not quiescent:
        assessment = "EFFECT_UNQUIESCED"
    elif after is None:
        assessment = "FINAL_STATE_UNAVAILABLE"
    else:
        try:
            outcome = evaluate_captured_oracle(case, trace, before, after,
                effect_move_id=facts["effect_move_id"], expected_effect=expected_effect)
            if proposal is None and (outcome.benign_task_success is True or outcome.utility_under_attack is True):
                # Invalid output is a task failure, not evidence of a valid
                # proposal. Preserve the anomaly without a favourable score.
                raise OracleContractError("unexpected successful effect without a valid proposal")
            assessment = "EVALUATED"
        except (OracleContractError, CompanyCaptureError):
            assessment = "ORACLE_CONTRACT_REJECTED"
            outcome = None
            # A readable capture alone does not make an unrepresentable effect
            # evaluable. Keep the complete capture and suspend classification.
            technical = classify_run(RunTechnicalEvidence(True, True, True, True, False, False, False,
                                                          reset_status == "VERIFIED"))
    batch_gate = technical.batch_gate
    if batch_gate == "CONTINUE" and stage_outcome_uncertain(stage):
        batch_gate = "HALT_LLM_UNCERTAIN"
    return {
        "proposal_sha256": canonical_json_sha256(proposal.to_mapping()) if proposal else None,
        "technical_disposition": technical.to_mapping(), "oracle": asdict(outcome) if outcome else None,
        "state_sha256": {key: capture.reset_sha256 if capture is not None else None for key, capture in parsed.items()},
        "reset_status": reset_status, "assessment_status": assessment, "batch_gate": batch_gate,
    }


def build_run_record_v2(*, identity: RunIdentity, document_bytes: bytes, request_value: dict,
                        stage: LLMStageResult, policy_sha256: str, supervision: RunSupervision,
                        case: OracleCase, trace: OracleTrace, expected_effect: ExpectedEffect,
                        baseline: CapturedCompanyState, before: CapturedCompanyState,
                        after: CapturedCompanyState | None, restored: CapturedCompanyState | None) -> RunRecord:
    """Preserve one immutable checkpoint; no retry/resumption or exclusion.

    A suspended record is not overwritten if its observations later change.
    Append-only resolution of that same slot needs the later supervisor journal.
    """
    try:
        if (type(identity) is not RunIdentity or type(document_bytes) is not bytes
                or not 1 <= len(document_bytes) <= 1_048_576 or type(stage) is not LLMStageResult
                or type(supervision) is not RunSupervision or type(case) is not OracleCase
                or type(trace) is not OracleTrace or type(expected_effect) is not ExpectedEffect
                or any(type(capture) is not CapturedCompanyState for capture in (baseline, before))
                or any(capture is not None and type(capture) is not CapturedCompanyState for capture in (after, restored))):
            _fail()
        trace.__post_init__()
        llm = [interval for interval in supervision.intervals if interval.name == "llm"]
        if len(llm) != 1:
            _fail()
        proposal = validate_terminal_llm_stage(request_value, stage,
            elapsed_ns=llm[0].ended_ns - llm[0].started_ns)
        expected_proposal = OracleProposal.from_action_proposal_v2(proposal, target_move_id=case.target_move_id) if proposal else None
        if (trace.condition != identity.condition or not trace.document_hash_verified
                or not trace.initial_state_verified or not trace.pipeline_started
                or trace.state_read_failure_after_retries or trace.before != before.oracle_state
                or trace.after != (after.oracle_state if after is not None else None)
                or trace.proposal != expected_proposal):
            _fail()
        value = {
            "schema_version": VERSION, "identity": asdict(identity), "policy_sha256": policy_sha256,
            "supervision": supervision.to_mapping(), "evidence": {
                "document_base64": base64.b64encode(document_bytes).decode("ascii"), "request": request_value,
                "stage": {"condition": stage.condition, "status": stage.status, "reason": stage.reason,
                    "attempts": [attempt.to_mapping() for attempt in stage.attempts], "response": stage.response},
                "case": asdict(case), "trace": {key: getattr(trace, key) for key in _TRACE_FIELDS},
                "expected_effect": {"invoice_date": expected_effect.invoice_date,
                                    "lines": [asdict(line) for line in expected_effect.lines]},
                "captures": {key: capture.to_mapping() if capture is not None else None for key, capture in
                             (("baseline", baseline), ("before", before), ("after", after), ("restored", restored))},
            }, "derived": {}, "pending": list(PENDING), "scientific_run": False, "human_review_complete": False,
        }
        value["evidence"]["trace"]["executed_methods"] = list(trace.executed_methods)
        value = _json_snapshot(value)
        value["derived"] = json.loads(canonical_json_bytes(_derive(value)))
        return parse_run_record_v2(value)
    except (ValueError, TypeError, AttributeError, KeyError, OverflowError, RecursionError):
        raise RunRecordContractError("invalid candidate v2 run record") from None


def parse_run_record_v2(value: dict) -> RunRecord:
    """Closed v2 parser; recompute every gate and outcome before accepting."""
    try:
        value = _json_snapshot(value)
        _closed(value, _TOP_FIELDS)
        if (not _validator().is_valid(value) or value["schema_version"] != VERSION
                or value["pending"] != list(PENDING) or value["scientific_run"] is not False
                or value["human_review_complete"] is not False):
            _fail()
        expected = canonical_json_bytes(_derive(value))
        if expected != canonical_json_bytes(value["derived"]):
            _fail()
        return RunRecord(canonical_json_bytes(value))
    except (ValueError, TypeError, AttributeError, KeyError, OverflowError, RecursionError):
        raise RunRecordContractError("invalid candidate v2 run record") from None
