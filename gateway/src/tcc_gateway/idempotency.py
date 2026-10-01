"""C1 document idempotency identity, independent of proposed business fields.

A hash is not authority: only a trusted reader/workflow can supply these IDs.
The addon repeats this independent calculation inside the transaction.
"""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any

from .policy_contracts import TrustedPolicyState
from .trusted_resolution import ResolvedPurchaseLine, ResolvedTrustedState


IDEMPOTENCY_VERSION = "bill-idempotency/v1"


def _invalid() -> None:
    raise ValueError("invalid trusted idempotency identity")


def _id(value: Any) -> None:
    if type(value) is not int or value <= 0:
        _invalid()


def bill_idempotency_key(
    *, document_sha256: str, company_id: int, vendor_id: int,
    purchase_order_id: int, purchase_line_ids: tuple[int, ...] | list[int],
) -> str:
    """Return a canonical digest from trusted IDs, never proposal references.

Line order is normalized; duplicate/nonpositive/noninteger IDs, bools and
collections other than tuple/list are rejected. CREATE/POST namespace is a
separate ledger field and does not alter this document identity.
"""
    try:
        if type(document_sha256) is not str or re.fullmatch(r"[0-9a-f]{64}", document_sha256) is None:
            _invalid()
        for value in (company_id, vendor_id, purchase_order_id):
            _id(value)
        if type(purchase_line_ids) not in {tuple, list} or not 1 <= len(purchase_line_ids) <= 50:
            _invalid()
        for value in purchase_line_ids:
            _id(value)
        if len(set(purchase_line_ids)) != len(purchase_line_ids):
            _invalid()
        value = {
            "schema_version": IDEMPOTENCY_VERSION,
            "document_sha256": document_sha256,
            "company_id": company_id,
            "vendor_id": vendor_id,
            "purchase_order_id": purchase_order_id,
            "purchase_line_ids": sorted(purchase_line_ids),
        }
        encoded = json.dumps(
            value, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
        return "sha256:" + hashlib.sha256(encoded).hexdigest()
    except (TypeError, ValueError, OverflowError):
        raise ValueError("invalid trusted idempotency identity") from None


def idempotency_key_for_resolved(resolved: ResolvedTrustedState) -> str:
    """Small read-only adapter from C1-03; no state revalidation or I/O.

It uses only document hash and resolved internal record identities. Descriptions,
references, quantities/prices, banks and current invoiceability are excluded.
Callers still need server-side locked revalidation and receipt uniqueness.
"""
    try:
        if type(resolved) is not ResolvedTrustedState or type(resolved.state) is not TrustedPolicyState:
            _invalid()
        if type(resolved.lines) is not tuple or any(
            type(line) is not ResolvedPurchaseLine for line in resolved.lines
        ):
            _invalid()
        return bill_idempotency_key(
            document_sha256=resolved.state.document_sha256,
            company_id=resolved.company_id,
            vendor_id=resolved.vendor_id,
            purchase_order_id=resolved.purchase_order_id,
            purchase_line_ids=tuple(line.purchase_line_id for line in resolved.lines),
        )
    except (AttributeError, TypeError, ValueError):
        raise ValueError("invalid trusted idempotency identity") from None
