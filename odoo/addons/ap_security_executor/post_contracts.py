# SPDX-License-Identifier: LGPL-3.0-or-later
"""Closed administrative POST registration; never a document/RPC contract."""

from dataclasses import dataclass, fields

from .draft_contracts import TrustedDraftWorkflow, _id, _invalid


@dataclass(frozen=True, slots=True)
class TrustedPostWorkflow:
    draft: TrustedDraftWorkflow
    target_move_id: int
    phase: str = "POST_REVIEW"

    def __post_init__(self):
        if type(self.draft) is not TrustedDraftWorkflow:
            _invalid()
        # Validate even privileged corruption of a previously frozen object.
        try:
            registered = TrustedDraftWorkflow(**{
                item.name: getattr(self.draft, item.name) for item in fields(TrustedDraftWorkflow)
            })
        except (AttributeError, TypeError, ValueError, OverflowError):
            _invalid()
        object.__setattr__(self, "draft", registered)
        _id(self.target_move_id)
        if type(self.phase) is not str or self.phase != "POST_REVIEW":
            _invalid()
