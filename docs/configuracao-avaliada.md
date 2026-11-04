# Configuração avaliada no piloto do Odoo

Esta página registra num lugar só exatamente o que foi testado na execução de 27/10/2026. Os números estão no [resultado do piloto no Odoo](pilot-state-resultado.md), a decisão que os registra é a [DEC-098](decision-log.md#dec-098) e a revisão independente da execução está em [revisão do piloto concluído](reviews/2026-10-27-piloto-concluido.md).

Os valores abaixo foram lidos do `evidence.json` da execução e dos 144 registros por slot, não copiados de outros documentos. Para conferir um valor, compare-o com o mesmo campo nesses arquivos ou recalcule o SHA-256 do arquivo indicado.

Siglas usadas aqui:

- **C0:** versão simples. O que o modelo propõe vai direto ao Odoo.
- **C1:** versão protegida, com regras, aprovação e executor restrito.
- **SHA-256:** impressão digital de um arquivo. Se um byte mudar, o valor muda.

## Execução

| Item | Valor |
|---|---|
| Identificador da execução | `fc6da3e17e5c475fb1c072d1894f3d64` |
| Data e horário | 27/10/2026, chamadas ao modelo entre 08:22 e 11:10 (Brasília) |
| Resultado técnico | 144/144 slots aprovados; limpeza conferida; nenhum segredo nos logs |
| Commit de base | `c6f95eccfea823b29a450941925f48f70450f780`, marcado com a tag `pilot-odoo-20261027` |
| Arquivo de evidência | `evidence.json`, SHA-256 `2d2f06a670e1d04cfde9aaed04a702cb1c3d9c84b130a5935c794e6c5994ba06` |
| Pacote de fontes conferido | 158 arquivos, SHA-256 do conjunto `5634ce68d735fa5e50a06cb07e2073ecd0e911bbfb34aa40f41d9b6c4eace5ee`. Cada slot confere os hashes antes de rodar. |
| Tentativa anterior | `bd5ae5b439a94a16b6cf540e9396ea90`: interrompida no 37º slot por falha de rede, preservada e fora dos números ([DEC-096](decision-log.md#dec-096)) |

## Modelo

| Item | Valor |
|---|---|
| Provedor e endereço | DeepSeek, `https://api.deepseek.com/chat/completions` |
| Modelo pedido e devolvido | `deepseek-flash` nos dois casos, nas 143 respostas válidas |
| Identificador do servidor do provedor | `bc19ba97cbe016479903222bb1578db6` em todas as respostas |
| Temperatura | 0 |
| Raciocínio (*thinking*) | desligado |
| Limite de saída | 2.048 tokens |
| Formato de saída | modo JSON do provedor (`response_format: json_object`). Garante JSON válido, mas não os campos do nosso schema. |
| Adaptador | `deepseek-chat-completions/v1`, em `gateway/src/tcc_gateway/llm_adapters.py` (SHA-256 `4097564b21601558e6f012c6ac43e4e0a2a3708527e75e0fa79ceb0cbd27cb78`) |
| Tentativas | Até 3 por slot, só em falha de rede, com esperas de 2 s e 4 s. Conexão 10 s, inatividade 120 s, prazo total 180 s ([DEC-029](decision-log.md#dec-029)). Na execução, cada slot fez uma tentativa. Resposta fora do schema não é repetida. |
| Política de tentativas | `gateway/src/tcc_gateway/attempt_policy.py`, SHA-256 `52c00bc87c6dd63e2d4d84239e38f4d232b182345e1409e12a18d8d2168fdd19` |

O alias `deepseek-flash` é móvel: o provedor pode trocar o modelo por trás dele. Por isso guardamos o nome e o identificador devolvidos em cada resposta, sem afirmar uma versão fixa.

## Prompt e schema

| Item | Valor |
|---|---|
| Versão do prompt | `ap-task-prompt/v1`, em `gateway/src/tcc_gateway/task_prompt.py` (SHA-256 `6beab2ce9dae894ed50897fa4b16e467fb5d38b33bb42b8844847d578dc45e7c`) |
| Prompt de sistema, fase de rascunho | SHA-256 `a4af8ba528162d98b2c53ee1729ff85af25a3309309590319fd8d82226352f70` (95 respostas) |
| Prompt de sistema, fase de contabilização | SHA-256 `bf074c1ce63c187990e7b93957b456ffd975ba6bb963e84f57297ef1c473bd7e` (48 respostas) |
| Schema enviado ao modelo | SHA-256 `d9c3a129e7827460d32c0248e42227d9f876552a2aee33aab9e95ad15a3c8bd9` |
| Schema de saída versionado | `gateway/src/tcc_gateway/schemas/vendor_bill_action_output_v2.schema.json` (SHA-256 `6563b239d19db80d42c64037d023e18f4a3c956d455dbdafe1bebdee826ffef5`) |
| Igualdade entre C0 e C1 | Nos 24 documentos, a requisição ao modelo teve o mesmo SHA-256 nas seis execuções: três em C0 e três em C1. O modelo recebeu exatamente a mesma entrada nas duas versões. |

## Política e executor (só em C1)

| Item | Valor |
|---|---|
| Versão da política | `policy-v1.0.0` |
| Motor de política | `gateway/src/tcc_gateway/policy_engine.py`, SHA-256 `9d25fd76fd6b76ca35169d5b44ee3772b396599d2d52c6657c5b672555eea051`, o mesmo valor gravado em `policy_sha256` nos 144 registros |
| Contratos da política | `gateway/src/tcc_gateway/policy_contracts.py`, SHA-256 `2d5964f2620828a6afbcecb69fb19e1671f414900842a79be42f8388050f7ae6` |
| Executor restrito no Odoo | add-on `ap_security_executor`, manifesto SHA-256 `b51509fee41ed8511b3fe99cb064b80cc37f15a0e8c39b1c8d0cedc11ddad272` |
| Método público `execute` | fechado durante toda a execução (`public_executor_enabled=false`) |

## Odoo, banco e imagens

| Item | Valor |
|---|---|
| Odoo | 19.0 Community, commit `a4b877245c9cb5e3d7152d1593a518170f115ca1` |
| Imagem do Odoo, manifesto OCI | `sha256:3e0bcf8e796820e89577b1db24b4dbb54a63669f66384c4b61577068adf1f392`, igual ao registrado em [`reproducibility/odoo-source.lock.json`](../reproducibility/odoo-source.lock.json) |
| Imagem do Odoo, config | `sha256:c85221764b096dde2df68c50e2da634147b10c14dcfb98bf57f71f62a14bd1f2` |
| PostgreSQL | `postgres:18@sha256:7341002d2b8c7c5bdd7542a671a95b36196c0b5b888daf454ae4fc33ba5346d7` |
| Imagem do gateway e do cliente do modelo | `sha256:5c81dda4565efdc0d3352edd5223ca0addbab510e502fdc5e77de269320e16c0`, construída sobre `python:3.12-slim-bookworm@sha256:4427763a1ba36f5aa8f656a03e5d00f3b8d61f5dd950c73df6c14f8c7640f8ab` |
| Relógio usado nas medições de tempo | relógio Linux da [DEC-080](decision-log.md#dec-080), escopo SHA-256 `c0c0fa5bcafecfb3513b583d57280727e374b8ffbf80fa4d1d76f404d22312e7` |
| Runner | `scripts/pilot_state_harness.py`, SHA-256 `53e65463650aa08878ec95b2d68adeb944157bab023636750ecb2302900a18dc` |

## Faturas e estado inicial

| Item | Valor |
|---|---|
| Conjunto de faturas | `pilot-v0-candidate.4`, 12 pares (24 PDFs sintéticos sem valor fiscal), codebook `ap-ipi-codebook/v0.1` |
| SHA-256 do conjunto | `cd3ff7b73c7d2f61b307ac89edc44387131704cf2bae28317087c3c5f64966f5` |
| Composição | 4 pares por família de ataque (A1, A2, A3a); 4 dos 12 documentos benignos são *hard negatives* |
| Estado inicial com rascunhos benignos (B0) | SHA-256 do estado `3d07664d271597c04ffc0e20ce702b0736ae34c3f6f00333cd2c935cdb4cc20c`; cópia `255cc12d8d59f3300003137f32fcef3d0b3adcf2ea39dc3ec0f4fb26c5828eff` |
| Estado inicial com rascunhos adversariais (B1) | SHA-256 do estado `badc69d4bca8a68ab295caa9965b811e0a396f97c399fca72a959beff7715a01`; cópia `0c9ec296ac8673c8acf6793848b190dc632ea638e4445bd56358971ec14ebd7d` |
| Cópia do núcleo comum | `0af04724e1bfc0bb3b538830955bb958d22214d14097ef4d12fbf967e81eb7bb` |

## Ordem e análise

| Item | Valor |
|---|---|
| Desenho | 12 pares × 2 documentos × C0/C1 × 3 repetições = 144 execuções |
| Ordem | um sorteio único dos 144 slots, semente `2026102701`, agenda SHA-256 `63cee27ce1b4f58456b5ce44274b57560973b1e761764eed837752ecc14c2165` |
| Script de análise | `scripts/analyze_pilot_state.py`, SHA-256 `351ee9abe3c2c0b2cd04096cb7c1176364e5fdf6e2aa599367a3b13cc5ad0f4f` |
| Intervalos | bootstrap por par, 10.000 réplicas, semente `2026102801`. Quando o bootstrap degenera, aplica-se a fronteira conservadora da [DEC-089](decision-log.md#dec-089), em `gateway/src/tcc_gateway/paired_analysis.py` (SHA-256 `a122ca60a1e966e2c43245d41cb5e6e5dc8244fd87382bb53807cb7ce398974a`). |
| Tokens e custo | conferidos com o extrato de uso do DeepSeek: 217.862 tokens cobrados, cerca de US$ 0,03 |

## Comando usado

```bash
python scripts/pilot_state_harness.py --cohort-root .runtime/p4 --cohort-sha256 cd3ff7b73c7d2f61b307ac89edc44387131704cf2bae28317087c3c5f64966f5 --seed-file <seed> --alternatives-file <catálogo> --origin-files <origem-membro-0> <origem-membro-1> --schedule-seed 2026102701 --provider observed --confirm-real-calls 144 --docker-context desktop-linux
```

Os caminhos entre `<>` são os derivados do Odoo da [DEC-090](decision-log.md#dec-090), passados como caminhos absolutos. Detalhes no [runbook](lab-runbook.md#piloto-estado-odoo).

## O que fica fora do Git

- **Dados brutos:** os registros por slot, as capturas do Odoo e os logs ficam em `.runtime/state-oracle/fc6da3e17e5c475fb1c072d1894f3d64/`, com cópia local cifrada e restauração conferida ([DEC-099](decision-log.md#dec-099)).
- **Extrato do DeepSeek:** fica em `.runtime/`, porque contém o identificador da conta.
- **O que não existe:** as respostas brutas do modelo nunca foram guardadas, só os seus hashes.

## Conferência pelo grupo

Felipe e Thomaz conferem se o artigo diz o mesmo que esta página e marcam cada item. Se algo divergir, anotem página, trecho e diferença.

Felipe conferiu os sete itens em 29/10/2026, na [auditoria documental](reviews/2026-10-29-auditoria-felipe.md). A conferência é documental; os registros brutos foram validados na [revisão independente da execução](reviews/2026-10-27-piloto-concluido.md). A coluna do Thomaz não foi preenchida até 04/11, e o grupo seguiu sem ela ([DEC-100](decision-log.md#dec-100)).

| Conferir no artigo | Seção e página do PDF | Valor nesta página | Felipe | Thomaz |
|---|---|---|---|---|
| Commit do Odoo, PostgreSQL 18 e gateway Python 3.12 | 3.5, p. 10 | seção "Odoo, banco e imagens" | [x] | [ ] |
| Modelo `deepseek-flash`, temperatura 0, raciocínio desligado, 2.048 tokens | 3.5, p. 10 | seção "Modelo" | [x] | [ ] |
| Prompt `ap-task-prompt/v1`, igual em C0 e C1 | 3.5, p. 10 | seção "Prompt e schema" | [x] | [ ] |
| 12 pares, 24 documentos, 3 repetições, 144 execuções | 3.8, p. 12 | seção "Ordem e análise" | [x] | [ ] |
| Sorteio único com semente 2026102701 | 3.8, p. 12 | seção "Ordem e análise" | [x] | [ ] |
| Tentativa parcial excluída (36 chamadas cobradas) | 3.8, p. 12 | seção "Execução" | [x] | [ ] |
| Bootstrap com 10.000 réplicas, semente 2026102801 | 3.8, p. 12 | seção "Ordem e análise" | [x] | [ ] |
