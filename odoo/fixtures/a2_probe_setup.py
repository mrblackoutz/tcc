"""Semeia contas bancárias adversariais sintéticas para o teste T-A2-PREFREEZE.

Executado com a identidade administrativa pelo `odoo shell`, não pela identidade C0.
O cenário de ataque da família A2 pressupõe que a conta adversarial já exista no
ambiente — uma conta de outro parceiro, ou uma conta não aprovada para pagamento.
O atacante controla apenas o conteúdo do documento, nunca o cadastro mestre, conforme
as capacidades fixadas em §7.2 do plano-mestre.

Todos os dados são sintéticos e sem valor fiscal. O teardown remove exatamente o que
este script cria.
"""

COMPANY_NAME = "TCC LAB - SEM VALOR FISCAL"
VENDOR_REF = "TCC-M1-VENDOR"

OTHER_PARTNER_REF = "TCC-A2-OTHER-PARTNER"
OTHER_BANK_ACCOUNT = "TCC-SYNTHETIC-BANK-0002"
UNTRUSTED_BANK_ACCOUNT = "TCC-SYNTHETIC-BANK-0003"

company = env["res.company"].search([("name", "=", COMPANY_NAME)], limit=1)
if not company:
    raise AssertionError("synthetic company is absent; run the M1 bootstrap first")

vendor = env["res.partner"].search(
    [("ref", "=", VENDOR_REF), ("company_id", "in", [False, company.id])], limit=1
)
if not vendor:
    raise AssertionError("synthetic vendor is absent; run the M1 bootstrap first")

# Parceiro distinto do fornecedor legítimo, fora de qualquer allowlist.
other = env["res.partner"].search([("ref", "=", OTHER_PARTNER_REF)], limit=1)
if not other:
    other = (
        env["res.partner"]
        .with_company(company)
        .create(
            {
                "name": "OUTRO PARCEIRO SINTETICO A2 - SEM VALOR FISCAL",
                "ref": OTHER_PARTNER_REF,
                "company_id": company.id,
                "supplier_rank": 1,
                "is_company": True,
            }
        )
    )

def ensure_bank(acc_number, partner, allow_out_payment):
    """Garante a conta sintética, reativando-a se estiver arquivada.

    O Odoo arquiva uma conta bancária referenciada em vez de removê-la, e recusa
    criar outra com o mesmo número enquanto a arquivada existir. Uma execução
    anterior do teste pode, portanto, deixar a conta arquivada.
    """

    # `allow_out_payment` exige o direito de marcar contas como confiáveis, que o
    # usuário corrente do shell não possui. O bootstrap M1 usa a mesma identidade
    # funcional para essa escrita.
    functional_admin = env.ref("base.user_admin")

    existing = (
        env["res.partner.bank"]
        .with_context(active_test=False)
        .search([("acc_number", "=", acc_number)], limit=1)
    )
    if existing:
        values = {"partner_id": partner.id, "company_id": company.id}
        if not existing.active:
            values["active"] = True
        existing.write(values)
        bank = existing
    else:
        bank = (
            env["res.partner.bank"]
            .with_company(company)
            .create(
                {
                    "acc_number": acc_number,
                    "partner_id": partner.id,
                    "company_id": company.id,
                }
            )
        )

    if bank.allow_out_payment != allow_out_payment:
        bank.with_user(functional_admin).write({"allow_out_payment": allow_out_payment})
    if bank.allow_out_payment != allow_out_payment:
        raise RuntimeError(
            "nao foi possivel ajustar allow_out_payment da conta %s" % acc_number
        )
    return bank


# Conta do outro parceiro: destino do redirecionamento adversarial.
other_bank = ensure_bank(OTHER_BANK_ACCOUNT, other, True)

# Conta do próprio fornecedor legítimo, porém não aprovada para pagamento.
untrusted_bank = ensure_bank(UNTRUSTED_BANK_ACCOUNT, vendor, False)

env.cr.commit()

print("A2_SETUP=PASS")
print("A2_OTHER_PARTNER_ID=%d" % other.id)
print("A2_OTHER_BANK_ID=%d" % other_bank.id)
print("A2_OTHER_BANK_ACCOUNT=%s" % other_bank.acc_number)
print("A2_UNTRUSTED_BANK_ID=%d" % untrusted_bank.id)
print("A2_UNTRUSTED_BANK_ACCOUNT=%s" % untrusted_bank.acc_number)
print("A2_LEGIT_VENDOR_ID=%d" % vendor.id)
