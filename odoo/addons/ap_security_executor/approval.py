# SPDX-License-Identifier: LGPL-3.0-or-later
"""Private cryptographic approval verification, without nonce consumption.

Valid MACs authenticate a laboratory fixture, not the supplied policy decision
or the state of Odoo. Trusted inputs must come from server configuration and
the registered manifest, never from the token or an LLM proposal. This module
does not read secrets, clocks or the environment and cannot apply effects.
"""

from __future__ import annotations

from dataclasses import dataclass, field, fields
from datetime import datetime, timedelta
import hashlib
import hmac
import re

from .contracts import (
    ExecutorContractError, _bytes, _match, _snapshot, _text, _time,
    canonical_action_bytes, validate_command,
)


SIGNATURE_PREFIX = "hmac-sha256/v1:"
APPROVAL_DOMAIN = b"tcc-approval-fixture/hmac-sha256/v1\x00"
NONCE_DOMAIN = b"tcc-approval-nonce/v1\x00"
ERROR_CODES = frozenset({
    "DEPENDENCY_UNAVAILABLE", "CONTRACT_INVALID", "BINDING_MISMATCH",
    "SIGNATURE_INVALID", "NOT_YET_VALID", "EXPIRED",
    "NONCE_REUSED", "IDENTITY_INVALID", "RESERVATION_INVALID",
})


class ApprovalVerificationError(ValueError):
    """Finite category with no token, key or caller-controlled error text."""

    def __init__(self, code: str):
        self.code = code if type(code) is str and code in ERROR_CODES else "DEPENDENCY_UNAVAILABLE"
        super().__init__("approval verification failed: " + self.code)


def _fail(code: str) -> None:
    raise ApprovalVerificationError(code) from None


def _positive_id(value: object) -> None:
    if type(value) is not int or value <= 0:
        _fail("DEPENDENCY_UNAVAILABLE")


@dataclass(frozen=True, slots=True)
class ApprovalKey:
    """Runtime-only secret; identity and company are selected by trusted code."""

    company_id: int
    key_id: str
    material: bytes = field(repr=False)

    def __post_init__(self) -> None:
        _positive_id(self.company_id)
        try:
            _match(self.key_id, "version")
        except ExecutorContractError:
            _fail("DEPENDENCY_UNAVAILABLE")
        if type(self.material) is not bytes or not 32 <= len(self.material) <= 64:
            _fail("DEPENDENCY_UNAVAILABLE")


@dataclass(frozen=True, slots=True)
class ApprovalAuthority:
    """Exact fixture registration, supplied independently of the token."""

    company_id: int
    executor_user_id: int
    fixture_id: str
    scenario_id: str
    approver_ref: str
    nonce: str = field(repr=False)
    issued_at: str
    expires_at: str
    key_id: str

    def __post_init__(self) -> None:
        _positive_id(self.company_id)
        _positive_id(self.executor_user_id)
        try:
            for value, definition in (
                (self.fixture_id, "reference"), (self.scenario_id, "scenarioId"),
                (self.approver_ref, "reference"), (self.key_id, "version"),
            ):
                _match(value, definition)
                _text(value)
            issued, expires = _time(self.issued_at), _time(self.expires_at)
            if expires <= issued:
                _fail("DEPENDENCY_UNAVAILABLE")
        except (ExecutorContractError, ValueError, TypeError, OverflowError):
            _fail("DEPENDENCY_UNAVAILABLE")
        if (
            type(self.nonce) is not str or not 1 <= len(self.nonce) <= 128
            or re.fullmatch(r"[A-Za-z0-9_-]+", self.nonce) is None
        ):
            _fail("DEPENDENCY_UNAVAILABLE")


@dataclass(frozen=True, slots=True)
class VerifiedApproval:
    """Sane metadata only; this result does NOT attest nonce availability."""

    action_hash: str
    approval_sha256: str
    nonce_sha256: str
    command_sha256: str
    key_id: str
    fixture_id: str
    scenario_id: str
    approver_ref: str
    issued_at: str
    expires_at: str


