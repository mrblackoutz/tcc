# SPDX-License-Identifier: LGPL-3.0-or-later
"""DEC-076 pure approval observer; never an execution or nonce gate.

The trusted caller supplies actual identity, reference action, clock and prior
nonce availability. This module does not access Odoo, a database or the clock,
reserve/consume anything, sign a proposal, or block C0's financial operation.
Only sanitized detached metadata escapes; token/key/authority stay in memory.
Live transaction/snapshot integration is deliberately a separate gate.
"""

from dataclasses import asdict
from datetime import datetime, timedelta

from tcc_gateway.approval_observation import (
    ApprovalObservationError, REJECTED_REASON_CODES, VERSION, parse_approval_observation,
)


def _dependencies():
    """Lazy native imports; the gateway's jsonschema model is never imported."""
    from odoo.addons.ap_security_executor.approval import ApprovalVerificationError, verify_approval
    from odoo.addons.ap_security_executor.contracts import canonical_action_bytes
    return verify_approval, ApprovalVerificationError, canonical_action_bytes


def _utc_text(value):
    try:
        if type(value) is not datetime or value.tzinfo is None or value.utcoffset() != timedelta(0):
            raise ValueError
        return value.isoformat().replace("+00:00", "Z")
    except Exception:
        raise ApprovalObservationError("invalid sanitized approval observation") from None


def begin_approval_observation(*, binding, reference_action, command, authority, key,
                               now, nonce_available, decision_window):
    """Read-only verification against independent exact reference, no minting.

    A rejected/absent grant is observed and returned, not raised as an execution
    veto. Invalid observation bindings cannot be represented and raise a finite
    contract error. An unavailable native/configuration dependency is recorded
    as INDETERMINATE, never misreported as absence or an attack result.
    """
    result = parse_approval_observation({
        "schema_version": VERSION, "binding": binding, "reference_action": reference_action,
        "verification": {"status": "INDETERMINATE", "reason_code": "DEPENDENCY_UNAVAILABLE", "metadata": None},
        "nonce_available": nonce_available,
        "timing": {"checked_at": _utc_text(now), "call_started_at": None, "call_finished_at": None,
                   "started_ns": None, "finished_ns": None},
        "decision_window": decision_window,
    })
    if command is None or type(command) is dict and "approval" not in command:
        result["verification"] = {"status": "ABSENT", "reason_code": "APPROVAL_ABSENT", "metadata": None}
        return parse_approval_observation(result)
    try:
        verify, error_type, canonical_action_bytes = _dependencies()
        # No caller-controlled policy object or token configures the observer.
        if (authority.company_id != result["binding"]["company_id"]
                or authority.executor_user_id != result["binding"]["executor_user_id"]
                or authority.scenario_id != result["binding"]["scenario_id"]):
            result["verification"]["reason_code"] = "IDENTITY_INVALID"
            return parse_approval_observation(result)
        canonical_action_bytes(result["reference_action"])
        if (type(command) is dict and type(command.get("policy_decision")) is dict
                and {name: command["policy_decision"].get(name) for name in ("evaluated_at", "expires_at")}
                    != result["decision_window"]):
            result["verification"]["reason_code"] = "DECISION_WINDOW_MISMATCH"
            return parse_approval_observation(result)
        try:
            verified = verify(command, trusted_action=result["reference_action"],
                              authority=authority, key=key, now=now)
        except error_type as error:
            status = "REJECTED" if error.code in REJECTED_REASON_CODES else "INDETERMINATE"
            result["verification"] = {"status": status, "reason_code": error.code, "metadata": None}
        else:
            result["verification"] = {"status": "VERIFIED", "reason_code": None, "metadata": asdict(verified)}
        return parse_approval_observation(result)
    except Exception:
        # Never persist arbitrary exception messages, reprs or dependency codes.
        result["verification"] = {"status": "INDETERMINATE", "reason_code": "DEPENDENCY_UNAVAILABLE", "metadata": None}
        return parse_approval_observation(result)


def finish_approval_observation(observation, *, call_started_at, call_finished_at,
                                started_ns, finished_ns):
    """Append declared call boundaries, preserving uncertainty for attribution.

    This does not execute the call, infer its identity/outcome, or claim that a
    token verified before the call remained valid throughout its interval.
    """
    result = parse_approval_observation(observation)
    result["timing"].update(
        call_started_at=None if call_started_at is None else _utc_text(call_started_at),
        call_finished_at=None if call_finished_at is None else _utc_text(call_finished_at),
        started_ns=started_ns, finished_ns=finished_ns,
    )
    return parse_approval_observation(result)
