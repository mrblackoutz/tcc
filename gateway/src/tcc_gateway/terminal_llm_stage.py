"""DEC-057: validate terminal proposal histories without executing or retrying.

Attempt summaries and a declared stage interval establish consistency bounds,
not an exact clock trace or remote-process termination. Failures can exceed the
approved waiting budget and must remain recordable. No financial effect or
scientific disposition is inferred here.
"""

from __future__ import annotations

from .action_proposal_v2 import ActionProposalV2
from .attempt_policy import AttemptRecord, DEEPSEEK_PILOT_POLICY, decide_next_attempt
from .llm_client_service import parse_client_request_v2
from .pilot_llm_runner import LLMStageResult
from .runner_contract_v2 import proposal_from_llm_stage_v2
from .state import canonical_json_sha256


class TerminalLLMStageError(ValueError):
    """Finite diagnostic; never expose the received evidence or credentials."""


_ERROR_CATEGORIES = frozenset({
    "empty_response", "incomplete", "invalid_json", "invalid_json_object",
    "invalid_response_json", "invalid_response_shape", "invalid_schema",
    "model_mismatch", "multiple_or_missing_outputs", "provider_unavailable",
    "rate_limit", "request_not_serializable", "request_rejected",
    "thinking_not_disabled", "timeout", "transport", "truncated",
    "unexpected_tool_call", "invalid_client_response", "client_outcome_uncertain",
    "request_binding_mismatch", "proposal_hash_mismatch", "scenario_mismatch",
    "document_binding_mismatch", "prompt_contract_mismatch",
})
_POLICY = DEEPSEEK_PILOT_POLICY


def _fail() -> None:
    raise TerminalLLMStageError("invalid terminal LLM stage")


def stage_outcome_uncertain(stage: LLMStageResult) -> bool:
    """Identify uncertainty separately from the runner's terminal status.

    Use only after validation. In particular, ``client_outcome_uncertain`` is
    currently emitted as a permanent classified error, not status uncertain.
    This predicate does not establish whether that outcome was later resolved.
    """
    if type(stage) is not LLMStageResult or type(stage.attempts) is not tuple:
        _fail()
    if any(type(attempt) is not AttemptRecord for attempt in stage.attempts):
        _fail()
    # Generic transport errors also include ReadError/ReadTimeout after send.
    # A later response cannot establish termination of an earlier attempt.
    return stage.status == "uncertain" or any(
        attempt.outcome in {"deadline_exceeded", "uncertain"}
        or attempt.error_category in {"client_outcome_uncertain", "timeout", "transport"}
        for attempt in stage.attempts
    )


def stage_uncertainty_blocks(stage: LLMStageResult) -> bool:
    """DEC-060: uncertainty halts the batch only when no proposal resulted.

    The model has no tools, so an uncertain attempt cannot change Odoo state.
    When a later attempt returned a valid proposal, the earlier uncertainty is
    recorded as a flag instead of stopping the batch. Without a proposal the
    run outcome stays unresolved (missing vs. failure is an SCI-03 decision).
    """
    return stage_outcome_uncertain(stage) and stage.status != "success"


