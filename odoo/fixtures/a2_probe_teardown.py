"""Remove exatamente o que `a2_probe_setup.py` criou para o teste T-A2-PREFREEZE.

Executado com a identidade administrativa pelo `odoo shell`. Recusa-se a remover
qualquer registro fora do escopo sintético do teste.
"""

OTHER_PARTNER_REF = "TCC-A2-OTHER-PARTNER"
OTHER_BANK_ACCOUNT = "TCC-SYNTHETIC-BANK-0002"
UNTRUSTED_BANK_ACCOUNT = "TCC-SYNTHETIC-BANK-0003"
REF_PREFIX = "TCC-A2-PROBE"

residual_moves = env["account.move"].search([("ref", "like", REF_PREFIX)])
if residual_moves:
    non_draft = residual_moves.filtered(lambda m: m.state != "draft")
    if non_draft:
        raise AssertionError(
            "probe left non-draft moves; refusing to remove: %s" % non_draft.mapped("ref")
        )
    residual_moves.unlink()

banks = env["res.partner.bank"].search(
    [("acc_number", "in", [OTHER_BANK_ACCOUNT, UNTRUSTED_BANK_ACCOUNT])]
)
removed_banks = len(banks)
if banks:
    banks.unlink()

other = env["res.partner"].search([("ref", "=", OTHER_PARTNER_REF)])
removed_partners = len(other)
if other:
    other.unlink()

env.cr.commit()

print("A2_TEARDOWN=PASS")
print("A2_REMOVED_RESIDUAL_MOVES=%d" % len(residual_moves))
print("A2_REMOVED_BANKS=%d" % removed_banks)
print("A2_REMOVED_PARTNERS=%d" % removed_partners)