def _trusted_configuration(
    authority: ApprovalAuthority, key: ApprovalKey, now: datetime,
) -> tuple[ApprovalAuthority, ApprovalKey]:
    if type(authority) is not ApprovalAuthority or type(key) is not ApprovalKey:
        _fail("DEPENDENCY_UNAVAILABLE")
    # Frozen instances can still be corrupted by privileged Python callers.
    # Reconstruct from every field rather than treating type as validation.
    try:
        registered = ApprovalAuthority(**{item.name: getattr(authority, item.name) for item in fields(ApprovalAuthority)})
        selected = ApprovalKey(**{item.name: getattr(key, item.name) for item in fields(ApprovalKey)})
        valid_clock = type(now) is datetime and now.tzinfo is not None and now.utcoffset() == timedelta(0)
    except ApprovalVerificationError:
        raise
    except Exception:
        # tzinfo is external Python code even on an exact datetime instance.
        # This pure boundary must not echo arbitrary config/clock exceptions.
        # Database concurrency exceptions are not encountered in this module.
        _fail("DEPENDENCY_UNAVAILABLE")
    if not valid_clock or (registered.company_id, registered.key_id) != (selected.company_id, selected.key_id):
        _fail("DEPENDENCY_UNAVAILABLE")
    return registered, selected


def _digest(value: dict) -> str:
    return "sha256:" + hashlib.sha256(_bytes(value)).hexdigest()


def verify_approval(
    command: dict, *, trusted_action: dict, authority: ApprovalAuthority,
    key: ApprovalKey, now: datetime,
) -> VerifiedApproval:
    """Authenticate exact registration and time; neither reserve nor consume.

    The trusted action must be independently resolved/revalidated by server
    code. A structural policy decision is never promoted to authority here.
    """
    registered, selected = _trusted_configuration(authority, key, now)
    try:
        trusted = _snapshot(trusted_action)
        trusted_bytes = canonical_action_bytes(trusted)
    except ExecutorContractError:
        _fail("DEPENDENCY_UNAVAILABLE")
    if trusted["executor_mode"] != "POST_APPROVED":
        _fail("DEPENDENCY_UNAVAILABLE")
    try:
        snapshot = _snapshot(command)
        validated = validate_command(snapshot)
    except ExecutorContractError:
        _fail("CONTRACT_INVALID")
    if validated.executor_mode != "POST_APPROVED":
        _fail("CONTRACT_INVALID")

    action_hash = "sha256:" + hashlib.sha256(trusted_bytes).hexdigest()
    approval = snapshot["approval"]
    expected = {
        "fixture_id": registered.fixture_id,
        "scenario_id": registered.scenario_id,
        "approver_ref": registered.approver_ref,
        "decision": "APPROVE",
        "canonical_action_hash": action_hash,
        "nonce": registered.nonce,
        "issued_at": registered.issued_at,
        "expires_at": registered.expires_at,
        "key_id": registered.key_id,
    }
    unsigned = {name: value for name, value in approval.items() if name != "signature"}
    if (
        snapshot["action"] != trusted or validated.action_hash != action_hash
        or trusted["scenario_id"] != registered.scenario_id or unsigned != expected
    ):
        _fail("BINDING_MISMATCH")

    signature = approval["signature"]
    if re.fullmatch(r"hmac-sha256/v1:[0-9a-f]{64}", signature) is None:
        _fail("SIGNATURE_INVALID")
    preimage = APPROVAL_DOMAIN + _bytes({"company_id": registered.company_id, "approval": unsigned})
    calculated = SIGNATURE_PREFIX + hmac.new(selected.material, preimage, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(signature, calculated):
        _fail("SIGNATURE_INVALID")

    # No implicit grace period, local clock lookup or time-window threshold.
    issued, expires = _time(registered.issued_at), _time(registered.expires_at)
    decision = snapshot["policy_decision"]
    evaluated, decision_expires = _time(decision["evaluated_at"]), _time(decision["expires_at"])
    if now < issued or now < evaluated:
        _fail("NOT_YET_VALID")
    if now >= expires or now >= decision_expires:
        _fail("EXPIRED")

    return VerifiedApproval(
        action_hash=action_hash, approval_sha256=_digest(approval),
        nonce_sha256="sha256:" + hashlib.sha256(NONCE_DOMAIN + registered.nonce.encode("utf-8")).hexdigest(),
        command_sha256=_digest(snapshot), key_id=registered.key_id,
        fixture_id=registered.fixture_id, scenario_id=registered.scenario_id,
        approver_ref=registered.approver_ref, issued_at=registered.issued_at,
        expires_at=registered.expires_at,
    )
