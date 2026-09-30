# SPDX-License-Identifier: LGPL-3.0-or-later
"""C1-04 entry point. No effect is authorized by a received policy decision."""

from odoo import SUPERUSER_ID, api, models
from odoo.exceptions import AccessError, MissingError, ValidationError

from ..contracts import ExecutorContractError, validate_command


class ApSecurityExecutor(models.AbstractModel):
    _name = "ap.security.executor"
    _description = "Restricted Accounts Payable Capability Executor"

    @api.model
    def execute(self, command):
        """The sole custom public method; inherited ORM methods still exist.

        JSON-2 consumes its outer context before this call. Rebuild the
        environment rather than claiming literal rejection of that context.
        Until transactional policy, approval and audit exist, even a valid
        command produces a closed preflight denial, without financial effects.
        """
        return self._trusted_service()._preflight(command)

    def _trusted_service(self):
        if self.env.su or self.env.uid == SUPERUSER_ID:
            raise AccessError("Executor access denied.")
        try:
            neutral = api.Environment(self.env.cr, self.env.uid, {}, su=False)
            service = neutral[self._name]
            user = neutral.user
            if not user.active or not user.has_group("ap_security_executor.group_executor"):
                raise AccessError("Executor access denied.")
            service.check_access("read")
            # Neither env.company nor incoming allowed_company_ids selects the
            # company. C1-06 must additionally bind this to trusted workflow.
            company = user.company_id
            if not company or company.id not in user.company_ids.ids:
                raise AccessError("Executor access denied.")
            context = {
                "allowed_company_ids": [company.id], "force_company": company.id,
                "lang": "en_US", "tz": "UTC", "active_test": True,
            }
            return api.Environment(self.env.cr, self.env.uid, context, su=False)[self._name]
        except (AccessError, MissingError, ValueError):
            raise AccessError("Executor access denied.") from None

    def _preflight(self, command):
        try:
            checked = validate_command(command)
        except ExecutorContractError:
            raise ValidationError("Invalid capability command.") from None
        # This is a technical unavailability result, not the policy decision
        # supplied by the caller and not an experiment outcome. No feature flag
        # can bypass the unfinished C1-06/07/09 gates.
        return {
            "schema_version": "executor-preflight-result/v1",
            "decision": "DENY", "deny_class": "FAIL_CLOSED_UNAVAILABILITY",
            "reason_codes": ["DEPENDENCY_UNAVAILABLE"],
            "executor_status": "SCAFFOLD_NOT_READY", "effect_applied": False,
            "proposed_action_hash": checked.action_hash,
        }