def validate_terminal_llm_stage(
    request_value: dict, stage: LLMStageResult, *, elapsed_ns: int,
) -> ActionProposalV2 | None:
    """Revalidate a DeepSeek v2 terminal history and return only its proposal.

    ``elapsed_ns`` is the containing LLM interval, not reconstructed attempt
    timing. It can corroborate budget exhaustion but cannot prove the exact
    decision instant. A missing proposal is never replaced with an empty one.
    """
    try:
        if (type(request_value) is not dict or type(stage) is not LLMStageResult
                or type(elapsed_ns) is not int or elapsed_ns < 0
                or type(stage.condition) is not str or stage.condition not in {"C0", "C1"}
                or type(stage.status) is not str or type(stage.reason) is not str
                or type(stage.attempts) is not tuple or len(stage.attempts) > _POLICY.max_attempts):
            _fail()
        provider, _request = parse_client_request_v2(request_value)
        if provider != "deepseek":
            _fail()
        request_hash = canonical_json_sha256(request_value)
        floor_ns = 0
        for number, item in enumerate(stage.attempts, start=1):
            if type(item) is not AttemptRecord:
                _fail()
            # Re-run constructor checks even if a frozen instance was bypassed.
            attempt = AttemptRecord(**item.to_mapping())
            if (type(attempt.outcome) is not str or type(attempt.request_sha256) is not str
                    or (attempt.response_sha256 is not None and type(attempt.response_sha256) is not str)
                    or (attempt.error_category is not None and type(attempt.error_category) is not str)
                    or attempt.number != number or attempt.request_sha256 != request_hash
                    or attempt.side_effect_started):
                _fail()
            if attempt.outcome == "classified_error":
                if attempt.error_category not in _ERROR_CATEGORIES or attempt.response_sha256 is not None:
                    _fail()
            elif attempt.outcome != "success":
                if (attempt.response_sha256 is not None or attempt.error_category is not None
                        or attempt.http_status is not None or attempt.retryable_hint):
                    _fail()
            floor_ns += attempt.elapsed_ns
            if floor_ns > elapsed_ns:
                _fail()
            terminal = number == len(stage.attempts)
            if not terminal:
                if (attempt.outcome != "classified_error"
                        or attempt.elapsed_ns > _POLICY.wall_deadline_ns
                        or floor_ns > _POLICY.logical_budget_ns):
                    _fail()
                retry = decide_next_attempt(attempt, logical_elapsed_ns=floor_ns)
                if not retry.should_retry:
                    _fail()
                floor_ns += retry.delay_ns
                if floor_ns > elapsed_ns:
                    _fail()

        if stage.status == "success":
            if not floor_ns <= elapsed_ns <= _POLICY.logical_budget_ns:
                _fail()
            return proposal_from_llm_stage_v2(request_value, stage)
        if stage.response is not None:
            _fail()
        if not stage.attempts:
            if (stage.status != "budget_exhausted" or stage.reason != "BUDGET_EXHAUSTED"
                    or elapsed_ns < _POLICY.logical_budget_ns):
                _fail()
            return None

        last = stage.attempts[-1]
        if stage.status == "uncertain":
            if stage.reason != "UNCONFIRMED_WALL_OUTCOME" or last.outcome != "deadline_exceeded":
                _fail()
            return None
        if (last.outcome != "classified_error" or last.elapsed_ns > _POLICY.wall_deadline_ns
                or floor_ns > _POLICY.logical_budget_ns):
            _fail()
        decision = decide_next_attempt(last, logical_elapsed_ns=floor_ns)
        if stage.status == "budget_exhausted":
            # The runner scheduled a retry, then exhausted its logical budget
            # while waiting or before starting the next attempt. The last delay
            # need not have completed, so it is not added to the lower bound.
            if (stage.reason != "BUDGET_EXHAUSTED" or not decision.should_retry
                    or elapsed_ns < _POLICY.logical_budget_ns):
                _fail()
            return None
        if stage.status != "classified_error":
            _fail()
        if stage.reason in {"PERMANENT_ERROR", "RETRY_EXHAUSTED"}:
            if decision.reason != stage.reason:
                _fail()
            return None
        if stage.reason == "BUDGET_EXHAUSTED":
            if (last.number >= _POLICY.max_attempts
                    or decision.reason not in {"RETRY_SCHEDULED", "BUDGET_EXHAUSTED"}
                    or elapsed_ns < _POLICY.logical_budget_ns - _POLICY.retry_delays_ns[last.number - 1]):
                _fail()
            return None
        _fail()
    except (ValueError, TypeError, AttributeError, KeyError, OverflowError, RecursionError):
        raise TerminalLLMStageError("invalid terminal LLM stage") from None
