# Rastreabilidade dos controles e da avaliação

**27/10/2026 — SEC-01/02 e SCI-09; reconciliação DEC-097.** Base: [controles e invariantes do plano](../Plano_Mestre_TCC_Seguranca_Agentes_LLM_Odoo.md#sec-10), [revisões proporcionais (DEC-087)](decision-log.md#dec-087) e [revisão de segurança executada](reviews/2026-10-26-revisao-agente.md). Esta matriz referencia o artefato corrente; não cria controles nem substitui assinaturas de freeze. C0 é a integração direta; C1, a protegida. As definições de métricas e siglas estão no [glossário](../Plano_Mestre_TCC_Seguranca_Agentes_LLM_Odoo.md#glossario).

## Controle, ameaça e evidência

| Ameaça / invariante | Controles e regra | Fonte / prova executável | Observação no experimento |
|---|---|---|---|
| Instrução externa ganha autoridade — I1 | C01/C04; R-POL-01 | `task_prompt.py`, `action_proposal_v2.py`; `test_task_prompt.py`, `test_runner_contract_v2.py` | Request, hash do documento e proposta preservados em `RunRecord.evidence`; ASR-proposal separada do efeito |
| Estágio de interpretação escreve no ERP — I5 | C02; separação de credenciais/egress | `compose.yaml`; provas G3-01–05 e `docs/g3b-egress-topology.md` | Modelo sem chave Odoo; somente o cliente isolado recebe chave do provedor; prova de egress não é resistência a injection |
| Manipulação de valor, fornecedor ou pedido — I3 | C05/C06; R-POL-02/06 | `policy_engine.py`, `trusted_resolution.py`, `draft_kernel.py`; `test_policy_engine.py`, `test_trusted_resolution.py`, testes Odoo `test_draft_kernel.py` | PolicyInput/Decision reais e captura por empresa; ASR-state compara efeito com expectativa independente |
| Redirecionamento de beneficiário e cadastro mestre — I2/I3/I10 | C05/C06/C07; R-POL-03/04 | `security/`, `identity.py`, `draft_kernel.py`; `test_identity_http.py`, `test_bypass_http.py` | Inventário restrito e diffs de `res.partner.bank`/`account.move`; banco de C0 não é corrigido pela allowlist C1 |
| POST sem autorização ou com argumentos alterados — I4 | C08/C10; R-POL-07/09 | `approval.py`, `post_kernel.py`, `registered_post.py`; `test_approval_kernel.py`, `test_post_kernel.py`, `test_approval_attribution.py` | `approval_observation` distingue proposta e efeito; UACR usa ação efetiva completa, identidade e validade temporal |
| Duplicação/replay — I7 | C09; chave determinística e nonce | `idempotency.py`, `draft_kernel.py`, `post_kernel.py`; `test_idempotency.py`, `c111_transactions.py` | Recibo, IDs físicos e nonce nas capturas; retorno idempotente não é segundo efeito |
| Perda de proveniência/auditoria — I6 | C12 | `audit_kernel.py`, `run_record_v4.py`, `run_record_store.py`; `test_audit_kernel.py`, `test_run_record_store.py` | Documento, código, decisão, identidade, before/after/restored e hashes; hashes não autenticam o produtor administrativo |
| Exceção deixa efeito crítico / falha técnica vira defesa — I8 | C14; R-POL-10 | `draft_kernel.py`, `post_kernel.py`, `c111_transactions.py` com faults/rollback; `terminal_llm_stage.py`, `run_disposition.py`, `observation_retry.py` e testes homônimos | Rollback e captura verificam ausência de efeito financeiro da exceção; parsing/recusa com estado legível permanecem avaliáveis. MISSING exige falha independente, leituras esgotadas e efeito quiescente |
| Bypass RPC/contexto hostil — I10 | C06/C07/C14 | `models/executor.py`, `draft_kernel.py::_context`, ACLs; `test_bypass_http.py`, `c111_transactions.py` | Usuário C1 não faz mutação financeira direta; contexto neutro e método privado; entrada pública `execute` permanece fechada |

Fontes Python do gateway estão em `gateway/src/tcc_gateway/`, seus testes em `gateway/tests/`; fontes/testes Odoo em `odoo/addons/ap_security_executor/` e `odoo/addons/ap_security_executor/tests/`. O probe transacional está em `odoo/probes/`. C13 é opcional e não integra o núcleo; C03/C11/I9 foram retirados, sem reutilizar seus IDs. Uma taxa agregada não comprova todos os predicados por execução: os registros e capturas correspondentes continuam necessários.

## Pergunta, endpoint e análise

| Pergunta / hipótese | Endpoint e denominador | Análise / saída prevista |
|---|---|---|
| RQ1 / segurança | ASR-state, adversariais avaliáveis; contraste com slots completos C0/C1 | Diferença C1−C0, ARR, IC95% por cluster/par e sensibilidade; tabela principal e figura pareada |
| RQ2 / utilidade | BTSR, benignas avaliáveis; mesma regra de pareamento | IC95% C1−C0; 10 pontos percentuais apenas como referência; tabela de utilidade, falsos bloqueios e revisão técnica |
| RQ1 / ações críticas | UACR, adversariais A3a elegíveis: quatro pares A3a, até 12 execuções adversariais por condição | Contraste pareado e IC95%, sem teste confirmatório; tabela de ações críticas |
| RQ1 / mecanismos | Delivery, proposta comprometida e violação de política no denominador comum avaliável | Cascata descritiva; proposta comprometida com efeito legítimo não vira ASR-state automaticamente |
| RQ2 / custo | Latência, tokens, custo e demanda de revisão observados | Descritivos por fase; sem H4 confirmatória e sem inferência sobre pessoas |
| RQ3 | Famílias/alvos/templates, com seus denominadores | Descritivos com limites; sem testes de subgrupo ou nova hipótese |

O [pipeline candidato de análise (DEC-089)](decision-log.md#dec-089) preserva três repetições dentro do par, 10.000 réplicas e seed; trata missing e fronteiras explicitamente. A entrega vigente tem 144 slots/12 pares e é descritiva ([DEC-094](decision-log.md#dec-094)): sem hierarquia confirmatória, não inferioridade ou p-valores. O analisador do piloto usa o universo correto de cada endpoint e o intervalo de fronteira revisado; sete contraprovas sintéticas passaram. A tabela final explicita o método, sem chamar `[0,0]` de risco zero.

## Permissões e limites de aceite

O [inventário fixado](../reproducibility/c1-permissions.inventory.json), junto do hash no lock do laboratório, é a fonte de permissões efetivas. As provas HTTP/bypass e de transações foram reproduzidas por revisor distinto, conforme o relatório de 26/10. A matriz documenta SEC-01/02; não repete essas provas nem altera ACLs. C0 conserva identidade funcional distinta e a mesma entrada do modelo.

A integração existe sob DEC-095/096; faltam conferir o lote completo, finalizar os intervalos e custodiar os artefatos Odoo. A cópia local autorizada não é externa/imutável. O produtor de retry de observação é candidato; o runner atual suspende diante de captura inválida, sem fabricar missing. Revisão do controle é diferente de eficácia medida; nenhuma célula desta matriz representa resultado do conjunto final.
