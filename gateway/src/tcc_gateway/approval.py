"""Runtime laboratory fixture issuer; never approve an observed LLM proposal.

The caller supplies a legitimate canonical fixture action and all registration
metadata from trusted configuration. No key, clock, nonce or deadline is chosen
implicitly. Authentication uses the stdlib independently of the Odoo verifier.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Context, DecimalException, ROUND_HALF_EVEN, localcontext
import hashlib
import hmac
import json
import re

from .policy_contracts import ApprovalFixture, CanonicalAction, PolicyContractError


SIGNATURE_PREFIX = "hmac-sha256/v1:"
APPROVAL_DOMAIN = b"tcc-approval-fixture/hmac-sha256/v1\x00"
_ERROR_CODES = frozenset({"DEPENDENCY_UNAVAILABLE", "CONTRACT_INVALID"})


class ApprovalIssuanceError(ValueError):
    """Finite, sanitized failure with no key, nonce or token echoed."""

    def __init__(self, code: str):
        self.code = code if type(code) is str and code in _ERROR_CODES else "DEPENDENCY_UNAVAILABLE"
        super().__init__("approval issuance failed: " + self.code)


def _fail(code: str) -> None:
    raise ApprovalIssuanceError(code)


@dataclass(frozen=True, slots=True)
class ApprovalKey:
    company_id: int
    key_id: str
    material: bytes = field(repr=False)

    def __post_init__(self) -> None:
        if type(self.company_id) is not int or self.company_id <= 0:
            _fail("DEPENDENCY_UNAVAILABLE")
        if (
            type(self.key_id) is not str
            or re.fullmatch(r"[a-z][a-z0-9._/-]{0,63}", self.key_id) is None
        ):
            _fail("DEPENDENCY_UNAVAILABLE")
        if type(self.material) is not bytes or not 32 <= len(self.material) <= 64:
            _fail("DEPENDENCY_UNAVAILABLE")


def _bytes(value: dict) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"),
        ensure_ascii=False, allow_nan=False,
    ).encode("utf-8")


def issue_approval_fixture(
    action: CanonicalAction, *, company_id: int, fixture_id: str,
    approver_ref: str, nonce: str, issued_at: str, expires_at: str,
    key: ApprovalKey,
) -> ApprovalFixture:
    """Sign the manifest action only; the returned transport is not a log.

    Runtime key custody and registration are caller responsibilities. This
    function does not reserve a nonce or assert that it has not been used.
    """
    if type(key) is not ApprovalKey:
        _fail("DEPENDENCY_UNAVAILABLE")
    try:
        selected = ApprovalKey(key.company_id, key.key_id, key.material)
    except ApprovalIssuanceError:
        raise
    except (AttributeError, TypeError, ValueError):
        _fail("DEPENDENCY_UNAVAILABLE")
    if type(company_id) is not int or company_id <= 0 or company_id != selected.company_id:
        _fail("DEPENDENCY_UNAVAILABLE")
    if type(action) is not CanonicalAction:
        _fail("CONTRACT_INVALID")
    try:
        with localcontext(Context(prec=32, rounding=ROUND_HALF_EVEN)):
            canonical = CanonicalAction.from_mapping(action.to_mapping())
        if canonical.executor_mode != "POST_APPROVED" or canonical.action != "POST_VENDOR_BILL":
            _fail("CONTRACT_INVALID")
        # ApprovalFixture enforces closed metadata, UTC strings and ordering.
        pending = ApprovalFixture(
            fixture_id=fixture_id, scenario_id=canonical.scenario_id,
            approver_ref=approver_ref, canonical_action_hash=canonical.action_hash,
            nonce=nonce, issued_at=issued_at, expires_at=expires_at,
            key_id=selected.key_id, signature="runtime-pending",
        )
        unsigned = {name: value for name, value in pending.to_mapping().items() if name != "signature"}
        preimage = APPROVAL_DOMAIN + _bytes({"company_id": company_id, "approval": unsigned})
        signature = SIGNATURE_PREFIX + hmac.new(selected.material, preimage, hashlib.sha256).hexdigest()
        return ApprovalFixture(**unsigned, signature=signature)
    except ApprovalIssuanceError:
        raise
    except (PolicyContractError, AttributeError, TypeError, ValueError, OverflowError, RecursionError, DecimalException):
        raise ApprovalIssuanceError("CONTRACT_INVALID") from None
