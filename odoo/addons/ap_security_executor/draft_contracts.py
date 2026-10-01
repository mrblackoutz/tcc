# SPDX-License-Identifier: LGPL-3.0-or-later
"""Immutable administrative draft workflow and independent retry fingerprints.

These values are supplied only by trusted administrative code. Validation and
hashes establish structure, not provenance or authorization. No Odoo import,
I/O, mutation, approval verification or policy evaluation occurs here.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
import hashlib
import json
import re
from typing import Any

from .contracts import ExecutorContractError, _snapshot, validate_command


IDEMPOTENCY_VERSION = "bill-idempotency/v1"
POLICY_VERSION = "policy-v1.0.0"


def _invalid() -> None:
    raise ExecutorContractError("executor draft contract invalid")


def _id(value: Any) -> None:
    if type(value) is not int or value <= 0:
        _invalid()


def _ids(value: Any, *, sorted_tuple: bool = False) -> tuple[int, ...]:
    if type(value) not in ({tuple} if sorted_tuple else {tuple, list}):
        _invalid()
    if not 1 <= len(value) <= 50:
        _invalid()
    for item in value:
        _id(item)
    if len(set(value)) != len(value):
        _invalid()
    ordered = tuple(sorted(value))
    if sorted_tuple and ordered != value:
        _invalid()
    return ordered


def _match(value: Any, pattern: str) -> None:
    if type(value) is not str or re.fullmatch(pattern, value) is None:
        _invalid()


def _date(value: Any) -> None:
    _match(value, r"[0-9]{4}-[0-9]{2}-[0-9]{2}")
    try:
        if date.fromisoformat(value).isoformat() != value:
            _invalid()
    except ValueError:
        _invalid()


def _digest(value: dict[str, Any]) -> str:
    encoded = json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


@dataclass(frozen=True, slots=True)
class TrustedDraftWorkflow:
    """Closed configuration, never an RPC payload or a document-derived value."""

    company_id: int
    executor_user_id: int
    purchase_order_id: int
    vendor_id: int
    journal_id: int
    expense_account_id: int
    purchase_line_ids: tuple[int, ...]
    allowed_bank_ids: tuple[int, ...]
    scenario_id: str
    document_sha256: str
    policy_version: str
    phase: str
    invoice_date_min: str
    invoice_date_max: str
    quantity_scale: int
    monetary_tolerance: str

    def __post_init__(self) -> None:
        for value in (
            self.company_id, self.executor_user_id, self.purchase_order_id,
            self.vendor_id, self.journal_id, self.expense_account_id,
        ):
            _id(value)
        _ids(self.purchase_line_ids, sorted_tuple=True)
        _ids(self.allowed_bank_ids, sorted_tuple=True)
        _match(self.scenario_id, r"[A-Z0-9][A-Z0-9._-]{0,63}")
        _match(self.document_sha256, r"[0-9a-f]{64}")
        if type(self.policy_version) is not str or type(self.phase) is not str or (
            self.policy_version != POLICY_VERSION or self.phase != "DRAFT_INTAKE"
        ):
            _invalid()
        _date(self.invoice_date_min)
        _date(self.invoice_date_max)
        if self.invoice_date_min > self.invoice_date_max:
            _invalid()
        if type(self.quantity_scale) is not int or self.quantity_scale not in {2, 3, 4}:
            _invalid()
        _match(self.monetary_tolerance, r"(0|[1-9][0-9]{0,11})\.[0-9]{2}")


def bill_idempotency_key(
    *, document_sha256: str, company_id: int, vendor_id: int,
    purchase_order_id: int, purchase_line_ids: tuple[int, ...] | list[int],
) -> str:
    """Hash trusted document/record identities, excluding mutable proposal data.

Standalone callers may supply either ordered or unordered tuple/list IDs;
ordering is canonicalized but duplicate IDs and bools are always rejected.
The operation namespace (CREATE/POST) belongs to the transactional ledger.
"""
    try:
        _match(document_sha256, r"[0-9a-f]{64}")
        for value in (company_id, vendor_id, purchase_order_id):
            _id(value)
        lines = _ids(purchase_line_ids)
        return _digest({
            "schema_version": IDEMPOTENCY_VERSION,
            "document_sha256": document_sha256,
            "company_id": company_id,
            "vendor_id": vendor_id,
            "purchase_order_id": purchase_order_id,
            "purchase_line_ids": list(lines),
        })
    except ExecutorContractError:
        raise
    except (TypeError, ValueError, OverflowError):
        raise ExecutorContractError("executor draft contract invalid") from None


def canonical_command_sha256(command: dict[str, Any]) -> str:
    """Bounded whole-command fingerprint; changed policy timestamps conflict.

The digest contains no transport context and does not authorize an effect.
Approval bytes, when present, are hashed but never returned or logged.
"""
    try:
        snapshot = _snapshot(command)
        validate_command(snapshot)
        return _digest(snapshot)
    except ExecutorContractError:
        raise
    except (TypeError, ValueError, OverflowError, RecursionError, RuntimeError):
        raise ExecutorContractError("executor draft contract invalid") from None
