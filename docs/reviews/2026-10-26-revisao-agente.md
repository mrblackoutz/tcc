# Revisão adversarial por agente distinto — 26/10/2026

**Base:** [DEC-081](../decision-log.md#dec-081) e [DEC-082](../decision-log.md#dec-082). **Revisor:** Claude Sonnet 5.5 (`claude-sonnet-5-5`). **Autor dos artefatos:** assistente de código Codex/GPT sob direção de Gustavo. **Árvore revista:** commit `ecf15dc`. Esta revisão **não é revisão humana** e não assina em nome de Felipe ou Thomaz.

## Resultado

Nenhum defeito de segurança ou de correção foi encontrado nos itens abaixo. Nada foi alterado no código de produção. Foi acrescentado um teste de regressão.

| Itens | O que foi feito (executado) | Resultado |
|---|---|---|
| C1-01, C1-02, C1-03, A3A-01 (contratos, política, canonicalização) | Oráculo da especificação escrito de forma independente do motor e confrontado com cerca de 33 mil entradas hostis (campos trocados, espaços, caracteres invisíveis, homóglifos, pares ação/modo incoerentes, datas e valores de fronteira, combinações de dois campos) em CREATE e POST. Regra: `ALLOW`/`REVIEW` só se a especificação é satisfeita; especificação satisfeita não pode ser negada. | 0 aceitações indevidas, 0 negações falsas, 0 falhas inesperadas. Teste de mutação: 10 de 11 defeitos plantados no motor foram detectados; o 11º (`POST` nunca vira `REVIEW`) é barrado pelo contrato, que rejeita a decisão incoerente, ou seja, falha fechada. |
| C1-04 a C1-11 (add-on, identidade, rascunho, POST, aprovação, auditoria, bypass, transações) | Reprodução independente das suítes adversariais na árvore atual: bypass HTTP (76 testes Odoo) e transações concorrentes (22 casos, cinco pares de conexões). Leitura dirigida de `draft_kernel.py` e `post_kernel.py`: bloqueios antes da checagem, relógio do servidor, aprovação verificada dentro da transação, contexto neutro. | `PASS` nas duas suítes, banco e filestore descartáveis, laboratório existente intocado. |
| SEC-A2 (`partner_id` depois de `partner_bank_id`) | O rascunho grava os dois campos em um único `create()` e confere `move.partner_bank_id == bank` depois (`draft_kernel.py`, linhas 225-226). | Já coberto; nenhum código novo necessário. |
| DATA-03, DATA-04 (24 PDFs) | Para os 12 pares: o adversarial é o benigno mais 2-3 linhas de nota (as únicas "remoções" são linhas em branco deslocadas pela paginação); palavras reveladoras ("experiment", "c1") aparecem igualmente nos dois documentos; fornecedor, pedido, banco e itens do gabarito aparecem no texto do benigno (48 verificações). | Sem vazamento assimétrico e sem divergência gabarito/documento. |

## O que não foi coberto

- Não li semanticamente os 24 PDFs para julgar a plausibilidade dos ataques; a checagem de DATA-03/04 foi automatizada.
- A política foi testada em isolamento; a composição com LLM real ainda não existe (RUN-02 pendente).
- Dois modelos de linguagem podem compartilhar pontos cegos; por isso o aceite se apoia em testes executados, não em leitura.
- Em C1-07 e C1-09 (aprovação e auditoria) não escrevi contraexemplos próprios; confiei nas suítes existentes reproduzidas acima.
- Itens de severidade baixa não foram perseguidos, conforme a DEC-082.

## Achados de severidade baixa (anotados, sem ação)

1. Cerca de 91% das mutações caem no schema (`PolicyContractError`) antes de chegar à política. Isso é falha fechada, mas o runner precisa classificar esses casos de forma consistente em C1 (SCI-03), senão eles distorcem a métrica de ataques. Já é escopo de SCI-03.
2. `document_ref` vem do LLM em CREATE. Alterá-lo não está entre os objetivos medidos (valor, beneficiário, ação crítica), então não afeta as métricas do TCC.

## Reprodução

- Teste novo: `gateway/tests/test_policy_adversarial_review.py` (16 s).
- Suítes Odoo: `scripts/test_c1_scaffold.ps1 -WithBypass` e `-WithTransactions` (ver [runbook](../lab-runbook.md)).
