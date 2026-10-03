# SPDX-License-Identifier: LGPL-3.0-or-later
"""Closed administrative audit metadata and bounded operational event digests.

These objects are not RPC input or authority. Well-formed hashes do not prove
the provenance of the trusted caller that supplies them. No external I/O,
implicit clock, secret, financial capability or scientific RunRecord lives here.
"""

from dataclasses import dataclass
import hashlib
import re

from .contracts import ExecutorContractError, _bytes, _snapshot


class AuditContractError(ValueError):
    """A finite diagnostic that never echoes caller-provided values."""

    def __init__(self):
        super().__init__("Invalid operational audit contract.")


@dataclass(frozen=True, slots=True)
class TrustedAuditContext:
    """Explicit trusted configuration, not an authentication assertion."""

    run_id: str
    attempt_id: str
    code_commit: str
    code_sha256: str
    configuration_sha256: str

    def __post_init__(self):
        for value, pattern in (
            (self.run_id, r"[A-Z0-9][A-Z0-9._-]{0,63}"),
            (self.attempt_id, r"[0-9a-f]{32}"),
            (self.code_commit, r"[0-9a-f]{40}"),
            (self.code_sha256, r"sha256:[0-9a-f]{64}"),
            (self.configuration_sha256, r"sha256:[0-9a-f]{64}"),
        ):
            if type(value) is not str or re.fullmatch(pattern, value) is None:
                raise AuditContractError()


def audit_digest(value: dict) -> str:
    """Hash a detached, closed-type JSON object under an audit-only domain.

    The structural snapshot rejects cycles, oversized/deep trees, noncanonical
    text, float values and custom JSON-compatible classes before serialization.
    Event semantics are closed independently by the private writer.
    """
    if type(value) is not dict:
        raise AuditContractError()
    try:
        snapshot = _snapshot(value)
        return "sha256:" + hashlib.sha256(
            b"tcc-operational-audit/v1\0" + _bytes(snapshot)
        ).hexdigest()
    except (ExecutorContractError, ValueError, TypeError, OverflowError, RecursionError):
        raise AuditContractError() from None
